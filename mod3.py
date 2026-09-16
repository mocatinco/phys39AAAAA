import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
x, y = np.loadtxt("mod3data.txt", unpack=True)

# 2. Plot the data
plt.plot(x, y, marker="s", linestyle="--", color="r")

# 3. Add labels and show the plot
plt.title("Line Plot from TXT File")
plt.xlabel("Time (s)")
plt.ylabel("Temperature (°C)")
plt.grid(True)
plt.show()