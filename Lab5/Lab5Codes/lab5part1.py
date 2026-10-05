
# ========================================================
# PROPORTIONAL CONTROLLER
# ========================================================

def automatic_temperature_control(
    self,
    temperature
):
    """
    Pure proportional temperature controller.

        error = desired_temperature - temperature

        HEAT:
            PWM = KP_HEAT * error

        COOL:
            PWM = KP_COOL * error

    There is NO baseline PWM, offset, bias, or correction term.

    At exactly the setpoint:
        error = 0
        PWM = 0
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
    # SELECT PROPORTIONAL GAIN
    # ====================================================

    if error > 0:
        # Temperature is below setpoint -> HEAT
        kp = KP_HEAT
        mode = "HEAT"

    elif error < 0:
        # Temperature is above setpoint -> COOL
        kp = KP_COOL
        mode = "COOL"

    else:
        # Exactly at setpoint -> NO OUTPUT
        kp = 0.0
        mode = "AT TARGET"

    # ====================================================
    # PURE PROPORTIONAL CONTROL
    # ====================================================

    requested_signed_pwm = kp * error

    # ====================================================
    # CLAMP PWM
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

    previous_pwm = self.current_signed_pwm

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
    # SECOND SAFETY CLAMP
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
