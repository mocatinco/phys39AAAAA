
"""
Arduino Temperature + PWM Control GUI

This program:
    - Reads temperature/PWM/direction/time from the Arduino.
    - Displays the live measurements.
    - Plots temperature versus Arduino time.
    - Plots PWM versus Arduino time.
    - Uses red for HEAT and blue for COOL.
    - Provides a HEAT/COOL switch.
    - Provides a PWM slider.
    - Provides an editable PWM text box.
    - Keeps the slider and text box synchronized.
    - Sends commands to the Arduino.
    - Saves accepted measurements to CSV.

Arduino measurement format:

Temperature (C): 27.73, Time (ms): 645060,
PWM: 120, Active PWM pin: 9

Commands sent FROM Python TO Arduino:

SET PWM 120 DIR HEAT
SET PWM 45 DIR COOL

IMPORTANT:
The original Arduino sketch does not currently read commands.
The Arduino must be modified to process these commands for the
GUI controls to actually change the Arduino's output.
"""

# ============================================================
# SETTINGS
# ============================================================

SERIAL_PORT = "COM3"
BAUD_RATE = 9600

# How much data remains visible on the graphs.
WINDOW_SECONDS = 60

# How often the GUI checks for new serial data.
UPDATE_INTERVAL_MS = 100

# Temperature graph limits.
TEMP_MIN = 0
TEMP_MAX = 100

# PWM limits.
PWM_MIN = 0
PWM_MAX = 255

# CSV file used to save measurements.
CSV_FILENAME = "temperature_data.csv"


# ============================================================
# IMPORTS
# ============================================================

import csv
import re
import sys

import serial

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

import pyqtgraph as pg


# ============================================================
# SERIAL LINE PARSER
# ============================================================

# This matches the ACTUAL measurement format produced by
# the Arduino sketch.
LINE_PATTERN = re.compile(
    r"Temperature \(C\):\s*([-+]?\d+(?:\.\d+)?)"
    r",\s*Time \(ms\):\s*(\d+)"
    r",\s*PWM:\s*(\d+)"
    r",\s*Active PWM pin:\s*(\d+)"
)


def parse_arduino_line(line):
    """
    Parse one measurement line from the Arduino.

    Returns:
        time_s, temperature, pwm, heat_cool

    Returns None for malformed lines.
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

    # Arduino sends time in milliseconds.
    # Convert it to seconds.
    time_s = time_ms / 1000.0

    # Pin 9 means HEAT.
    # Pin 10 means COOL.
    if active_pin == 9:
        heat_cool = 0

    elif active_pin == 10:
        heat_cool = 1

    else:
        return None

    return time_s, temperature, pwm, heat_cool


# ============================================================
# CSV SETUP
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

except serial.SerialException as error:

    print(f"Could not open {SERIAL_PORT}: {error}")

    csv_file.close()
    sys.exit(1)


# ============================================================
# MAIN GUI WINDOW
# ============================================================

class TemperatureWindow(QMainWindow):

    def __init__(self):

        super().__init__()

        self.setWindowTitle(
            "Arduino Temperature and PWM Control"
        )

        self.resize(1100, 750)

        # ----------------------------------------------------
        # Main layout
        # ----------------------------------------------------

        main_layout = QVBoxLayout()

        # ====================================================
        # CONTROL WIDGETS
        # ====================================================

        control_layout = QHBoxLayout()

        # ----------------------------------------------------
        # HEAT / COOL SWITCH
        # ----------------------------------------------------

        self.direction_button = QPushButton("HEAT")

        self.direction_button.setCheckable(True)

        # HEAT is the initial state.
        self.direction_button.setChecked(True)

        self.direction_button.setStyleSheet(
            """
            QPushButton {
                background-color: red;
                color: white;
                font-weight: bold;
                padding: 8px;
            }

            QPushButton:checked {
                background-color: red;
                color: white;
            }
            """
        )

        # Clicking the button changes between HEAT and COOL.
        self.direction_button.clicked.connect(
            self.direction_changed
        )

        control_layout.addWidget(
            QLabel("Direction:")
        )

        control_layout.addWidget(
            self.direction_button
        )

        # ----------------------------------------------------
        # PWM SLIDER
        # ----------------------------------------------------

        # Slider allows PWM values from 0 to 255.
        self.pwm_slider = QSlider(Qt.Horizontal)

        self.pwm_slider.setMinimum(PWM_MIN)
        self.pwm_slider.setMaximum(PWM_MAX)
        self.pwm_slider.setValue(0)

        # Whenever the slider moves, update the text box.
        self.pwm_slider.valueChanged.connect(
            self.slider_changed
        )

        control_layout.addWidget(
            QLabel("PWM:")
        )

        control_layout.addWidget(
            self.pwm_slider
        )

        # ----------------------------------------------------
        # EDITABLE PWM TEXT BOX
        # ----------------------------------------------------

        # The user can type a PWM value directly.
        self.pwm_text = QLineEdit("0")

        self.pwm_text.setFixedWidth(60)

        # When the user finishes typing, process the value.
        self.pwm_text.editingFinished.connect(
            self.text_pwm_changed
        )

        control_layout.addWidget(
            self.pwm_text
        )

        # ----------------------------------------------------
        # SEND BUTTON
        # ----------------------------------------------------

        # Pressing this button sends the current PWM and
        # direction to the Arduino.
        self.send_button = QPushButton("Send")

        self.send_button.clicked.connect(
            self.send_command
        )

        control_layout.addWidget(
            self.send_button
        )

        main_layout.addLayout(
            control_layout
        )

        # ====================================================
        # LIVE VALUE DISPLAYS
        # ====================================================

        values_layout = QHBoxLayout()

        # Live temperature display.
        self.temperature_label = QLabel(
            "Temperature: -- °C"
        )

        # Live PWM display.
        self.live_pwm_label = QLabel(
            "PWM: --"
        )

        # Live direction display.
        self.direction_label = QLabel(
            "Direction: --"
        )

        # Live Arduino time display.
        self.time_label = QLabel(
            "Time: -- s"
        )

        values_layout.addWidget(
            self.temperature_label
        )

        values_layout.addWidget(
            self.live_pwm_label
        )

        values_layout.addWidget(
            self.direction_label
        )

        values_layout.addWidget(
            self.time_label
        )

        main_layout.addLayout(
            values_layout
        )

        # ====================================================
        # TEMPERATURE PLOT
        # ====================================================

        self.temperature_plot = pg.PlotWidget()

        self.temperature_plot.setTitle(
            "Temperature"
        )

        self.temperature_plot.setLabel(
            "left",
            "Temperature",
            units="°C"
        )

        self.temperature_plot.setLabel(
            "bottom",
            "Arduino Time",
            units="s"
        )

        self.temperature_plot.setYRange(
            TEMP_MIN,
            TEMP_MAX
        )

        self.temperature_plot.showGrid(
            x=True,
            y=True,
            alpha=0.3
        )

        main_layout.addWidget(
            self.temperature_plot
        )

        # ====================================================
        # PWM PLOT
        # ====================================================

        self.pwm_plot = pg.PlotWidget()

        self.pwm_plot.setTitle(
            "PWM"
        )

        self.pwm_plot.setLabel(
            "left",
            "PWM"
        )

        self.pwm_plot.setLabel(
            "bottom",
            "Arduino Time",
            units="s"
        )

        self.pwm_plot.setYRange(
            PWM_MIN,
            PWM_MAX
        )

        self.pwm_plot.showGrid(
            x=True,
            y=True,
            alpha=0.3
        )

        main_layout.addWidget(
            self.pwm_plot
        )

        # ====================================================
        # GRAPH DATA
        # ====================================================

        self.times = []
        self.temperatures = []
        self.pwms = []
        self.directions = []

        # Separate temperature curves are used so that:
        #     HEAT = red
        #     COOL = blue
        #
        # A None value creates a break in the line.
        self.heat_temperature = []
        self.cool_temperature = []

        # PWM curves.
        self.heat_pwm = []
        self.cool_pwm = []

        # ====================================================
        # TEMPERATURE CURVES
        # ====================================================

        self.heat_curve = self.temperature_plot.plot(
            pen=pg.mkPen(
                color="red",
                width=2
            )
        )

        self.cool_curve = self.temperature_plot.plot(
            pen=pg.mkPen(
                color="blue",
                width=2
            )
        )

        # ====================================================
        # PWM CURVES
        # ====================================================

        self.heat_pwm_curve = self.pwm_plot.plot(
            pen=pg.mkPen(
                color="red",
                width=2
            )
        )

        self.cool_pwm_curve = self.pwm_plot.plot(
            pen=pg.mkPen(
                color="blue",
                width=2
            )
        )

        # ====================================================
        # SET MAIN WIDGET
        # ====================================================

        central_widget = QWidget()

        central_widget.setLayout(
            main_layout
        )

        self.setCentralWidget(
            central_widget
        )

        # ====================================================
        # SERIAL READ TIMER
        # ====================================================

        self.timer = QTimer()

        self.timer.timeout.connect(
            self.read_serial
        )

        self.timer.start(
            UPDATE_INTERVAL_MS
        )


    # ========================================================
    # DIRECTION SWITCH
    # ========================================================

    def direction_changed(self):
        """
        Change the GUI between HEAT and COOL.

        This does not automatically implement feedback
        control. It only changes the selected direction.
        """

        if self.direction_button.isChecked():

            self.direction_button.setText(
                "HEAT"
            )

            self.direction_button.setStyleSheet(
                """
                QPushButton {
                    background-color: red;
                    color: white;
                    font-weight: bold;
                    padding: 8px;
                }
                """
            )

        else:

            self.direction_button.setText(
                "COOL"
            )

            self.direction_button.setStyleSheet(
                """
                QPushButton {
                    background-color: blue;
                    color: white;
                    font-weight: bold;
                    padding: 8px;
                }
                """
            )


    # ========================================================
    # SLIDER CHANGED
    # ========================================================

    def slider_changed(self, value):
        """
        Keep the editable PWM text box synchronized
        with the slider.
        """

        self.pwm_text.setText(
            str(value)
        )


    # ========================================================
    # TEXT PWM CHANGED
    # ========================================================

    def text_pwm_changed(self):
        """
        Read the PWM value typed by the user.

        The value is clamped to 0-255.
        """

        try:

            value = int(
                self.pwm_text.text()
            )

        except ValueError:

            # If the user typed something that is not a
            # number, restore the slider value.
            value = self.pwm_slider.value()

        # Clamp the value to the legal PWM range.
        value = max(
            PWM_MIN,
            min(PWM_MAX, value)
        )

        # Update both controls.
        self.pwm_slider.setValue(
            value
        )

        self.pwm_text.setText(
            str(value)
        )


    # ========================================================
    # SEND SERIAL COMMAND
    # ========================================================

    def send_command(self):
        """
        Send the selected PWM and direction to the Arduino.

        Commands have the required format:

            SET PWM 120 DIR HEAT

        or:

            SET PWM 45 DIR COOL
        """

        # Get PWM from the text box.
        try:

            pwm = int(
                self.pwm_text.text()
            )

        except ValueError:

            pwm = self.pwm_slider.value()

        # Clamp PWM to 0-255.
        pwm = max(
            PWM_MIN,
            min(PWM_MAX, pwm)
        )

        # Synchronize GUI controls.
        self.pwm_slider.setValue(
            pwm
        )

        self.pwm_text.setText(
            str(pwm)
        )

        # Determine direction.
        if self.direction_button.isChecked():

            direction = "HEAT"

        else:

            direction = "COOL"

        # Build the required command.
        command = (
            f"SET PWM {pwm} DIR {direction}\n"
        )

        try:

            # Send the command to the Arduino.
            serial_port.write(
                command.encode("utf-8")
            )

            print(
                f"Sent: SET PWM {pwm} DIR {direction}"
            )

        except serial.SerialException as error:

            print(
                f"Could not send command: {error}"
            )


    # ========================================================
    # READ ARDUINO DATA
    # ========================================================

    def read_serial(self):
        """
        Read measurement lines from the Arduino.

        Python does not echo the complete raw Arduino line.
        Only accepted/extracted values are printed.
        """

        while serial_port.in_waiting:

            try:

                raw_line = serial_port.readline()

                line = raw_line.decode(
                    "utf-8",
                    errors="ignore"
                ).strip()

            except Exception:

                continue

            # Try to parse the measurement.
            result = parse_arduino_line(
                line
            )

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
            # TERMINAL OUTPUT
            # ------------------------------------------------

            print(
                f"Temperature (C): {temperature:.2f}, "
                f"Time (s): {time_s:.2f}, "
                f"PWM: {pwm}, "
                f"Heat/Cool: {heat_cool}"
            )

            # ------------------------------------------------
            # UPDATE LIVE DISPLAYS
            # ------------------------------------------------

            self.temperature_label.setText(
                f"Temperature: {temperature:.2f} °C"
            )

            self.live_pwm_label.setText(
                f"PWM: {pwm}"
            )

            if heat_cool == 1:

                self.direction_label.setText(
                    "Direction: HEAT"
                )

            else:

                self.direction_label.setText(
                    "Direction: COOL"
                )

            self.time_label.setText(
                f"Time: {time_s:.2f} s"
            )

            # ------------------------------------------------
            # SAVE TO CSV
            # ------------------------------------------------

            csv_writer.writerow([
                time_s,
                temperature,
                pwm,
                heat_cool
            ])

            csv_file.flush()

            # ------------------------------------------------
            # STORE DATA
            # ------------------------------------------------

            self.times.append(
                time_s
            )

            self.temperatures.append(
                temperature
            )

            self.pwms.append(
                pwm
            )

            self.directions.append(
                heat_cool
            )

            # ------------------------------------------------
            # ROLLING WINDOW
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
                self.pwms.pop(0)
                self.directions.pop(0)

            # ------------------------------------------------
            # UPDATE PLOTS
            # ------------------------------------------------

            self.update_plots()


    # ========================================================
    # UPDATE PLOTS
    # ========================================================

    def update_plots(self):
        """
        Update both strip charts.

        Temperature:
            HEAT = solid red
            COOL = solid blue

        PWM:
            HEAT = red
            COOL = blue
        """

        if len(self.times) == 0:
            return

        # ----------------------------------------------------
        # Create separate HEAT and COOL data.
        # ----------------------------------------------------

        heat_temperature = []
        cool_temperature = []

        heat_pwm = []
        cool_pwm = []

        for i in range(len(self.times)):

            if self.directions[i] == 1:

                heat_temperature.append(
                    self.temperatures[i]
                )

                cool_temperature.append(
                    float("nan")
                )

                heat_pwm.append(
                    self.pwms[i]
                )

                cool_pwm.append(
                    float("nan")
                )

            else:

                heat_temperature.append(
                    float("nan")
                )

                cool_temperature.append(
                    self.temperatures[i]
                )

                heat_pwm.append(
                    float("nan")
                )

                cool_pwm.append(
                    self.pwms[i]
                )

        # ----------------------------------------------------
        # Update temperature plot.
        # ----------------------------------------------------

        self.heat_curve.setData(
            self.times,
            heat_temperature
        )

        self.cool_curve.setData(
            self.times,
            cool_temperature
        )

        # ----------------------------------------------------
        # Update PWM plot.
        # ----------------------------------------------------

        self.heat_pwm_curve.setData(
            self.times,
            heat_pwm
        )

        self.cool_pwm_curve.setData(
            self.times,
            cool_pwm
        )

        # ----------------------------------------------------
        # Keep both plots focused on the rolling window.
        # ----------------------------------------------------

        if len(self.times) >= 2:

            left_edge = max(
                0,
                self.times[-1] - WINDOW_SECONDS
            )

            right_edge = self.times[-1]

            if right_edge <= left_edge:
                right_edge = left_edge + 1

            self.temperature_plot.setXRange(
                left_edge,
                right_edge,
                padding=0
            )

            self.pwm_plot.setXRange(
                left_edge,
                right_edge,
                padding=0
            )


    # ========================================================
    # CLOSE PROGRAM
    # ========================================================

    def closeEvent(self, event):
        """
        Close the timer, serial connection, and CSV file.
        """

        self.timer.stop()

        if serial_port.is_open:
            serial_port.close()

        csv_file.close()

        event.accept()


# ============================================================
# START APPLICATION
# ============================================================

app = QApplication(sys.argv)

window = TemperatureWindow()

window.show()

sys.exit(app.exec())
