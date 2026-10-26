"""

Arduino Temperature + PWM Control GUI

FIXED-GAIN P CONTROLLER

Python communicates with the Arduino over COM3.

Arduino sends:

Temperature (C): 27.73, Time (s): 645.06,

PWM: 120, Heat/Cool: 1

Python sends:

SET PWM 120 DIR HEAT

SET PWM 45 DIR COOL

*\\=*===========================================================

CONTROL ALGORITHM

*\\=*===========================================================

Simple proportional temperature controller:

  error = desired_temperature - measured_temperature

  P_correction = KP * error

  PWM_command = P_correction

Positive PWM:

  HEAT

Negative PWM:

  COOL

There is:

  - No thermal equilibrium model

  - No RT

  - No gain scheduling

  - No transient gain

  - No hold gain

  - No integral

  - No derivative

Kp is selected by the user through the GUI.

*\\=*===========================================================

SIGNED PWM

*\\=*===========================================================

  +PWM = HEAT

  -PWM = COOL

The Arduino receives a positive PWM magnitude:

  SET PWM <magnitude> DIR HEAT

or:

  SET PWM <magnitude> DIR COOL

"""

# ============================================================

# IMPORTS

# ============================================================

import csv, re, sys, serial, os, math
from datetime import datetime

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

CSV_FILENAME = "temperature_data.csv"  # Base name; a timestamp is added for every run.

# ============================================================

# DESIRED TEMPERATURE

# ============================================================

DEFAULT_DESIRED_TEMP = 25.0

# ============================================================

# PROPORTIONAL GAIN

# ============================================================

DEFAULT_KP = 3.0

DEFAULT_KI = 0.1

print(f"Kp = {DEFAULT_KP}")

print(f"Ki = {DEFAULT_KI}")

# ============================================================

# ARDUINO MEASUREMENT PARSER

# ============================================================

DATA_COLUMNS = [
    "time_s", "tec_C", "rod1_C", "rod2_C", "rod3_C",
    "rod4_C", "rod5_C", "pwm", "heat_cool", "setpoint_C", "safety"
]


def parse_arduino_line(line):
    """Parse one complete DATA record; return a dictionary or None.

    Headers, acknowledgments, diagnostics, and malformed records are not data.
    """
    line = line.strip()
    if not line.startswith("DATA,"):
        return None

    fields = line.split(",")
    # DATA plus the 11 named fields must be present, with no extras.
    if len(fields) != len(DATA_COLUMNS) + 1 or fields[0] != "DATA":
        return None

    try:
        values = dict(zip(DATA_COLUMNS, fields[1:]))
        record = {
            "time_s": float(values["time_s"]),
            "tec_C": float(values["tec_C"]),
            "rod1_C": float(values["rod1_C"]),
            "rod2_C": float(values["rod2_C"]),
            "rod3_C": float(values["rod3_C"]),
            "rod4_C": float(values["rod4_C"]),
            "rod5_C": float(values["rod5_C"]),
            "pwm": int(values["pwm"]),
            "heat_cool": int(values["heat_cool"]),
            "setpoint_C": float(values["setpoint_C"]),
            "safety": int(values["safety"]),
        }
    except (ValueError, TypeError):
        return None

    # Reject impossible status fields and non-finite sensor/time values.
    if record["heat_cool"] not in (0, 1) or record["safety"] not in (0, 1):
        return None
    if not all(math.isfinite(record[key]) for key in
               ("time_s", "tec_C", "rod1_C", "rod2_C", "rod3_C", "rod4_C", "rod5_C")):
        return None
    if not PWM_MIN <= record["pwm"] <= PWM_MAX:
        return None
    return record


# Make a unique filename so this run never overwrites an earlier CSV.
run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
base_name, extension = os.path.splitext(CSV_FILENAME)
CSV_OUTPUT_FILENAME = f"{base_name}_{run_stamp}{extension or '.csv'}"
csv_file = open(CSV_OUTPUT_FILENAME, "x", newline="", encoding="utf-8")
csv_writer = csv.DictWriter(csv_file, fieldnames=DATA_COLUMNS)
csv_writer.writeheader()
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

      "Arduino Temperature + PI Control"

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

    self.kp = DEFAULT_KP

    self.ki = DEFAULT_KI

    self.integral_error = 0.0

    self.previous_time = None

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

    # ============================================================

    # KI CONTROL ROW

    # ============================================================

    ki_layout = QHBoxLayout()

    ki_layout.addWidget(QLabel("Ki:"))

    self.ki_text = QLineEdit(f"{self.ki:.3f}")

    self.ki_text.setFixedWidth(80)

    self.ki_text.editingFinished.connect(self.set_ki)

    ki_layout.addWidget(self.ki_text)

    self.set_ki_button = QPushButton("Set Ki")

    self.set_ki_button.clicked.connect(self.set_ki)

    ki_layout.addWidget(self.set_ki_button)

    self.ki_status_label = QLabel(

      f"Current Ki: {self.ki:.3f}"

    )

    ki_layout.addWidget(self.ki_status_label)

    main_layout.addLayout(ki_layout)

    # ====================================================

    # CONTROLLER INFORMATION

    # ====================================================

    controller_layout = QHBoxLayout()

    self.gain_label = QLabel(

      f"Kp: {self.kp:.3f}"

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
    # LIVE DATA: show each thermistor and serial-line counters.
    # ====================================================
    live_layout = QHBoxLayout()
    self.temperature_label = QLabel("A0 (TEC): -- °C")
    self.rod_temperature_labels = [QLabel(f"A{i}: -- °C") for i in range(1, 6)]
    self.time_label = QLabel("Time: -- s")
    self.live_pwm_label = QLabel("PWM: --")
    self.direction_label = QLabel("Direction: --")
    self.safety_label = QLabel("Safety: --")
    self.line_count_label = QLabel("Accepted: 0 | Rejected: 0")
    for label in [self.temperature_label, *self.rod_temperature_labels,
                  self.time_label, self.live_pwm_label, self.direction_label,
                  self.safety_label, self.line_count_label]:
      live_layout.addWidget(label)
    main_layout.addLayout(live_layout)

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
    # Six temperature traces. The legend maps each Arduino analog pin
    # to its fixed color; A0 is the TEC sensor used for control and safety.
    # ----------------------------------------------------
    # Create the legend before adding curves so pyqtgraph registers each label.
    self.temperature_plot.addLegend()
    self.temperature_curves = {}
    temperature_styles = [
      ("tec_C", "A0 (TEC)", "red", 3),
      ("rod1_C", "A1", "blue", 3),
      ("rod2_C", "A2", "green", 3),
      ("rod3_C", "A3", "purple", 3),
      ("rod4_C", "A4", "orange", 3),
      ("rod5_C", "A5", "#EEDE04", 3),
    ]
    for key, label, color, width in temperature_styles:
      self.temperature_curves[key] = self.temperature_plot.plot(
        name=label, pen=pg.mkPen(color=color, width=width)
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

          width=3,

          style=Qt.DashLine

        )

      )

    )

    self.temperature_plot.addItem(

      self.desired_temperature_line

    )

    # ====================================================

    # PLOT TIME-RANGE CONTROLS

    # ====================================================

    range_layout = QHBoxLayout()

    self.last_60_button = QPushButton("Last 60 seconds")

    self.last_60_button.clicked.connect(self.show_last_60_seconds)

    range_layout.addWidget(self.last_60_button)

    range_layout.addWidget(QLabel("Start time (s):"))

    self.start_time_text = QLineEdit()

    self.start_time_text.setPlaceholderText("e.g. 100")

    self.start_time_text.setFixedWidth(90)

    range_layout.addWidget(self.start_time_text)

    range_layout.addWidget(QLabel("End time (s):"))

    self.end_time_text = QLineEdit()

    self.end_time_text.setPlaceholderText("e.g. 160")

    self.end_time_text.setFixedWidth(90)

    range_layout.addWidget(self.end_time_text)

    self.show_segment_button = QPushButton("Show Segment")

    self.show_segment_button.clicked.connect(self.show_time_segment)

    range_layout.addWidget(self.show_segment_button)

    self.range_status_label = QLabel("Showing last 60 seconds")

    range_layout.addWidget(self.range_status_label)

    main_layout.addLayout(range_layout)

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

          width=3

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

          width=3

        )

      )

    )

    main_layout.addWidget(

      self.pwm_plot

    )

    # ====================================================

    # DATA ARRAYS

    # ====================================================

    # Keep one list per CSV field used by the plots/controller.
    self.times = []
    self.temperatures = []  # TEC/A0 only: PI control and safety use this list.
    self.rod_temperatures = [[] for _ in range(5)]
    self.pwms = []
    self.directions = []
    self.accepted_lines = 0
    self.rejected_lines = 0

    self.view_mode = "last60"

    self.view_start = None

    self.view_end = None

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

  # ============================================================

  def set_ki(self):

    try:

      new_ki = float(self.ki_text.text())

    except ValueError:

      print("Invalid Ki value.")

      self.ki_text.setText(f"{self.ki:.3f}")

      return

    if new_ki < 0:

      print("Ki must be greater than or equal to 0.")

      self.ki_text.setText(f"{self.ki:.3f}")

      return

    self.ki = new_ki

    self.ki_text.setText(f"{self.ki:.3f}")

    self.ki_status_label.setText(

      f"Current Ki: {self.ki:.3f}"

    )

    # Reset integral state when Ki changes.

    self.integral_error = 0.0

    self.previous_time = None

    # Force a new automatic command.

    self.last_auto_signed_pwm = None

    print(f"Ki set to {self.ki:.3f}")

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

    # ----------------------------------------------------

    # FORCE NEW AUTO COMMAND

    # ----------------------------------------------------

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

    self.integral_error = 0.0

    self.previous_time = None

    if self.auto_control:

      print(

        f"Automatic control ON | "

        f"Target = "

        f"{self.desired_temperature:.2f} °C | "

        f"Kp = {self.kp:.3f}"

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

# AUTOMATIC TEMPERATURE CONTROL — PI

# ========================================================

  def automatic_temperature_control(self, temperature, time_s):

    """

    PI controller.

    error = desired_temperature - measured_temperature

    integral_error += error * dt

    P = Kp * error

    I = Ki * integral_error

    signed_pwm = P + I

    Positive PWM: HEAT

    Negative PWM: COOL

    """

    if not self.auto_control:

      return

    if not self.temperature_safe:

      return

    # ====================================================

    # TIME STEP

    # ====================================================

    if self.previous_time is None:

      dt = 0.0

    else:

      dt = time_s - self.previous_time

    self.previous_time = time_s

    # Ignore invalid or non-increasing time intervals.

    if dt < 0:

      dt = 0.0

    # ====================================================

    # TEMPERATURE ERROR

    # ====================================================

    error = self.desired_temperature - temperature

    # ====================================================

    # INTEGRAL TERM

    # ====================================================

    self.integral_error += error * dt

    # ====================================================

    # PI CORRECTION

    # ====================================================

    p_correction = self.kp * error

    i_correction = self.ki * self.integral_error

    correction = p_correction + i_correction

    # ====================================================

    # SIGNED PWM

    # ====================================================

    signed_pwm = max(

      -PWM_MAX,

      min(PWM_MAX, correction)

    )

    signed_pwm = int(round(signed_pwm))

    # ====================================================

    # DETERMINE DIRECTION

    # ====================================================

    if signed_pwm > 0:

      direction = "HEAT"

      pwm = signed_pwm

    elif signed_pwm < 0:

      direction = "COOL"

      pwm = abs(signed_pwm)

    else:

      direction = "HEAT"

      pwm = 0

    # ====================================================

    # CONTROLLER DISPLAY

    # ====================================================

    self.gain_label.setText(

      f"Kp: {self.kp:.3f} | Ki: {self.ki:.3f}"

    )

    self.error_label.setText(

      f"Error: {error:+.2f} °C"

    )

    self.p_correction_label.setText(

      f"P: {p_correction:+.1f} | I: {i_correction:+.1f}"

    )

    self.command_label.setText(

      f"PWM: {signed_pwm:+d} | Direction: {direction}"

    )

    # ====================================================

    # DON'T RESEND SAME COMMAND

    # ====================================================

    if self.last_auto_signed_pwm == signed_pwm:

      self.pwm_slider.setValue(pwm)

      self.pwm_text.setText(str(pwm))

      return

    # ====================================================

    # SEND COMMAND TO ARDUINO

    # ====================================================

    command = f"SET PWM {pwm} DIR {direction}\n"

    try:

      serial_port.write(command.encode("utf-8"))

    except serial.SerialException as error:

      print(f"Automatic control serial error: {error}")

      return

    self.last_auto_signed_pwm = signed_pwm

    # ====================================================

    # UPDATE GUI

    # ====================================================

    self.pwm_slider.setValue(pwm)

    self.pwm_text.setText(str(pwm))

    # ====================================================

    # TERMINAL OUTPUT

    # ====================================================

    print(

      f"AUTO | "

      f"Target={self.desired_temperature:.2f} °C | "

      f"Temp={temperature:.2f} °C | "

      f"Error={error:+.2f} °C | "

      f"Kp={self.kp:.3f} | "

      f"Ki={self.ki:.3f} | "

      f"P={p_correction:+.2f} | "

      f"I={i_correction:+.2f} | "

      f"PWM={signed_pwm:+d} | "

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
    """Read complete serial lines, validate DATA records, and store them."""
    while serial_port.in_waiting:
      try:
        raw_line = serial_port.readline()
        line = raw_line.decode("utf-8", errors="ignore").strip()
      except Exception:
        self.rejected_lines += 1
        continue
      if not line:
        continue

      # Only parse DATA records. Headers and diagnostics are ignored by the
      # parser; every nonempty line that is not a valid record counts rejected.
      record = parse_arduino_line(line)
      if record is None:
        self.rejected_lines += 1
        self.line_count_label.setText(
          f"Accepted: {self.accepted_lines} | Rejected: {self.rejected_lines}"
        )
        continue

      self.accepted_lines += 1
      time_s = record["time_s"]
      temperature = record["tec_C"]  # A0 is the only PI/safety temperature.
      pwm = record["pwm"]
      heat_cool = record["heat_cool"]

      # Preserve the existing software safety cutoff based only on TEC/A0.
      if temperature < SAFE_TEMP_MIN or temperature > SAFE_TEMP_MAX:
        if self.temperature_safe:
          print(f"SAFETY CUTOFF: Temperature outside {SAFE_TEMP_MIN}-{SAFE_TEMP_MAX} °C.")
        self.temperature_safe = False
        self.last_auto_signed_pwm = None
        self.integral_error = 0.0
        self.previous_time = None
        direction = "HEAT" if self.direction_button.isChecked() else "COOL"
        try:
          serial_port.write(f"SET PWM 0 DIR {direction}\n".encode("utf-8"))
        except serial.SerialException as error:
          print(f"Serial send error: {error}")
        self.pwm_slider.setValue(0)
        self.pwm_text.setText("0")
      else:
        if not self.temperature_safe:
          print("Temperature returned to safe range.")
        self.temperature_safe = True

      # Existing PI controller is unchanged and receives TEC/A0 only.
      self.automatic_temperature_control(temperature, time_s)

      signed_pwm = pwm if heat_cool == 1 else -pwm
      print(f"TEC (C): {temperature:.2f}, Time (s): {time_s:.2f}, PWM: {signed_pwm:+d}, Heat/Cool: {heat_cool}")

      # Update the existing control displays plus all five rod displays.
      self.temperature_label.setText(f"A0 (TEC): {record['tec_C']:.2f} °C")
      for index, key in enumerate(("rod1_C", "rod2_C", "rod3_C", "rod4_C", "rod5_C")):
        self.rod_temperature_labels[index].setText(f"A{index + 1}: {record[key]:.2f} °C")
      self.time_label.setText(f"Time: {time_s:.2f} s")
      self.live_pwm_label.setText(f"PWM: {signed_pwm:+d}")
      self.direction_label.setText("Direction: HEAT" if heat_cool == 1 else "Direction: COOL")
      self.safety_label.setText("Safety: SAFE" if record["safety"] == 1 else "Safety: LIMIT")
      self.line_count_label.setText(f"Accepted: {self.accepted_lines} | Rejected: {self.rejected_lines}")

      # Store raw sensor values without calibration corrections.
      self.times.append(time_s)
      self.temperatures.append(record["tec_C"])
      for index, key in enumerate(("rod1_C", "rod2_C", "rod3_C", "rod4_C", "rod5_C")):
        self.rod_temperatures[index].append(record[key])
      self.pwms.append(signed_pwm)
      self.directions.append(heat_cool)

      # Write exactly the named fields, preserving raw values from Arduino.
      csv_writer.writerow({key: record[key] for key in DATA_COLUMNS})
      csv_file.flush()  # Flush every accepted row to reduce loss on a crash.

      self.update_plots()

  def show_last_60_seconds(self):

    self.view_mode = "last60"

    self.view_start = None

    self.view_end = None

    self.range_status_label.setText("Showing last 60 seconds")

    self.update_plots()

  def show_time_segment(self):

    try:

      start_time = float(self.start_time_text.text().strip())

      end_time = float(self.end_time_text.text().strip())

      if start_time >= end_time:

        raise ValueError("Start time must be less than end time.")

    except ValueError as error:

      self.range_status_label.setText(str(error) or "Enter valid start and end times.")

      return

    self.view_mode = "segment"

    self.view_start = start_time

    self.view_end = end_time

    self.range_status_label.setText(f"Showing {start_time:g} to {end_time:g} s")

    self.update_plots()

  # ========================================================

  # UPDATE PLOTS

  # ========================================================

  def update_plots(self):
    """Refresh all six temperature curves and the existing signed-PWM plot."""
    if not self.times:
      return

    newest_time = self.times[-1]
    if self.view_mode == "last60":
      left_edge = max(0, newest_time - WINDOW_SECONDS)
      right_edge = newest_time
    else:
      left_edge = self.view_start
      right_edge = self.view_end

    selected = [i for i, t in enumerate(self.times) if left_edge <= t <= right_edge]
    display_times = [self.times[i] for i in selected]
    display_temperatures = [self.temperatures[i] for i in selected]
    display_pwms = [self.pwms[i] for i in selected]
    display_directions = [self.directions[i] for i in selected]

    # Use the same selected time window for every temperature trace.
    keys = ("tec_C", "rod1_C", "rod2_C", "rod3_C", "rod4_C", "rod5_C")
    values_by_key = {"tec_C": display_temperatures}
    for index, key in enumerate(keys[1:]):
      values_by_key[key] = [self.rod_temperatures[index][i] for i in selected]
    for key in keys:
      self.temperature_curves[key].setData(display_times, values_by_key[key])

    if display_temperatures:
      temp_min = min(min(values_by_key[key]) for key in keys)
      temp_max = max(max(values_by_key[key]) for key in keys)
      temp_range = max(temp_max - temp_min, 2)
      self.temperature_plot.setYRange(
        max(TEMP_MIN, temp_min - temp_range * 0.10),
        min(TEMP_MAX, temp_max + temp_range * 0.10), padding=0
      )

    # Keep the original heat/cool split and signed PWM plot behavior.
    heat_pwm, cool_pwm = [], []
    for pwm, direction in zip(display_pwms, display_directions):
      heat_pwm.append(pwm if direction == 1 else float("nan"))
      cool_pwm.append(pwm if direction == 0 else float("nan"))
    self.heat_pwm_curve.setData(display_times, heat_pwm)
    self.cool_pwm_curve.setData(display_times, cool_pwm)

    if display_pwms:
      pwm_min, pwm_max = min(display_pwms), max(display_pwms)
      padding = max((pwm_max - pwm_min), 10) * 0.15
      axis_min = max(-PWM_MAX, min(0, pwm_min - padding))
      axis_max = min(PWM_MAX, max(0, pwm_max + padding))
      if axis_max - axis_min < 10:
        axis_min, axis_max = max(-PWM_MAX, axis_min - 5), min(PWM_MAX, axis_max + 5)
      self.pwm_plot.setYRange(axis_min, axis_max, padding=0)

    if right_edge <= left_edge:
      right_edge = left_edge + 1
    self.temperature_plot.setXRange(left_edge, right_edge, padding=0)
    self.pwm_plot.setXRange(left_edge, right_edge, padding=0)

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

      f"{CSV_OUTPUT_FILENAME}"

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
