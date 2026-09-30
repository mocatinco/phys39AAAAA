"""
Arduino Temperature + PWM Control GUI

Python communicates with the Arduino over COM3.

Arduino sends measurements such as:

Temperature (C): 27.73, Time (s): 645.06,
PWM: 120, Heat/Cool: 1

Python sends commands such as:

SET PWM 120 DIR HEAT
SET PWM 45 DIR COOL


============================================================
AUTOMATIC PROPORTIONAL TEMPERATURE CONTROL
============================================================

The controller uses:

    e = T_set - T

    u = Kp * e

Positive u:
    HEAT

Negative u:
    COOL

PWM magnitude:

    P = |u|

Therefore:

    +PWM = HEAT
    -PWM = COOL

At exactly the desired temperature:

    error = 0
    PWM = 0

If temperature moves away from the setpoint, the
controller automatically applies a small correction.

Heating and cooling have separate proportional gains
because the measured system response is very different
for heating and cooling.

The Arduino should perform the thermistor averaging:

    ~1000 raw voltage measurements
             ↓
        average voltage
             ↓
        voltage → temperature
             ↓
        send temperature to Python


============================================================
CONTROL PARAMETERS
============================================================
"""

# ============================================================
# SETTINGS
# ============================================================

SERIAL_PORT = "COM3"
BAUD_RATE = 9600

WINDOW_SECONDS = 60

UPDATE_INTERVAL_MS = 100


# ============================================================
# TEMPERATURE GRAPH
# ============================================================

TEMP_MIN = 0
TEMP_MAX = 100


# ============================================================
# PWM LIMITS
# ============================================================

PWM_MIN = 0
PWM_MAX = 255


# ============================================================
# SAFETY TEMPERATURE RANGE
# ============================================================

SAFE_TEMP_MIN = 0
SAFE_TEMP_MAX = 60


# ============================================================
# CSV FILE
# ============================================================

CSV_FILENAME = "temperature_data.csv"


# ============================================================
# DEFAULT DESIRED TEMPERATURE
# ============================================================

DEFAULT_DESIRED_TEMP = 25.0


# ============================================================
# PROPORTIONAL GAINS
# ============================================================

"""
Your measured equilibrium data showed approximately:

Heating:

    dT/dPWM ≈ +0.505 °C/PWM

Cooling:

    dT/dPWM ≈ -0.153 °C/PWM

Cooling is therefore substantially less sensitive than
heating.

The gains below are starting values.

If heating is too aggressive:
    reduce KP_HEAT.

If heating is too slow:
    increase KP_HEAT.

If cooling is too aggressive:
    reduce KP_COOL.

If cooling is too slow:
    increase KP_COOL.
"""

KP_HEAT = 8.0

KP_COOL = 20.0


# ============================================================
# SMALL TEMPERATURE DEAD BAND
# ============================================================

"""
Inside this very small range, PWM is set to zero.

This prevents rapid switching caused by tiny temperature
measurement fluctuations.

The deadband is intentionally small so the controller can
still make minor corrections around the desired temperature.
"""

TEMPERATURE_DEADBAND = 0.05


# ============================================================
# PWM SLEW LIMIT
# ============================================================

"""
Maximum change in PWM magnitude per controller update.

This prevents commands such as:

    0 → 100

from happening instantly.

Because UPDATE_INTERVAL_MS is 100 ms, a value of 10 means
PWM can change by at most approximately 10 counts per
100 ms update.
"""

MAX_PWM_CHANGE = 10


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
Expected Arduino line:

Temperature (C): 27.73, Time (s): 645.06,
PWM: 120, Heat/Cool: 1

Heat/Cool:

    1 = HEAT
    0 = COOL
"""

LINE_PATTERN = re.compile(
    r"Temperature \(C\):\s*([-+]?\d+(?:\.\d+)?)"
    r",\s*Time \(s\):\s*([-+]?\d+(?:\.\d+)?)"
    r",\s*PWM:\s*(\d+)"
    r",\s*Heat/Cool:\s*([01])"
)


def parse_arduino_line(line):
    """
    Parse one measurement line from Arduino.

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

        temperature = float(
            match.group(1)
        )

        time_s = float(
            match.group(2)
        )

        pwm = int(
            match.group(3)
        )

        heat_cool = int(
            match.group(4)
        )

    except ValueError:

        return None


    # Extra PWM safety clamp.

    pwm = max(
        PWM_MIN,
        min(
            PWM_MAX,
            pwm
        )
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

csv_writer = csv.writer(
    csv_file
)

csv_writer.writerow([
    "time_s",
    "temperature_C",
    "setpoint_C",
    "error_C",
    "pwm_signed",
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
            1150,
            1000
        )


        # ====================================================
        # CONTROLLER STATE
        # ====================================================

        self.desired_temperature = (
            DEFAULT_DESIRED_TEMP
        )

        self.auto_control = False

        self.temperature_safe = True

        # Signed PWM:

        # positive = HEAT
        # negative = COOL

        self.current_signed_pwm = 0


        # ====================================================
        # MAIN LAYOUT
        # ====================================================

        main_layout = QVBoxLayout()


        # ====================================================
        # MANUAL CONTROL ROW
        # ====================================================

        control_layout = QHBoxLayout()


        control_layout.addWidget(
            QLabel("Direction:")
        )


        self.direction_button = QPushButton(
            "HEAT"
        )

        self.direction_button.setCheckable(
            True
        )

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

        self.pwm_slider.setValue(
            0
        )


        self.pwm_slider.valueChanged.connect(
            self.slider_changed
        )


        control_layout.addWidget(
            self.pwm_slider
        )


        # ----------------------------------------------------
        # PWM TEXT
        # ----------------------------------------------------

        self.pwm_text = QLineEdit(
            "0"
        )

        self.pwm_text.setFixedWidth(
            60
        )


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
        # DESIRED TEMPERATURE ROW
        # ====================================================

        target_layout = QHBoxLayout()


        target_layout.addWidget(
            QLabel(
                "Desired Temperature:"
            )
        )


        self.desired_temperature_text = (
            QLineEdit(
                str(
                    DEFAULT_DESIRED_TEMP
                )
            )
        )


        self.desired_temperature_text.setFixedWidth(
            80
        )


        target_layout.addWidget(
            self.desired_temperature_text
        )


        target_layout.addWidget(
            QLabel("°C")
        )


        self.set_temperature_button = (
            QPushButton(
                "Set Desired Temp"
            )
        )


        self.set_temperature_button.clicked.connect(
            self.set_desired_temperature
        )


        target_layout.addWidget(
            self.set_temperature_button
        )


        self.desired_temperature_label = QLabel(
            f"Target: "
            f"{self.desired_temperature:.2f} °C"
        )


        target_layout.addWidget(
            self.desired_temperature_label
        )


        # ----------------------------------------------------
        # AUTO CONTROL BUTTON
        # ----------------------------------------------------

        self.auto_button = QPushButton(
            "AUTO CONTROL OFF"
        )


        self.auto_button.setCheckable(
            True
        )


        self.auto_button.clicked.connect(
            self.auto_control_changed
        )


        self.update_auto_button()


        target_layout.addWidget(
            self.auto_button
        )


        main_layout.addLayout(
            target_layout
        )


        # ====================================================
        # CONTROLLER STATUS
        # ====================================================

        controller_layout = QHBoxLayout()


        self.error_label = QLabel(
            "Error: --"
        )


        self.kp_label = QLabel(
            "Kp: --"
        )


        self.requested_pwm_label = QLabel(
            "Requested PWM: --"
        )


        self.command_label = QLabel(
            "Command: --"
        )


        controller_layout.addWidget(
            self.error_label
        )


        controller_layout.addWidget(
            self.kp_label
        )


        controller_layout.addWidget(
            self.requested_pwm_label
        )


        controller_layout.addWidget(
            self.command_label
        )


        main_layout.addLayout(
            controller_layout
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

        self.temperature_plot = (
            pg.PlotWidget()
        )


        self.temperature_plot.setTitle(
            "Temperature and Setpoint"
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


        # ----------------------------------------------------
        # HEAT TEMPERATURE
        # ----------------------------------------------------

        self.heat_temperature_curve = (
            self.temperature_plot.plot(
                pen=pg.mkPen(
                    color="red",
                    width=2
                )
            )
        )


        # ----------------------------------------------------
        # COOL TEMPERATURE
        # ----------------------------------------------------

        self.cool_temperature_curve = (
            self.temperature_plot.plot(
                pen=pg.mkPen(
                    color="blue",
                    width=2
                )
            )
        )


        # ----------------------------------------------------
        # SETPOINT
        # ----------------------------------------------------

        self.desired_temperature_line = (
            pg.InfiniteLine(
                pos=self.desired_temperature,
                angle=0,
                pen=pg.mkPen(
                    color="green",
                    width=2,
                    style=Qt.DashLine
                )
            )
        )


        self.temperature_plot.addItem(
            self.desired_temperature_line
        )


        main_layout.addWidget(
            self.temperature_plot
        )


        # ====================================================
        # PWM PLOT
        # ====================================================

        self.pwm_plot = (
            pg.PlotWidget()
        )


        self.pwm_plot.setTitle(
            "Signed PWM vs Arduino Time"
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
            -PWM_MAX,
            PWM_MAX
        )


        self.pwm_plot.showGrid(
            x=True,
            y=True,
            alpha=0.3
        )


        # ----------------------------------------------------
        # HEAT PWM
        # ----------------------------------------------------

        self.heat_pwm_curve = (
            self.pwm_plot.plot(
                pen=pg.mkPen(
                    color="red",
                    width=2
                )
            )
        )


        # ----------------------------------------------------
        # COOL PWM
        # ----------------------------------------------------

        self.cool_pwm_curve = (
            self.pwm_plot.plot(
                pen=pg.mkPen(
                    color="blue",
                    width=2
                )
            )
        )


        # ----------------------------------------------------
        # ZERO PWM LINE
        # ----------------------------------------------------

        self.zero_pwm_line = (
            pg.InfiniteLine(
                pos=0,
                angle=0,
                pen=pg.mkPen(
                    color="gray",
                    width=1,
                    style=Qt.DashLine
                )
            )
        )


        self.pwm_plot.addItem(
            self.zero_pwm_line
        )


        main_layout.addWidget(
            self.pwm_plot
        )


        # ====================================================
        # ERROR PLOT
        # ====================================================

        self.error_plot = (
            pg.PlotWidget()
        )


        self.error_plot.setTitle(
            "Temperature Error"
        )


        self.error_plot.setLabel(
            "left",
            "Error",
            units="°C"
        )


        self.error_plot.setLabel(
            "bottom",
            "Arduino Time",
            units="s"
        )


        self.error_plot.showGrid(
            x=True,
            y=True,
            alpha=0.3
        )


        self.error_curve = (
            self.error_plot.plot(
                pen=pg.mkPen(
                    color="purple",
                    width=2
                )
            )
        )


        self.zero_error_line = (
            pg.InfiniteLine(
                pos=0,
                angle=0,
                pen=pg.mkPen(
                    color="gray",
                    width=1,
                    style=Qt.DashLine
                )
            )
        )


        self.error_plot.addItem(
            self.zero_error_line
        )


        main_layout.addWidget(
            self.error_plot
        )


        # ====================================================
        # DATA ARRAYS
        # ====================================================

        self.times = []

        self.temperatures = []

        self.setpoints = []

        self.errors = []

        self.pwms = []

        self.directions = []


        # ====================================================
        # MAIN WINDOW
        # ====================================================

        central_widget = QWidget()

        central_widget.setLayout(
            main_layout
        )

        self.setCentralWidget(
            central_widget
        )


        # ====================================================
        # SERIAL TIMER
        # ====================================================

        self.timer = QTimer()

        self.timer.timeout.connect(
            self.read_serial
        )


        self.timer.start(
            UPDATE_INTERVAL_MS
        )


    # ========================================================
    # DIRECTION BUTTON APPEARANCE
    # ========================================================

    def update_direction_button(self):

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
    # AUTO BUTTON APPEARANCE
    # ========================================================

    def update_auto_button(self):

        if self.auto_button.isChecked():

            self.auto_button.setText(
                "AUTO CONTROL ON"
            )


            self.auto_button.setStyleSheet(
                """
                QPushButton {
                    background-color: green;
                    color: white;
                    font-weight: bold;
                    padding: 8px;
                }
                """
            )


        else:

            self.auto_button.setText(
                "AUTO CONTROL OFF"
            )


            self.auto_button.setStyleSheet(
                """
                QPushButton {
                    background-color: gray;
                    color: white;
                    font-weight: bold;
                    padding: 8px;
                }
                """
            )


    # ========================================================
    # SET DESIRED TEMPERATURE
    # ========================================================

    def set_desired_temperature(self):

        try:

            desired_temperature = float(
                self.desired_temperature_text.text()
            )

        except ValueError:

            print(
                "Invalid desired temperature."
            )

            self.desired_temperature_text.setText(
                f"{self.desired_temperature:.2f}"
            )

            return


        # Clamp desired temperature to safe range.

        desired_temperature = max(
            SAFE_TEMP_MIN,
            min(
                SAFE_TEMP_MAX,
                desired_temperature
            )
        )


        self.desired_temperature = (
            desired_temperature
        )


        self.desired_temperature_text.setText(
            f"{desired_temperature:.2f}"
        )


        self.desired_temperature_label.setText(
            f"Target: "
            f"{desired_temperature:.2f} °C"
        )


        self.desired_temperature_line.setValue(
            desired_temperature
        )


        print(
            f"Desired temperature set to "
            f"{desired_temperature:.2f} °C"
        )


    # ========================================================
    # AUTO CONTROL BUTTON
    # ========================================================

    def auto_control_changed(self):

        self.auto_control = (
            self.auto_button.isChecked()
        )


        self.update_auto_button()


        if self.auto_control:

            print(
                "Automatic proportional control ON."
            )

            print(
                f"Target = "
                f"{self.desired_temperature:.2f} °C"
            )


        else:

            print(
                "Automatic proportional control OFF."
            )


            # Stop automatic control immediately.

            self.current_signed_pwm = 0


            try:

                serial_port.write(
                    b"SET PWM 0 DIR HEAT\n"
                )

            except serial.SerialException as error:

                print(
                    f"Serial send error: {error}"
                )


            self.pwm_slider.setValue(
                0
            )

            self.pwm_text.setText(
                "0"
            )


            self.command_label.setText(
                "Command: OFF"
            )


    # ========================================================
    # DIRECTION BUTTON
    # ========================================================

    def direction_changed(self):

        self.update_direction_button()


    # ========================================================
    # PWM SLIDER
    # ========================================================

    def slider_changed(
        self,
        value
    ):

        self.pwm_text.setText(
            str(value)
        )


    # ========================================================
    # PWM TEXT
    # ========================================================

    def text_pwm_changed(self):

        try:

            value = int(
                self.pwm_text.text()
            )

        except ValueError:

            value = (
                self.pwm_slider.value()
            )


        value = max(
            PWM_MIN,
            min(
                PWM_MAX,
                value
            )
        )


        self.pwm_slider.setValue(
            value
        )


        self.pwm_text.setText(
            str(value)
        )


    # ========================================================
    # PROPORTIONAL CONTROLLER
    # ========================================================

    def automatic_temperature_control(
        self,
        temperature
    ):
        """
        Calculate and send the automatic PWM.

        Controller:

            error = desired_temperature - temperature

            u = Kp * error

        Positive u:
            HEAT

        Negative u:
            COOL

        u = 0:
            PWM 0
        """

        if not self.auto_control:

            return


        if not self.temperature_safe:

            return


        # ====================================================
        # CALCULATE ERROR
        # ====================================================

        error = (
            self.desired_temperature
            -
            temperature
        )


        # ====================================================
        # DEAD BAND
        # ====================================================

        if abs(error) <= TEMPERATURE_DEADBAND:

            requested_signed_pwm = 0.0

            kp = 0.0

            mode = "AT TARGET"


        else:

            # ------------------------------------------------
            # HEATING
            # ------------------------------------------------

            if error > 0:

                kp = KP_HEAT

            # ------------------------------------------------
            # COOLING
            # ------------------------------------------------

            else:

                kp = KP_COOL


            # ------------------------------------------------
            # PROPORTIONAL CONTROL
            # ------------------------------------------------

            requested_signed_pwm = (
                kp
                *
                error
            )


            mode = "HEAT" if error > 0 else "COOL"


        # ====================================================
        # CLAMP REQUESTED PWM
        # ====================================================

        requested_signed_pwm = max(
            -PWM_MAX,
            min(
                PWM_MAX,
                requested_signed_pwm
            )
        )


        # ====================================================
        # PWM SLEW LIMIT
        # ====================================================

        previous_pwm = (
            self.current_signed_pwm
        )


        difference = (
            requested_signed_pwm
            -
            previous_pwm
        )


        if difference > MAX_PWM_CHANGE:

            commanded_signed_pwm = (
                previous_pwm
                +
                MAX_PWM_CHANGE
            )


        elif difference < -MAX_PWM_CHANGE:

            commanded_signed_pwm = (
                previous_pwm
                -
                MAX_PWM_CHANGE
            )


        else:

            commanded_signed_pwm = (
                requested_signed_pwm
            )


        # ====================================================
        # ROUND TO INTEGER
        # ====================================================

        commanded_signed_pwm = int(
            round(
                commanded_signed_pwm
            )
        )


        # ====================================================
        # SECOND CLAMP
        # ====================================================

        commanded_signed_pwm = max(
            -PWM_MAX,
            min(
                PWM_MAX,
                commanded_signed_pwm
            )
        )


        # ====================================================
        # DETERMINE DIRECTION
        # ====================================================

        if commanded_signed_pwm > 0:

            direction = "HEAT"

            pwm_magnitude = (
                commanded_signed_pwm
            )


        elif commanded_signed_pwm < 0:

            direction = "COOL"

            pwm_magnitude = abs(
                commanded_signed_pwm
            )


        else:

            direction = "HEAT"

            pwm_magnitude = 0


        # ====================================================
        # UPDATE CONTROLLER DISPLAY
        # ====================================================

        self.error_label.setText(
            f"Error: "
            f"{error:+.3f} °C"
        )


        self.kp_label.setText(
            f"Kp: "
            f"{kp:.1f}"
        )


        self.requested_pwm_label.setText(
            f"Requested PWM: "
            f"{requested_signed_pwm:+.1f}"
        )


        self.command_label.setText(
            f"{mode} | "
            f"Command: "
            f"{commanded_signed_pwm:+d}"
        )


        # ====================================================
        # SEND COMMAND
        # ====================================================

        command = (
            f"SET PWM "
            f"{pwm_magnitude} "
            f"DIR "
            f"{direction}\n"
        )


        try:

            serial_port.write(
                command.encode(
                    "utf-8"
                )
            )

        except serial.SerialException as error:

            print(
                f"Automatic control "
                f"serial error: {error}"
            )

            return


        # ====================================================
        # SAVE CURRENT COMMAND
        # ====================================================

        self.current_signed_pwm = (
            commanded_signed_pwm
        )


        # ====================================================
        # UPDATE GUI
        # ====================================================

        self.pwm_slider.setValue(
            pwm_magnitude
        )


        self.pwm_text.setText(
            str(
                pwm_magnitude
            )
        )


        # ====================================================
        # TERMINAL OUTPUT
        # ====================================================

        print(
            f"AUTO | "
            f"Target="
            f"{self.desired_temperature:.2f} °C | "
            f"Temp="
            f"{temperature:.2f} °C | "
            f"Error="
            f"{error:+.3f} °C | "
            f"Kp="
            f"{kp:.1f} | "
            f"Requested="
            f"{requested_signed_pwm:+.1f} | "
            f"Command="
            f"{commanded_signed_pwm:+d}"
        )


    # ========================================================
    # MANUAL SEND
    # ========================================================

    def send_command(self):

        # Automatic control has priority.

        if self.auto_control:

            print(
                "Manual PWM ignored while "
                "AUTO CONTROL is ON."
            )

            return


        # ====================================================
        # SAFETY
        # ====================================================

        if not self.temperature_safe:

            if self.direction_button.isChecked():

                direction = "HEAT"

            else:

                direction = "COOL"


            command = (
                f"SET PWM 0 DIR {direction}\n"
            )


            try:

                serial_port.write(
                    command.encode(
                        "utf-8"
                    )
                )

            except serial.SerialException as error:

                print(
                    f"Serial send error: {error}"
                )


            self.pwm_slider.setValue(
                0
            )

            self.pwm_text.setText(
                "0"
            )

            return


        # ====================================================
        # GET PWM
        # ====================================================

        try:

            pwm = int(
                self.pwm_text.text()
            )

        except ValueError:

            pwm = (
                self.pwm_slider.value()
            )


        # ====================================================
        # CLAMP
        # ====================================================

        pwm = max(
            PWM_MIN,
            min(
                PWM_MAX,
                pwm
            )
        )


        # ====================================================
        # SYNCHRONIZE GUI
        # ====================================================

        self.pwm_slider.setValue(
            pwm
        )

        self.pwm_text.setText(
            str(pwm)
        )


        # ====================================================
        # DIRECTION
        # ====================================================

        if self.direction_button.isChecked():

            direction = "HEAT"

            self.current_signed_pwm = pwm

        else:

            direction = "COOL"

            self.current_signed_pwm = -pwm


        # ====================================================
        # SEND
        # ====================================================

        command = (
            f"SET PWM "
            f"{pwm} "
            f"DIR "
            f"{direction}\n"
        )


        try:

            serial_port.write(
                command.encode(
                    "utf-8"
                )
            )


            print(
                f"Sent: "
                f"SET PWM {pwm} "
                f"DIR {direction}"
            )


        except serial.SerialException as error:

            print(
                f"Serial send error: {error}"
            )


    # ========================================================
    # READ SERIAL
    # ========================================================

    def read_serial(self):

        while serial_port.in_waiting:

            # =================================================
            # READ LINE
            # =================================================

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


            # =================================================
            # PARSE
            # =================================================

            result = parse_arduino_line(
                line
            )


            if result is None:

                continue


            (
                time_s,
                temperature,
                pwm,
                heat_cool
            ) = result


            # =================================================
            # SAFETY CHECK
            # =================================================

            if (
                temperature < SAFE_TEMP_MIN
                or
                temperature > SAFE_TEMP_MAX
            ):

                if self.temperature_safe:

                    print(
                        "SAFETY CUTOFF: "
                        "Temperature outside "
                        f"{SAFE_TEMP_MIN}-"
                        f"{SAFE_TEMP_MAX} °C."
                    )


                self.temperature_safe = False


                # Stop automatic control output.

                self.current_signed_pwm = 0


                if self.direction_button.isChecked():

                    direction = "HEAT"

                else:

                    direction = "COOL"


                try:

                    command = (
                        f"SET PWM 0 "
                        f"DIR {direction}\n"
                    )


                    serial_port.write(
                        command.encode(
                            "utf-8"
                        )
                    )


                except serial.SerialException as error:

                    print(
                        f"Serial send error: "
                        f"{error}"
                    )


                self.pwm_slider.setValue(
                    0
                )


                self.pwm_text.setText(
                    "0"
                )


            else:

                if not self.temperature_safe:

                    print(
                        "Temperature returned "
                        "to safe range."
                    )


                self.temperature_safe = True


            # =================================================
            # AUTOMATIC CONTROL
            # =================================================

            self.automatic_temperature_control(
                temperature
            )


            # =================================================
            # CONVERT ARDUINO PWM TO SIGNED PWM
            # =================================================

            if heat_cool == 1:

                signed_pwm = pwm

            else:

                signed_pwm = -pwm


            # =================================================
            # ERROR
            # =================================================

            error = (
                self.desired_temperature
                -
                temperature
            )


            # =================================================
            # TERMINAL OUTPUT
            # =================================================

            print(
                f"Temperature (C): "
                f"{temperature:.2f}, "
                f"Time (s): "
                f"{time_s:.2f}, "
                f"PWM: "
                f"{signed_pwm:+d}, "
                f"Error: "
                f"{error:+.3f}, "
                f"Heat/Cool: "
                f"{heat_cool}"
            )


            # =================================================
            # LIVE GUI
            # =================================================

            self.temperature_label.setText(
                f"Temperature: "
                f"{temperature:.2f} °C"
            )


            self.time_label.setText(
                f"Time: "
                f"{time_s:.2f} s"
            )


            self.live_pwm_label.setText(
                f"PWM: "
                f"{signed_pwm:+d}"
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
            # CSV
            # =================================================

            csv_writer.writerow([
                time_s,
                temperature,
                self.desired_temperature,
                error,
                signed_pwm,
                heat_cool
            ])


            csv_file.flush()


            # =================================================
            # STORE DATA
            # =================================================

            self.times.append(
                time_s
            )


            self.temperatures.append(
                temperature
            )


            self.setpoints.append(
                self.desired_temperature
            )


            self.errors.append(
                error
            )


            self.pwms.append(
                signed_pwm
            )


            self.directions.append(
                heat_cool
            )


            # =================================================
            # REMOVE OLD DATA
            # =================================================

            newest_time = (
                self.times[-1]
            )


            oldest_allowed = (
                newest_time
                -
                WINDOW_SECONDS
            )


            while (
                self.times
                and
                self.times[0]
                <
                oldest_allowed
            ):

                self.times.pop(0)

                self.temperatures.pop(0)

                self.setpoints.pop(0)

                self.errors.pop(0)

                self.pwms.pop(0)

                self.directions.pop(0)


            # =================================================
            # UPDATE PLOTS
            # =================================================

            self.update_plots()


    # ========================================================
    # UPDATE PLOTS
    # ========================================================

    def update_plots(self):

        if len(self.times) == 0:

            return


        # ====================================================
        # TEMPERATURE AUTO-ZOOM
        # ====================================================

        temp_min = min(
            min(self.temperatures),
            min(self.setpoints)
        )


        temp_max = max(
            max(self.temperatures),
            max(self.setpoints)
        )


        temp_range = (
            temp_max
            -
            temp_min
        )


        if temp_range < 1.0:

            temp_range = 1.0


        temp_padding = (
            temp_range
            *
            0.15
        )


        temperature_axis_min = (
            temp_min
            -
            temp_padding
        )


        temperature_axis_max = (
            temp_max
            +
            temp_padding
        )


        temperature_axis_min = max(
            TEMP_MIN,
            temperature_axis_min
        )


        temperature_axis_max = min(
            TEMP_MAX,
            temperature_axis_max
        )


        if (
            temperature_axis_max
            <=
            temperature_axis_min
        ):

            temperature_axis_min = TEMP_MIN

            temperature_axis_max = TEMP_MAX


        self.temperature_plot.setYRange(
            temperature_axis_min,
            temperature_axis_max,
            padding=0
        )


        # ====================================================
        # PWM AUTO-ZOOM
        # ====================================================

        pwm_min = min(
            self.pwms
        )


        pwm_max = max(
            self.pwms
        )


        pwm_range = (
            pwm_max
            -
            pwm_min
        )


        if pwm_range < 10:

            pwm_range = 10


        pwm_padding = (
            pwm_range
            *
            0.15
        )


        pwm_axis_min = (
            pwm_min
            -
            pwm_padding
        )


        pwm_axis_max = (
            pwm_max
            +
            pwm_padding
        )


        # Always show zero.

        if pwm_axis_min > 0:

            pwm_axis_min = 0


        if pwm_axis_max < 0:

            pwm_axis_max = 0


        pwm_axis_min = max(
            -PWM_MAX,
            pwm_axis_min
        )


        pwm_axis_max = min(
            PWM_MAX,
            pwm_axis_max
        )


        if (
            pwm_axis_max
            -
            pwm_axis_min
            <
            10
        ):

            center = (
                pwm_axis_max
                +
                pwm_axis_min
            ) / 2


            pwm_axis_min = (
                center - 5
            )


            pwm_axis_max = (
                center + 5
            )


        self.pwm_plot.setYRange(
            pwm_axis_min,
            pwm_axis_max,
            padding=0
        )


        # ====================================================
        # ERROR AUTO-ZOOM
        # ====================================================

        error_min = min(
            self.errors
        )


        error_max = max(
            self.errors
        )


        error_range = (
            error_max
            -
            error_min
        )


        if error_range < 0.5:

            error_range = 0.5


        error_padding = (
            error_range
            *
            0.20
        )


        error_axis_min = (
            error_min
            -
            error_padding
        )


        error_axis_max = (
            error_max
            +
            error_padding
        )


        # Always show zero.

        if error_axis_min > 0:

            error_axis_min = 0


        if error_axis_max < 0:

            error_axis_max = 0


        self.error_plot.setYRange(
            error_axis_min,
            error_axis_max,
            padding=0
        )


        # ====================================================
        # SEPARATE HEAT / COOL DATA
        # ====================================================

        heat_temperature = []

        cool_temperature = []

        heat_pwm = []

        cool_pwm = []


        for i in range(
            len(self.times)
        ):

            if self.directions[i] == 1:

                # ------------------------------------------------
                # HEAT
                # ------------------------------------------------

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

                # ------------------------------------------------
                # COOL
                # ------------------------------------------------

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


        # ====================================================
        # TEMPERATURE CURVES
        # ====================================================

        self.heat_temperature_curve.setData(
            self.times,
            heat_temperature
        )


        self.cool_temperature_curve.setData(
            self.times,
            cool_temperature
        )


        # ====================================================
        # SETPOINT LINE
        # ====================================================

        self.desired_temperature_line.setValue(
            self.desired_temperature
        )


        # ====================================================
        # PWM CURVES
        # ====================================================

        self.heat_pwm_curve.setData(
            self.times,
            heat_pwm
        )


        self.cool_pwm_curve.setData(
            self.times,
            cool_pwm
        )


        # ====================================================
        # ERROR CURVE
        # ====================================================

        self.error_curve.setData(
            self.times,
            self.errors
        )


        # ====================================================
        # X AXIS
        # ====================================================

        if len(self.times) >= 2:

            left_edge = max(
                0,
                self.times[-1]
                -
                WINDOW_SECONDS
            )


            right_edge = (
                self.times[-1]
            )


            if right_edge <= left_edge:

                right_edge = (
                    left_edge
                    +
                    1
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


            self.error_plot.setXRange(
                left_edge,
                right_edge,
                padding=0
            )


    # ========================================================
    # CLOSE PROGRAM
    # ========================================================

    def closeEvent(
        self,
        event
    ):

        self.timer.stop()


        if serial_port.is_open:

            serial_port.close()


        csv_file.close()


        print(
            f"Data saved to "
            f"{CSV_FILENAME}"
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
