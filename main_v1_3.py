import sys
from datetime import datetime

from PySide6.QtCore import QThread, QTimer, Slot
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QPushButton, QComboBox, QSpinBox, QDoubleSpinBox,
    QTextEdit, QMessageBox, QFormLayout, QProgressBar
)
from serial.tools import list_ports

from modbus_rtu import ModbusRTU, to_signed16
from scanner import ScanWorker, BAUDS

APP_TITLE = "Leadshine iSV2-RS8075V48G — RS-485 Tester v1.3"

REG_SW_VERSION_1       = 0x0B00
REG_CURRENT_ALARM_B    = 0x0B03
REG_NOT_ROTATING_CAUSE = 0x0B04
REG_DRIVE_STATUS       = 0x0B05
REG_JOG_VELOCITY       = 0x0609
REG_CONTROL_WORD       = 0x1801
REG_COMM_MODE          = 0x053B
REG_BAUD_INDEX         = 0x053D
REG_AXIS_ID            = 0x053F
CMD_RESET_ALARM        = 0x1111
CMD_JOG_LEFT           = 0x4001
CMD_JOG_RIGHT          = 0x4002

REG_CONTROL_MODE       = 0x0003
REG_PR_TRIGGER         = 0x6002
REG_PR0_MODE           = 0x6200
REG_PR0_VELOCITY       = 0x6203
REG_PR0_ACCEL          = 0x6204
REG_PR0_DECEL          = 0x6205
PR_MODE_VELOCITY       = 0x0002
CMD_PR0_TRIGGER        = 0x0010
CMD_EMERGENCY_STOP     = 0x0040


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.mb = ModbusRTU()
        self.mb.on_log = self.add_log
        self.jog_cmd = None

        self.scan_thread = None
        self.scan_worker = None

        self.telemetry_timer = QTimer(self)
        self.telemetry_timer.setInterval(500)
        self.telemetry_timer.timeout.connect(self.poll_telemetry)

        self.jog_timer = QTimer(self)
        self.jog_timer.setInterval(60)
        self.jog_timer.timeout.connect(self.send_jog_keepalive)

        self.timed_stop = QTimer(self)
        self.timed_stop.setSingleShot(True)
        self.timed_stop.timeout.connect(self.stop_jog)

        self.cycle_timer = QTimer(self)
        self.cycle_timer.setSingleShot(True)
        self.cycle_timer.timeout.connect(self._cycle_next)
        self.cycle_stage = 0

        self.setWindowTitle(APP_TITLE)
        self.resize(1240, 850)
        self.build_ui()
        self.apply_dark_theme()
        self.refresh_ports()

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        conn = QGroupBox("1. Подключение и сканер Modbus RTU")
        g = QGridLayout(conn)

        self.port_combo = QComboBox()
        self.btn_refresh = QPushButton("Обновить COM")
        self.btn_refresh.clicked.connect(self.refresh_ports)

        self.baud_combo = QComboBox()
        self.baud_combo.addItems([str(x) for x in BAUDS])
        self.baud_combo.setCurrentText("9600")

        self.parity_combo = QComboBox()
        self.parity_combo.addItems(["N", "E", "O"])
        self.parity_combo.setCurrentText("N")

        self.stop_combo = QComboBox()
        self.stop_combo.addItems(["1", "2"])
        self.stop_combo.setCurrentText("2")

        self.slave_spin = QSpinBox()
        self.slave_spin.setRange(1, 127)
        self.slave_spin.setValue(16)

        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(0.03, 1.0)
        self.timeout_spin.setSingleStep(0.02)
        self.timeout_spin.setDecimals(2)
        self.timeout_spin.setValue(0.20)

        self.btn_connect = QPushButton("ПОДКЛЮЧИТЬ")
        self.btn_connect.clicked.connect(self.toggle_connection)

        self.btn_scan = QPushButton("СКАНИРОВАТЬ ВСЕ ID + BAUD")
        self.btn_scan.clicked.connect(self.start_scan)

        self.btn_scan_stop = QPushButton("СТОП СКАН")
        self.btn_scan_stop.clicked.connect(self.stop_scan)
        self.btn_scan_stop.setEnabled(False)

        self.status_conn = QLabel("OFFLINE")
        self.scan_progress = QProgressBar()
        self.scan_progress.setRange(0, 100)
        self.scan_progress.setValue(0)
        self.scan_state = QLabel("Готов к сканированию")

        g.addWidget(QLabel("COM:"), 0, 0)
        g.addWidget(self.port_combo, 0, 1, 1, 2)
        g.addWidget(self.btn_refresh, 0, 3)
        g.addWidget(QLabel("Baud:"), 0, 4)
        g.addWidget(self.baud_combo, 0, 5)
        g.addWidget(QLabel("Parity:"), 0, 6)
        g.addWidget(self.parity_combo, 0, 7)
        g.addWidget(QLabel("Stop bits:"), 0, 8)
        g.addWidget(self.stop_combo, 0, 9)

        g.addWidget(QLabel("Slave ID:"), 1, 0)
        g.addWidget(self.slave_spin, 1, 1)
        g.addWidget(QLabel("Timeout, s:"), 1, 2)
        g.addWidget(self.timeout_spin, 1, 3)
        g.addWidget(self.btn_connect, 1, 4, 1, 2)
        g.addWidget(self.btn_scan, 1, 6, 1, 2)
        g.addWidget(self.btn_scan_stop, 1, 8)
        g.addWidget(self.status_conn, 1, 9)

        g.addWidget(self.scan_progress, 2, 0, 1, 7)
        g.addWidget(self.scan_state, 2, 7, 1, 3)

        defaults = QLabel(
            "Текущий стенд: RCS=0 → ID 16, SW1=OFF + SW2=OFF → 9600 baud, "
            "основной профиль 8N2. Сканер первым проверяет именно 9600/ID16, "
            "затем все адреса 1–127 и все baud. IN и OUT — два проходных "
            "разъёма одной RS-485 шины, а не отдельные вход и выход команд."
        )
        defaults.setWordWrap(True)
        defaults.setStyleSheet("color:#9fd3ff;")
        g.addWidget(defaults, 3, 0, 1, 10)
        root.addWidget(conn)

        mid = QHBoxLayout()
        root.addLayout(mid, 1)

        tele = QGroupBox("2. Телеметрия")
        form = QFormLayout(tele)
        self.lbl_ready = QLabel("—")
        self.lbl_run = QLabel("—")
        self.lbl_error = QLabel("—")
        self.lbl_atspeed = QLabel("—")
        self.lbl_speed = QLabel("— rpm")
        self.lbl_speed_f = QLabel("— rpm")
        self.lbl_current = QLabel("— A")
        self.lbl_torque = QLabel("— %")
        self.lbl_bus = QLabel("— V")
        self.lbl_temp = QLabel("— °C")
        self.lbl_alarm = QLabel("—")
        self.lbl_notrot = QLabel("—")
        self.lbl_sw = QLabel("—")

        for name, w in [
            ("Servo Ready:", self.lbl_ready),
            ("RUN:", self.lbl_run),
            ("ERROR:", self.lbl_error),
            ("AT-SPEED:", self.lbl_atspeed),
            ("Скорость:", self.lbl_speed),
            ("Скорость filtered:", self.lbl_speed_f),
            ("Ток:", self.lbl_current),
            ("Момент:", self.lbl_torque),
            ("DC bus:", self.lbl_bus),
            ("Температура:", self.lbl_temp),
            ("Alarm:", self.lbl_alarm),
            ("Почему не вращается:", self.lbl_notrot),
            ("DSP version:", self.lbl_sw),
        ]:
            form.addRow(name, w)
        mid.addWidget(tele, 1)

        control = QGroupBox("3. Проверка команд и JOG")
        c = QVBoxLayout(control)

        info = QLabel(
            "После подключения сначала можно сделать PING/READ STATUS без движения. "
            "Далее короткие тесты сами задают 100 rpm, держат JOG 0.8 с и останавливают его."
        )
        info.setWordWrap(True)
        c.addWidget(info)

        quick = QHBoxLayout()
        self.btn_ping = QPushButton("PING / READ STATUS")
        self.btn_test_left = QPushButton("ТЕСТ ← 0.8 c / 100 rpm")
        self.btn_test_right = QPushButton("ТЕСТ → 0.8 c / 100 rpm")
        self.btn_test_cycle = QPushButton("ТЕСТ ЦИКЛ ← →")
        self.btn_ping.clicked.connect(self.command_ping)
        self.btn_test_left.clicked.connect(lambda: self.timed_jog(CMD_JOG_LEFT))
        self.btn_test_right.clicked.connect(lambda: self.timed_jog(CMD_JOG_RIGHT))
        self.btn_test_cycle.clicked.connect(self.start_test_cycle)
        quick.addWidget(self.btn_ping)
        quick.addWidget(self.btn_test_left)
        quick.addWidget(self.btn_test_right)
        quick.addWidget(self.btn_test_cycle)
        c.addLayout(quick)

        jog_info = QLabel(
            "Непрерывный JOG: Pr6.04 (0x0609) задаёт скорость, а 0x4001/0x4002 "
            "передаются в Control Word 0x1801 каждые 60 мс."
        )
        jog_info.setWordWrap(True)
        c.addWidget(jog_info)

        row = QHBoxLayout()
        self.jog_rpm = QSpinBox()
        self.jog_rpm.setRange(1, 10000)
        self.jog_rpm.setValue(100)
        self.jog_rpm.setSuffix(" rpm")
        self.btn_left = QPushButton("СТАРТ JOG ←")
        self.btn_right = QPushButton("СТАРТ JOG →")
        self.btn_left.clicked.connect(lambda: self.start_jog(CMD_JOG_LEFT))
        self.btn_right.clicked.connect(lambda: self.start_jog(CMD_JOG_RIGHT))
        row.addWidget(QLabel("Скорость:"))
        row.addWidget(self.jog_rpm)
        row.addWidget(self.btn_left)
        row.addWidget(self.btn_right)
        c.addLayout(row)

        row2 = QHBoxLayout()
        self.btn_stop = QPushButton("СТОП JOG")
        self.btn_estop = QPushButton("EMERGENCY STOP")
        self.btn_reset = QPushButton("RESET ALARM")
        self.btn_stop.clicked.connect(self.stop_jog)
        self.btn_estop.clicked.connect(self.emergency_stop)
        self.btn_reset.clicked.connect(self.reset_alarm)
        row2.addWidget(self.btn_stop)
        row2.addWidget(self.btn_estop)
        row2.addWidget(self.btn_reset)
        c.addLayout(row2)

        sep = QLabel("Расширенный PR0 velocity mode (опционально)")
        sep.setStyleSheet("font-weight:600; margin-top:12px;")
        c.addWidget(sep)

        adv = QGridLayout()
        self.pr_rpm = QSpinBox()
        self.pr_rpm.setRange(1, 10000)
        self.pr_rpm.setValue(300)
        self.pr_acc = QSpinBox()
        self.pr_acc.setRange(1, 65535)
        self.pr_acc.setValue(50)
        self.pr_dec = QSpinBox()
        self.pr_dec.setRange(1, 65535)
        self.pr_dec.setValue(50)
        self.btn_set_pr_mode = QPushButton("Записать Pr0.01=6\n(нужен restart)")
        self.btn_pr_run = QPushButton("PR0 START")
        self.btn_pr_stop = QPushButton("PR STOP")
        self.btn_set_pr_mode.clicked.connect(self.set_pr_control_mode)
        self.btn_pr_run.clicked.connect(self.start_pr_velocity)
        self.btn_pr_stop.clicked.connect(self.emergency_stop)
        adv.addWidget(QLabel("Velocity:"), 0, 0)
        adv.addWidget(self.pr_rpm, 0, 1)
        adv.addWidget(QLabel("Acceleration:"), 1, 0)
        adv.addWidget(self.pr_acc, 1, 1)
        adv.addWidget(QLabel("Deceleration:"), 2, 0)
        adv.addWidget(self.pr_dec, 2, 1)
        adv.addWidget(self.btn_set_pr_mode, 0, 2, 3, 1)
        adv.addWidget(self.btn_pr_run, 0, 3, 2, 1)
        adv.addWidget(self.btn_pr_stop, 2, 3)
        c.addLayout(adv)

        warn = QLabel(
            "Важно: если короткий JOG принят по Modbus, но вал не вращается, проверь "
            "Servo Enable (CN1 DI3 / SRV-ON). Программа не включает Servo Enable автоматически."
        )
        warn.setWordWrap(True)
        warn.setObjectName("warningLabel")
        c.addWidget(warn)
        mid.addWidget(control, 2)

        log_group = QGroupBox("4. Modbus журнал")
        lv = QVBoxLayout(log_group)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.document().setMaximumBlockCount(2000)
        lv.addWidget(self.log)
        btn_clear = QPushButton("Очистить журнал")
        btn_clear.clicked.connect(self.log.clear)
        lv.addWidget(btn_clear)
        root.addWidget(log_group, 1)

        self.set_controls_enabled(False)

    def apply_dark_theme(self):
        self.setStyleSheet("""
        QWidget { background:#17191d; color:#e8e8e8; font-size:13px; }
        QGroupBox { border:1px solid #3b3f46; border-radius:7px; margin-top:10px; padding-top:10px; font-weight:600; }
        QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 4px; }
        QPushButton { background:#2b3038; border:1px solid #555c66; border-radius:5px; padding:7px 12px; min-height:24px; }
        QPushButton:hover { background:#363d47; }
        QPushButton:pressed { background:#20252b; }
        QPushButton:disabled { color:#777; background:#222; border-color:#333; }
        QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QProgressBar { background:#101216; border:1px solid #454b54; border-radius:4px; padding:4px; }
        QProgressBar { text-align:center; }
        QProgressBar::chunk { background:#3b82f6; }
        #warningLabel { color:#ffd36e; background:#242116; border:1px solid #5a4d20; padding:7px; border-radius:4px; }
        """)

    def refresh_ports(self):
        current = self.port_combo.currentData()
        self.port_combo.clear()
        for p in list_ports.comports():
            text = f"{p.device} — {p.description}" if p.description else p.device
            self.port_combo.addItem(text, p.device)
        if current:
            for i in range(self.port_combo.count()):
                if self.port_combo.itemData(i) == current:
                    self.port_combo.setCurrentIndex(i)
                    break

    def add_log(self, text):
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log.append(f"[{stamp}] {text}")

    def set_controls_enabled(self, enabled):
        for w in [
            self.btn_ping, self.btn_test_left, self.btn_test_right, self.btn_test_cycle,
            self.btn_left, self.btn_right, self.btn_stop, self.btn_estop, self.btn_reset,
            self.btn_set_pr_mode, self.btn_pr_run, self.btn_pr_stop
        ]:
            w.setEnabled(enabled)

    def toggle_connection(self):
        self.disconnect() if self.mb.connected else self.connect_drive()

    def connect_drive(self):
        if self.port_combo.count() == 0:
            QMessageBox.warning(self, "COM", "COM-порт не найден.")
            return False
        try:
            port = self.port_combo.currentData()
            self.mb.open(
                port=port,
                baudrate=int(self.baud_combo.currentText()),
                parity=self.parity_combo.currentText(),
                stopbits=int(self.stop_combo.currentText()),
                timeout=self.timeout_spin.value(),
                slave=self.slave_spin.value(),
            )
            sw = self.mb.read_holding(REG_SW_VERSION_1, 1)[0]
            self.lbl_sw.setText(f"0x{sw:04X}")
            self.status_conn.setText("ONLINE")
            self.status_conn.setStyleSheet("color:#6ee7a2;font-weight:700;")
            self.btn_connect.setText("ОТКЛЮЧИТЬ")
            self.set_controls_enabled(True)
            self.telemetry_timer.start()
            self.add_log(
                f"Connected: {port}, {self.baud_combo.currentText()} 8"
                f"{self.parity_combo.currentText()}{self.stop_combo.currentText()}, "
                f"Slave={self.slave_spin.value()}, DSP=0x{sw:04X}"
            )
            self.read_comm_settings()
            return True
        except Exception as e:
            self.mb.close()
            self.add_log("ERROR connect: " + str(e))
            QMessageBox.critical(self, "Нет связи", str(e))
            return False

    def disconnect(self):
        self.telemetry_timer.stop()
        self.jog_timer.stop()
        self.timed_stop.stop()
        self.cycle_timer.stop()
        self.jog_cmd = None
        self.mb.close()
        self.status_conn.setText("OFFLINE")
        self.status_conn.setStyleSheet("color:#ff7070;font-weight:700;")
        self.btn_connect.setText("ПОДКЛЮЧИТЬ")
        self.set_controls_enabled(False)
        self.add_log("Disconnected")

    def start_scan(self):
        if self.scan_thread is not None:
            return
        if self.mb.connected:
            self.disconnect()
        if self.port_combo.count() == 0:
            QMessageBox.warning(self, "COM", "COM-порт не найден.")
            return

        self.scan_progress.setValue(0)
        self.scan_state.setText("Старт: 9600 8N2 / ID 16")
        self.btn_scan.setEnabled(False)
        self.btn_scan_stop.setEnabled(True)
        self.btn_connect.setEnabled(False)
        self.btn_refresh.setEnabled(False)

        self.scan_thread = QThread(self)
        self.scan_worker = ScanWorker(
            port=self.port_combo.currentData(),
            preferred_slave=self.slave_spin.value(),
            timeout=min(0.12, max(0.05, self.timeout_spin.value())),
        )
        self.scan_worker.moveToThread(self.scan_thread)
        self.scan_thread.started.connect(self.scan_worker.run)
        self.scan_worker.progress.connect(self.on_scan_progress)
        self.scan_worker.log.connect(self.add_log)
        self.scan_worker.found.connect(self.on_scan_found)
        self.scan_worker.finished.connect(self.on_scan_finished)
        self.scan_worker.finished.connect(self.scan_thread.quit)
        self.scan_thread.finished.connect(self.cleanup_scan_thread)
        self.scan_thread.start()

    def stop_scan(self):
        if self.scan_worker is not None:
            self.scan_worker.stop()
            self.scan_state.setText("Остановка…")
            self.add_log("SCAN: stop requested")

    @Slot(int, int, str)
    def on_scan_progress(self, done, total, text):
        self.scan_progress.setValue(int(done * 100 / max(1, total)))
        self.scan_state.setText(text)

    @Slot(int, str, int, int, int)
    def on_scan_found(self, baud, parity, stopbits, slave, dsp):
        self.baud_combo.setCurrentText(str(baud))
        self.parity_combo.setCurrentText(parity)
        self.stop_combo.setCurrentText(str(stopbits))
        self.slave_spin.setValue(slave)
        self.lbl_sw.setText(f"0x{dsp:04X}")
        self.scan_state.setText(f"НАЙДЕНО: {baud} 8{parity}{stopbits}, ID {slave}")

    @Slot(bool)
    def on_scan_finished(self, found):
        self.btn_scan.setEnabled(True)
        self.btn_scan_stop.setEnabled(False)
        self.btn_connect.setEnabled(True)
        self.btn_refresh.setEnabled(True)

        if found:
            QTimer.singleShot(150, self._connect_after_scan)
        elif self.scan_worker is not None and self.scan_worker.cancelled:
            self.scan_state.setText("Сканирование остановлено")
        else:
            self.scan_state.setText("Устройство не найдено")
            QMessageBox.warning(
                self,
                "Сканирование завершено",
                "Leadshine не найден. Проверены ID 1–127 и все штатные baud в 8N2, "
                "а затем ограниченный fallback. Следующий тест — поменять A/B местами "
                "и повторить скан.",
            )

    def cleanup_scan_thread(self):
        if self.scan_worker is not None:
            self.scan_worker.deleteLater()
        if self.scan_thread is not None:
            self.scan_thread.deleteLater()
        self.scan_worker = None
        self.scan_thread = None

    def _connect_after_scan(self):
        if self.connect_drive():
            QMessageBox.information(
                self,
                "Leadshine найден",
                f"Связь установлена: {self.baud_combo.currentText()} baud, 8"
                f"{self.parity_combo.currentText()}{self.stop_combo.currentText()}, "
                f"Slave ID {self.slave_spin.value()}.\n\nТеперь можно нажать PING "
                f"или короткий JOG-тест.",
            )

    def read_comm_settings(self):
        try:
            mode = self.mb.read_holding(REG_COMM_MODE, 1)[0]
            baud = self.mb.read_holding(REG_BAUD_INDEX, 1)[0]
            axis = self.mb.read_holding(REG_AXIS_ID, 1)[0]
            self.add_log(f"Drive params: Pr5.29={mode}, Pr5.30={baud}, Pr5.31={axis}")
        except Exception as e:
            self.add_log("Comm params read warning: " + str(e))

    def poll_telemetry(self):
        if not self.mb.connected or self.jog_timer.isActive():
            return
        try:
            vals = self.mb.read_holding(REG_DRIVE_STATUS, 7)
            status, spd, torque, current, spdf, bus, temp = vals
            self.lbl_ready.setText("YES" if status & 0x01 else "NO")
            self.lbl_run.setText("YES" if status & 0x02 else "NO")
            self.lbl_error.setText("YES" if status & 0x04 else "NO")
            self.lbl_atspeed.setText("YES" if status & 0x20 else "NO")
            self.lbl_speed.setText(f"{to_signed16(spd)} rpm")
            self.lbl_torque.setText(f"{to_signed16(torque)} %")
            self.lbl_current.setText(f"{to_signed16(current)/100.0:.2f} A")
            self.lbl_speed_f.setText(f"{to_signed16(spdf)} rpm")
            self.lbl_bus.setText(f"{bus} V")
            self.lbl_temp.setText(f"{to_signed16(temp)} °C")
            alarm = self.mb.read_holding(REG_CURRENT_ALARM_B, 1)[0]
            self.lbl_alarm.setText(f"0x{alarm:04X}" + (" (Normal)" if alarm == 0 else ""))
            cause = self.mb.read_holding(REG_NOT_ROTATING_CAUSE, 1)[0]
            self.lbl_notrot.setText(f"0x{cause:04X}")
        except Exception as e:
            self.add_log("Telemetry: " + str(e))

    def command_ping(self):
        try:
            dsp = self.mb.read_holding(REG_SW_VERSION_1, 1)[0]
            status = self.mb.read_holding(REG_DRIVE_STATUS, 1)[0]
            self.add_log(f"PING OK: DSP=0x{dsp:04X}, status=0x{status:04X}")
            QMessageBox.information(
                self, "PING OK",
                f"Привод ответил по Modbus.\nDSP: 0x{dsp:04X}\nStatus: 0x{status:04X}"
            )
        except Exception as e:
            QMessageBox.critical(self, "PING", str(e))

    def start_jog(self, cmd, rpm=None):
        if not self.mb.connected:
            return
        try:
            speed = self.jog_rpm.value() if rpm is None else int(rpm)
            self.mb.write_single(REG_JOG_VELOCITY, speed)
            self.jog_cmd = cmd
            self.mb.write_single(REG_CONTROL_WORD, cmd)
            self.jog_timer.start()
            self.add_log(f"JOG START: {'LEFT' if cmd == CMD_JOG_LEFT else 'RIGHT'}, {speed} rpm")
        except Exception as e:
            self.jog_timer.stop()
            self.jog_cmd = None
            QMessageBox.critical(self, "JOG", str(e))

    def send_jog_keepalive(self):
        if not self.mb.connected or self.jog_cmd is None:
            self.jog_timer.stop()
            return
        try:
            self.mb.write_single(REG_CONTROL_WORD, self.jog_cmd)
        except Exception as e:
            self.jog_timer.stop()
            self.jog_cmd = None
            self.add_log("JOG keepalive ERROR: " + str(e))
            QMessageBox.critical(self, "JOG остановлен", str(e))

    def stop_jog(self):
        self.jog_timer.stop()
        self.timed_stop.stop()
        self.jog_cmd = None
        if self.mb.connected:
            try:
                self.mb.write_single(REG_JOG_VELOCITY, 0)
            except Exception as e:
                self.add_log("JOG stop speed=0 warning: " + str(e))
        self.add_log("JOG STOP")
        QTimer.singleShot(250, self.poll_telemetry)

    def timed_jog(self, cmd, duration_ms=800, rpm=100):
        if not self.mb.connected:
            return
        self.cycle_timer.stop()
        self.cycle_stage = 0
        self.start_jog(cmd, rpm=rpm)
        if self.jog_timer.isActive():
            self.timed_stop.start(duration_ms)
            self.add_log(f"TIMED TEST: {'LEFT' if cmd == CMD_JOG_LEFT else 'RIGHT'}, {rpm} rpm, {duration_ms} ms")

    def start_test_cycle(self):
        if not self.mb.connected:
            return
        self.cycle_stage = 0
        self._cycle_next()

    def _cycle_next(self):
        if self.cycle_stage == 0:
            self.cycle_stage = 1
            self.start_jog(CMD_JOG_LEFT, rpm=100)
            self.cycle_timer.start(800)
        elif self.cycle_stage == 1:
            self.stop_jog()
            self.cycle_stage = 2
            self.cycle_timer.start(500)
        elif self.cycle_stage == 2:
            self.cycle_stage = 3
            self.start_jog(CMD_JOG_RIGHT, rpm=100)
            self.cycle_timer.start(800)
        else:
            self.stop_jog()
            self.cycle_stage = 0
            self.add_log("TEST CYCLE complete")

    def emergency_stop(self):
        self.jog_timer.stop()
        self.timed_stop.stop()
        self.cycle_timer.stop()
        self.jog_cmd = None
        try:
            self.mb.write_single(REG_PR_TRIGGER, CMD_EMERGENCY_STOP)
            self.add_log("EMERGENCY STOP: 0x6002 <- 0x0040")
        except Exception as e:
            QMessageBox.critical(self, "Emergency Stop", str(e))

    def reset_alarm(self):
        try:
            self.mb.write_single(REG_CONTROL_WORD, CMD_RESET_ALARM)
            self.add_log("RESET ALARM: 0x1801 <- 0x1111")
            QTimer.singleShot(250, self.poll_telemetry)
        except Exception as e:
            QMessageBox.critical(self, "Reset alarm", str(e))

    def set_pr_control_mode(self):
        ans = QMessageBox.question(
            self,
            "Pr0.01 = 6",
            "Записать Control Mode = PR internal command control (Pr0.01=6)?\n"
            "Параметр вступает в силу ПОСЛЕ перезапуска привода.\n\nПродолжить?",
        )
        if ans != QMessageBox.Yes:
            return
        try:
            self.mb.write_single(REG_CONTROL_MODE, 6)
            self.add_log("Pr0.01=6 written. POWER RESTART REQUIRED.")
            QMessageBox.information(self, "Готово", "Pr0.01=6 записан. Перезапусти питание привода.")
        except Exception as e:
            QMessageBox.critical(self, "PR mode", str(e))

    def start_pr_velocity(self):
        try:
            rpm = self.pr_rpm.value()
            self.mb.write_single(REG_PR0_MODE, PR_MODE_VELOCITY)
            self.mb.write_single(REG_PR0_VELOCITY, rpm)
            self.mb.write_single(REG_PR0_ACCEL, self.pr_acc.value())
            self.mb.write_single(REG_PR0_DECEL, self.pr_dec.value())
            self.mb.write_single(REG_PR_TRIGGER, CMD_PR0_TRIGGER)
            self.add_log(f"PR0 VELOCITY START: {rpm} rpm")
        except Exception as e:
            QMessageBox.critical(self, "PR0", str(e))

    def closeEvent(self, event):
        if self.scan_worker is not None:
            self.scan_worker.stop()
        self.jog_timer.stop()
        self.telemetry_timer.stop()
        self.timed_stop.stop()
        self.cycle_timer.stop()
        self.mb.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
