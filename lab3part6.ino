
/*
  Arduino Temperature + Python PWM Control

  Hardware:
    A0  = thermistor measurement
    Pin 9  = HEAT
    Pin 10 = COOL

  The A1 trim potentiometer and pin 11 switch
  have been removed.

  Python sends commands such as:

      SET PWM 120 DIR HEAT
      SET PWM 45 DIR COOL

  The Arduino starts with PWM = 0.

  Safety behavior:
    - PWM is always limited to 0-255.
    - At startup, both H-bridge outputs are OFF.
    - Only one H-bridge direction is active at a time.
    - Invalid commands are ignored.
    - No feedback control is implemented.
*/


// ============================================================
// PIN DEFINITIONS
// ============================================================

const int THERM_PIN = A0;

const int HEAT_PIN = 9;
const int COOL_PIN = 10;


// ============================================================
// THERMISTOR SETTINGS
// ============================================================

const int SAMPLE_COUNT = 1000;

// Reference resistance used by the thermistor calculation.
double R0 = 100 * 1000.0;


// ============================================================
// PWM / DIRECTION SETTINGS
// ============================================================

// PWM starts at zero for safety.
int pwmValue = 0;

// 1 = HEAT
// 0 = COOL
//
// This value is only reported according to the experimentally
// verified direction mapping:
//
//     Pin 9  = HEAT = 1
//     Pin 10 = COOL = 0
//
// Start with HEAT selected, but PWM is zero so neither output
// is actively driving the H-bridge.
int heatCool = 1;


// ============================================================
// SERIAL COMMAND BUFFER
// ============================================================

// Python sends commands as complete lines.
// For example:
//
//     SET PWM 120 DIR HEAT
//
// The buffer stores one incoming command at a time.
const int COMMAND_LENGTH = 40;

char commandBuffer[COMMAND_LENGTH];

int commandIndex = 0;


// ============================================================
// SETUP
// ============================================================

void setup()
{
  Serial.begin(9600);

  pinMode(THERM_PIN, INPUT);

  pinMode(HEAT_PIN, OUTPUT);
  pinMode(COOL_PIN, OUTPUT);

  // ----------------------------------------------------------
  // SAFETY STARTUP
  // ----------------------------------------------------------

  // Both outputs start OFF.
  analogWrite(HEAT_PIN, 0);
  analogWrite(COOL_PIN, 0);

  // Start with PWM zero.
  pwmValue = 0;

  // ----------------------------------------------------------
  // Make sure the serial command buffer starts empty.
  // ----------------------------------------------------------

  commandIndex = 0;
}


// ============================================================
// MAIN LOOP
// ============================================================

void loop()
{
  // ----------------------------------------------------------
  // 1. Check for commands from Python.
  // ----------------------------------------------------------

  readSerialCommands();


  // ----------------------------------------------------------
  // 2. Measure thermistor temperature.
  // ----------------------------------------------------------

  double adcAverage = averageAdcSamples(SAMPLE_COUNT);

  double voltageAverage = adcToVoltage(adcAverage);

  double resistance = voltageToResistance(
    voltageAverage
  );

  double temperature = resistanceToCelsius(
    resistance
  );


  // ----------------------------------------------------------
  // 3. Get elapsed Arduino time.
  // ----------------------------------------------------------

  // millis() gives the time since the Arduino started,
  // in milliseconds.

  double timeSeconds = millis() / 1000.0;


  // ----------------------------------------------------------
  // 4. Print measurement line.
  // ----------------------------------------------------------

  printMeasurement(
    temperature,
    timeSeconds,
    pwmValue,
    heatCool
  );


  // ----------------------------------------------------------
  // 5. Small delay before the next measurement.
  // ----------------------------------------------------------

  delay(10);
}


// ============================================================
// SERIAL COMMAND PARSER
// ============================================================

void readSerialCommands()
{
  /*
    Read characters sent by Python until a newline is received.

    Expected commands:

        SET PWM 120 DIR HEAT
        SET PWM 45 DIR COOL

    Safety behavior:
      - Commands must begin with "SET PWM".
      - PWM values are clamped to 0-255.
      - Only HEAT or COOL is accepted.
      - Invalid commands are ignored.
      - The Arduino does not perform feedback control.
  */

  while (Serial.available() > 0)
  {
    char incoming = Serial.read();


    // --------------------------------------------------------
    // A newline means the complete command has arrived.
    // --------------------------------------------------------

    if (incoming == '\n' || incoming == '\r')
    {
      if (commandIndex > 0)
      {
        commandBuffer[commandIndex] = '\0';

        processCommand(commandBuffer);

        commandIndex = 0;
      }
    }


    // --------------------------------------------------------
    // Store another character.
    // --------------------------------------------------------

    else
    {
      // Leave room for the terminating '\0'.
      if (commandIndex < COMMAND_LENGTH - 1)
      {
        commandBuffer[commandIndex] = incoming;
        commandIndex++;
      }

      else
      {
        // Command is too long.
        // Discard it for safety.
        commandIndex = 0;
      }
    }
  }
}


// ============================================================
// PROCESS ONE COMMAND
// ============================================================

void processCommand(char *command)
{
  /*
    Parse commands in the form:

        SET PWM ### DIR HEAT

    or:

        SET PWM ### DIR COOL

    Example:

        SET PWM 120 DIR HEAT

    The PWM value is clamped to 0-255.
  */

  int newPWM;

  char direction[10];


  // ----------------------------------------------------------
  // Try to parse the command.
  // ----------------------------------------------------------

  int items = sscanf(
    command,
    "SET PWM %d DIR %9s",
    &newPWM,
    direction
  );


  // ----------------------------------------------------------
  // Ignore malformed commands.
  // ----------------------------------------------------------

  if (items != 2)
  {
    return;
  }


  // ----------------------------------------------------------
  // Clamp PWM.
  // ----------------------------------------------------------

  if (newPWM < 0)
  {
    newPWM = 0;
  }

  if (newPWM > 255)
  {
    newPWM = 255;
  }


  // ----------------------------------------------------------
  // HEAT command
  // ----------------------------------------------------------

  if (strcmp(direction, "HEAT") == 0)
  {
    heatCool = 1;

    pwmValue = newPWM;

    // Apply HEAT only to pin 9.
    //
    // Pin 10 is explicitly turned OFF first so that
    // both H-bridge directions cannot be active together.

    analogWrite(COOL_PIN, 0);
    analogWrite(HEAT_PIN, pwmValue);
  }


  // ----------------------------------------------------------
  // COOL command
  // ----------------------------------------------------------

  else if (strcmp(direction, "COOL") == 0)
  {
    heatCool = 0;

    pwmValue = newPWM;

    // Apply COOL only to pin 10.
    //
    // Pin 9 is explicitly turned OFF first.

    analogWrite(HEAT_PIN, 0);
    analogWrite(COOL_PIN, pwmValue);
  }


  // ----------------------------------------------------------
  // Unknown direction
  // ----------------------------------------------------------

  else
  {
    // Ignore the command.
    return;
  }
}


// ============================================================
// PRINT MEASUREMENT
// ============================================================

void printMeasurement(
  double temperature,
  double timeSeconds,
  int pwm,
  int direction
)
{
  /*
    This is the measurement-line interface used by Python.

    Example:

    Temperature (C): 27.73, Time (s): 645.06,
    PWM: 120, Heat/Cool: 1
  */

  Serial.print("Temperature (C): ");
  Serial.print(temperature, 2);

  Serial.print(", Time (s): ");
  Serial.print(timeSeconds, 2);

  Serial.print(", PWM: ");
  Serial.print(pwm);

  Serial.print(", Heat/Cool: ");
  Serial.println(direction);
}


// ============================================================
// AVERAGE ADC SAMPLES
// ============================================================

double averageAdcSamples(int numSamples)
{
  double adcAverage = 0.0;


  for (int i = 0; i < numSamples; i++)
  {
    int sensorValue = analogRead(THERM_PIN);

    adcAverage += sensorValue;
  }


  adcAverage = adcAverage / numSamples;

  return adcAverage;
}


// ============================================================
// ADC TO VOLTAGE
// ============================================================

double adcToVoltage(double adcAverage)
{
  double voltageAverage =
    adcAverage * (5.0 / 1023.0);

  return voltageAverage;
}


// ============================================================
// VOLTAGE TO THERMISTOR RESISTANCE
// ============================================================

double voltageToResistance(double voltage)
{
  double R1 = 100 * 1000.0;

  /*
    Voltage divider equation:

        R2 = R1 * Vout / (5 - Vout)
  */

  double R2 =
    (R1 * voltage) / (5.0 - voltage);

  return R2;
}


// ============================================================
// THERMISTOR RESISTANCE TO TEMPERATURE
// ============================================================

double resistanceToCelsius(double resistance)
{
  /*
    Beta equation used by the original Arduino sketch.
  */

  double kelvin =
    4540.0 /
    (
      log(resistance / R0)
      +
      (4540.0 / (25.0 + 273.15))
    );


  double celsius =
    kelvin - 273.15;

  return celsius;
}
