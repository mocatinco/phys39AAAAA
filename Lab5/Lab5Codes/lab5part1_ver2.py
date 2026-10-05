"""
Arduino Temperature + PWM Control GUI
FIXED-GAIN P CONTROLLER
WITH THERMAL EQUILIBRIUM ENVELOPE

Python communicates with the Arduino over COM3.

Arduino sends:
Temperature (C): 27.73, Time (s): 645.06,
PWM: 120, Heat/Cool: 1

Python sends:
SET PWM 120 DIR HEAT
SET PWM 45 DIR COOL

============================================================
CONTROL ALGORITHM
============================================================

The experimentally measured thermal equilibrium is modeled as:

HEATING:
    T = RT + 0.50489 * PWM

COOLING:
    T = RT + 0.15280 * PWM_signed

where:

    PWM_signed > 0  -> HEAT
    PWM_signed < 0  -> COOL

RT is a SINGLE user-adjustable equilibrium/reference
temperature.

Previously, separate intercepts were used:

    Heating: 22.7673
    Cooling: 23.1063

These were measurement uncertainty rather than two
independent controller parameters.

Therefore, this program uses ONE shared variable:

    RT

Default:

    RT = 22.85 °C

The user can change RT from the GUI.

The controller first estimates the PWM required to reach
the desired temperature at thermal equilibrium.

The controller then adds a proportional correction:

    error = desired_temperature - measured_temperature

    P_correction = KP * error

    PWM_command =
        equilibrium_PWM
        +
        P_correction

KP is selected by the user through the GUI.

There is:
    - No gain scheduling
    - No transient gain
    - No hold gain
    - No integral
    - No derivative

============================================================
SIGNED PWM
============================================================

    +PWM = HEAT
    -PWM = COOL

The Arduino still receives a positive PWM magnitude:

    SET PWM <magnitude> DIR HEAT

or:

    SET PWM <magnitude> DIR COOL

============================================================
THERMAL EQUILIBRIUM MODEL
============================================================

Shared intercept/reference temperature:

    RT = user adjustable

Heating slope:

    HEAT_SLOPE = 0.50489

Cooling slope:

    COOL_SLOPE = 0.15280

Therefore:

HEATING:

    T = RT + HEAT_SLOPE * PWM

COOLING:

    T = RT + COOL_SLOPE * PWM_signed

============================================================
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
# PROPORTIONAL GAIN
# ============================================================

DEFAULT_KP = 3.0

# ============================================================
# EQUILIBRIUM REFERENCE TEMPERATURE
# ============================================================

"""
RT is the SINGLE equilibrium-model intercept.

Previously:

    HEAT_INTERCEPT = 22.7673
    COOL_INTERCEPT = 23.1063

Those values were treated as measurement uncertainty.

Now both heating and cooling use the same RT.

The midpoint of approximately 22.7 and 23.0 is:

    RT = 22.85 °C

The user can change RT from the GUI.
"""

DEFAULT_RT = 22.85

# ============================================================
# THERMAL EQUILIBRIUM SLOPES
# ============================================================

HEAT_SLOPE = 0.50489
COOL_SLOPE = 0.15280

print(f"Kp = {DEFAULT_KP}")
print(f"RT = {DEFAULT_RT:.2f} °C")


# ============================================================
# EQUILIBRIUM PWM FUNCTION
# ============================================================

def calculate_equilibrium_pwm(
    target_temperature,
    rt
):
    """
    Calculate the signed PWM predicted to produce the
    desired temperature at thermal equilibrium.

    Positive result:
        HEAT

    Negative result:
        COOL

    The same RT is used for both heating and cooling.

    Heating:

        T = RT + HEAT_SLOPE * PWM

        PWM = (T - RT) / HEAT_SLOPE

    Cooling:

        T = RT + COOL_SLOPE * PWM_signed

        PWM_signed = (T - RT) / COOL_SLOPE
    """

    # --------------------------------------------------------
    # HEATING SIDE
    # --------------------------------------------------------

    if target_temperature >= rt:

        pwm = (
            target_temperature
            -
            rt
        ) / HEAT_SLOPE

        return pwm

    # --------------------------------------------------------
    # COOLING SIDE
    # --------------------------------------------------------

    pwm = (
        target_temperature
        -
        rt
    ) / COOL_SLOPE

    return pwm


# ============================================================
# EQUILIBRIUM TEMPERATURE FUNCTION
# ============================================================

def calculate_equilibrium_temperature(
    signed_pwm,
    rt
):
    """
    Calculate the temperature predicted by the experimental
    thermal equilibrium envelope for a given signed PWM.

    Positive PWM:
        Heating model

    Negative PWM:
        Cooling model
    """

    if signed_pwm >= 0:

        return (
            rt
            +
            HEAT_SLOPE
            *
            signed_pwm
        )

    else:

        return (
            rt
            +
            COOL_SLOPE
            *
            signed_pwm
        )


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
            "Arduino Temperature + Fixed Kp Control"
        )

        self.resize(
            1150,
            1000
        )

        # ====================================================
        # CONTROL STATE
        # ====================================================

        self.desired_temperature = (
            DEFAULT_DESIRED_TEMP
        )

        self.kp = DEFAULT_KP

        # ----------------------------------------------------
        # SINGLE RT VARIABLE
        # ----------------------------------------------------

        self.rt = DEFAULT_RT

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
        # KP CONTROL ROW
        # ====================================================

        kp_layout = QHBoxLayout()

        kp_layout.addWidget(
            QLabel("Kp:")
        )

        self.kp_text = QLineEdit(
            f"{self.kp:.3f}"
        )

        self.kp_text.setFixedWidth(
            80
        )

        self.kp_text.editingFinished.connect(
            self.set_kp
        )

        kp_layout.addWidget(
            self.kp_text
        )

        self.set_kp_button = QPushButton(
            "Set Kp"
        )

        self.set_kp_button.clicked.connect(
            self.set_kp
        )

        kp_layout.addWidget(
            self.set_kp_button
        )

        self.kp_status_label = QLabel(
            f"Current Kp: {self.kp:.3f}"
        )

        kp_layout.addWidget(
            self.kp_status_label
        )

        main_layout.addLayout(
            kp_layout
        )

        # ====================================================
        # RT CONTROL ROW
        # ====================================================

        rt_layout = QHBoxLayout()

        rt_layout.addWidget(
            QLabel("RT:")
        )

        self.rt_text = QLineEdit(
            f"{self.rt:.2f}"
        )

        self.rt_text.setFixedWidth(
            80
        )

        self.rt_text.editingFinished.connect(
            self.set_rt
        )

        rt_layout.addWidget(
            self.rt_text
        )

        rt_layout.addWidget(
            QLabel("°C")
        )

        self.set_rt_button = QPushButton(
            "Set RT"
        )

        self.set_rt_button.clicked.connect(
            self.set_rt
        )

        rt_layout.addWidget(
            self.set_rt_button
        )

        self.rt_status_label = QLabel(
            f"Current RT: {self.rt:.2f} °C"
        )

        rt_layout.addWidget(
            self.rt_status_label
        )

        rt_layout.addWidget(
            QLabel(
                "(Shared heating/cooling equilibrium reference)"
            )
        )

        main_layout.addLayout(
            rt_layout
        )

        # ====================================================
        # MODEL INFORMATION
        # ====================================================

        model_layout = QHBoxLayout()

        self.model_label = QLabel(
            f"Model: "
            f"HEAT T = RT + {HEAT_SLOPE:.5f}×PWM | "
            f"COOL T = RT + {COOL_SLOPE:.5f}×PWM_signed"
        )

        model_layout.addWidget(
            self.model_label
        )

        main_layout.addLayout(
            model_layout
        )

        # ====================================================
        # CONTROLLER INFORMATION
        # ====================================================

        controller_layout = QHBoxLayout()

        self.gain_label = QLabel(
            f"Kp: {self.kp:.3f}"
        )

        self.rt_controller_label = QLabel(
            f"RT: {self.rt:.2f} °C"
        )

        self.equilibrium_label = QLabel(
            "EQ PWM: --"
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
            self.gain_label
        )

        controller_layout.addWidget(
            self.rt_controller_label
        )

        controller_layout.addWidget(
            self.equilibrium_label
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

        self.temperature_plot.setBackground(
            "white"
        )

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

        self.temperature_plot.getAxis(
            "left"
        ).setPen("black")

        self.temperature_plot.getAxis(
            "bottom"
        ).setPen("black")

        self.temperature_plot.getAxis(
            "left"
        ).setTextPen("black")

        self.temperature_plot.getAxis(
            "bottom"
        ).setTextPen("black")

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

        self.pwm_plot.setBackground(
            "white"
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

        self.pwm_plot.getAxis(
            "left"
        ).setPen("black")

        self.pwm_plot.getAxis(
            "bottom"
        ).setPen("black")

        self.pwm_plot.getAxis(
            "left"
        ).setTextPen("black")

        self.pwm_plot.getAxis(
            "bottom"
        ).setTextPen("black")

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
    # SET KP
    # ========================================================

    def set_kp(self):

        try:

            new_kp = float(
                self.kp_text.text()
            )

        except ValueError:

            print(
                "Invalid Kp value."
            )

            self.kp_text.setText(
                f"{self.kp:.3f}"
            )

            return

        # ----------------------------------------------------
        # KP VALIDATION
        # ----------------------------------------------------

        if new_kp < 0:

            print(
                "Kp must be greater than or equal to 0."
            )

            self.kp_text.setText(
                f"{self.kp:.3f}"
            )

            return

        # ----------------------------------------------------
        # UPDATE KP
        # ----------------------------------------------------

        self.kp = new_kp

        self.kp_text.setText(
            f"{self.kp:.3f}"
        )

        self.kp_status_label.setText(
            f"Current Kp: {self.kp:.3f}"
        )

        self.gain_label.setText(
            f"Kp: {self.kp:.3f}"
        )

        # ----------------------------------------------------
        # FORCE NEW AUTO COMMAND
        # ----------------------------------------------------

        self.last_auto_signed_pwm = None

        print(
            f"Kp set to {self.kp:.3f}"
        )

    # ========================================================
    # SET RT
    # ========================================================

    def set_rt(self):

        try:

            new_rt = float(
                self.rt_text.text()
            )

        except ValueError:

            print(
                "Invalid RT value."
            )

            self.rt_text.setText(
                f"{self.rt:.2f}"
            )

            return

        # ----------------------------------------------------
        # RT VALIDATION
        # ----------------------------------------------------

        if new_rt < SAFE_TEMP_MIN:

            print(
                f"RT must be at least "
                f"{SAFE_TEMP_MIN} °C."
            )

            self.rt_text.setText(
                f"{self.rt:.2f}"
            )

            return

        if new_rt > SAFE_TEMP_MAX:

            print(
                f"RT must be no greater than "
                f"{SAFE_TEMP_MAX} °C."
            )

            self.rt_text.setText(
                f"{self.rt:.2f}"
            )

            return

        # ----------------------------------------------------
        # UPDATE RT
        # ----------------------------------------------------

        self.rt = new_rt

        self.rt_text.setText(
            f"{self.rt:.2f}"
        )

        self.rt_status_label.setText(
            f"Current RT: {self.rt:.2f} °C"
        )

        self.rt_controller_label.setText(
            f"RT: {self.rt:.2f} °C"
        )

        # ----------------------------------------------------
        # FORCE NEW AUTO COMMAND
        # ----------------------------------------------------

        self.last_auto_signed_pwm = None

        print(
            f"RT set to {self.rt:.2f} °C"
        )

        # ----------------------------------------------------
        # UPDATE EQUILIBRIUM DISPLAY
        # ----------------------------------------------------

        if self.auto_control:

            self.equilibrium_label.setText(
                "EQ PWM: recalculating..."
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
                f"Automatic control ON | "
                f"Target = "
                f"{self.desired_temperature:.2f} °C | "
                f"Kp = {self.kp:.3f} | "
                f"RT = {self.rt:.2f} °C"
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

            self.gain_label.setText(
                f"Kp: {self.kp:.3f}"
            )

            self.rt_controller_label.setText(
                f"RT: {self.rt:.2f} °C"
            )

            self.equilibrium_label.setText(
                "EQ PWM: --"
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
    # AUTOMATIC TEMPERATURE CONTROL
    # ========================================================

    def automatic_temperature_control(
        self,
        temperature
    ):
        """
        Proportional controller with thermal equilibrium
        feed-forward.

        Algorithm:

            error = target - measured_temperature

            equilibrium_pwm =
                experimentally predicted PWM
                required to maintain target

            p_correction =
                Kp * error

            signed_pwm =
                equilibrium_pwm
                +
                p_correction

        The equilibrium calculation uses the single shared RT.
        """

        if not self.auto_control:
            return

        if not self.temperature_safe:
            return

        # ====================================================
        # TEMPERATURE ERROR
        # ====================================================

        error = (
            self.desired_temperature
            -
            temperature
        )

        # ====================================================
        # EQUILIBRIUM PWM
        # ====================================================

        equilibrium_pwm_value = (
            calculate_equilibrium_pwm(
                self.desired_temperature,
                self.rt
            )
        )

        # ====================================================
        # PROPORTIONAL CORRECTION
        # ====================================================

        p_correction = (
            self.kp
            *
            error
        )

        # ====================================================
        # EQUILIBRIUM ENVELOPE + P CONTROL
        # ====================================================

        signed_pwm = (
            equilibrium_pwm_value
            +
            p_correction
        )

        # ====================================================
        # CLAMP PWM
        # ====================================================

        signed_pwm = max(
            -PWM_MAX,
            min(
                PWM_MAX,
                signed_pwm
            )
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
        # PREDICTED EQUILIBRIUM TEMPERATURE
        # ====================================================

        predicted_temperature = (
            calculate_equilibrium_temperature(
                signed_pwm,
                self.rt
            )
        )

        # ====================================================
        # CONTROLLER DISPLAY
        # ====================================================

        self.gain_label.setText(
            f"Kp: {self.kp:.3f}"
        )

        self.rt_controller_label.setText(
            f"RT: {self.rt:.2f} °C"
        )

        self.kp_status_label.setText(
            f"Current Kp: {self.kp:.3f}"
        )

        self.rt_status_label.setText(
            f"Current RT: {self.rt:.2f} °C"
        )

        self.equilibrium_label.setText(
            f"EQ PWM: "
            f"{equilibrium_pwm_value:+.1f}"
        )

        self.error_label.setText(
            f"Error: "
            f"{error:+.2f} °C"
        )

        self.p_correction_label.setText(
            f"P: "
            f"{p_correction:+.1f}"
        )

        self.command_label.setText(
            f"PWM: "
            f"{signed_pwm:+d} | "
            f"EQ T: "
            f"{predicted_temperature:.2f} °C"
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
            f"Target={self.desired_temperature:.2f} °C | "
            f"Temp={temperature:.2f} °C | "
            f"Error={error:+.2f} °C | "
            f"RT={self.rt:.2f} °C | "
            f"EQ_PWM={equilibrium_pwm_value:+.2f} | "
            f"Kp={self.kp:.3f} | "
            f"P={p_correction:+.2f} | "
            f"PWM={signed_pwm:+d} | "
            f"EQ_T={predicted_temperature:.2f} °C | "
            f"Direction={direction}"
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

        # ----------------------------------------------------
        # SAFETY: STOP OUTPUT
        # ----------------------------------------------------

        try:

            serial_port.write(
                b"SET PWM 0 DIR HEAT\n"
            )

        except Exception:

            pass

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
