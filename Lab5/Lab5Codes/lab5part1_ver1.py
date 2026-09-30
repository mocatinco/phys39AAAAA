"""
Arduino Temperature + PWM Control GUI

Python communicates with the Arduino over COM3.

Arduino sends measurements such as:

Temperature (C): 27.73, Time (s): 645.06,
PWM: 120, Heat/Cool: 1

Python sends commands such as:

SET PWM 120 DIR HEAT
SET PWM 45 DIR COOL

------------------------------------------------------------
AUTOMATIC TEMPERATURE CONTROL
------------------------------------------------------------

The experimentally measured equilibrium data was measured
after approximately 5 minutes.

Heating:

    T = 22.77 + 0.5049 * PWM

Cooling:

    T = 23.11 + 0.1528 * PWM

Those equations describe STEADY-STATE behavior.

The controller therefore uses:

    1. Equilibrium feed-forward
    2. Stronger transient proportional control
    3. Reduced proportional correction near the target
    4. Gentle holding control once near the target

The objective is to approach the desired temperature quickly
(approximately 1 minute where the thermal system permits)
and then maintain the temperature.

Signed PWM convention:

    +PWM = HEAT
    -PWM = COOL

The Arduino itself still receives:

    SET PWM <positive magnitude> DIR HEAT

or

    SET PWM <positive magnitude> DIR COOL
"""


# ============================================================
# SETTINGS
# ============================================================

SERIAL_PORT = "COM3"
BAUD_RATE = 9600

WINDOW_SECONDS = 60

UPDATE_INTERVAL_MS = 100

# Temperature graph limits.
TEMP_MIN = 0
TEMP_MAX = 100

# PWM magnitude limits.
PWM_MIN = 0
PWM_MAX = 255

# Safe temperature range.
SAFE_TEMP_MIN = 0
SAFE_TEMP_MAX = 60

# CSV output file.
CSV_FILENAME = "temperature_data.csv"


# ============================================================
# DESIRED TEMPERATURE
# ============================================================

DEFAULT_DESIRED_TEMP = 25.0


# ============================================================
# EQUILIBRIUM MODEL
# ============================================================

# These came from the measured 5-minute equilibrium data.

# Heating:
#
# T = 22.7673 + 0.50489 * PWM

HEAT_INTERCEPT = 22.7673
HEAT_SLOPE = 0.50489


# Cooling:
#
# T = 23.1063 + 0.15280 * PWM_signed

COOL_INTERCEPT = 23.1063
COOL_SLOPE = 0.15280


# ============================================================
# TRANSIENT CONTROL
# ============================================================

"""
These gains are intentionally stronger than the previous
holding controller.

The equilibrium model gives us the long-term PWM.

The transient proportional term provides the extra PWM
needed to move toward the target more quickly.

If the system overshoots:
    decrease these values.

If the system approaches too slowly:
    increase them.

The cooling system is often weaker/slower than heating,
so its gain is larger.
"""

HEAT_TRANSIENT_KP = 3.0

COOL_TRANSIENT_KP = 4.0


# ============================================================
# HOLD CONTROL
# ============================================================

"""
Once close to the desired temperature, the controller should
not continue using the strong transient correction.

These smaller gains are used for temperature holding.
"""

HEAT_HOLD_KP = 0.60

COOL_HOLD_KP = 1.00


# ============================================================
# TEMPERATURE ERROR REGIONS
# ============================================================

"""
FAR_ERROR:

When the temperature is far from the target, use stronger
transient control.

NEAR_ERROR:

When approaching the target, gradually reduce the
transient correction.

HOLD_ERROR:

Inside this range the controller behaves mainly as a
temperature holding controller.
"""

FAR_ERROR = 3.0

NEAR_ERROR = 1.0

HOLD_ERROR = 0.20


# ============================================================
# TEMPERATURE DEAD BAND
# ============================================================

"""
Inside this temperature error, don't chase tiny fluctuations.
"""

TEMPERATURE_DEADBAND = 0.15


# ============================================================
# ZERO PWM EQUILIBRIUM REGION
# ============================================================

ZERO_PWM_TEMP_LOW = 22.7

ZERO_PWM_TEMP_HIGH = 23.2


# ============================================================
# MINIMUM PWM
# ============================================================

"""
Very small PWM values may have little physical effect.

This prevents the controller from repeatedly commanding
1-2 PWM when it would be effectively meaningless.

The value is only used when the controller is sufficiently
far from the target.

Near the target, PWM can still go to zero.
"""

MIN_EFFECTIVE_PWM = 3


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

    Returns None if malformed.
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
            900
        )


        # ====================================================
        # CONTROL STATE
        # ====================================================

        self.desired_temperature = (
            DEFAULT_DESIRED_TEMP
        )

        self.auto_control = False

        self.temperature_safe = True

        self.last_auto_signed_pwm = None


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
        # SEND
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
        # TEMPERATURE CONTROL ROW
        # ====================================================

        target_layout = QHBoxLayout()


        target_layout.addWidget(
            QLabel("Desired Temperature:")
        )


        self.desired_temperature_text = (
            QLineEdit(
                str(DEFAULT_DESIRED_TEMP)
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


        self.set_temperature_button = QPushButton(
            "Set Desired Temp"
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
        # AUTO CONTROL
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
        # CONTROLLER INFORMATION
        # ====================================================

        controller_layout = QHBoxLayout()


        self.feedforward_label = QLabel(
            "FF: --"
        )

        self.error_label = QLabel(
            "Error: --"
        )

        self.p_correction_label = QLabel(
            "P: --"
        )

        self.command_label = QLabel(
            "Command: --"
        )


        controller_layout.addWidget(
            self.feedforward_label
        )

        controller_layout.addWidget(
            self.error_label
        )

        controller_layout.addWidget(
            self.p_correction_label
        )

        controller_layout.addWidget(
            self.command_label
        )


        main_layout.addLayout(
            controller_layout
        )


        # ====================================================
        # LIVE DATA
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
        # TARGET TEMPERATURE
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

        self.pwm_plot = pg.PlotWidget()


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
    # DIRECTION BUTTON
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
    # AUTO BUTTON
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


        self.last_auto_signed_pwm = None


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

        self.last_auto_signed_pwm = None


        if self.auto_control:

            print(
                f"Automatic control ON. "
                f"Target = "
                f"{self.desired_temperature:.2f} °C"
            )

        else:

            print(
                "Automatic control OFF."
            )


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


            self.feedforward_label.setText(
                "FF: --"
            )

            self.error_label.setText(
                "Error: --"
            )

            self.p_correction_label.setText(
                "P: --"
            )

            self.command_label.setText(
                "Command: --"
            )


    # ========================================================
    # EQUILIBRIUM FEED-FORWARD
    # ========================================================

    def calculate_feedforward_pwm(
        self,
        target_temperature
    ):
        """
        Calculate the steady-state PWM required by the
        experimentally measured equilibrium model.

        Positive = HEAT
        Negative = COOL
        """

        # ----------------------------------------------------
        # Near natural equilibrium.
        # ----------------------------------------------------

        if (
            ZERO_PWM_TEMP_LOW
            <=
            target_temperature
            <=
            ZERO_PWM_TEMP_HIGH
        ):

            return 0.0


        # ----------------------------------------------------
        # HEATING
        # ----------------------------------------------------

        if target_temperature > ZERO_PWM_TEMP_HIGH:

            pwm = (
                target_temperature
                -
                HEAT_INTERCEPT
            ) / HEAT_SLOPE

            return pwm


        # ----------------------------------------------------
        # COOLING
        # ----------------------------------------------------

        pwm = (
            target_temperature
            -
            COOL_INTERCEPT
        ) / COOL_SLOPE

        return pwm


    # ========================================================
    # AUTOMATIC TEMPERATURE CONTROL
    # ========================================================

    def automatic_temperature_control(
        self,
        temperature
    ):
        """
        Two-stage controller.

        FAR FROM TARGET:
            Strong transient proportional control.

        NEAR TARGET:
            Gradually reduce the transient correction.

        AT TARGET:
            Mainly use equilibrium feed-forward.

        This provides a faster approach while avoiding the
        use of an excessively large equilibrium multiplier.
        """

        if not self.auto_control:

            return


        if not self.temperature_safe:

            return


        # ----------------------------------------------------
        # TEMPERATURE ERROR
        # ----------------------------------------------------

        error = (
            self.desired_temperature
            -
            temperature
        )


        absolute_error = abs(
            error
        )


        # ----------------------------------------------------
        # EQUILIBRIUM FEED-FORWARD
        # ----------------------------------------------------

        feedforward_pwm = (
            self.calculate_feedforward_pwm(
                self.desired_temperature
            )
        )


        # ====================================================
        # PROPORTIONAL CONTROL
        # ====================================================

        if absolute_error <= HOLD_ERROR:

            # ------------------------------------------------
            # HOLD MODE
            # ------------------------------------------------

            if error > 0:

                p_correction = (
                    HEAT_HOLD_KP
                    *
                    error
                )

            else:

                p_correction = (
                    COOL_HOLD_KP
                    *
                    error
                )


        elif absolute_error < NEAR_ERROR:

            # ------------------------------------------------
            # APPROACH MODE
            #
            # Blend between transient and hold gains.
            # ------------------------------------------------

            if error > 0:

                transient_gain = (
                    HEAT_TRANSIENT_KP
                )

                hold_gain = (
                    HEAT_HOLD_KP
                )

            else:

                transient_gain = (
                    COOL_TRANSIENT_KP
                )

                hold_gain = (
                    COOL_HOLD_KP
                )


            blend = (
                absolute_error
                -
                HOLD_ERROR
            ) / (
                NEAR_ERROR
                -
                HOLD_ERROR
            )


            gain = (
                hold_gain
                +
                (
                    transient_gain
                    -
                    hold_gain
                )
                *
                blend
            )


            p_correction = (
                gain
                *
                error
            )


        else:

            # ------------------------------------------------
            # STRONG TRANSIENT MODE
            # ------------------------------------------------

            if error > 0:

                p_correction = (
                    HEAT_TRANSIENT_KP
                    *
                    error
                )

            else:

                p_correction = (
                    COOL_TRANSIENT_KP
                    *
                    error
                )


        # ====================================================
        # ADD FEED-FORWARD + CORRECTION
        # ====================================================

        signed_pwm = (
            feedforward_pwm
            +
            p_correction
        )


        # ====================================================
        # SPECIAL CASE:
        # TARGET NEAR NATURAL TEMPERATURE
        # ====================================================

        if (
            abs(
                self.desired_temperature
                -
                23.0
            )
            <
            0.30
            and
            absolute_error
            <
            0.30
        ):

            signed_pwm = 0.0


        # ====================================================
        # CLAMP
        # ====================================================

        signed_pwm = max(
            -PWM_MAX,
            min(
                PWM_MAX,
                signed_pwm
            )
        )


        # ====================================================
        # REMOVE TINY PWM
        # ====================================================

        if (
            absolute_error
            >
            HOLD_ERROR
            and
            abs(signed_pwm)
            <
            MIN_EFFECTIVE_PWM
        ):

            if signed_pwm > 0:

                signed_pwm = (
                    MIN_EFFECTIVE_PWM
                )

            elif signed_pwm < 0:

                signed_pwm = (
                    -MIN_EFFECTIVE_PWM
                )


        # ====================================================
        # INTEGER PWM
        # ====================================================

        signed_pwm = int(
            round(
                signed_pwm
            )
        )


        # ====================================================
        # DETERMINE DIRECTION
        # ====================================================

        if signed_pwm > 0:

            direction = "HEAT"

            pwm = signed_pwm

        elif signed_pwm < 0:

            direction = "COOL"

            pwm = abs(
                signed_pwm
            )

        else:

            direction = "HEAT"

            pwm = 0


        # ====================================================
        # CONTROLLER DISPLAY
        # ====================================================

        if absolute_error > NEAR_ERROR:

            control_mode = "FAST"

        elif absolute_error > HOLD_ERROR:

            control_mode = "APPROACH"

        else:

            control_mode = "HOLD"


        self.feedforward_label.setText(
            f"FF: {feedforward_pwm:+.1f}"
        )


        self.error_label.setText(
            f"Error: {error:+.2f} °C"
        )


        self.p_correction_label.setText(
            f"P: {p_correction:+.1f}"
        )


        self.command_label.setText(
            f"{control_mode} | "
            f"PWM: {signed_pwm:+d}"
        )


        # ====================================================
        # DON'T RESEND SAME COMMAND
        # ====================================================

        if (
            self.last_auto_signed_pwm
            ==
            signed_pwm
        ):

            self.pwm_slider.setValue(
                pwm
            )

            self.pwm_text.setText(
                str(pwm)
            )

            return


        # ====================================================
        # SEND COMMAND TO ARDUINO
        # ====================================================

        command = (
            f"SET PWM {pwm} DIR {direction}\n"
        )


        try:

            serial_port.write(
                command.encode("utf-8")
            )

        except serial.SerialException as error:

            print(
                f"Automatic control serial error: "
                f"{error}"
            )

            return


        self.last_auto_signed_pwm = (
            signed_pwm
        )


        # ====================================================
        # UPDATE GUI
        # ====================================================

        self.pwm_slider.setValue(
            pwm
        )

        self.pwm_text.setText(
            str(pwm)
        )


        # ====================================================
        # TERMINAL OUTPUT
        # ====================================================

        print(
            f"AUTO | "
            f"Mode={control_mode} | "
            f"Target={self.desired_temperature:.2f} °C | "
            f"Temp={temperature:.2f} °C | "
            f"Error={error:+.2f} °C | "
            f"FF={feedforward_pwm:+.1f} | "
            f"P={p_correction:+.1f} | "
            f"PWM={signed_pwm:+d}"
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
    # MANUAL SEND
    # ========================================================

    def send_command(self):

        if self.auto_control:

            print(
                "Manual PWM ignored because "
                "automatic control is ON."
            )

            return


        # ----------------------------------------------------
        # SAFETY
        # ----------------------------------------------------

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
                    command.encode("utf-8")
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


        # ----------------------------------------------------
        # GET PWM
        # ----------------------------------------------------

        try:

            pwm = int(
                self.pwm_text.text()
            )

        except ValueError:

            pwm = (
                self.pwm_slider.value()
            )


        # ----------------------------------------------------
        # CLAMP
        # ----------------------------------------------------

        pwm = max(
            PWM_MIN,
            min(
                PWM_MAX,
                pwm
            )
        )


        self.pwm_slider.setValue(
            pwm
        )

        self.pwm_text.setText(
            str(pwm)
        )


        # ----------------------------------------------------
        # DIRECTION
        # ----------------------------------------------------

        if self.direction_button.isChecked():

            direction = "HEAT"

        else:

            direction = "COOL"


        command = (
            f"SET PWM {pwm} DIR {direction}\n"
        )


        try:

            serial_port.write(
                command.encode("utf-8")
            )

            print(
                f"Sent: "
                f"SET PWM {pwm} DIR {direction}"
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


            # ------------------------------------------------
            # PARSE
            # ------------------------------------------------

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
            # TEMPERATURE SAFETY
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

                self.last_auto_signed_pwm = None


                if self.direction_button.isChecked():

                    direction = "HEAT"

                else:

                    direction = "COOL"


                try:

                    command = (
                        f"SET PWM 0 DIR {direction}\n"
                    )

                    serial_port.write(
                        command.encode("utf-8")
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


            else:

                if not self.temperature_safe:

                    print(
                        "Temperature returned "
                        "to safe range."
                    )


                self.temperature_safe = True


            # =================================================
            # AUTOMATIC CONTROLLER
            # =================================================

            self.automatic_temperature_control(
                temperature
            )


            # =================================================
            # SIGNED PWM
            # =================================================

            if heat_cool == 1:

                signed_pwm = pwm

            else:

                signed_pwm = -pwm


            # =================================================
            # TERMINAL
            # =================================================

            print(
                f"Temperature (C): "
                f"{temperature:.2f}, "
                f"Time (s): "
                f"{time_s:.2f}, "
                f"PWM: "
                f"{signed_pwm:+d}, "
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
            self.temperatures
        )

        temp_max = max(
            self.temperatures
        )


        temp_range = (
            temp_max
            -
            temp_min
        )


        if temp_range < 2:

            temp_range = 2


        temp_padding = (
            temp_range
            *
            0.10
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


        # Keep physical limits.

        pwm_axis_min = max(
            -PWM_MAX,
            pwm_axis_min
        )


        pwm_axis_max = min(
            PWM_MAX,
            pwm_axis_max
        )


        # Always show zero.

        if pwm_axis_min > 0:

            pwm_axis_min = 0


        if pwm_axis_max < 0:

            pwm_axis_max = 0


        # Prevent an extremely small axis.

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


        pwm_axis_min = max(
            -PWM_MAX,
            pwm_axis_min
        )

        pwm_axis_max = min(
            PWM_MAX,
            pwm_axis_max
        )


        self.pwm_plot.setYRange(
            pwm_axis_min,
            pwm_axis_max,
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
