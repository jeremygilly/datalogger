'''
#~ Constant current datalogger.

Jeremy Gillbanks 22 Jan 2021

# Requires connection of the ads1261evm

To use this program, connect:
AIN4        power+
AIN3        sense+
AIN2        sense-
AINCOM      power- (GND)

By default, this program will output 100 µA via AIN4.
AINCOM is level-shifted to 2.5 V to maximise the sensitivity to the measurement.

To use: 
python3 /home/pi/Documents/datalogger/jianan_constant_100uA.py

Scroll to the bottom of the program to make changes :)

'''


import sys, statistics, csv, threading, queue, time
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
path_to_ads1261evm = "/home/pi/Documents/ads1261evm/"
sys.path.insert(0, path_to_ads1261evm)
from ads1261evm import ADC1261 as ads1261

def get_experiment_time():
    timestamp = datetime.now()
    measurement_date = str(timestamp.year)+'-'+str(timestamp.month)+'-'+str(timestamp.day)
    measurement_time = str(timestamp.hour)+'.'+str(timestamp.minute)+'.'+str(timestamp.second)+'.'+str(timestamp.microsecond)
    return measurement_date, measurement_time

def initialise_instruments():
    ''' Sets up the device. '''
    adc = ads1261()
    adc.setup_measurements()
    adc.reset()
    DeviceID, RevisionID = adc.check_ID()
    print(DeviceID, RevisionID)
    return adc

def setup(adc, 
            adc_frequency = 20, 
            digital_filter = 'FIR', 
            BYPASS = 0, 
            gain = 1, 
            constant_current = '100', 
            current_out_pin = 'AIN4'):
                
    #~ gain = 2
    #~ adc_frequency, digital_filter, constant_current, current_out_pin = data_rate, digital_filter, constant_current, pin # must remove this later
    adc.set_frequency(data_rate=adc_frequency, digital_filter = digital_filter, print_freq = False)
    adc.PGA(BYPASS = BYPASS, GAIN = gain)
    #~ adc.print_PGA()
    adc.reference_config(reference_enable = 1, RMUXP = 'Internal Positive', RMUXN = 'Internal Negative')
    #~ adc.print_reference_config()
    
    # Wait for reference voltage to settlec
    # Internal voltage reference takes 100 ms to settle to within 0.001% of final value after power-on.
    # 7.5 Electrical Characteristics, ADS1261 data sheet.
    time.sleep(0.1) 
    
    adc.mode1(CHOP='normal', CONVRT='continuous', DELAY = '50us')
    #~ adc.print_mode1()
    #~ adc.mode2(gpio3_connection = 'connect',
            #~ gpio2_connection = 'connect',
            #~ gpio1_connection = 'disconnect',
            #~ gpio0_connection = 'disconnect',
            #~ gpio3_direction = 'output',
            #~ gpio2_direction = 'output',
            #~ gpio1_direction = 'output',
            #~ gpio0_direction = 'output')
    adc.mode2()
    adc.mode3()
    x,y = adc.current_out_magnitude(current1 = constant_current, current2 = 'off')
    x,y = adc.current_out_pin(IMUX1 = current_out_pin, IMUX2 = 'NONE')
    adc.burn_out_current_source(VBIAS = 'enabled', polarity = 'pull-up mode', magnitude = 'off')
    adc.start1()
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

def GaN_measurement(adc, positive, negative, reference, gain, window = 10, status_byte = 'disabled'):
    adc.stop() # stop measurements and allows the register to be changed.
    adc.choose_inputs(positive = positive, negative = negative)
    #~ adc.PGA(BYPASS = 0, GAIN = gain)
    adc.start1() # starts measurements and prevents register changes.
    response = None
    samples = []
    for i in range(window):
        try:
            response = adc.collect_measurement(method='hardware', reference = reference, gain = gain, status = status_byte, bits = True)
            response = abs(response) # remove this if necessary
            #~ print(response)
            samples.append(response)
        except KeyboardInterrupt:
            adc.end()
    return np.median(samples), np.std(samples)

def multiplex(adc, measurement_pairs, result_queue, gain, reference = 5000, window = 100, status_byte = 'enabled', data_rate = 7200, digital_filter = 'sinc2'):
    medians, standard_deviations = [], []
    #~ external_reference = adc.ac_simple('AC') # need to grab the current then replace the ac-excitation settings
    #~ external_reference = adc.power_readback()
    external_reference = reference
    #~ setup(adc)
    #~ external_reference = 5000 # reference voltage, not completely accurate
    #~ adc.PGA(BYPASS = 0, GAIN = gain)
    #~ adc.print_PGA()
    #~ adc.set_frequency(data_rate = data_rate, digital_filter = digital_filter, print_freq = False)
    #~ adc.mode3(PWDN = 0,
        #~ STATENB = 1,
        #~ CRCENB = 0,
        #~ SPITIM = 0,
        #~ GPIO3 = 0,
        #~ GPIO2 = 0,
        #~ GPIO1 = 0,
        #~ GPIO0 = 0)
    #~ adc.mode3()
    #~ print(adc.check_mode3())
    #~ adc.print_mode3()
    print("Positive \t Negative \t Median (mV) \t Standard Deviation (uV)")
    for measurement_pair in measurement_pairs:
        positive, negative = measurement_pair[0], measurement_pair[1]
        median, standard_deviation = GaN_measurement(adc, positive, negative, external_reference, gain, window = window, status_byte = status_byte)
        medians.append(median)
        standard_deviations.append(standard_deviation)
        print(positive,'\t\t', negative,'\t\t', round(median,2),'\t\t', round(standard_deviation*1000,2)) # x1000 for uV
        #~ adc.print_mode3()
        #~ print(adc.check_current())
    temperature = adc.check_temperature()
    #~ temperature = 0
    print("Temperature (deg C):", temperature)
    result_queue.put(("GaN", [external_reference, medians, standard_deviations, temperature]))
    return 0

def write_to_csv(saved_file_location, fieldnames, measurement_date, measurement_time, GaN_sensor_result, measurement_pairs):
    ''' This function writes all the results to CSV. It requires the results to be 
        unpacked before submission. Would be good to remove the print requirement. '''
    #~ print(all_results)
    external_reference, medians, standard_deviations, temperature = GaN_sensor_result
    
    row = [measurement_date, measurement_time, external_reference]
    for measurement_pair, median, standard_deviation in zip(measurement_pairs, medians, standard_deviations):
        row.extend([median, standard_deviation*1000, temperature])

    row = dict(zip(fieldnames, row))
    try:
        with open(saved_file_location, 'a') as csvfile:
            # write each row
            writer = csv.writer(csvfile)
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writerow(row)
    except IOError as e:
        print("Unable to save to csv")  
        print(e)
    except KeyboardInterrupt:
        adc.end()
        csvfile.close()

    return 0    
    
def main():
    # Change these parameters:
    window = 18
    data_rate, digital_filter = 20, 'FIR'
    constant_current, pin = '100', 'AIN4'
    gain = 8 # maximise this?
    connected_pH_meter = False # set to true if connected
       
    # forward measurement pairs
    measurement_pairs = [
        ['AIN3', 'AIN2'],
        #~ ['AIN2', 'AIN3'],
    ]

    
    fieldnames = ['Date', 
        'Time', 
        'Reference Voltage (mV)',
        'Sense Pad 1 (mV)', 
        'Standard deviation of Sense Pad 1 (uV)',
        'Air Temperature from ADS1261 (deg C)']
        
    # Avoid changing the following parameters:
    adc = initialise_instruments()
    reference = adc.power_readback()/2
    #~ reference = 2483
    
    setup(adc = adc,
        adc_frequency = data_rate, 
        digital_filter = digital_filter, 
        BYPASS = 0, 
        gain = gain,
        constant_current = constant_current,
        current_out_pin = pin)
    
    #~ gain = check_maximum_gain(adc, measurement_pairs)
    
    print("Chosen maximum gain:", gain)
    
    data = []
    averaged_data = []
    stdev_data = []
    
    for pair in range(len(measurement_pairs)):
        data.append([])
        averaged_data.append([])
        stdev_data.append([])

    try:
        with open(saved_file_location, 'w') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
        print("CSV File successfully created", saved_file_location)
    except IOError:
        print("Unable to save to csv")

    _, STATENB_status, _, _, _, _, _, _ = adc.check_mode3()
    if STATENB_status == 0:
        status_byte = 'disabled'
    else: 
        status_byte = "enabled"
    print("Status byte:", status_byte)
    flag = 0
    while(1):        
        try:
            start = time.time()
            q = queue.Queue()

            GaN_sensor_thread = threading.Thread(target = multiplex, args=(adc, measurement_pairs, q, gain, reference, window, status_byte, data_rate, digital_filter))
            
            threads = [GaN_sensor_thread]
            
            for thread in threads:
                thread.daemon = True
                thread.start() # start the threads running
            
            # Get timestamp data while the threads are running.
            timestamp, measurement_date, measurement_time = None, None, None # clear previous values (just in case!)    
            measurement_date, measurement_time = get_experiment_time() 
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
                else:
                    pass
            
            csv_thread = threading.Thread(target = write_to_csv, args=(saved_file_location, fieldnames, measurement_date, measurement_time, GaN_sensor_result, measurement_pairs))
            csv_thread.start()
                        
            # Could be a good spot to print current results.
            #~ print("GaN result:", GaN_sensor_result)
            print("Total time taken (sec):", time.time() - start,'\n')   
        except KeyboardInterrupt:
            adc.end()
        except Exception as e:
            print("Error in constant current program")
            print(e)
            
    flag = 1 
    
    return 0

if __name__ == "__main__":
    
    # Change these parameters:
    #~ level_shift = True # make this True to connect GND to 2.5 V or False to connect to 0 V.
    start_date, start_time = get_experiment_time()

    saved_file_location = '/media/pi/JEREMY/results/' + str(start_date) + ' ' + str(start_time) + '.csv'
    # Do not change past here.
    
    main()
