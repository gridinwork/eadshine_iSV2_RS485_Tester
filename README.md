# Leadshine iSV2 RS-485 Tester

![Leadshine iSV2 RS-485 Tester GUI](docs/images/gui-main.svg)

Windows/Python GUI for testing and controlling **Leadshine iSV2-RS8075V48G** over **Modbus RTU / RS-485**.

## Current bench defaults

- Baud: **9600**
- Data bits: **8**
- Parity: **None**
- Stop bits: **2**
- Slave ID: **16** when the drive RCS rotary switch is at `0`
- SW1/SW2/SW3/SW4: **OFF** for the current bench setup

## IN / OUT ports

The two CN5 connectors marked **IN** and **OUT** are used as pass-through points for the same bidirectional RS-485 bus. They are not separate command input/output channels and they are not RX/TX ports.

## Features — v1.3

- COM-port selection
- Default connection profile `9600 / 8N2 / ID 16`
- Background exhaustive scanner:
  - first probe: `9600 / 8N2 / ID 16`
  - then all Modbus IDs `1..127`
  - all supported baud rates `9600, 19200, 38400, 57600, 115200, 4800, 2400`
  - limited N1/E1/E2 fallback on likely IDs if 8N2 finds nothing
  - progress bar and Stop Scan button
- Scanner is read-only: it reads the DSP/version register and never moves the motor
- Automatic reconnect with the parameters found by the scanner
- `PING / READ STATUS` button for a no-motion communication test
- Short motor command tests:
  - `TEST LEFT` — 100 rpm for 0.8 s
  - `TEST RIGHT` — 100 rpm for 0.8 s
  - `TEST CYCLE` — short left/pause/right sequence
- Continuous JOG left/right with configurable RPM
- Stop / emergency stop
- Alarm reset
- Telemetry: ready/run/error, RPM, current, torque, DC bus voltage, temperature
- Raw TX/RX Modbus log
- Optional PR0 velocity mode

> A successful Modbus write does not guarantee shaft movement when Servo Enable / SRV-ON is not active. The software intentionally does not enable SRV-ON automatically.

## Install on Windows

1. Install Python 3.11 or 3.12 x64.
2. Run `install.bat`.
3. Run `start.bat`.

`start.bat` launches `main_v1_3.py`.

See `README_RU.txt` for wiring and detailed Russian instructions.
