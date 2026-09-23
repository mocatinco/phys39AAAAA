"""Display-only Arduino temperature monitor.

This script reads the measurement lines produced by the Arduino sketch in
Lab3/Lab3Codes/lab3part3.ino, ignores malformed lines, and plots only
temperature versus Arduino time.

The parser is intentionally strict: it accepts only the serial format printed by
that sketch and ignores anything else.
"""

import csv
import os
import re
import sys

import pyqtgraph as pg
import serial
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QMessageBox, QVBoxLayout, QWidget

# ---------------------------------------------------------------------------
# User settings: change these near the top of the file before running.
# ---------------------------------------------------------------------------
SERIAL_PORT = "COM3"
BAUD_RATE = 9600
WINDOW_DURATION_S = 60.0
UPDATE_INTERVAL_MS = 100
TEMP_MIN_C = 0.0
TEMP_MAX_C = 60.0
CSV_FILENAME = "arduino_measurements.csv"
# ---------------------------------------------------------------------------

# This must match the Arduino sketch exactly.
MEASUREMENT_PATTERN = re.compile(
    r"^Temperature \(C\):\s*(?P<temperature>[+-]?\d+(?:\.\d+)?)\s*,\s*"
    r"Time \(ms\):\s*(?P<time_ms>[+-]?\d+(?:\.\d+)?)\s*,\s*"
    r"PWM:\s*(?P<pwm>\d+)\s*,\s*"
    r"Active PWM pin:\s*(?P<pin>9|10)\s*$"
)


# ---------------------------------------------------------------------------
# Serial parsing
# ---------------------------------------------------------------------------
def parse_measurement_line(raw_line):
    """Return a cleaned dictionary for a valid Arduino measurement line.

    Example valid line from the sketch:
    Temperature (C): 27.73, Time (ms): 645.06, PWM: 120, Active PWM pin: 9
    """
    text = raw_line.decode("utf-8", errors="replace").strip()
    if not text:
        return None

    match = MEASUREMENT_PATTERN.match(text)
    if match is None:
        return None

    try:
        temperature_c = float(match.group("temperature"))
        time_ms = float(match.group("time_ms"))
        pwm = int(match.group("pwm"))
        pin_number = int(match.group("pin"))
    except ValueError:
        return None

    # The Arduino code uses pin 9 for one direction and pin 10 for the opposite.
    # We translate that into 1 for heat and 0 for cool for the printout.
    heat_cool = 1 if pin_number == 9 else 0

    return {
        "temperature_C": temperature_c,
        "time_s": time_ms / 1000.0,
        "pwm": pwm,
        "heat_cool": heat_cool,
    }


# ---------------------------------------------------------------------------
# CSV saving
# ---------------------------------------------------------------------------
def append_csv_row(row):
    """Append accepted values to a CSV file with the requested columns."""
    file_exists = os.path.exists(CSV_FILENAME)

    with open(CSV_FILENAME, "a", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=["time_s", "temperature_C", "pwm", "heat_cool"],
        )

        if not file_exists:
            writer.writeheader()
            print(f"CSV file created: {CSV_FILENAME}")

        writer.writerow(
            {
                "time_s": float(row["time_s"]),
                "temperature_C": float(row["temperature_C"]),
                "pwm": int(row["pwm"]),
                "heat_cool": int(row["heat_cool"]),
            }
        )


# ---------------------------------------------------------------------------
# GUI window
# ---------------------------------------------------------------------------
class TemperatureMonitorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Arduino Temperature Monitor")
        self.resize(900, 600)

        self.serial_port = None
        self.times = []
        self.temperatures = []

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)

        # Small status line near the top of the window.
        self.status_label = QLabel("Waiting for serial data...")
        self.status_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.status_label)

        # Plot only temperature versus Arduino time.
        self.plot_widget = pg.PlotWidget(title="Temperature vs. Arduino Time")
        self.plot_widget.setLabel("left", "Temperature (C)")
        self.plot_widget.setLabel("bottom", "Time (s)")
        self.plot_widget.setYRange(TEMP_MIN_C, TEMP_MAX_C)
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_curve = self.plot_widget.plot([], [], pen=pg.mkPen("#00aaff", width=2))
        layout.addWidget(self.plot_widget)

        # Open serial port without sending commands.
        self.open_serial_port()

        self.timer = QTimer(self)
        self.timer.setInterval(UPDATE_INTERVAL_MS)
        self.timer.timeout.connect(self.poll_serial)
        self.timer.start()

    def open_serial_port(self):
        """Open the serial port in read-only mode."""
        try:
            self.serial_port = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.05)
            self.status_label.setText(f"Connected on {SERIAL_PORT} at {BAUD_RATE} baud")
        except serial.SerialException as exc:
            self.status_label.setText(
                f"Could not open {SERIAL_PORT}. Check the port name and cable. Error: {exc}"
            )
            self.serial_port = None
            QMessageBox.warning(
                self,
                "Serial Port Error",
                f"Unable to open {SERIAL_PORT}.\n\n{exc}",
            )

    def poll_serial(self):
        """Read lines and accept only valid measurement records."""
        if self.serial_port is None or not self.serial_port.is_open():
            return

        while True:
            raw_line = self.serial_port.readline()
            if not raw_line:
                break

            parsed = parse_measurement_line(raw_line)
            if parsed is None:
                # Malformed lines are ignored intentionally.
                continue

            temp_c = parsed["temperature_C"]
            time_s = parsed["time_s"]
            pwm = parsed["pwm"]
            heat_cool = parsed["heat_cool"]

            # Print only the extracted values requested by the assignment.
            print(
                f"Temperature (C): {temp_c:.2f}, "
                f"Time (s): {time_s:.2f}, "
                f"PWM: {pwm}, "
                f"Heat/Cool: {heat_cool}"
            )

            append_csv_row(parsed)
            self.status_label.setText(
                f"Accepted reading: T={temp_c:.2f} C, time={time_s:.2f} s, PWM={pwm}, heat/cool={heat_cool}"
            )
            self.add_plot_point(time_s, temp_c)

    def add_plot_point(self, time_s, temperature_c):
        """Store the newest point and keep a rolling time window."""
        self.times.append(time_s)
        self.temperatures.append(temperature_c)

        cutoff_time = self.times[-1] - WINDOW_DURATION_S
        while self.times and self.times[0] < cutoff_time:
            self.times.pop(0)
            self.temperatures.pop(0)

        self.plot_curve.setData(self.times, self.temperatures)
        self.plot_widget.setYRange(TEMP_MIN_C, TEMP_MAX_C)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TemperatureMonitorWindow()
    window.show()
    sys.exit(app.exec())

