
import serial
import time
from collections import deque

import numpy as np
import matplotlib.pyplot as plt


# =========================
# Configuration
# =========================
SERIAL_PORT = "COM3"    # Change to your Arduino port
BAUD_RATE = 115200

SETPOINT_C = 30.0          # Desired temperature
KP = 25.0                  # PWM per degree C

N_SAMPLES = 1000            # Raw thermistor measurements per control cycle

# Thermistor / voltage-divider parameters
VCC = 5.0
R_FIXED = 10_000.0          # Ohms
R0 = 10_000.0               # Thermistor resistance at T0
T0_K = 25.0 + 273.15
BETA = 3950.0               # Thermistor beta value

CONTROL_PERIOD = 0.05       # Seconds between control updates


# =========================
# Thermistor conversion
# =========================
def voltage_to_temperature(voltage):
    """
    Convert thermistor-divider voltage to Celsius.

    Assumes:
        VCC --- R_FIXED --- ADC node --- thermistor --- GND
    """

    voltage = np.asarray(voltage, dtype=float)

    # Prevent division by zero / invalid logarithms.
    voltage = np.clip(voltage, 1e-6, VCC - 1e-6)

    # Thermistor resistance.
    r_therm = R_FIXED * voltage / (VCC - voltage)

    # Beta equation.
    inv_T = (1.0 / T0_K) + (1.0 / BETA) * np.log(r_therm / R0)

    return (1.0 / inv_T) - 273.15


# =========================
# Arduino communication
# =========================
arduino = serial.Serial(
    SERIAL_PORT,
    BAUD_RATE,
    timeout=1
)

time.sleep(2)
arduino.reset_input_buffer()


def read_averaged_temperature():
    """
    Read exactly N_SAMPLES raw voltage measurements,
    average them, then convert the average voltage to temperature.
    """

    voltages = np.empty(N_SAMPLES, dtype=np.float64)

    i = 0

    while i < N_SAMPLES:
        line = arduino.readline()

        if not line:
            continue

        try:
            voltage = float(line.decode("ascii").strip())
        except ValueError:
            continue

        if 0.0 <= voltage <= VCC:
            voltages[i] = voltage
            i += 1

    # Step 1: average approximately 1000 raw measurements.
    average_voltage = np.mean(voltages)

    # Step 2: convert the averaged voltage to temperature.
    temperature = float(voltage_to_temperature(average_voltage))

    return temperature


def send_control(direction, pwm):
    """
    Arduino protocol:
        H,123
        C,87
        S,0

    H = heat
    C = cool
    S = stop
    """

    arduino.write(f"{direction},{pwm}\n".encode("ascii"))


# =========================
# Plot setup
# =========================
plt.ion()

fig, (ax_temp, ax_control) = plt.subplots(
    2, 1,
    figsize=(10, 7),
    sharex=True
)

time_data = deque(maxlen=500)
temp_data = deque(maxlen=500)
setpoint_data = deque(maxlen=500)
error_data = deque(maxlen=500)
pwm_data = deque(maxlen=500)
direction_data = deque(maxlen=500)

temp_line, = ax_temp.plot([], [], label="Temperature (°C)")
setpoint_line, = ax_temp.plot([], [], "--", label="Setpoint (°C)")
error_line, = ax_temp.plot([], [], label="Error (°C)")

pwm_line, = ax_control.plot([], [], label="PWM")
direction_line, = ax_control.step(
    [], [], where="post", label="Direction"
)

ax_temp.set_ylabel("Temperature / Error")
ax_temp.grid(True)
ax_temp.legend()

ax_control.set_ylabel("PWM / Direction")
ax_control.set_xlabel("Time (s)")
ax_control.set_ylim(-1.5, 256)
ax_control.grid(True)
ax_control.legend()

start_time = time.monotonic()


# =========================
# Main control loop
# =========================
try:
    while plt.fignum_exists(fig.number):

        loop_start = time.monotonic()

        # -------------------------------------------------
        # 1. Read ~1000 raw measurements and average them.
        #    Then convert the average voltage to temperature.
        # -------------------------------------------------
        temperature = read_averaged_temperature()

        # -------------------------------------------------
        # 2. Calculate temperature error.
        # -------------------------------------------------
        error = SETPOINT_C - temperature

        # -------------------------------------------------
        # 3. Calculate controller output.
        # -------------------------------------------------
        control = KP * error

        # -------------------------------------------------
        # 4. Convert sign of control into heat/cool direction.
        # -------------------------------------------------
        if control > 0:
            direction = "H"       # Heat
            direction_value = 1

        elif control < 0:
            direction = "C"       # Cool
            direction_value = -1

        else:
            direction = "S"       # Stop
            direction_value = 0

        # -------------------------------------------------
        # 5. Convert control to integer PWM magnitude.
        # -------------------------------------------------
        pwm = int(round(abs(control)))

        # -------------------------------------------------
        # 6. Clamp PWM to 0...255.
        # -------------------------------------------------
        pwm = np.clip(pwm, 0, 255)
        pwm = int(pwm)

        # -------------------------------------------------
        # 7. Send direction + PWM to Arduino.
        # -------------------------------------------------
        send_control(direction, pwm)

        # -------------------------------------------------
        # 8. Update plots.
        # -------------------------------------------------
        elapsed = time.monotonic() - start_time

        time_data.append(elapsed)
        temp_data.append(temperature)
        setpoint_data.append(SETPOINT_C)
        error_data.append(error)
        pwm_data.append(pwm)
        direction_data.append(direction_value)

        temp_line.set_data(time_data, temp_data)
        setpoint_line.set_data(time_data, setpoint_data)
        error_line.set_data(time_data, error_data)

        pwm_line.set_data(time_data, pwm_data)
        direction_line[0].set_data(time_data, direction_data)

        ax_temp.relim()
        ax_temp.autoscale_view()

        ax_control.set_xlim(
            max(0, elapsed - 30),
            max(30, elapsed)
        )

        fig.canvas.draw_idle()
        fig.canvas.flush_events()

        # Maintain approximately the requested control period.
        remaining = CONTROL_PERIOD - (
            time.monotonic() - loop_start
        )

        if remaining > 0:
            time.sleep(remaining)

except KeyboardInterrupt:
    print("Stopping controller...")

finally:
    # Safely stop the heater/cooler.
    send_control("S", 0)
    arduino.close()

    plt.ioff()
    plt.show()
