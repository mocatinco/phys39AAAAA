const int trim= A1;
const int therm=A0;

unsigned long t=0.0;
int sample_count=500;
double R0 = 100*1000.0;

void setup() {
  Serial.begin(9600);
  pinMode(trim, INPUT);
  pinMode(therm, INPUT);
  pinMode(9, OUTPUT);
  pinMode(10, OUTPUT);
  pinMode(11,INPUT);
}

void loop() {
  double AdcAve=averageAdcSamples(sample_count);
  double VoltAve=adcToVoltage(AdcAve);
  double resistance=voltageToResistance(VoltAve);
  double temperature=resistanceToCelsius(resistance);
  trimpod();
  Serial.println(temperature);
  delay(10);
}

void trimpod ()
{
  int val = analogRead(trim); // Read trimpod (0 to 1023)
  Serial.print(val);
  Serial.print("\t");
  if(digitalRead(11)==LOW)
  {
      analogWrite(9, map(val, 0, 1023, 0, 255)); 
      digitalWrite(10, LOW); 
  }
 else {
    digitalWrite(9, LOW);
    analogWrite(10, map(val, 0,1023, 0, 255)); 
  }
  delay(10);
}
double averageAdcSamples (int numAve)
{
  double AdcAve = 0.;
  long t1=micros();
    for (int i = 0; i < numAve; i++){
    int sensorValue = analogRead(A0);
    AdcAve += sensorValue;
  }
  long t2=micros();
   t = (t2-t1)/1000.0;
  AdcAve = AdcAve/numAve;
  return AdcAve;
}

double adcToVoltage(double AdcAve){
  double voltAve = AdcAve * (5/1023.);
  return voltAve;
}

double voltageToResistance(double V_out)
{
  double R1=100*1000.;
  double R2 = ((R1*V_out)/(5.0-V_out)) ;
  return R2;
}

double resistanceToCelsius(double R){ 
  double kelvin = ((4540.0)/((log(R/R0)+(4540.0/(25.0+273.15))))); 
  //kelvin = 1./(1./(25.0 + 273.15) + log(R/R0) / 4540.0);
  double celsius = kelvin -273.15;
  return celsius;

}
