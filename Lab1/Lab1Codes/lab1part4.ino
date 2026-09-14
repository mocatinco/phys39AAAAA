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
