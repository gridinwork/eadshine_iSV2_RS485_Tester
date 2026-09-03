import struct
import time
import serial

class ModbusError(Exception):
    pass

def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF

def append_crc(frame: bytes) -> bytes:
    crc = crc16_modbus(frame)
    return frame + bytes((crc & 0xFF, (crc >> 8) & 0xFF))

def to_signed16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v

class ModbusRTU:
    def __init__(self):
        self.ser = None
        self.slave = 1
        self.on_log = None

    @property
    def connected(self):
        return self.ser is not None and self.ser.is_open

    def log(self, text):
        if self.on_log:
            self.on_log(text)

    def open(self, port, baudrate=38400, bytesize=8, parity='N', stopbits=2, timeout=0.10, slave=1):
        self.close()
        self.slave = int(slave)
        parity_map = {'N': serial.PARITY_NONE, 'E': serial.PARITY_EVEN, 'O': serial.PARITY_ODD}
        stop_map = {1: serial.STOPBITS_ONE, 2: serial.STOPBITS_TWO}
        self.ser = serial.Serial(
            port=port, baudrate=int(baudrate), bytesize=bytesize,
            parity=parity_map[parity], stopbits=stop_map[int(stopbits)],
            timeout=float(timeout), write_timeout=float(timeout)
        )
        time.sleep(0.08)
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

    def close(self):
        if self.ser is not None:
            try:
                if self.ser.is_open:
                    self.ser.close()
            finally:
                self.ser = None

    def _exchange(self, pdu: bytes, expected_min: int = 5) -> bytes:
        if not self.connected:
            raise ModbusError('COM-порт не открыт')
        req = append_crc(bytes([self.slave]) + pdu)
        self.ser.reset_input_buffer()
        self.log('TX  ' + req.hex(' ').upper())
        self.ser.write(req)
        self.ser.flush()
        head = self.ser.read(3)
        if len(head) < 3:
            raise ModbusError('Нет ответа от привода')
        if head[0] != self.slave:
            raise ModbusError(f'Ответ от другого Slave ID: {head[0]}')
        fc = head[1]
        if fc & 0x80:
            rest = self.ser.read(2)
            frame = head + rest
            self.log('RX  ' + frame.hex(' ').upper())
            if len(frame) != 5:
                raise ModbusError('Неполный Modbus exception')
            if crc16_modbus(frame[:-2]) != int.from_bytes(frame[-2:], 'little'):
                raise ModbusError('Ошибка CRC в ответе')
            code = head[2]
            meanings = {1:'Function code error',2:'Address error',3:'Data error',8:'CRC checksum error'}
            raise ModbusError(f'Modbus exception 0x{code:02X}: {meanings.get(code,"Unknown")}')
        if fc == 0x03:
            byte_count = head[2]
            rest = self.ser.read(byte_count + 2)
            frame = head + rest
        elif fc == 0x06:
            rest = self.ser.read(5)
            frame = head + rest
        else:
            time.sleep(0.02)
            frame = head + self.ser.read(256)
        self.log('RX  ' + frame.hex(' ').upper())
        if len(frame) < expected_min:
            raise ModbusError('Слишком короткий ответ')
        rx_crc = int.from_bytes(frame[-2:], 'little')
        calc = crc16_modbus(frame[:-2])
        if rx_crc != calc:
            raise ModbusError(f'Ошибка CRC: RX=0x{rx_crc:04X}, calc=0x{calc:04X}')
        return frame

    def read_holding(self, address: int, count: int = 1):
        pdu = bytes([0x03]) + struct.pack('>HH', int(address), int(count))
        frame = self._exchange(pdu)
        if frame[1] != 0x03:
            raise ModbusError('Неожиданный function code')
        bc = frame[2]
        data = frame[3:3+bc]
        if len(data) != count * 2:
            raise ModbusError('Неверная длина данных')
        return list(struct.unpack('>' + 'H'*count, data))

    def write_single(self, address: int, value: int):
        value &= 0xFFFF
        pdu = bytes([0x06]) + struct.pack('>HH', int(address), value)
        frame = self._exchange(pdu)
        if frame[1] != 0x06:
            raise ModbusError('Неожиданный function code')
        addr_rx, val_rx = struct.unpack('>HH', frame[2:6])
        if addr_rx != int(address) or val_rx != value:
            raise ModbusError('Эхо записи не совпало')
        return True
