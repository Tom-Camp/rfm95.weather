import os
import time

import adafruit_sht4x
import analogio
import board
import busio
import digitalio
import keypad

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
SEND_INTERVAL_S = 300
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


def _i2c():
    # Feather: the STEMMA QT connector's bus. Dev boards like the Pico W have no
    # STEMMA_I2C, so use the same GPIOs (SDA=GP2, SCL=GP3) there.
    if hasattr(board, "STEMMA_I2C"):
        return board.STEMMA_I2C()
    return busio.I2C(scl=board.GP3, sda=board.GP2)


def init_sht41():
    # RuntimeError: no pull-ups on the bus. ValueError: no device at 0x44.
    # OSError: I2C transfer failed.
    try:
        sht = adafruit_sht4x.SHT4x(_i2c())
        sht.mode = adafruit_sht4x.Mode.NOHEAT_HIGHPRECISION
    except (RuntimeError, ValueError, OSError) as e:
        print("SHT41 not found: {}".format(e))
        return None
    return sht


def celsius_to_fahrenheit(celsius):
    return celsius * 9 / 5 + 32


def read_sht41(sht):
    # RuntimeError: bad CRC. OSError: I2C transfer failed.
    try:
        temp_c, humidity = sht.measurements
    except (RuntimeError, OSError) as e:
        print("SHT41 read failed: {}".format(e))
        return None
    return celsius_to_fahrenheit(temp_c), humidity


def get_device_num():
    value = os.getenv("DEVICE_NUM")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def init_lora():
    if not hasattr(board, "RFM_CS"):
        print("no RFM95 radio on this board; not sending")
        return None

    device_num = get_device_num()
    if device_num is None:
        print("DEVICE_NUM missing or not an int in settings.toml; not sending")
        return None

    # Imported here so dev boards without the radio can still run this file.
    from lib.lora_sender import LoraSender

    try:
        return LoraSender(device_num=device_num)
    except (RuntimeError, ValueError, OSError) as e:
        print("RFM95 not found: {}".format(e))
        return None


def init_battery():
    # BatteryMonitor claims A3 and D13 on import; dev boards lack D13.
    if not hasattr(board, "D13"):
        return None
    from lib.battery_monitor import BatteryMonitor

    return BatteryMonitor()


def build_data(mph, direction, rain_tips, air, voltage):
    # These keys are the API contract: the gateway forwards them unchanged.
    # A missing reading is sent as None so the keys stay the same.
    temp_f, humidity = air if air is not None else (None, None)
    return {
        "wind_speed": mph,  # mph
        "wind_dir": direction,  # N, NE, E, SE, S, SW, W, NW
        "rain_tips": rain_tips,  # running count; resets to 0 on boot
        "temp": temp_f,  # F
        "humidity": humidity,  # % RH
        "battery": voltage,  # V
    }


def init_rain():
    # keypad scans in the background, so tips are still queued while the loop is
    # blocked sampling wind or sending. It doesn't run during deep sleep.
    return keypad.Keys(
        (RAIN_PIN,),
        value_when_pressed=False,
        pull=False,  # external pull-up (from 3V3) handles this
        interval=DEBOUNCE_S,
    )


def count_new_tips(rain):
    tips = 0
    event = rain.events.get()
    while event:
        if event.pressed:  # reed closed
            tips += 1
        event = rain.events.get()
    return tips


def main():
    print("rfm95.weather wiring test -- Ctrl-C to stop")

    rain = init_rain()

    sht = init_sht41()
    lora = init_lora()
    battery = init_battery()

    rain_tips = 0
    last_wind_sample = 0.0
    last_send = None  # None: send right after the first sample

    while True:
        now = time.monotonic()

        new_tips = count_new_tips(rain)
        if new_tips:
            rain_tips += new_tips
            print(
                "rain tip #{} ({:.2f} mm total)".format(
                    rain_tips, rain_tips * RAIN_MM_PER_TIP
                )
            )

        if now - last_wind_sample >= WIND_SAMPLE_INTERVAL_S:
            pulses, mph = sample_anemometer()
            raw, voltage, direction = read_vane()
            print(
                "wind: {} pulses -> {:.1f} mph | vane: {} raw={} ({:.2f} V)".format(
                    pulses, mph, direction, raw, voltage
                )
            )
            air = read_sht41(sht) if sht is not None else None
            if air is not None:
                print("air: {:.1f} F, {:.1f} % RH".format(*air))

            now = time.monotonic()
            if lora is not None and (
                last_send is None or now - last_send >= SEND_INTERVAL_S
            ):
                voltage = (
                    battery.read_battery_voltage() if battery is not None else None
                )
                # Include tips queued during the wind sample.
                rain_tips += count_new_tips(rain)
                data = build_data(mph, direction, rain_tips, air, voltage)
                # Blocks for several seconds if the gateway doesn't answer.
                acked = lora.send_data(data)
                print("LoRa {}: {}".format("ACKed" if acked else "not ACKed", data))
                last_send = now
            last_wind_sample = time.monotonic()


if __name__ == "__main__":
    main()
