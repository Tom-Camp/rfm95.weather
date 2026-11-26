# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`rfm95.weather` is a battery-powered weather station node in the `yard.net` sensor network (see `../CLAUDE.md` for the network overview and gateway packet format). Hardware: Adafruit Feather RP2040 RFM95 running **CircuitPython**, wired to a SparkFun Weather Meter Kit (SEN-15901: rain gauge, anemometer, and wind vane) and an Adafruit SHT41 temperature/humidity sensor on the STEMMA QT connector. Power: 3.7 V 2000 mAh Li-ion battery, Voltaic P126 6 V 2 W solar panel, and Adafruit bq24074 linear charger.

**Status: in progress.** `code.py` (the CircuitPython entry point, run on boot) reads every sensor and sends over LoRa, but never sleeps. Deep sleep, wake alarms, and the saved rain count are designed but not written. The sender, SHT41, and `keypad` code has been tested only in simulation, not on the board.

## Firmware layout

- `code.py`: the main loop. `build_data()` defines the packet's `data` keys, which are the API contract (README "LoRa packet"); send `None` for a missing reading instead of dropping its key.
- `lib/lora_sender.py`: **differs from the copies in `nulayinn` and `rfm95.soil`; don't overwrite it with theirs.** It sets `node`/`destination` so ACKs and retries work (a broadcast always returns `True`), starts from a random sequence number so the gateway doesn't discard retries after a reboot, and sleeps the radio after each send. The other copies lack all three.
- `lib/battery_monitor.py`: claims A3 and D13 when imported, so `code.py` imports it only on boards that have D13.
- `vane_lookup.py`: calibrated for this vane. Recalibrate with `calibrate_vane.py`.
- `_pin()`, `_i2c()`, `init_lora()`, and `init_battery()` let `code.py` run on dev boards without the radio (e.g. Pico W).

## Development

`uv` and `pyproject.toml` exist only for local tooling/IDE support. There are no tests, linters, or pre-commit hooks configured yet. Firmware runs on-device as `.py`/`.mpy` files copied to the board; libraries go in `lib/` (no pip on device).

```sh
uv sync
```

The sibling project `../nulayinn/` runs on the same board; reuse its approach for deep sleep and low-battery handling. `DEVICE_NUM` (3) comes from `settings.toml`, which is gitignored; copy `settings.toml.example`. LoRa settings must match the gateway: 915 MHz, SF7, 125 kHz BW, CR 5, CRC on.

## Sources of truth

- **`README.md` wiring section is authoritative.** `wiring-diagram.pdf` is out of date (drawn for the plain Feather RP2040).
- **`notes.md`** is a design-discussion log. Its earlier sections contain advice that was later corrected (e.g. `pull=True`, using GP7). The dated "Update" sections at the end supersede them; the latest wins.

## Hardware constraints that shape the firmware

- **Pin names:** this board's `board` module has no `GPx` names. Use `board.D6`, `board.D5`, `board.D9`, `board.D10`, `board.A0`, `board.A3` (battery). Avoid D4 (NeoPixel), D7 (BOOT button, GP7, not on header), D13 (LED); the radio uses GP8 and GP14–GP23.
- **Rain (D6):** external 10 kΩ pull-up to 3V3 + 0.1 µF cap. Wake source is `alarm.pin.PinAlarm(pin=board.D6, value=False, edge=True, pull=False)`. One wake = one tip; after a rain wake, stay awake and count tips with `keypad` until ~20–60 min of quiet, then sleep again. 0.2794 mm per tip. `code.py` already counts with `keypad.Keys`, which scans in the background (polling missed about 35% of simulated tips) but doesn't run during deep sleep. `countio` can't use D6 (GP6 is a PWM A-channel pin).
- **Anemometer (D5):** cannot be counted during sleep (each pulse would reboot the chip). Wake on a `TimeAlarm`, drive **D9 HIGH** (powers its pull-up), wait a few ms for the cap to charge, count pulses for 3–5 s with `pull=None` and ~5 ms software debounce, then set D9 LOW. `mph = pulses / window_s * 1.492`. Wake frequency dominates the power budget.
- **Wind vane (A0):** resistor ladder read via ADC; drive **D10 HIGH** only while reading. Map raw `adc.value` (0–65535) to direction with an empirically calibrated lookup table, not datasheet values.
- **SHT41 (STEMMA QT):** I2C address 0x44 (fixed), on GP2 (SDA) / GP3 (SCL), shared with the SDA/SCL header pins. Use `adafruit_sht4x.SHT4x(board.STEMMA_I2C())` in `Mode.NOHEAT_HIGHPRECISION`. Read once per timed wake; it can't wake the chip. Convert °C to °F before sending. `adafruit_sht4x.mpy` is in `lib/`; its dependency `adafruit_bus_device` is built into CircuitPython on this board.
- **Power:** charger LOAD feeds the Feather's BAT input. Battery voltage is read on A3 through a 100 kΩ/100 kΩ divider on the battery itself, because LOAD reads up to 4.4 V in sun. The estimated budget (README "Power" section) is ~180–200 mAh/day with deep sleep vs ~600–720 mAh/day always awake; the panel supplies ~300 mAh/day in winter, so the firmware needs deep sleep to last through winter. These are estimates until measured.
- **State persistence:** running counters in `alarm.sleep_memory` (survives deep sleep, lost on power loss); periodic checkpoints in `microcontroller.nvm` (limited write endurance, don't write per tip); larger structured state as a JSON file.
- **Testing:** test deep sleep on battery, not USB. Over USB the board does a "fake" deep sleep and `alarm.wake_alarm` may be unset (adafruit/circuitpython#5794).
