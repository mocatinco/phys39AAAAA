const int trim= A1;
void setup() {
  Serial.begin(9600);
  pinMode(trim, INPUT);
  pinMode(9, OUTPUT);
  pinMode(10, OUTPUT);
}

void loop() {
  int val = analogRead(trim); // Read trimpod (0 to 1023)
  Serial.println(val);

  if (val > 512) {
    analogWrite(9, map(val, 0, 511, 0, 255)); 
    digitalWrite(10, LOW);
  } else {
    digitalWrite(9, LOW);
    analogWrite(10, map(val, 1023,512, 0, 255)); 
  }
  delay(10);
}

