import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

a = pd.read_csv('/content/drive/MyDrive/Colab Notebooks/lab3 phys39.txt')


# 2. Plot the data
#plt.plot(x, y, marker="s", linestyle="--", color="r")
plt.plot(a.iloc[1:, 1],a.iloc[1:, 0], color='#675c7b')
plt.show()
# 3. Add labels and show the plot
plt.title("Line Plot from TXT File")
plt.xlabel("Time (s)")
plt.ylabel("Temperature (°C)")
plt.grid(True)
plt.show()