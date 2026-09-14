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

