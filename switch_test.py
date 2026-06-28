import RPi.GPIO as GPIO
import time

PIN_REED  = 12
PIN_LIMIT = 16

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN_REED,  GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(PIN_LIMIT, GPIO.IN, pull_up_down=GPIO.PUD_UP)

try:
    while True:
        reed  = GPIO.input(PIN_REED)
        limit = GPIO.input(PIN_LIMIT)
        print(f"Lid: {'CLOSED' if reed == GPIO.LOW else 'OPEN  '}  |  Phone: {'PRESENT' if limit == GPIO.HIGH else 'ABSENT '}", end='\r')
        time.sleep(0.1)
except KeyboardInterrupt:
    pass
finally:
    GPIO.cleanup()