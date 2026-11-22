import time

import analogio
import board
import digitalio

VANE_POWER_PIN = board.D10
VANE_ADC_PIN = board.A0

SAMPLE_INTERVAL_S = 0.5
SAMPLES_PER_READING = 16


def read_vane():
    power = digitalio.DigitalInOut(VANE_POWER_PIN)
    power.direction = digitalio.Direction.OUTPUT
    power.value = True
    time.sleep(0.005)

    adc = analogio.AnalogIn(VANE_ADC_PIN)
    samples = [adc.value for _ in range(SAMPLES_PER_READING)]
    adc.deinit()

    power.value = False
    power.deinit()

    raw = sum(samples) // len(samples)
    voltage = raw / 65535 * 3.3
    return raw, voltage, min(samples), max(samples)


def main():
    print("vane calibration -- rotate to each marked direction and hold still")
    print("record the averaged value once it settles, then move to the next")
    while True:
        raw, voltage, lo, hi = read_vane()
        print(
            "raw={:5d}  (spread {}-{})  voltage={:.3f} V".format(raw, lo, hi, voltage)
        )
        time.sleep(SAMPLE_INTERVAL_S)


if __name__ == "__main__":
    main()
