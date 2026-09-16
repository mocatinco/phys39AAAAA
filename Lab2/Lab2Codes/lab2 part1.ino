
unsigned long t=0.0;
int sample_count=500;
double R0 = 100*1000.0;
void setup() {
  Serial.begin(9600);
  pinMode(A0, INPUT);
}

void loop() {
  double AdcAve=averageAdcSamples(sample_count);
  double VoltAve=adcToVoltage(AdcAve);
  double resistance=voltageToResistance(VoltAve);
  double temperature=resistanceToCelsius(resistance);
  //printHumanReadable(AdcAve,VoltAve,resistance,temperature);
  Serial.println(temperature);
  delay(1);
}
void printHumanReadable(double AdcAve,double VoltAve,double resistance,double temperature)
{
  Serial.print("time = ");
  Serial.print(t);
  Serial.print("ms\t");
  Serial.print("average ADC = ");
  Serial.print(AdcAve);
  Serial.print("\t");
  Serial.print("voltage = ");
  Serial.print(VoltAve);
  Serial.print("V\t");
  Serial.print("resistance = ");
  Serial.print(resistance/1000.);
  Serial.print("kOhm\t");
  Serial.print("temperature = ");
  Serial.print(temperature);
  Serial.print("C\t");
  Serial.print("samples = ");
  Serial.println(sample_count);
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