from PySide6.QtCore import QObject, Signal, Slot

from modbus_rtu import ModbusRTU

REG_SW_VERSION_1 = 0x0B00
BAUDS = [9600, 19200, 38400, 57600, 115200, 4800, 2400]


class ScanWorker(QObject):
    """Background RS-485 scanner.

    First probe is always the current bench default: 9600 8N2 / ID 16.
    Then all IDs 1..127 are swept at every supported baud in 8N2.
    If nothing is found, a small N1/E1/E2 fallback is tried on likely IDs.
    The scanner only READS a status/version register; it never moves the motor.
    """

    progress = Signal(int, int, str)
    found = Signal(int, str, int, int, int)  # baud, parity, stopbits, slave, dsp
    log = Signal(str)
    finished = Signal(bool)

    def __init__(self, port, preferred_slave=16, timeout=0.08):
        super().__init__()
        self.port = port
        self.preferred_slave = int(preferred_slave)
        self.timeout = float(timeout)
        self.cancelled = False

    def stop(self):
        self.cancelled = True

    @Slot()
    def run(self):
        ids = [16]
        if 1 <= self.preferred_slave <= 127 and self.preferred_slave not in ids:
            ids.append(self.preferred_slave)
        ids.extend(i for i in range(1, 128) if i not in ids)

        fallback_ids = []
        for sid in (16, self.preferred_slave, 8, 1):
            if 1 <= sid <= 127 and sid not in fallback_ids:
                fallback_ids.append(sid)
        fallback_profiles = [("N", 1), ("E", 1), ("E", 2)]

        total = len(BAUDS) * len(ids) + len(BAUDS) * len(fallback_ids) * len(fallback_profiles)
        done = 0
        mb = ModbusRTU()

        self.log.emit(
            f"SCAN START {self.port}: first 9600 8N2 ID=16; then all IDs 1..127 and bauds {BAUDS}"
        )

        try:
            # Main exhaustive profile used by iSV2-RS: 8N2.
            for baud in BAUDS:
                if self.cancelled:
                    self.finished.emit(False)
                    return
                try:
                    mb.open(
                        port=self.port,
                        baudrate=baud,
                        parity="N",
                        stopbits=2,
                        timeout=self.timeout,
                        slave=16,
                    )
                except Exception as exc:
                    done += len(ids)
                    self.progress.emit(done, total, f"{baud} 8N2 — COM error")
                    self.log.emit(f"SCAN {baud}: cannot open COM: {exc}")
                    continue

                for sid in ids:
                    if self.cancelled:
                        mb.close()
                        self.finished.emit(False)
                        return
                    mb.slave = sid
                    done += 1
                    self.progress.emit(done, total, f"{baud} 8N2 / ID {sid}")
                    try:
                        dsp = mb.read_holding(REG_SW_VERSION_1, 1)[0]
                        mb.close()
                        self.log.emit(f"SCAN FOUND: {baud} 8N2 ID={sid}, DSP=0x{dsp:04X}")
                        self.found.emit(baud, "N", 2, sid, dsp)
                        self.finished.emit(True)
                        return
                    except Exception:
                        pass
                mb.close()

            # Fallback for unusual parameterization. Kept deliberately small.
            self.log.emit("SCAN: 8N2 not found; limited N1/E1/E2 fallback on IDs 16/8/1")
            for parity, stopbits in fallback_profiles:
                for baud in BAUDS:
                    if self.cancelled:
                        self.finished.emit(False)
                        return
                    try:
                        mb.open(
                            port=self.port,
                            baudrate=baud,
                            parity=parity,
                            stopbits=stopbits,
                            timeout=self.timeout,
                            slave=fallback_ids[0],
                        )
                    except Exception:
                        done += len(fallback_ids)
                        continue

                    for sid in fallback_ids:
                        if self.cancelled:
                            mb.close()
                            self.finished.emit(False)
                            return
                        mb.slave = sid
                        done += 1
                        self.progress.emit(done, total, f"{baud} 8{parity}{stopbits} / ID {sid}")
                        try:
                            dsp = mb.read_holding(REG_SW_VERSION_1, 1)[0]
                            mb.close()
                            self.log.emit(
                                f"SCAN FOUND: {baud} 8{parity}{stopbits} ID={sid}, DSP=0x{dsp:04X}"
                            )
                            self.found.emit(baud, parity, stopbits, sid, dsp)
                            self.finished.emit(True)
                            return
                        except Exception:
                            pass
                    mb.close()
        finally:
            mb.close()

        self.finished.emit(False)
