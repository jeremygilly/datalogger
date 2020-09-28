#~ Constant current datalogger.
# Requires connection of the ads1261evm and a Atlas Scientific pH meter

import sys, statistics, csv, threading, queue, time
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime

path_to_ads1261evm = "/home/pi/Documents/ads1261evm/"

sys.path.insert(0, path_to_ads1261evm)

from ads1261evm import ADC1261 as ads1261

def initialise_instruments():
    ''' Sets up the device. '''
    adc = ads1261()
    adc.setup_measurements()
    adc.reset()
    DeviceID, RevisionID = adc.check_ID()
    print(DeviceID, RevisionID)

    return adc

def setup(adc, 
            adc_frequency = 7200, 
            digital_filter = 'sinc4', 
            BYPASS = 0, 
            gain = 1, 
            constant_current = 'off', 
            current_out_pin = 'none'):
    
    ''' Change thse values '''
    # data_rate, digital_filter = 10, 'FIR'
    # constant_current, pin = '100', 'AIN4'
    # gain = 2
    
    #adc_frequency, digital_filter, constant_current, current_out_pin = data_rate, digital_filter, constant_current, pin # must remove this later
    adc.set_frequency(data_rate=adc_frequency, digital_filter = digital_filter, print_freq = False)
    adc.PGA(BYPASS = BYPASS, GAIN = gain)
    #~ adc.print_PGA()
    adc.reference_config(reference_enable = 1, RMUXP = 'Internal Positive', RMUXN = 'Internal Negative')
    #~ adc.print_reference_config()
    
    # Wait for reference voltage to settle
    # Internal voltage reference takes 100 ms to settle to within 0.001% of final value after power-on.
    # 7.5 Electrical Characteristics, ADS1261 data sheet.
    time.sleep(0.1) 
    
    adc.mode1(CHOP='chop', CONVRT='continuous', DELAY = '17.8ms') # 50us default
    #~ adc.print_mode1()
    adc.mode2()
    adc.mode3(PWDN = 0,
        STATENB = 1, # enable the status_byte
        CRCENB = 0,
        SPITIM = 0,
        GPIO3 = 0,
        GPIO2 = 0,
        GPIO1 = 0,
        GPIO0 = 0)
    x,y = adc.current_out_magnitude(current1 = constant_current, current2 = 'off')
    x,y = adc.current_out_pin(IMUX1 = current_out_pin, IMUX2 = 'NONE')
    adc.burn_out_current_source(VBIAS = 'enabled') # default is 'disabled' and level shifts the voltage to 2.5V
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

def GaN_measurement(adc, positive, negative, reference, gain, window = 10, status_byte = 'enabled'):
    adc.stop() # stop measurements and allows the register to be changed.
    adc.choose_inputs(positive = positive, negative = negative)

    #~ adc.PGA(BYPASS = 0, GAIN = gain)
    adc.start1() # starts measurements and prevents register changes.
    response = None
    samples = []
    time.sleep(0.1) # sleep for 50 ms after changing inputs allowing the voltage to settle with a FIR and 20 SPS. x2 for chop-mode.
    #~ print("Reference:", reference, "Gain:", gain) # for diagnostics only
    for i in range(window):
        try:
            response = adc.collect_measurement(method='hardware', reference = reference, gain = gain, status = status_byte, bits = True)
            response = abs(response) # remove this if necessary
            #~ print(response)
            samples.append(response)
        except KeyboardInterrupt:
            adc.end()
        except Exception as e:
            pass
    return np.median(samples), np.std(samples)

def multiplex(adc, measurement_pairs, result_queue, gain, reference = 5000, window = 100, status_byte = 'enabled', data_rate = 7200, digital_filter = 'sinc2'):
    # print(adc.check_current())
    medians, standard_deviations = [], []
    #~ external_reference = adc.ac_simple('AC') # need to grab the current then replace the ac-excitation settings
    #external_reference = adc.power_readback()
    external_reference = reference
    #adc.print_status()
    print("Positive \t Negative \t Median (mV) \t Standard Deviation (uV)")
    for measurement_pair in measurement_pairs:
        positive, negative = measurement_pair[0], measurement_pair[1]
        median, standard_deviation = GaN_measurement(adc, positive, negative, external_reference, gain, window = window, status_byte = status_byte)
        medians.append(median)
        standard_deviations.append(standard_deviation)
        print(positive,'\t\t', negative,'\t\t', median,'\t\t', standard_deviation*1000)
    temperature = adc.check_temperature()
    #~ temperature = 0
    print("Temperature (deg C):", temperature)
    result_queue.put(("GaN", [medians, standard_deviations, temperature]))
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
        time.sleep(0)
        #~ time.sleep(0.8)
        result_queue.put(("commercial_pH", "Not connected."))
    return 0

def write_to_csv(csv_file, fieldnames, measurement_date, measurement_time, GaN_sensor_result, measurement_pairs):
    ''' This function writes all the results to CSV. It requires the results to be 
        unpacked before submission. Would be good to remove the print requirement. '''
    #~ print(all_results)
    medians, standard_deviations, temperature = GaN_sensor_result

    
    row = [measurement_date, measurement_time]
    for measurement_pair, median, standard_deviation in zip(measurement_pairs, medians, standard_deviations):
        row.extend([median, standard_deviation*1000])

    row.extend([temperature])
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
    window = 10
    data_rate, digital_filter = 20, 'FIR'
    constant_current, pin = '100', 'AIN9' # connect the positive pin of the sensor to AIN4 and the negative to GND.
    gain = 16
    connected_pH_meter = False # set to true if connected
    status_byte = 'enabled'

    # forward measurement pairs
    measurement_pairs = [
        #~ ['AIN8', 'AINCOM'], # somehow this was 608 mV?! with 985 + 1110 + 1200 Ohms and 100 uA.
        ['AIN8', 'AIN7'],   # resistor, then you can check the "constant" current source 
        ['AIN6', 'AIN5'],   # top 2-wire sense
        ['AIN4', 'AIN3']    # bottom 2-wire sense
        
    ]

    
    fieldnames = ['Date', 
        'Time', 
        'Resistor (985 ohm, mV)',
        'Standard deviation of Resistor (uV)',
        'Top 2-wire (mV)',
        'Standard deviation of Top 2-wire (uV)',
        'Bottom 2-wire (mV)', 
        'Standard deviation of Bottom 2-wire (uV)',
        'Air Temperature from ADS1261 (deg C)']
        
    # Avoid changing the following parameters:
    adc = initialise_instruments()
    reference = adc.power_readback()/2
    #~ reference = 2500 # internal reference enabled?
    
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

    # set up csv
    timestamp = datetime.now()
    measurement_date = str(timestamp.year)+'-'+str(timestamp.month)+'-'+str(timestamp.day)+'_'
    measurement_time = str(timestamp.hour)+'-'+str(timestamp.minute)+'-'+str(timestamp.second)  
    
    # Save location
    csv_file = "/media/pi/THESISDATA/Results/"+measurement_date+measurement_time+".csv"

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
    print("Status byte:", status_byte)
    flag = 0
    while(1):        
        try:
            start = time.time()
            q = queue.Queue()

            GaN_sensor_thread = threading.Thread(target = multiplex, 
                args=(adc, measurement_pairs, q, gain, reference, window, status_byte, data_rate, digital_filter))
            
            threads = [GaN_sensor_thread]
            
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
                else:
                    pass
            
            csv_thread = threading.Thread(target = write_to_csv, args=(csv_file, fieldnames, measurement_date, measurement_time, GaN_sensor_result, measurement_pairs))
            csv_thread.start()
                        
            # Could be a good spot to print current results.
            print("Total time taken:", time.time() - start)   
        except KeyboardInterrupt:
            adc.end()
        except Exception as e:
            print("Error in constant current program")
            print(e)
            
    flag = 1 
    
    return 0

if __name__ == "__main__":
    main()
