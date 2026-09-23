
"""
Arduino Temperature + PWM Control GUI

Python communicates with the Arduino over COM3.

Python receives measurements such as:

Temperature (C): 27.73, Time (s): 645.06,
PWM: 120, Heat/Cool: 1

Python sends commands such as:

SET PWM 120 DIR HEAT
SET PWM 45 DIR COOL

The program:
    - Displays live temperature
    - Displays live PWM
    - Displays live direction
    - Displays Arduino time
    - Plots temperature
    - Plots PWM
    - Uses red for HEAT
    - Uses blue for COOL
    - Saves measurements to CSV
    - Allows manual PWM control
    - Clamps PWM to 0-255
    - Does NOT implement feedback control
"""

# ============================================================
# SETTINGS
# ============================================================

SERIAL_PORT = "COM3"
BAUD_RATE = 9600

# How many seconds of data should remain visible
# on the graphs.
WINDOW_SECONDS = 60

# How often Python checks the serial port.
UPDATE_INTERVAL_MS = 100

# Temperature graph limits.
TEMP_MIN = 0
TEMP_MAX = 100

# PWM limits.
PWM_MIN = 0
PWM_MAX = 255

# CSV output file.
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
# ARDUINO MEASUREMENT PARSER
# ============================================================

"""
This regular expression matches the Arduino's actual
measurement format:

Temperature (C): 27.73, Time (s): 645.06,
PWM: 120, Heat/Cool: 1

Malformed lines are ignored.
"""

LINE_PATTERN = re.compile(
    r"Temperature \(C\):\s*([-+]?\d+(?:\.\d+)?)"
    r",\s*Time \(s\):\s*([-+]?\d+(?:\.\d+)?)"
    r",\s*PWM:\s*(\d+)"
    r",\s*Heat/Cool:\s*([01])"
)


def parse_arduino_line(line):
    """
    Parse one measurement line from the Arduino.

    Returns:

        time_s
        temperature
        pwm
        heat_cool

    Returns None if the line is malformed.
    """

    match = LINE_PATTERN.fullmatch(
        line.strip()
    )

    if match is None:
        return None

    try:
        temperature = float(match.group(1))
        time_s = float(match.group(2))
        pwm = int(match.group(3))
        heat_cool = int(match.group(4))

    except ValueError:
        return None

    # Extra safety: make sure PWM is inside
    # the expected Arduino range.
    pwm = max(
        PWM_MIN,
        min(PWM_MAX, pwm)
    )

    return (
        time_s,
        temperature,
        pwm,
        heat_cool
    )


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

    print(
        f"Connected to Arduino on {SERIAL_PORT}"
    )

except serial.SerialException as error:

    print(
        f"Could not open {SERIAL_PORT}: {error}"
    )

    csv_file.close()

    sys.exit(1)


# ============================================================
# MAIN WINDOW
# ============================================================

class ArduinoWindow(QMainWindow):

    def __init__(self):

        super().__init__()

        self.setWindowTitle(
            "Arduino Temperature + PWM Control"
        )

        self.resize(
            1100,
            800
        )

        # ====================================================
        # MAIN LAYOUT
        # ====================================================

        main_layout = QVBoxLayout()


        # ====================================================
        # CONTROL ROW
        # ====================================================

        control_layout = QHBoxLayout()


        # ----------------------------------------------------
        # HEAT / COOL BUTTON
        # ----------------------------------------------------

        control_layout.addWidget(
            QLabel("Direction:")
        )

        self.direction_button = QPushButton(
            "HEAT"
        )

        self.direction_button.setCheckable(
            True
        )

        # Start in HEAT mode.
        self.direction_button.setChecked(
            True
        )

        self.update_direction_button()

        self.direction_button.clicked.connect(
            self.direction_changed
        )

        control_layout.addWidget(
            self.direction_button
        )


        # ----------------------------------------------------
        # PWM SLIDER
        # ----------------------------------------------------

        control_layout.addWidget(
            QLabel("PWM:")
        )

        self.pwm_slider = QSlider(
            Qt.Horizontal
        )

        self.pwm_slider.setMinimum(
            PWM_MIN
        )

        self.pwm_slider.setMaximum(
            PWM_MAX
        )

        # Start at PWM = 0.
        self.pwm_slider.setValue(0)

        self.pwm_slider.valueChanged.connect(
            self.slider_changed
        )

        control_layout.addWidget(
            self.pwm_slider
        )


        # ----------------------------------------------------
        # PWM TEXT BOX
        # ----------------------------------------------------

        self.pwm_text = QLineEdit("0")

        self.pwm_text.setFixedWidth(60)

        self.pwm_text.editingFinished.connect(
            self.text_pwm_changed
        )

        control_layout.addWidget(
            self.pwm_text
        )


        # ----------------------------------------------------
        # SEND BUTTON
        # ----------------------------------------------------

        self.send_button = QPushButton(
            "Send"
        )

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
        # LIVE DATA DISPLAY
        # ====================================================

        live_layout = QHBoxLayout()


        self.temperature_label = QLabel(
            "Temperature: -- °C"
        )

        self.time_label = QLabel(
            "Time: -- s"
        )

        self.live_pwm_label = QLabel(
            "PWM: --"
        )

        self.direction_label = QLabel(
            "Direction: --"
        )


        live_layout.addWidget(
            self.temperature_label
        )

        live_layout.addWidget(
            self.time_label
        )

        live_layout.addWidget(
            self.live_pwm_label
        )

        live_layout.addWidget(
            self.direction_label
        )


        main_layout.addLayout(
            live_layout
        )


        # ====================================================
        # TEMPERATURE PLOT
        # ====================================================

        self.temperature_plot = pg.PlotWidget()

        self.temperature_plot.setTitle(
            "Temperature vs Arduino Time"
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


        # Red = heating.
        self.heat_temperature_curve = (
            self.temperature_plot.plot(
                pen=pg.mkPen(
                    color="red",
                    width=2
                )
            )
        )


        # Blue = cooling.
        self.cool_temperature_curve = (
            self.temperature_plot.plot(
                pen=pg.mkPen(
                    color="blue",
                    width=2
                )
            )
        )


        main_layout.addWidget(
            self.temperature_plot
        )


        # ====================================================
        # PWM PLOT
        # ====================================================

        self.pwm_plot = pg.PlotWidget()

        self.pwm_plot.setTitle(
            "PWM vs Arduino Time"
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


        # Red = HEAT.
        self.heat_pwm_curve = (
            self.pwm_plot.plot(
                pen=pg.mkPen(
                    color="red",
                    width=2
                )
            )
        )


        # Blue = COOL.
        self.cool_pwm_curve = (
            self.pwm_plot.plot(
                pen=pg.mkPen(
                    color="blue",
                    width=2
                )
            )
        )


        main_layout.addWidget(
            self.pwm_plot
        )


        # ====================================================
        # DATA ARRAYS
        # ====================================================

        self.times = []

        self.temperatures = []

        self.pwms = []

        self.directions = []


        # ====================================================
        # SET MAIN WINDOW WIDGET
        # ====================================================

        central_widget = QWidget()

        central_widget.setLayout(
            main_layout
        )

        self.setCentralWidget(
            central_widget
        )


        # ====================================================
        # SERIAL UPDATE TIMER
        # ====================================================

        self.timer = QTimer()

        self.timer.timeout.connect(
            self.read_serial
        )

        self.timer.start(
            UPDATE_INTERVAL_MS
        )


    # ========================================================
    # UPDATE HEAT / COOL BUTTON APPEARANCE
    # ========================================================

    def update_direction_button(self):
        """
        Change the button color and text.

        Red = HEAT
        Blue = COOL
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
    # DIRECTION BUTTON
    # ========================================================

    def direction_changed(self):
        """
        Update the GUI when HEAT/COOL is selected.

        The Arduino is not changed until the user presses
        the Send button.
        """

        self.update_direction_button()


    # ========================================================
    # PWM SLIDER
    # ========================================================

    def slider_changed(self, value):
        """
        Keep the PWM text box synchronized with
        the slider.
        """

        self.pwm_text.setText(
            str(value)
        )


    # ========================================================
    # PWM TEXT BOX
    # ========================================================

    def text_pwm_changed(self):
        """
        Read the PWM typed by the user.

        Values are clamped to 0-255.
        """

        try:

            value = int(
                self.pwm_text.text()
            )

        except ValueError:

            # Restore the current slider value
            # if the text isn't a number.
            value = self.pwm_slider.value()


        # Clamp to 0-255.
        value = max(
            PWM_MIN,
            min(PWM_MAX, value)
        )


        # Synchronize both controls.
        self.pwm_slider.setValue(
            value
        )

        self.pwm_text.setText(
            str(value)
        )


    # ========================================================
    # SEND COMMAND TO ARDUINO
    # ========================================================

    def send_command(self):
        """
        Send the PWM and direction to the Arduino.

        Example:

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


        # Clamp PWM.
        pwm = max(
            PWM_MIN,
            min(PWM_MAX, pwm)
        )


        # Synchronize GUI.
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


        # Build the command exactly as required.
        command = (
            f"SET PWM {pwm} DIR {direction}\n"
        )


        try:

            # Send command to Arduino.
            serial_port.write(
                command.encode("utf-8")
            )

            # Print only the command we intentionally sent.
            print(
                f"Sent: SET PWM {pwm} DIR {direction}"
            )

        except serial.SerialException as error:

            print(
                f"Serial send error: {error}"
            )


    # ========================================================
    # READ SERIAL DATA
    # ========================================================

    def read_serial(self):
        """
        Read measurement lines from Arduino.

        Malformed lines are ignored.
        """

        while serial_port.in_waiting:

            try:

                raw_line = (
                    serial_port.readline()
                )

                line = raw_line.decode(
                    "utf-8",
                    errors="ignore"
                ).strip()

            except Exception:

                continue


            # Parse the measurement.
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


            # =================================================
            # TERMINAL OUTPUT
            # =================================================

            print(
                f"Temperature (C): {temperature:.2f}, "
                f"Time (s): {time_s:.2f}, "
                f"PWM: {pwm}, "
                f"Heat/Cool: {heat_cool}"
            )


            # =================================================
            # LIVE GUI VALUES
            # =================================================

            self.temperature_label.setText(
                f"Temperature: {temperature:.2f} °C"
            )

            self.time_label.setText(
                f"Time: {time_s:.2f} s"
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


            # =================================================
            # CSV LOGGING
            # =================================================

            csv_writer.writerow([
                time_s,
                temperature,
                pwm,
                heat_cool
            ])

            csv_file.flush()


            # =================================================
            # STORE DATA FOR PLOTS
            # =================================================

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


            # =================================================
            # REMOVE OLD DATA
            # =================================================

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


            # =================================================
            # UPDATE GRAPHS
            # =================================================

            self.update_plots()


    # ========================================================
    # UPDATE BOTH STRIP CHARTS
    # ========================================================

    def update_plots(self):
        """
        Update the temperature and PWM graphs.

        HEAT:
            red line

        COOL:
            blue line
        """

        if len(self.times) == 0:

            return


        # ----------------------------------------------------
        # Create separate HEAT and COOL data.
        #
        # NaN creates gaps so the red and blue lines
        # don't connect through a direction change.
        # ----------------------------------------------------

        heat_temperature = []
        cool_temperature = []

        heat_pwm = []
        cool_pwm = []


        for i in range(
            len(self.times)
        ):

            if self.directions[i] == 1:

                # HEAT
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

                # COOL
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

        self.heat_temperature_curve.setData(
            self.times,
            heat_temperature
        )

        self.cool_temperature_curve.setData(
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
        # Keep the plots focused on the rolling window.
        # ----------------------------------------------------

        if len(self.times) >= 2:

            left_edge = max(
                0,
                self.times[-1] - WINDOW_SECONDS
            )

            right_edge = self.times[-1]


            if right_edge <= left_edge:

                right_edge = (
                    left_edge + 1
                )


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
        Safely close the serial port and CSV file.
        """

        self.timer.stop()

        if serial_port.is_open:

            serial_port.close()

        csv_file.close()

        print(
            f"Data saved to {CSV_FILENAME}"
        )

        event.accept()


# ============================================================
# START GUI
# ============================================================

app = QApplication(
    sys.argv
)

window = ArduinoWindow()

window.show()

sys.exit(
    app.exec()
)

