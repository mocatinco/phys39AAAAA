const int trim= A1;
const int therm=A0;

unsigned long t=0.0;
int sample_count=1000;
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
  long t1=micros();
  double AdcAve=averageAdcSamples(sample_count);
  double VoltAve=adcToVoltage(AdcAve);
  double resistance=voltageToResistance(VoltAve);
  double temperature=resistanceToCelsius(resistance);
  int pwm=trimpod();
  int pinnum=runpin(pwm);
  long t2=micros();
  t = (t2-t1)/1000.0;
  printpart2(temperature,pwm,pinnum,t);
  delay(10);
}
void printpart2(double temperature, int pwm, int pinnum, long t)
{
  Serial.print("Temperature (C): ");
  Serial.print(temperature, 2); // Prints double with 2 decimal places
  Serial.print(", Time (ms): ");
  Serial.print(t);              // Prints long integer
  Serial.print(", PWM: ");
  Serial.print(pwm);            // Prints int
  Serial.print(", Active PWM pin: ");
  Serial.println(pinnum);       // println finishes the line and moves to the next
}

int trimpod ()
{
  int val = analogRead(trim); // Read trimpod (0 to 1023)
  int pwm=map(val, 0, 1023, 0, 255);
  return pwm;
}

int runpin(int pwm)
{
    if(digitalRead(11)==LOW)
  {
      analogWrite(9, pwm); 
      digitalWrite(10, LOW); 
      return 9;
  }
 else {
    digitalWrite(9, LOW);
    analogWrite(10, pwm); 
  }
  return 10;
}
double averageAdcSamples (int numAve)
{
  double AdcAve = 0.;
  
    for (int i = 0; i < numAve; i++){
    int sensorValue = analogRead(A0);
    AdcAve += sensorValue;
  }
  
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
