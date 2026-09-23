
"""
Arduino Temperature Monitor

Reads the actual serial format produced by the Arduino sketch:

Temperature (C): 27.73, Time (ms): 645060, PWM: 120, Active PWM pin: 9

The program:
    - Reads measurements from COM3.
    - Ignores malformed lines.
    - Converts Arduino milliseconds to seconds.
    - Converts PWM pin 9/10 into Heat/Cool = 1/0.
    - Displays accepted measurements.
    - Plots temperature versus Arduino time.
    - Keeps a rolling graph window.
    - Saves accepted measurements to CSV.
    - Never sends commands to the Arduino.
"""

# ============================================================
# SETTINGS
# ============================================================

SERIAL_PORT = "COM3"
BAUD_RATE = 9600

WINDOW_SECONDS = 60
UPDATE_INTERVAL_MS = 100

TEMP_MIN = 0
TEMP_MAX = 100

CSV_FILENAME = "temperature_data.csv"


# ============================================================
# IMPORTS
# ============================================================

import csv
import re
import sys

import serial

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMainWindow

import pyqtgraph as pg


# ============================================================
# SERIAL LINE PARSER
# ============================================================

# Matches the ACTUAL Arduino output:
#
# Temperature (C): 27.73, Time (ms): 645060,
# PWM: 120, Active PWM pin: 9

LINE_PATTERN = re.compile(
    r"Temperature \(C\):\s*([-+]?\d+(?:\.\d+)?)"
    r",\s*Time \(ms\):\s*(\d+)"
    r",\s*PWM:\s*(\d+)"
    r",\s*Active PWM pin:\s*(\d+)"
)


def parse_arduino_line(line):
    """
    Convert one Arduino serial line into:

        time_s
        temperature
        pwm
        heat_cool

    Returns None if the line is malformed.
    """

    match = LINE_PATTERN.fullmatch(line.strip())

    if match is None:
        return None

    try:
        temperature = float(match.group(1))
        time_ms = int(match.group(2))
        pwm = int(match.group(3))
        active_pin = int(match.group(4))

    except ValueError:
        return None

    # Convert milliseconds to seconds.
    time_s = time_ms / 1000.0

    # Arduino pin 9 = Cool
    # Arduino pin 10 = Heat
    if active_pin == 9:
        heat_cool = 0

    elif active_pin == 10:
        heat_cool = 1

    else:
        return None

    return time_s, temperature, pwm, heat_cool


# ============================================================
# CSV FILE
# ============================================================

csv_file = open(
    CSV_FILENAME,
    "w",
    newline="",
    encoding="utf-8"
)

csv_writer = csv.writer(csv_file)

csv_writer.writerow([
    "time_s",
    "temperature_C",
    "pwm",
    "heat_cool"
])

csv_file.flush()


# ============================================================
# SERIAL CONNECTION
# ============================================================

try:

    serial_port = serial.Serial(
        SERIAL_PORT,
        BAUD_RATE,
        timeout=0.05
    )

    print(f"Connected to Arduino on {SERIAL_PORT}")
    print("Waiting for measurements...")

except serial.SerialException as error:

    print()
    print("Could not open the Arduino serial port.")
    print(f"Port: {SERIAL_PORT}")
    print(f"Error: {error}")
    print()
    print("Make sure:")
    print("  1. Arduino is connected.")
    print("  2. COM3 is the correct port.")
    print("  3. Arduino Serial Monitor is closed.")
    print("  4. No other program is using COM3.")

    csv_file.close()
    #sys.exit(1)


# ============================================================
# MAIN WINDOW
# ============================================================

class TemperatureWindow(QMainWindow):

    def __init__(self):

        super().__init__()

        self.setWindowTitle(
            "Arduino Temperature Monitor"
        )

        self.resize(900, 600)

        # ----------------------------------------------------
        # Create graph
        # ----------------------------------------------------

        self.plot_widget = pg.PlotWidget()

        self.plot_widget.setLabel(
            "left",
            "Temperature",
            units="°C"
        )

        self.plot_widget.setLabel(
            "bottom",
            "Arduino Time",
            units="s"
        )

        self.plot_widget.showGrid(
            x=True,
            y=True,
            alpha=0.3
        )

        self.plot_widget.setYRange(
            TEMP_MIN,
            TEMP_MAX
        )

        self.plot_curve = self.plot_widget.plot(
            pen=pg.mkPen(
                color="yellow",
                width=2
            )
        )

        self.setCentralWidget(
            self.plot_widget
        )

        # ----------------------------------------------------
        # Data storage
        # ----------------------------------------------------

        self.times = []
        self.temperatures = []

        # ----------------------------------------------------
        # Number of accepted measurements
        # ----------------------------------------------------

        self.measurement_count = 0

        # ----------------------------------------------------
        # Start timer
        # ----------------------------------------------------

        self.timer = QTimer()

        self.timer.timeout.connect(
            self.read_serial
        )

        self.timer.start(
            UPDATE_INTERVAL_MS
        )

    # ========================================================
    # READ SERIAL DATA
    # ========================================================

    def read_serial(self):

        while serial_port.in_waiting:

            try:

                raw_line = serial_port.readline()

                line = raw_line.decode(
                    "utf-8",
                    errors="ignore"
                ).strip()

            except Exception:
                continue

            # ------------------------------------------------
            # Try to parse the line.
            # ------------------------------------------------

            result = parse_arduino_line(line)

            # Ignore malformed lines.
            if result is None:
                continue

            (
                time_s,
                temperature,
                pwm,
                heat_cool
            ) = result

            # ------------------------------------------------
            # We successfully received a measurement.
            # ------------------------------------------------

            self.measurement_count += 1

            print(
                f"Temperature (C): {temperature:.2f}, "
                f"Time (s): {time_s:.2f}, "
                f"PWM: {pwm}, "
                f"Heat/Cool: {heat_cool}"
            )

            # ------------------------------------------------
            # Save to CSV.
            # ------------------------------------------------

            csv_writer.writerow([
                time_s,
                temperature,
                pwm,
                heat_cool
            ])

            csv_file.flush()

            # ------------------------------------------------
            # Add data to graph.
            # ------------------------------------------------

            self.times.append(time_s)
            self.temperatures.append(temperature)

            # ------------------------------------------------
            # Remove old data.
            # ------------------------------------------------

            newest_time = self.times[-1]

            oldest_allowed = (
                newest_time - WINDOW_SECONDS
            )

            while (
                self.times
                and self.times[0] < oldest_allowed
            ):

                self.times.pop(0)
                self.temperatures.pop(0)

            # ------------------------------------------------
            # Update graph.
            # ------------------------------------------------

            if len(self.times) >= 1:

                self.plot_curve.setData(
                    self.times,
                    self.temperatures
                )

                # Only set the X range if the time values
                # are valid and there is more than one point.

                if len(self.times) >= 2:

                    first_time = self.times[0]
                    last_time = self.times[-1]

                    if (
                        first_time == first_time
                        and last_time == last_time
                        and last_time >= first_time
                    ):

                        # If there is less than one window of
                        # data, start the graph at the first point.

                        left_edge = max(
                            0,
                            last_time - WINDOW_SECONDS
                        )

                        right_edge = last_time

                        # Avoid a zero-width X range when the
                        # first and last timestamps are equal.

                        if right_edge <= left_edge:

                            right_edge = (
                                left_edge + 1
                            )

                        self.plot_widget.setXRange(
                            left_edge,
                            right_edge,
                            padding=0
                        )


    # ========================================================
    # CLEANUP
    # ========================================================

    def closeEvent(self, event):

        self.timer.stop()

        if serial_port.is_open:
            serial_port.close()

        csv_file.close()

        print()
        print(
            f"Saved {self.measurement_count} "
            f"measurements to {CSV_FILENAME}"
        )

        event.accept()


# ============================================================
# START APPLICATION
# ============================================================

app = QApplication(sys.argv)

window = TemperatureWindow()

window.show()

sys.exit(app.exec())
