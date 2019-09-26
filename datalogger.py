#~ datalogger.py

import sys

path_to_ads1261evm = "/home/pi/Documents/ads1261evm/"
path_to_dac7562evm = "/home/pi/Documents/dac7562evm/"
path_to_AS_pH_meter = "/home/pi/Documents/AtlasScientific_pHmeter"

sys.path.insert(0,path_to_ads1261evm)
sys.path.insert(0,path_to_dac7562evm)
sys.path.insert(0,path_to_AS_pH_meter)

import ads1261evm as ads1261
import dac7562evm as dac7562
import AtlasScientific_pHmeter as pH_probe

import numpy as np
import matplotlib.pyplot as plt
import time
import statistics


# set up DAC & ADC (frequency, etc)
# set constant 100 uA current from ADC, then measure
# set voltage
# measure potential and record with timestamp (threads)
# measure pH (non-blocking)
	while(1):
		start_time = time.time()
		try:
			pH = device.query("R")[:5]
			print(len(pH), pH)
			print(type(pH))
			try:
				pH = float(pH)
				print(type(pH), pH)			
			except KeyboardInterrupt:
				device.close()
				sys.exit()
			
		except KeyboardInterrupt:
			device.close()
			sys.exit()
		end_time = time.time()
		print("Query time:", end_time - start_time)
# record to csv
# repeat
