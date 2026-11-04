
#include <math.h>
#include <stdio.h>
#include <string.h>

// ============================================================
// PIN DEFINITIONS
// ============================================================

const int TEC_THERM_PIN = A0;
const int ROD_THERM_PINS[5] = {A1, A2, A3, A4, A5};

const int HEAT_PIN = 10;
const int COOL_PIN = 9;

// ============================================================
// THERMISTOR SETTINGS
// ============================================================

const int SAMPLE_COUNT = 1000;

double R0 = 100 * 1000.0;

const double SAFE_TEMP_MIN = 0.0;
const double SAFE_TEMP_MAX = 60.0;

const double SETPOINT_NOT_TRANSMITTED = NAN;

// ============================================================
// PWM / DIRECTION SETTINGS
// ============================================================

int pwmValue = 0;

// 1 = HEAT, 0 = COOL
int heatCool = 1;

// ============================================================
// EXPERIMENT METADATA
// ============================================================

// Room temperature is measured separately and entered through
// the serial command: ROOM 22.5

double roomTemperatureC = NAN;

// Control mode: OPEN_LOOP, P, or PI
char controlMode[12] = "OPEN_LOOP";

// Open-loop command or requested TEC temperature setpoint
double commandInput = NAN;

// Raw P or PI controller output.
// NAN for open-loop operation.
double rawControllerCommand = NAN;

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

void printMeasurement(
    double timeSeconds,
    const double temperatures[6],
    int pwm,
    int direction,
    double setpoint,
    int safety
);

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

    pinMode(TEC_THERM_PIN, INPUT);

    for (int i = 0; i < 5; i++)
    {
        pinMode(ROD_THERM_PINS[i], INPUT);
    }

    pinMode(HEAT_PIN, OUTPUT);
    pinMode(COOL_PIN, OUTPUT);

    // SAFETY STARTUP
    analogWrite(HEAT_PIN, 0);
    analogWrite(COOL_PIN, 0);

    pwmValue = 0;
    heatCool = 1;

    commandIndex = 0;

    // Original columns are preserved.
    // Additional experimental metadata is appended.

    Serial.println(
        "DATA,time_s,tec_C,rod1_C,rod2_C,rod3_C,"
        "rod4_C,rod5_C,pwm,heat_cool,setpoint_C,safety,"
        "room_C,control_mode,command_input,raw_controller_cmd,"
        "signed_pwm"
    );
}

// ============================================================
// MAIN LOOP
// ============================================================

void loop()
{
    readSerialCommands();

    double temperatures[6];

    // Read all six thermistors.
    for (int channel = 0; channel < 6; channel++)
    {
        int sensorPin;

        if (channel == 0)
        {
            sensorPin = TEC_THERM_PIN;
        }
        else
        {
            sensorPin = ROD_THERM_PINS[channel - 1];
        }

        double adcAverage =
            averageAdcSamples(sensorPin, SAMPLE_COUNT);

        double voltageAverage =
            adcToVoltage(adcAverage);

        double resistance =
            voltageToResistance(voltageAverage);

        temperatures[channel] =
            resistanceToCelsius(resistance);
    }

    // Timestamp after all six measurements.
    double timeSeconds = millis() / 1000.0;

    // A0 remains the only Arduino safety sensor.
    int safety =
        (temperatures[0] >= SAFE_TEMP_MIN &&
         temperatures[0] <= SAFE_TEMP_MAX) ? 1 : 0;

    // Report the measurements and experiment metadata.
    printMeasurement(
        timeSeconds,
        temperatures,
        pwmValue,
        heatCool,
        SETPOINT_NOT_TRANSMITTED,
        safety
    );

    delay(10);
}

// ============================================================
// SERIAL COMMAND READER
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
                commandIndex = 0;
            }
        }
    }
}

// ============================================================
// PROCESS SERIAL COMMANDS
// ============================================================

void processCommand(char *command)
{
    int newPWM;
    char direction[10];

    // --------------------------------------------------------
    // ORIGINAL PYTHON PWM COMMANDS
    // --------------------------------------------------------

    int items = sscanf(
        command,
        "SET PWM %d DIR %9s",
        &newPWM,
        direction
    );

    if (items == 2)
    {
        if (newPWM < 0) newPWM = 0;
        if (newPWM > 255) newPWM = 255;

        if (strcmp(direction, "HEAT") == 0)
        {
            heatCool = 1;
            pwmValue = newPWM;

            analogWrite(COOL_PIN, 0);
            analogWrite(HEAT_PIN, pwmValue);
        }
        else if (strcmp(direction, "COOL") == 0)
        {
            heatCool = 0;
            pwmValue = newPWM;

            analogWrite(HEAT_PIN, 0);
            analogWrite(COOL_PIN, pwmValue);
        }

        return;
    }

    // --------------------------------------------------------
    // ROOM TEMPERATURE
    // --------------------------------------------------------

    double newRoomTemperature;

    if (sscanf(command, "ROOM %lf", &newRoomTemperature) == 1)
    {
        roomTemperatureC = newRoomTemperature;
        return;
    }

    // --------------------------------------------------------
    // EXPERIMENT METADATA
    // --------------------------------------------------------

    // Format:
    // META OPEN_LOOP 120 nan
    // META P 25.0 40.0
    // META PI 25.0 55.0
    //
    // Fields:
    // mode, command input, raw controller command

    char newMode[12];
    double newInput;
    double newRawCommand;

    if (sscanf(
        command,
        "META %11s %lf %lf",
        newMode,
        &newInput,
        &newRawCommand
    ) == 3)
    {
        if (strcmp(newMode, "OPEN_LOOP") == 0 ||
            strcmp(newMode, "P") == 0 ||
            strcmp(newMode, "PI") == 0)
        {
            strcpy(controlMode, newMode);

            commandInput = newInput;
            rawControllerCommand = newRawCommand;
        }

        return;
    }
}

// ============================================================
// SERIAL OUTPUT
// ============================================================

void printMeasurement(
    double timeSeconds,
    const double temperatures[6],
    int pwm,
    int direction,
    double setpoint,
    int safety
)
{
    // Signed PWM:
    // Positive = HEAT
    // Negative = COOL

    int signedPWM = direction ? pwm : -pwm;

    Serial.print("DATA,");

    Serial.print(timeSeconds, 2);

    // TEC and five rod temperatures.
    for (int i = 0; i < 6; i++)
    {
        Serial.print(',');
        Serial.print(temperatures[i], 2);
    }

    // Original fields.
    Serial.print(',');
    Serial.print(pwm);

    Serial.print(',');
    Serial.print(direction);

    Serial.print(',');

    if (isnan(setpoint))
        Serial.print("nan");
    else
        Serial.print(setpoint, 2);

    Serial.print(',');
    Serial.print(safety);

    // Additional experiment fields.
    Serial.print(',');

    if (isnan(roomTemperatureC))
        Serial.print("nan");
    else
        Serial.print(roomTemperatureC, 2);

    Serial.print(',');
    Serial.print(controlMode);

    Serial.print(',');

    if (isnan(commandInput))
        Serial.print("nan");
    else
        Serial.print(commandInput, 2);

    Serial.print(',');

    if (isnan(rawControllerCommand))
        Serial.print("nan");
    else
        Serial.print(rawControllerCommand, 2);

    Serial.print(',');
    Serial.println(signedPWM);
}

// ============================================================
// AVERAGE ADC SAMPLES
// ============================================================

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
// ADC TO VOLTAGE
// ============================================================

double adcToVoltage(double adcAverage)
{
    double voltageAverage =
        adcAverage * (5.0 / 1023.0);

    return voltageAverage;
}

// ============================================================
// VOLTAGE TO RESISTANCE
// ============================================================

double voltageToResistance(double voltage)
{
    double R1 = 100 * 1000.0;

    double R2 =
        (R1 * voltage) / (5.0 - voltage);

    return R2;
}

// ============================================================
// RESISTANCE TO CELSIUS
// ============================================================

double resistanceToCelsius(double resistance)
{
    double kelvin =
        4540.0 /
        (log(resistance / R0) +
         (4540.0 / (25.0 + 273.15)));

    double celsius = kelvin - 273.15;

    return celsius;
}
