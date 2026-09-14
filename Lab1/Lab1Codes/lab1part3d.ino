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

