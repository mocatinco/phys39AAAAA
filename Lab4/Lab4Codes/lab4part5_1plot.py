import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

data_10x2 = np.array([
    [-84,  9.75],
    [-63, 14.00],
    [-42, 16.70],
    [-21, 20.40],
    [  0, 23.00],
    [  0, 22.70],
    [ 10, 29.00],
    [ 21, 31.00],
    [ 30, 39.14],
    [ 42, 44.00]
])

x, y = [-84, -63, -42, -21, 0, 0, 10, 21, 30, 42], [9.75, 14, 16.7, 20.4, 23, 22.7, 29, 31, 39.14, 44]
plt.scatter(x[:5], y[:5], color='b', label='cooling')
plt.scatter(x[5:], y[5:], color='r', label='heating')
plt.plot(x[:5], np.poly1d(np.polyfit(x[:5], y[:5], 1))(x[:5]), 'b--', label='Cooling, slope=0.157')
plt.plot(x[5:], np.poly1d(np.polyfit(x[5:], y[5:], 1))(x[5:]), 'r--', label='Heating, slope=0.505')

slope_cooling = np.polyfit(x[:5], y[:5], 1)[0]
slope_heating = np.polyfit(x[5:], y[5:], 1)[0]
print(slope_cooling)
print(slope_heating)


plt.title("PWM vs Equil. Temp")
plt.xlabel("PWM")
plt.ylabel("Temperature (°C)")
plt.legend()
plt.savefig('lab4part5.png')