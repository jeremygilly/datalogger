#~ Constant current datalogger.

import sys

path_to_ads1261evm = "/home/pi/Documents/ads1261evm/"
path_to_dac7562evm = "/home/pi/Documents/dac7562evm/"
path_to_AS_pH_meter = "/home/pi/Documents/AtlasScientific_pHmeter"

sys.path.insert(0, path_to_ads1261evm)
sys.path.insert(0, path_to_dac7562evm)
sys.path.insert(0, path_to_AS_pH_meter)

from ads1261evm import ADC1261 as ads1261
from dac7562evm import DAC7562 as dac7562
from AtlasScientific_pHmeter import AS_pH_I2C as pH_probe

import numpy as np
import matplotlib.pyplot as plt
import time
import statistics
from datetime import datetime
import csv

# set up
def initialise_instruments():
	adc = ads1261()
	adc.setup_measurements()
	DeviceID, RevisionID = adc.check_ID()
	print(DeviceID, RevisionID)
	dac = dac7562()
	pH_meter = pH_probe()
	return adc, dac, pH_meter

def setup(adc, adc_frequency = 20, digital_filter = 'FIR', BYPASS = 1, gain = 1, constant_current = 100, current_out_pin = 'AIN0'):
	adc.set_frequency(data_rate=adc_frequency, digital_filter = 'sinc4')
	adc.PGA(BYPASS = BYPASS, GAIN = gain)
	adc.print_PGA()
	adc.reference_config(reference_enable=1, RMUXP = 'AVDD', RMUXN = 'AVSS')
	adc.print_reference_config()
	
	# Wait for reference voltage to settle
	# Internal voltage reference takes 100 ms to settle to within 0.001% of final value after power-on.
	# 7.5 Electrical Characteristics, ADS1261 data sheet.
	time.sleep(0.1) 
	
	adc.mode1(CHOP='normal', CONVRT='continuous', DELAY = '50us')
	adc.print_mode1()
	
	x,y = adc.current_out_magnitude(current1 = constant_current, current2 = 'off')
	x,y = adc.current_out_pin(IMUX1 = current_out_pin, IMUX2 = 'NONE')
	adc.start1()
	return 0
	

# measure potential and record with timestamp (threads)
# measure pH (non-blocking)
# record to csv
# keep under 4 kb and append mode -a flag (not -w or -r)
# repeat

def GaN_measurement(adc, positive, negative, reference, gain):
	adc.choose_inputs(positive = positive, negative = negative)
	adc.gpio("START","high") # starts the ADC from taking measurements
	response = None
	while(response == None or type(response) != float):
		try:
			response = adc.collect_measurement(method='hardware', reference = reference, gain = gain)
			if (type(response)==float):
				return response
		except KeyboardInterrupt:
			adc.end()


def main():
	adc, dac, pH_meter = initialise_instruments()
	setup(adc = adc,
		adc_frequency = 19200, 
		digital_filter = 'sinc1', 
		BYPASS = 1, 
		gain = 1, 
		constant_current = 100, 
		current_out_pin = 'AIN0')
	BYPASS, gain = adc.check_PGA()
	reference = adc.power_readback(power = 'analog')
	
	measurement_pairs = [
		['AIN2', 'AIN3'], # sense pad 1
		['AIN3', 'AIN4'], # between sense pads 1 & 2
		['AIN4', 'AIN5'], # sense pad 2
		['AIN5', 'AIN6'], # between sense pads 2 & 3
		['AIN6', 'AIN7'] # sense pad 3
	]

	data = []
	averaged_data = []
	
	for pair in range(len(measurement_pairs)):
		data.append([])
		averaged_data.append([])

	# set up csv
	timestamp = datetime.now()
	measurement_date = str(timestamp.year)+'-'+str(timestamp.month)+'-'+str(timestamp.day)+'_'
	measurement_time = str(timestamp.hour)+'-'+str(timestamp.minute)+'-'+str(timestamp.second)
	
	csv_file = "/home/pi/Documents/Results/"+measurement_date+measurement_time+".csv"
	fieldnames = ['Date', 
					'Time', 
					'Sense Pad 1 (mV)', 
					'Between Sense Pad 1 and 2 (mV)',
					'Sense Pad 2 (mV)', 
					'Between Sense Pad 2 and 3 (mV)',
					'Sense Pad 3 (mV)', 
					'Commercial pH Sensor (pH)', 
					'Air Temperature from ADS1261 (deg C)']
	
	try:
		with open(csv_file, 'w') as csvfile:
			writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
			writer.writeheader()
		print("CSV File successfully created", csv_file)
	except IOError:
		print("Unable to save to csv")

	writing_interval = 10 # 1 minute between csv writes
	pH_measurements_for_csv, GaN_measurements_for_csv, temperature_for_csv, date_for_csv, time_for_csv = [], [], [], [], []
	while(1):
		previous_time = time.time()
		while(time.time() - previous_time < writing_interval):
			try:
				commercial_pH = pH_meter.single_output()
				if commercial_pH in [254, 254.0, str(254), str(254.0)]: # if its an error code, collect other measurements
					for each_pair in range(len(measurement_pairs)): # collect GaN measurements
						measurement_GaN = GaN_measurement(adc, positive = measurement_pairs[each_pair][0], negative = measurement_pairs[each_pair][1], reference = reference, gain = gain)
						data[each_pair].append(measurement_GaN)
				else:
					pH_measurements_for_csv.append(commercial_pH)

					for each_pair in range(len(measurement_pairs)):
						mean = statistics.mean(data[each_pair])
						averaged_data[each_pair].append(mean)

					air_temperature = adc.check_temperature()
					temperature_for_csv.append(air_temperature)
					timestamp = datetime.now()
					measurement_date = str(timestamp.year)+'-'+str(timestamp.month)+'-'+str(timestamp.day)
					measurement_time = str(timestamp.hour)+':'+str(timestamp.minute)+':'+str(timestamp.second)+'.'+str(timestamp.microsecond)
					date_for_csv.append(measurement_date)
					time_for_csv.append(measurement_time)
			except KeyboardInterrupt:
				adc.end()

		
		# write to csv
		try:
			with open(csv_file, 'a') as csvfile:
				# write each row
				#~ writer = csv.writer(csvfile)
				writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
				for datapoint in range(len(date_for_csv)):
					print(fieldnames[0],date_for_csv[datapoint],
									fieldnames[1],time_for_csv[datapoint],
									fieldnames[2],round(averaged_data[0][datapoint],2),
									fieldnames[3],round(averaged_data[1][datapoint],2),
									fieldnames[4],round(averaged_data[2][datapoint],2),
									fieldnames[5],round(averaged_data[3][datapoint],2),
									fieldnames[6],round(averaged_data[4][datapoint],2),
									fieldnames[7],round(pH_measurements_for_csv[datapoint],2),
									fieldnames[8],round(temperature_for_csv[datapoint],2),"\n")
					writer.writerow({
									fieldnames[0]:date_for_csv[datapoint],
									fieldnames[1]:time_for_csv[datapoint],
									fieldnames[2]:round(averaged_data[0][datapoint],2),
									fieldnames[3]:round(averaged_data[1][datapoint],2),
									fieldnames[4]:round(averaged_data[2][datapoint],2),
									fieldnames[5]:round(averaged_data[3][datapoint],2),
									fieldnames[6]:round(averaged_data[4][datapoint],2),
									fieldnames[7]:round(pH_measurements_for_csv[datapoint],2),
									fieldnames[8]:round(temperature_for_csv[datapoint],2),
									})
		except IOError:
			print("Unable to save to csv")	
		except KeyboardInterrupt:
			adc.end()
			csvfile.close()	

		# clear all appended data
		for pair in range(len(measurement_pairs)):
			data[pair] = []
			averaged_data[pair] = []
		pH_measurements_for_csv, GaN_measurements_for_csv, temperature_for_csv, date_for_csv, time_for_csv = [], [], [], [], []
		
	return 0

if __name__ == "__main__":
	main()
