import alarm
import time
import board
import digitalio
import analogio


class BatteryMonitor:
    battery_pin = analogio.AnalogIn(board.A3)
    led = digitalio.DigitalInOut(board.D13)
    led.direction = digitalio.Direction.OUTPUT
    voltage_threshold = 3.4
    voltage = 0.0

    def read_battery_voltage(self) -> float:
        raw_value = self.battery_pin.value
        measured_voltage = (raw_value / 65535) * 3.3
        self.voltage = measured_voltage * 2
        return self.voltage

    def blink_status(self):
        if self.voltage > 4.0:
            self.led.value = True
            time.sleep(0.1)
            self.led.value = False
        elif self.voltage > 3.7:
            for _ in range(2):
                self.led.value = True
                time.sleep(0.1)
                self.led.value = False
                time.sleep(0.1)
        else:
            for _ in range(3):
                self.led.value = True
                time.sleep(0.1)
                self.led.value = False
                time.sleep(0.1)

    def safe_shutdown(self):
        for _ in range(5):
            self.led.value = True
            time.sleep(0.2)
            self.led.value = False
            time.sleep(0.2)
            print("Battery voltage below threshold. Shutting down.")
            print("System will reset in 3 seconds...")
            time.sleep(3)
            time_alarm = alarm.time.TimeAlarm(monotonic_time=time.monotonic() + 1800)
            alarm.exit_and_deep_sleep_until_alarms(time_alarm)
