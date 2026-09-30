import matplotlib.pyplot as plt
import pandas as pd
import numpy as np



x, y = [-84, -63, -42, -21, 0, 0, 10, 21, 30, 42], [9.75, 14, 16.7, 20.4, 23, 22.7, 29, 31, 39.14, 44]
plt.scatter(x[:5], y[:5], color='b', label='cooling')
plt.scatter(x[5:], y[5:], color='r', label='heating')

b, ln_a = np.polyfit(np.array(x), np.log(y), 1)
plt.plot(x, np.exp(ln_a) * np.exp(b * np.array(x)), 'k--',label="exp trendline, scale=25.65, rate=0.0111")
print(f"Fit Results -> Scale (a): {np.exp(ln_a):.4f}, Growth Rate (b): {b:.4f}")

plt.title("PWM vs Equil. Temp")
plt.xlabel("PWM")
plt.ylabel("Temperature (°C)")
plt.legend()
plt.savefig('lab4part4.png')
