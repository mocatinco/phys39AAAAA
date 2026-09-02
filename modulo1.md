# Module 1 Assignment: First Contact With The Instrument CODE
## Part 1: Blink And Digital Output
void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
}
void loop(){
  digitalWrite(LED_BUILTIN, HIGH);
  delay(100);
  digitalWrite(LED_BUILTIN, LOW);
  delay(100);
}


## Part 2: AnalogReadSerial

void setup() {
  Serial.begin(9600);
}
void loop() {
  int sensorValue = analogRead(A0);
  Serial.println(sensorValue);
    delay(1);
}


## Part 3: Quantify The Power Of Averaging
### 3A: Observe The Integer ADC Readings
Same code as Part 2

### 3B: Convert ADC Number To Voltage
void setup() {
  Serial.begin(9600);
}
void loop() {
  double voltAve = 0.;
  int numAve = 1;
    for (int i = 0; i < numAve; i++){
    int sensorValue = analogRead(A0);
    voltAve += sensorValue;
  }


  voltAve = voltAve/numAve;
  voltAve = voltAve * (5000 / 1023.); // convert to millivolts


  Serial.println(voltAve);
  delay(1);
}


### 3C: Compare One Reading With A 1000-Reading Average
Same code as Part 3B

### 3D: Measure The Time Cost Of Averaging
unsigned long t1;
unsigned long t2;


void setup() {
  Serial.begin(9600);
}
void loop() {
  double voltAve = 0.;
  int numAve = 1;
  t1=micros();
  for (int i = 0; i < numAve; i++){
    int sensorValue = analogRead(A0);
    voltAve += sensorValue;
  }
  t2=micros();
  Serial.println('t='+(t2-t1));
  delay(1);
}


## Part 4: LED Brightness From Averaged Analog Input
const int ledPin = 9;
void setup() {
  Serial.begin(9600);
  pinMode(ledPin, OUTPUT);
}


void loop() {
  double voltAve = 0.;
  int numAve = 1;
    for (int i = 0; i < numAve; i++){
    int sensorValue = analogRead(A0);
    voltAve += sensorValue;
  }
    voltAve = voltAve/numAve;
  analogWrite(ledPin, voltAve/4);  
}
