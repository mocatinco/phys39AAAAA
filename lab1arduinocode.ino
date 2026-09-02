//Part 1
void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
}
void loop(){
  digitalWrite(LED_BUILTIN, HIGH);
  delay(100);
  digitalWrite(LED_BUILTIN, LOW);
  delay(100);
}

//Part 2
void setup() {
  Serial.begin(9600);
}
void loop() {
  int sensorValue = analogRead(A0);
  Serial.println(sensorValue);
    delay(1);
}

//Part 3B
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

//Part 3D
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

//Part 4
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
