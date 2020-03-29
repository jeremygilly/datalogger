#~ Constant current datalogger.
# Requires connection of the ads1261evm and a Atlas Scientific pH meter

import sys, statistics, csv, threading, queue, time
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime

path_to_ads1261evm = "/home/pi/Documents/ads1261evm/"
path_to_dac7562evm = "/home/pi/Documents/dac7562evm/"
path_to_AS_pH_meter = "/home/pi/Documents/AtlasScientific_pHmeter"

sys.path.insert(0, path_to_ads1261evm)
sys.path.insert(0, path_to_dac7562evm)
sys.path.insert(0, path_to_AS_pH_meter)

from ads1261evm import ADC1261 as ads1261
from dac7562evm import DAC7562 as dac7562
from AtlasScientific_pHmeter import AS_pH_I2C as pH_probe

def initialise_instruments():
    ''' Sets up the device. '''
    adc = ads1261()
    adc.setup_measurements()
    DeviceID, RevisionID = adc.check_ID()
    print(DeviceID, RevisionID)
    #~ dac = dac7562()
    dac = 0
    pH_meter = pH_probe()
    return adc, dac, pH_meter

def setup(adc, 
            adc_frequency = 7200, 
            digital_filter = 'sinc4', 
            BYPASS = 0, 
            gain = 1, 
            constant_current = 'off', 
            current_out_pin = 'none'):
                
    adc.set_frequency(data_rate=adc_frequency, digital_filter = digital_filter)
    adc.PGA(BYPASS = BYPASS, GAIN = gain)
    adc.print_PGA()
    adc.reference_config(reference_enable=1, RMUXP = 'Internal Positive', RMUXN = 'Internal Negative')
    #~ adc.print_reference_config()
    
    # Wait for reference voltage to settle
    # Internal voltage reference takes 100 ms to settle to within 0.001% of final value after power-on.
    # 7.5 Electrical Characteristics, ADS1261 data sheet.
    time.sleep(0.1) 
    
    #~ adc.mode1(CHOP='normal', CONVRT='continuous', DELAY = '50us')
    #~ adc.print_mode1()
    
    #~ x,y = adc.current_out_magnitude(current1 = constant_current, current2 = 'off')
    #~ x,y = adc.current_out_pin(IMUX1 = current_out_pin, IMUX2 = 'NONE')
    #~ adc.start1()
    return 0

def check_maximum_gain(adc, measurement_pairs):
    previous_maximum_gain = 128
    for measurement_pair in measurement_pairs:
        maximum_gain = adc.maximum_gain(positive_input = measurement_pair[0], negative_input = measurement_pair[1])
        if maximum_gain < previous_maximum_gain:
            previous_maximum_gain = maximum_gain
    return previous_maximum_gain

# measure potential and record with timestamp (threads)
# measure pH (non-blocking)
# record to csv
# keep under 4 kb and append mode -a flag (not -w or -r)
# repeat

def GaN_measurement(adc, positive, negative, reference, gain, window = 10, status_byte = 'enabled'):
    adc.stop() # stop measurements and allows the register to be changed.
    adc.choose_inputs(positive = positive, negative = negative)
    #~ adc.PGA(BYPASS = 0, GAIN = gain)
    adc.start1() # starts measurements and prevents register changes.
    response = None
    samples = []
    for i in range(window):
        try:
            samples.append(adc.collect_measurement(method='hardware', reference = reference, gain = gain, status = status_byte))
        except KeyboardInterrupt:
            adc.end()
    return np.median(samples), np.std(samples)

def multiplex(adc, measurement_pairs, result_queue, gain, window = 100, status_byte = 'enabled', data_rate = 7200, digital_filter = 'sinc2'):
    medians, standard_deviations = [], []
    external_reference = adc.ac_simple('AC') # need to grab the current then replace the ac-excitation settings
    adc.PGA(BYPASS = 0, GAIN = gain)
    adc.set_frequency(data_rate = data_rate, digital_filter = digital_filter, print_freq = False)
    print("Positive \t Negative \t Median (mV) \t Standard Deviation (uV)")
    for measurement_pair in measurement_pairs:
        positive, negative = measurement_pair[0], measurement_pair[1]
        median, standard_deviation = GaN_measurement(adc, positive, negative, external_reference, gain, window = window, status_byte = status_byte)
        medians.append(median)
        standard_deviations.append(standard_deviation)
        print(positive,'\t\t', negative,'\t\t', median,'\t', standard_deviation*1000)
    temperature = adc.check_temperature()
    print("Temperature (deg C):", temperature)
    result_queue.put(("GaN", [external_reference, medians, standard_deviations, temperature]))
    return 0
    
def commercial_pH(result_queue, connected = False):
    if connected == True:
        start = time.time()
        commercial_pH = pH_meter.single_output()
        while commercial_pH in [254, 254.0, str(254), str(254.0), 255, 255.0, str(255), str(255.0)]:
            commercial_pH = pH_meter.single_output()
            if commercial_pH not in [254, 254.0, str(254), str(254.0), 255, 255.0, str(255), str(255.0)]: # if its an error code, collect other measurements
                result_queue.put(("commercial_pH", commercial_pH))
            elif time.time() - start > 10: # if it's taken more than 10 seconds, there's a fault.
                result_queue.put(("commercial_pH", "Timed out."))
            else:
                pass
    else: # if it's not connected, wait 0.8 seconds anyway
        time.sleep(0.8)
        result_queue.put(("commercial_pH", "Not connected."))
    return 0

def write_to_csv(csv_file, fieldnames, measurement_date, measurement_time, GaN_sensor_result, commercial_pH_result, measurement_pairs):
    ''' This function writes all the results to CSV. It requires the results to be 
        unpacked before submission. Would be good to remove the print requirement. '''
    #~ print(all_results)
    external_reference, medians, standard_deviations, temperature = GaN_sensor_result
    commercial_pH = commercial_pH_result
    
    row = [measurement_date, measurement_time, external_reference]
    for measurement_pair, median, standard_deviation in zip(measurement_pairs, medians, standard_deviations):
        row.extend([median, standard_deviation*1000])

    row.extend([commercial_pH, temperature])
    row = dict(zip(fieldnames, row))
    try:
        with open(csv_file, 'a') as csvfile:
            # write each row
            writer = csv.writer(csvfile)
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writerow(row)
    except IOError:
        print("Unable to save to csv")  
    except KeyboardInterrupt:
        adc.end()
        csvfile.close()

    return 0    
    
def main():
    # Change these parameters:
    window = 100
    data_rate = 7200
    connected_pH_meter = False # set to true if connected
       
    # forward measurement pairs
    measurement_pairs = [
        ['AIN2', 'AIN3'],   # sense pad 1
        ['AIN3', 'AIN6'],   # between sense pads 1 & 2
        ['AIN6', 'AIN7'],   # sense pad 2
        ['AIN7', 'AIN8'],   # between sense pads 2 & 3
        ['AIN8', 'AIN9']    # sense pad 3
    ]

    
    fieldnames = ['Date', 
        'Time', 
        'External Reference (mV with 10k resistor)',
        'Sense Pad 1 (mV)', 
        'Standard deviation of Sense Pad 1 (uV)',
        'Between Sense Pad 1 and 2 (mV)',
        'Standard deviation between Sense Pad 1 and 2 (uV)',
        'Sense Pad 2 (mV)', 
        'Standard deviation of Sense Pad 2 (uV)',
        'Between Sense Pad 2 and 3 (mV)',
        'Standard deviation between Sense Pad 2 and 3 (uV)',
        'Sense Pad 3 (mV)', 
        'Standard deviation of Sense Pad 3 (uV)',
        'Commercial pH Sensor (pH)', 
        'Air Temperature from ADS1261 (deg C)']
        
    # Avoid changing the following parameters:
    adc, dac, pH_meter = initialise_instruments()
    
    setup(adc = adc,
        adc_frequency = data_rate, 
        digital_filter = 'sinc4', 
        BYPASS = 0, 
        gain = 1)
    
    gain = check_maximum_gain(adc, measurement_pairs)
    #~ gain = 1
    print("Chosen maximum gain:", gain)
    
    data = []
    averaged_data = []
    stdev_data = []
    
    for pair in range(len(measurement_pairs)):
        data.append([])
        averaged_data.append([])
        stdev_data.append([])

    # set up csv
    timestamp = datetime.now()
    measurement_date = str(timestamp.year)+'-'+str(timestamp.month)+'-'+str(timestamp.day)+'_'
    measurement_time = str(timestamp.hour)+'-'+str(timestamp.minute)+'-'+str(timestamp.second)  
    
    csv_file = "/home/pi/Documents/Results/"+measurement_date+measurement_time+".csv"

    try:
        with open(csv_file, 'w') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
        print("CSV File successfully created", csv_file)
    except IOError:
        print("Unable to save to csv")

    _, STATENB_status, _, _, _, _, _, _ = adc.check_mode3()
    if STATENB_status == "No Status byte":
        status_byte = 'disabled'
    else: 
        status_byte = "enabled"
    flag = 0
    while(1):        
        try:
            start = time.time()
            q = queue.Queue()

            commercial_pH_thread = threading.Thread(target = commercial_pH, args=(q, connected_pH_meter))
            GaN_sensor_thread = threading.Thread(target = multiplex, args=(adc, measurement_pairs, q, gain, window, status_byte, data_rate, 'sinc1'))
            
            threads = [commercial_pH_thread, GaN_sensor_thread]
            
            for thread in threads:
                thread.daemon = True
                thread.start() # start the threads running
            
            # Get timestamp data while the threads are running.
            timestamp, measurement_date, measurement_time = None, None, None # clear previous values (just in case!)    
            timestamp = datetime.now()
            measurement_date = str(timestamp.year)+'-'+str(timestamp.month)+'-'+str(timestamp.day)
            measurement_time = str(timestamp.hour)+':'+str(timestamp.minute)+':'+str(timestamp.second)+'.'+str(timestamp.microsecond)
            if flag > 0: csv_thread.join() # what if I put this with the other threads?
            for thread in threads:
                thread.join() # wait until all the threads are completed before accessing results
            
            # Sometimes the results come in a different order in the queue, so you can't depend on 
            #   when the results arrive to be indicative of where the results came from. 
            #   Therefore, get all results into a list.
            results = []
            while not q.empty():
                results.append(q.get())
            #   Then search the all queued results for the name given in the functions above.
            #~ print("Results (raw):", results)
            for element in results:
                if 'GaN' in element[0]:
                    GaN_sensor_result = element[1]
                    if type(GaN_sensor_result) != list:
                        GaN_sensor_result = list(GaN_sensor_result)
                    
                elif 'commercial_pH' in element[0]:
                    commercial_pH_result = element[1]
                else:
                    pass
            
            csv_thread = threading.Thread(target = write_to_csv, args=(csv_file, fieldnames, measurement_date, measurement_time, GaN_sensor_result, commercial_pH_result, measurement_pairs))
            csv_thread.start()
                        
            # Could be a good spot to print current results.
            print("Commercial pH result:", commercial_pH_result)
            #~ print("GaN result:", GaN_sensor_result)
            print("Total time taken:", time.time() - start)   
        except KeyboardInterrupt:
            adc.end()
    flag = 1 
    
    return 0

if __name__ == "__main__":
    main()
