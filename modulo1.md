# Module 1 Assignment: First Contact With The Instrument
## Part 1: Blink And Digital Output
Change the HIGH:LOW time ratio from 1:1 to 10:1 and then 1:10. Play with the on and off times. For each case, use the oscilloscope to measure the output-pin high voltage, low voltage, period, frequency, and duty cycle.

## Part 2: AnalogReadSerial

Rotate the potentiometer and confirm that the reported ADC number responds. Part 3 develops this observation into a quantitative measurement of ADC digitization and averaging.

Use Analog, ADC, And PWM when you need the ideas behind the measurement.

## Part 3: Quantify The Power Of Averaging
### 3A: Observe The Integer ADC Readings
Do the reported values vary even when you do not touch the potentiometer?
Do the values change continuously, or do they occupy discrete integer levels? Why?
What does Serial Monitor reveal that is difficult to see in Serial Plotter, and vice versa?

### 3B: Convert ADC Number To Voltage
Calculate this resolution in millivolts. For a 5.00 V reference it is about 4.88 mV. Explain why printing many decimal places does not, by itself, give the ADC finer physical resolution.

### 3C: Compare One Reading With A 1000-Reading Average
Print only one plotted voltage quantity per line. In Serial Monitor, also identify the point number and whether it came from 

Stop the plotter when the transition between an unaveraged block and a 1000-reading average block is approximately halfway across the graph, as in the figure below. Your numerical values and detailed trace need not look identical to the example. Save this screenshot and the corresponding numerical output.

(a) For each 100-point block, calculate the mean voltage and sample standard deviation. In this exercise, use as an empirical estimate of the noise-limited voltage resolution of the reported value. Compare the measured ratio with the independent-noise prediction

(b) A second way to measure the effective resolution in millivolts for the unaveraged and averaged blocks is by looking at the smallest discrete voltage jump between two subsequent data points. Compare the unaveraged smallest discrete voltage jump between two subsequent data points with the ADC's fixed one-count digitization step. 

Explain likely departures from the prediction, including drift, correlated pickup, quantization, and variation of the Arduino reference voltage. Averaging improves precision under these conditions, but it does not automatically improve absolute accuracy or remove calibration errors.

### 3D: Measure The Time Cost Of Averaging
Explain the tradeoff. Averaging over a finite interval acts as a low-pass filter: rapid fluctuations tend to cancel, but changes occurring during the averaging window are smoothed or delayed. Improved voltage precision therefore comes with reduced time resolution.

## Part 4: LED Brightness From Averaged Analog Input
Record the PWM high and low voltages, period, frequency, and duty cycle at two substantially different potentiometer settings. Determine which quantities change and which remain approximately fixed. If you use Arduino Uno pin 9, compare the measured frequency with the expected value of approximately 490 Hz. Compare this with the roughly 50-60 Hz range above which ordinary flicker often appears steady to the eye. Explain why the LED looks continuously lit even though the oscilloscope resolves individual pulses.

test