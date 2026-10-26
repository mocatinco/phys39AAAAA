/*
  Arduino Temperature + Python PWM Control

  Thermistors:
    A0 = TEC-base thermistor (the only sensor used for control/safety)
    A1 = rod thermistor 1
    A2 = rod thermistor 2
    A3 = rod thermistor 3
    A4 = rod thermistor 4
    A5 = rod thermistor 5

  H-bridge outputs (preserved from the original sketch):
    Pin 10 = HEAT
    Pin 9  = COOL

  Python commands remain unchanged:
    SET PWM 120 DIR HEAT
    SET PWM 45 DIR COOL

  The Arduino starts with PWM = 0. It does not implement the PI
  controller; the PI controller and software cutoff remain in Python.
*/

#include <math.h>
#include <stdio.h>
#include <string.h>

// ============================================================
// PIN DEFINITIONS
// ============================================================

// A0 is the TEC-base sensor. A1-A5 are the five rod sensors.
// Keeping these pin names separate makes each sensor's purpose clear.
const int TEC_THERM_PIN = A0;
const int ROD_THERM_PINS[5] = {A1, A2, A3, A4, A5};

// Keep the original H-bridge output pins unchanged.
const int HEAT_PIN = 10;
const int COOL_PIN = 9;

// ============================================================
// THERMISTOR SETTINGS
// ============================================================

// Each analog channel is averaged this many times per acquisition cycle.
const int SAMPLE_COUNT = 1000;

// Reference resistance used by the original thermistor calculation.
double R0 = 100 * 1000.0;

// The software safety range is the same range used by Python.
const double SAFE_TEMP_MIN = 0.0;
const double SAFE_TEMP_MAX = 60.0;

// The setpoint is controlled by Python, but the existing PWM command
// does not transmit it. NAN honestly marks it as unavailable here.
// The Python command format is intentionally not changed.
const double SETPOINT_NOT_TRANSMITTED = NAN;

// ============================================================
// PWM / DIRECTION SETTINGS
// ============================================================

// PWM starts at zero for safety.
int pwmValue = 0;

// 1 = HEAT, 0 = COOL, matching the existing Python interpretation.
int heatCool = 1;

// ============================================================
// SERIAL COMMAND BUFFER
// ============================================================

const int COMMAND_LENGTH = 40;
char commandBuffer[COMMAND_LENGTH];
int commandIndex = 0;

// ============================================================
// FUNCTION DECLARATIONS
// ============================================================
void readSerialCommands();
void processCommand(char *command);
void printMeasurement(double timeSeconds, const double temperatures[6],
                      int pwm, int direction, double setpoint, int safety);
double averageAdcSamples(int pin, int numSamples);
double adcToVoltage(double adcAverage);
double voltageToResistance(double voltage);
double resistanceToCelsius(double resistance);

// ============================================================
// SETUP
// ============================================================

void setup()
{
  Serial.begin(9600);

  // Set all six analog inputs explicitly, including each rod sensor.
  pinMode(TEC_THERM_PIN, INPUT);
  for (int i = 0; i < 5; i++)
  {
    pinMode(ROD_THERM_PINS[i], INPUT);
  }

  pinMode(HEAT_PIN, OUTPUT);
  pinMode(COOL_PIN, OUTPUT);

  // SAFETY STARTUP: both H-bridge outputs are off and PWM is zero.
  analogWrite(HEAT_PIN, 0);
  analogWrite(COOL_PIN, 0);
  pwmValue = 0;
  heatCool = 1;
  commandIndex = 0;

  // Print the CSV-style data header exactly once at startup.
  Serial.println("DATA,time_s,tec_C,rod1_C,rod2_C,rod3_C,rod4_C,rod5_C,pwm,heat_cool,setpoint_C,safety");
}

// ============================================================
// MAIN LOOP: ACQUIRE SIX SENSORS, THEN TIMESTAMP AND REPORT
// ============================================================

void loop()
{
  // Continue accepting the same newline-terminated Python commands.
  readSerialCommands();

  double temperatures[6];

  // Beginner note: read each sensor separately. For every channel,
  // average SAMPLE_COUNT analog readings, then use the same voltage,
  // resistance, and Celsius conversion functions as the original sketch.
  for (int channel = 0; channel < 6; channel++)
  {
    int sensorPin;
    if (channel == 0)
    {
      sensorPin = TEC_THERM_PIN;  // A0: TEC-base sensor
    }
    else
    {
      sensorPin = ROD_THERM_PINS[channel - 1];  // A1-A5: rod sensors
    }

    double adcAverage = averageAdcSamples(sensorPin, SAMPLE_COUNT);
    double voltageAverage = adcToVoltage(adcAverage);
    double resistance = voltageToResistance(voltageAverage);
    temperatures[channel] = resistanceToCelsius(resistance);
  }

  // Record elapsed time only after all six measurements are acquired.
  double timeSeconds = millis() / 1000.0;

  // A0 alone determines the reported software-safety status, matching
  // Python's 0-60 C software limit. The Python program still enforces
  // the actual cutoff and remains the only feedback controller.
  int safety = (temperatures[0] >= SAFE_TEMP_MIN &&
                temperatures[0] <= SAFE_TEMP_MAX) ? 1 : 0;

  // Emit exactly one DATA record for this acquisition cycle.
  // No diagnostic, command acknowledgement, or error messages use DATA.
  printMeasurement(timeSeconds, temperatures, pwmValue, heatCool,
                   SETPOINT_NOT_TRANSMITTED, safety);

  delay(10);
}

// ============================================================
// SERIAL COMMAND PARSER (UNCHANGED COMMAND FORMAT AND BEHAVIOR)
// ============================================================

void readSerialCommands()
{
  while (Serial.available() > 0)
  {
    char incoming = Serial.read();

    if (incoming == '\n' || incoming == '\r')
    {
      if (commandIndex > 0)
      {
        commandBuffer[commandIndex] = '\0';
        processCommand(commandBuffer);
        commandIndex = 0;
      }
    }
    else
    {
      if (commandIndex < COMMAND_LENGTH - 1)
      {
        commandBuffer[commandIndex] = incoming;
        commandIndex++;
      }
      else
      {
        // Discard an overlong command, as in the original sketch.
        commandIndex = 0;
      }
    }
  }
}

// ============================================================
// PROCESS ONE COMMAND (UNCHANGED COMMAND FORMAT AND CONTROL LOGIC)
// ============================================================

void processCommand(char *command)
{
  int newPWM;
  char direction[10];

  int items = sscanf(command, "SET PWM %d DIR %9s", &newPWM, direction);
  if (items != 2)
  {
    return;  // Ignore malformed commands.
  }

  if (newPWM < 0) newPWM = 0;
  if (newPWM > 255) newPWM = 255;

  if (strcmp(direction, "HEAT") == 0)
  {
    heatCool = 1;
    pwmValue = newPWM;
    analogWrite(COOL_PIN, 0);       // Turn the opposite direction off first.
    analogWrite(HEAT_PIN, pwmValue);
  }
  else if (strcmp(direction, "COOL") == 0)
  {
    heatCool = 0;
    pwmValue = newPWM;
    analogWrite(HEAT_PIN, 0);       // Turn the opposite direction off first.
    analogWrite(COOL_PIN, pwmValue);
  }
  else
  {
    return;  // Ignore unknown directions.
  }
}

// ============================================================
// SERIAL OUTPUT: ONE COMMA-SEPARATED DATA RECORD PER CYCLE
// ============================================================

void printMeasurement(double timeSeconds, const double temperatures[6],
                      int pwm, int direction, double setpoint, int safety)
{
  // Keep the DATA prefix and field order exactly aligned with the header.
  // Each value is separated by a comma; no extra DATA lines are printed.
  Serial.print("DATA,");
  Serial.print(timeSeconds, 2);
  for (int i = 0; i < 6; i++)
  {
    Serial.print(',');
    Serial.print(temperatures[i], 2);
  }
  Serial.print(',');
  Serial.print(pwm);
  Serial.print(',');
  Serial.print(direction);
  Serial.print(',');
  if (isnan(setpoint)) Serial.print("nan");
  else Serial.print(setpoint, 2);
  Serial.print(',');
  Serial.println(safety);
}

// ============================================================
// AVERAGE ADC SAMPLES
// ============================================================

// Read the requested analog pin repeatedly and return its arithmetic mean.
double averageAdcSamples(int pin, int numSamples)
{
  double adcAverage = 0.0;
  for (int i = 0; i < numSamples; i++)
  {
    int sensorValue = analogRead(pin);
    adcAverage += sensorValue;
  }
  adcAverage = adcAverage / numSamples;
  return adcAverage;
}

// ============================================================
// ADC TO VOLTAGE (UNCHANGED CONVERSION)
// ============================================================

double adcToVoltage(double adcAverage)
{
  double voltageAverage = adcAverage * (5.0 / 1023.0);
  return voltageAverage;
}

// ============================================================
// VOLTAGE TO THERMISTOR RESISTANCE (UNCHANGED CONVERSION)
// ============================================================

double voltageToResistance(double voltage)
{
  double R1 = 100 * 1000.0;
  double R2 = (R1 * voltage) / (5.0 - voltage);
  return R2;
}

// ============================================================
// THERMISTOR RESISTANCE TO CELSIUS (UNCHANGED BETA EQUATION)
// ============================================================

double resistanceToCelsius(double resistance)
{
  double kelvin = 4540.0 /
    (log(resistance / R0) + (4540.0 / (25.0 + 273.15)));
  double celsius = kelvin - 273.15;
  return celsius;
}
