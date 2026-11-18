# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`rfm95.weather` is a battery-powered weather station node in the `yard.net` sensor network (see `../CLAUDE.md` for the network overview and gateway packet format). Hardware: Adafruit Feather RP2040 RFM95 running **CircuitPython**, wired to a SparkFun Weather Meter Kit (SEN-15901): rain gauge, anemometer, and wind vane.

**Status: design phase.** The wiring and sleep strategy are settled, but the firmware isn't written. `code.py` (the CircuitPython entry point, run on boot) is a uv-generated placeholder. The README calls it `main.py`, but CircuitPython runs `code.py`.

## Development

`uv` and `pyproject.toml` exist only for local tooling/IDE support. There are no tests, linters, or pre-commit hooks configured yet. Firmware runs on-device as `.py`/`.mpy` files copied to the board; libraries go in `lib/` (no pip on device).

```sh
uv sync
```

The sibling project `../nulayinn/` runs on the same board and already implements the patterns this project will need: LoRa send via msgpack with ACK/retries (`lib/lora_sender.py`), battery ADC monitoring, and the `secrets.py` / `secrets.example` convention. Reuse its approach rather than inventing a new one. LoRa settings must match the gateway: 915 MHz, SF7, 125 kHz BW, CR 5, CRC on.

## Sources of truth

- **`README.md` wiring section is authoritative.** `wiring-diagram.pdf` is out of date (drawn for the plain Feather RP2040).
- **`notes.md`** is a design-discussion log. Its earlier sections contain advice that was later corrected (e.g. `pull=True`, using GP7). The "Update (2026-11-11)" section at the end supersedes them.

## Hardware constraints that shape the firmware

- **Pin names:** this board's `board` module has no `GPx` names. Use `board.D6`, `board.D5`, `board.D9`, `board.D10`, `board.A0`. Avoid D4 (NeoPixel), D7 (BOOT button, GP7, not on header), D13 (LED); the radio uses GP8 and GP14–GP23.
- **Rain (D6):** external 10 kΩ pull-up to 3V3 + 0.1 µF cap. Wake source is `alarm.pin.PinAlarm(pin=board.D6, value=False, edge=True, pull=False)`. One wake = one tip; after a rain wake, stay awake and count tips (debounced) until ~20–60 min of quiet, then sleep again. 0.2794 mm per tip.
- **Anemometer (D5):** cannot be counted during sleep (each pulse would reboot the chip). Wake on a `TimeAlarm`, drive **D9 HIGH** (powers its pull-up), wait a few ms for the cap to charge, count pulses for 3–5 s with `pull=None` and ~5 ms software debounce, then set D9 LOW. `mph = pulses / window_s * 1.492`. Wake frequency dominates the power budget.
- **Wind vane (A0):** resistor ladder read via ADC; drive **D10 HIGH** only while reading. Map raw `adc.value` (0–65535) to direction with an empirically calibrated lookup table, not datasheet values.
- **State persistence:** running counters in `alarm.sleep_memory` (survives deep sleep, lost on power loss); periodic checkpoints in `microcontroller.nvm` (limited write endurance, don't write per tip); larger structured state as a JSON file.
- **Testing:** test deep sleep on battery, not USB. Over USB the board does a "fake" deep sleep and `alarm.wake_alarm` may be unset (adafruit/circuitpython#5794).
