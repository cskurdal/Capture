import CHIP_IO.GPIO as GPIO
import CHIP_IO.PWM as PWM
import CHIP_IO.Utilities as UT
import time
import threading
from enum import Enum
from threading import RLock, Condition
from random import randint
from time import sleep
import alsaaudio
import wave
import datetime
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive

localDirectory = 'captured/'
filename = None
googleDrivePath = 'capture'

gauth = GoogleAuth()

gauth.LoadCredentialsFile("credentials.txt")
if gauth.credentials is None:
    # Authenticate if they're not there
    gauth.LocalWebserverAuth()
elif gauth.access_token_expired:
    # Refresh them if expired
    gauth.Refresh()
else:
    # Initialize the saved creds
    gauth.Authorize()

# Save the current credentials to a file
gauth.SaveCredentialsFile("credentials.txt")

drive = GoogleDrive(gauth)


UT.unexport_all()

state_lock = threading.RLock()
callback_count = 0

# represents the addition of an item to a resource
recording_condition = threading.Condition()

class State(Enum):
	READY = 1
	RECORDING = 2
	PROCESSING = 3
	
#Initialize state
state = State.READY


#Threaded
def do_recording():
	print("in do_recording() thread")
	global state, filename
	
	channels = 1
	rate = 48000#44100

	t = datetime.datetime.fromtimestamp(time.time()).strftime('%Y%m%d%H%M%S')	

	filename = t + '.wav'
	state_lock.acquire()
	
	card = 'sysdefault:CARD=Device'

	f = wave.open(localDirectory + filename, 'w')
	f.setnchannels(channels)	
	f.setsampwidth(2)
	f.setframerate(rate)	

    # Open the device in nonblocking capture mode. The last argument could
    # just as well have been zero for blocking mode. Then we could have
    # left out the sleep call in the bottom of the loop
	inp = alsaaudio.PCM(alsaaudio.PCM_CAPTURE, alsaaudio.PCM_NONBLOCK, card)

    # Set attributes: Stereo, 44100 Hz, 16 bit little endian samples (CD format)
	inp.setchannels(channels)
	inp.setrate(rate)
	inp.setformat(alsaaudio.PCM_FORMAT_S16_LE)

    # The period size controls the internal number of frames per period.
    # The significance of this parameter is documented in the ALSA api.
    # For our purposes, it is suficcient to know that reads from the device
    # will return this many frames. Each frame being 2 bytes long.
    # This means that the reads below will return either 320 bytes of data
    # or 0 bytes of data. The latter is possible because we are in nonblocking
    # mode.
	inp.setperiodsize(160)
	print('recording')
	GPIO.output(pin_record_led, GPIO.HIGH)

	while state == State.RECORDING:
		state_lock.release()
        # Read data from device
		l, data = inp.read()

		if l:
			f.writeframes(data)
			sleep(.001)

		state_lock.acquire() #acquire
	
	state_lock.release()
	GPIO.output(pin_record_led, GPIO.LOW)			
			
def do_processing():
	print("in do_processing() thread")
	global state, filename
	
	print("in processing()... Sending: " + filename)

	#Get Directory
	
	id = None

	file_list = drive.ListFile({'q': "'root' in parents and trashed=false"}).GetList()
	for file1 in file_list:
	    if file1['title'] == googleDrivePath:
        	id = file1['id']
		break
	
	print("google drive folder id: " + id)

	file = drive.CreateFile({"parents":  [{"id": id}], "kind": "drive#fileLink"})
	file.SetContentFile(localDirectory + filename)
	file.Upload()

	with state_lock:
		state = State.READY
	print("done processing()")
	



def pin_record_callback(channel):
	global state, callback_count
	
	callback_count += 1
	
	#Start recording or processing
	with state_lock:
		if state == State.READY and callback_count % 2 == 1:
			state = State.RECORDING
			print("set state to RECORDING...")
			#start recording thread
			recording_thread = threading.Thread(target=do_recording)
			recording_thread.start()
		elif state == State.RECORDING:
			state = State.PROCESSING
			print("set state to PROCESSING...")
			#start processing thread
			processing_thread = threading.Thread(target=do_processing)
			processing_thread.start()



#Setup "record" button
pin_record = "XIO-P4"
pin_record_led = 'XIO-P6'

GPIO.setup(pin_record, GPIO.IN)
GPIO.setup(pin_record_led, GPIO.OUT)

# Specify pull up/pull down settings on a pin
#GPIO.setup(pin_record, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Add Callback for Both Edges using the add_event_detect() method
GPIO.add_event_detect(pin_record, GPIO.BOTH, pin_record_callback)
	
running = True
	
try:
	#main state
	while running:
		print("ready, acquiring recording_condition...")
		recording_condition.acquire()
		print("acquired...")
		recording_condition.wait() # sleep until item becomes available
		print("recording notify receieved...")

finally:
	GPIO.cleanup()
