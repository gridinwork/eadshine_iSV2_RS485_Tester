Leadshine iSV2-RS8075V48G — RS-485 Tester v1.2
==========================================

Windows GUI для первого теста Leadshine iSV2-RS8075V48G по Modbus RTU / RS-485.
Приложение НЕ использует CAN.

УСТАНОВКА
1. Установить Python 3.11/3.12 x64.
2. Запустить install.bat.
3. После установки запустить start.bat.

CN5
pin 1 = RS485+
pin 3 = RS485-
pin 5 = GND / reference ground
остальные = NC

НАСТРОЙКИ ДЛЯ ТЕКУЩЕГО ПРИВОДА (по присланным переключателям):
Baud rate = 9600
Data bits = 8
Parity = None
Stop bits = 2
Slave ID = 16  (при RCS=0 по текущему шильдику привода)
SW1 = OFF
SW2 = OFF
SW3 = OFF (терминатор отключен)
SW4 = OFF

Эти значения установлены в GUI по умолчанию.
Кнопка АВТОПОИСК пробует типовые скорости/форматы, не меняя параметры привода.
Если связи нет даже при автопоиске, проверь полярность RS485+/RS485-: на некоторых USB-RS485 адаптерах маркировка A/B трактуется наоборот.

ПЕРВЫЙ ТЕСТ — JOG
Рекомендуется начать без нагрузки с 50–100 rpm.
Pr6.04 / 0x0609 = JOG trial run velocity, rpm.
Control Word / 0x1801:
  0x4001 = JOG left
  0x4002 = JOG right
Leadshine требует повторять JOG trigger с интервалом <100 ms.
Программа отправляет команду каждые 60 ms.

SERVO ENABLE
Руководство Leadshine указывает, что SRV-ON должен быть назначен и привод должен быть Servo Enabled.
CN1 pin 5 = COM_IN
CN1 pin 6 = DI3, Servo Enable
Программа НЕ выдумывает неподтвержденный Modbus-регистр Servo-ON.
Если Modbus-команды принимаются, но двигатель не вращается, проверь SRV-ON / CN1 DI3.

ТЕЛЕМЕТРИЯ
0x0B05 Driver status: bit0 RDY, bit1 RUN, bit2 ERR, bit5 AT-SPEED
0x0B06 Motor speed, rpm
0x0B07 Motor torque, %
0x0B08 Motor current, 0.01 A
0x0B09 Filtered speed, rpm
0x0B0A DC bus voltage, V
0x0B0B Driver temperature, °C
0x0B03 Current alarm
0x0B04 Motor-not-rotating cause
0x0B00 DSP software version

RESET ALARM
0x1801 <- 0x1111

PR0 VELOCITY MODE — ADVANCED
Pr0.01 / 0x0003 = 6  PR internal command control (valid after restart)
Pr9.00 / 0x6200 = 2 velocity mode
Pr9.03 / 0x6203 = velocity, rpm
Pr9.04 / 0x6204 = acceleration
Pr9.05 / 0x6205 = deceleration
Pr8.02 / 0x6002 = 0x0010 trigger PR0
Pr8.02 / 0x6002 = 0x0040 emergency stop

Первый запуск выполнять без нагрузки и на малой скорости.
Аппаратная аварийная остановка должна оставаться независимой от ПК/USB/RS-485.
