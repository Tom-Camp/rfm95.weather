import time

import analogio
import board
import digitalio

import vane_lookup


def _pin(d_name, gp_name):
    # Feather RP2040 RFM95 (target board) only has D-names; dev boards like
    # the Pico W only have GP-names.
    return getattr(board, d_name, None) or getattr(board, gp_name)


RAIN_PIN = _pin("D6", "GP6")
ANEMOMETER_PIN = _pin("D5", "GP5")
ANEMOMETER_POWER_PIN = _pin("D9", "GP9")
VANE_POWER_PIN = _pin("D10", "GP10")
VANE_ADC_PIN = board.A0

WIND_SAMPLE_INTERVAL_S = 5
ANEMOMETER_WINDOW_S = 3
ANEMOMETER_MPH_PER_HZ = 1.492
RAIN_MM_PER_TIP = 0.2794
DEBOUNCE_S = 0.005


def read_vane():
    power = digitalio.DigitalInOut(VANE_POWER_PIN)
    power.direction = digitalio.Direction.OUTPUT
    power.value = True
    time.sleep(0.005)

    adc = analogio.AnalogIn(VANE_ADC_PIN)
    raw = adc.value
    adc.deinit()

    power.value = False
    power.deinit()

    voltage = raw / 65535 * 3.3
    direction = vane_lookup.raw_to_direction(raw)
    return raw, voltage, direction


def sample_anemometer(window_s=ANEMOMETER_WINDOW_S):
    power = digitalio.DigitalInOut(ANEMOMETER_POWER_PIN)
    power.direction = digitalio.Direction.OUTPUT
    power.value = True
    time.sleep(0.005)

    pin = digitalio.DigitalInOut(ANEMOMETER_PIN)
    pin.direction = digitalio.Direction.INPUT
    pin.pull = None  # external pull-up (from ANEMOMETER_POWER_PIN) handles this

    pulses = 0
    last_state = pin.value
    last_edge = time.monotonic()
    start = last_edge
    while time.monotonic() - start < window_s:
        state = pin.value
        now = time.monotonic()
        if state != last_state and (now - last_edge) > DEBOUNCE_S:
            if state is False:  # reed closed = falling edge
                pulses += 1
            last_edge = now
            last_state = state

    pin.deinit()
    power.value = False
    power.deinit()

    mph = (pulses / window_s) * ANEMOMETER_MPH_PER_HZ
    return pulses, mph


def main():
    print("rfm95.weather wiring test -- Ctrl-C to stop")

    rain_pin = digitalio.DigitalInOut(RAIN_PIN)
    rain_pin.direction = digitalio.Direction.INPUT
    rain_pin.pull = None  # external pull-up (from 3V3) handles this

    rain_tips = 0
    rain_last_state = rain_pin.value
    rain_last_edge = time.monotonic()
    last_wind_sample = 0.0

    while True:
        now = time.monotonic()

        state = rain_pin.value
        if state != rain_last_state and (now - rain_last_edge) > DEBOUNCE_S:
            if state is False:
                rain_tips += 1
                print(
                    "rain tip #{} ({:.2f} mm total)".format(
                        rain_tips, rain_tips * RAIN_MM_PER_TIP
                    )
                )
            rain_last_edge = now
            rain_last_state = state

        if now - last_wind_sample >= WIND_SAMPLE_INTERVAL_S:
            pulses, mph = sample_anemometer()
            raw, voltage, direction = read_vane()
            print(
                "wind: {} pulses -> {:.1f} mph | vane: {} raw={} ({:.2f} V)".format(
                    pulses, mph, direction, raw, voltage
                )
            )
            last_wind_sample = time.monotonic()


if __name__ == "__main__":
    main()
