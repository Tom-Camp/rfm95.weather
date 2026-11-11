# rfm95.weather

A battery-powered weather station for the `yard.net` sensor network. It uses an
[Adafruit Feather RP2040 RFM95](https://www.adafruit.com/product/5714) running
CircuitPython, connected to a
[SparkFun Weather Meter Kit (SEN-15901)](https://www.sparkfun.com/weather-meter-kit.html)
(rain gauge, anemometer, and wind vane).

> **Status:** design phase. The wiring and sleep strategy are worked out (see
> [`notes.md`](notes.md) and [`wiring-diagram.pdf`](wiring-diagram.pdf)), but the
> firmware isn't written yet. `main.py` is still a placeholder.

## How it works

All three sensors are passive, so they draw no power while the Feather sleeps.
The station uses CircuitPython deep sleep
(`alarm.exit_and_deep_sleep_until_alarms`) with two wake sources:

| Sensor     | Output                                    | Wake / read strategy                                                                 | Conversion                     |
|------------|-------------------------------------------|--------------------------------------------------------------------------------------|--------------------------------|
| Rain gauge | Reed switch, one closure per bucket tip   | **PinAlarm**: each tip wakes the chip; stay awake and count tips until rain stops    | 0.2794 mm (0.011″) per tip     |
| Anemometer | Reed switch, one closure per rotation     | **TimeAlarm**: wake on a schedule and count pulses for a 3–5 s window                | 1 closure/s = 1.492 mph        |
| Wind vane  | Resistor ladder (16 positions, 8 reliable) | Read with the ADC during the same timed wake; only power the divider while reading | Lookup table of ADC values     |

### Rain

Each bucket tip pulls GP6 low and wakes the chip. Pulses that arrive while the
chip is booting can't be counted, so after a rain wake the firmware stays awake
and counts tips with debounced polling or interrupts. It goes back to sleep after
a quiet period of about 20–60 minutes with no tips.

### Wind

The anemometer can't be counted while the chip sleeps, because every rotation
would trigger a full reboot. Instead the chip wakes on a timer, counts closures
for a short window, and computes `mph = (pulses / window_s) × 1.492`. Gusts
between samples are missed. How often the chip wakes for wind samples is the
main factor in the power budget.

### Persisting state

| Storage                  | Survives                                   | Use for                                                 |
|--------------------------|--------------------------------------------|---------------------------------------------------------|
| `alarm.sleep_memory`     | Deep sleep, soft/watchdog resets           | Running tip counter (cheap to update on every tip)      |
| `microcontroller.nvm`    | Power loss / battery swap                  | Periodic checkpoints of rain totals (limited write endurance) |
| File on the filesystem   | Power loss                                 | Larger structured state (JSON)                          |

On the RP2040, deep sleep keeps SRAM powered (it's closer to a very light power
mode than a true shutdown), which is why `sleep_memory` works. It also means
wake-ups cost almost as much power as staying awake.

## Wiring

Full diagram: [`wiring-diagram.pdf`](wiring-diagram.pdf).

| Feather pin   | Connects to                                                         | Notes                                                        |
|---------------|---------------------------------------------------------------------|--------------------------------------------------------------|
| **3V3**       | 10 kΩ pull-ups on GP6 and GP7                                        | System 3.3 V rail                                            |
| **GND**       | Rain gauge GND, anemometer GND, vane resistor leg, debounce caps     | Common ground                                                |
| **GP6**       | Rain gauge signal (RJ11 center pair, guide pins 2–3)                 | PinAlarm wake source, with RC debounce                       |
| **GP7**       | Anemometer signal (through the wind vane's RJ11 cable)               | Sampled on a timer, with RC debounce                         |
| **GP26 / A0** | Junction of the 10 kΩ series resistor and the wind vane              | ADC input                                                    |
| **GP10**      | 10 kΩ series resistor at the top of the vane divider                 | Driven HIGH only while measuring, LOW while asleep           |

The anemometer cable plugs into the wind vane. The vane's RJ11 cable carries
both the vane's resistor pair and the anemometer's switch pair down to the
electronics.

### Wind vane divider

```
GP10 ── 10 kΩ ──┬── GP26 (ADC)
                │
           vane resistor
                │
               GND
```

Because GP10 stays LOW during sleep, the divider draws almost no standby
current. Calibrate direction empirically: log the raw `adc.value` while rotating
the vane through each detent. Resistor tolerances are too loose at 16-bit ADC
resolution to rely on values calculated from the datasheet.

### Reed-switch debounce (GP6 and GP7)

Both reed inputs use the same RC network:

```
3V3 ── 10 kΩ ──┬── GPx
               │
        ┌──────┴──────┐
      reed          0.1 µF
        │             │
       GND           GND
```

- **τ = 10 kΩ × 0.1 µF ≈ 1 ms.** This absorbs contact bounce (a few ms) but
  still passes every real tip or rotation.
- No code runs during sleep, so the RC network is the only bounce filter for
  wake pulses. Without it, a bouncy tip causes several spurious wakes and
  inflates the rain count.
- The external pull-up replaces the internal one, so configure the alarm as:
  ```python
  alarm.pin.PinAlarm(pin=board.GP6, value=False, edge=True, pull=False)
  ```
  (Alternatively, drop the external resistor and use `pull=True`.)
- **Tuning:** if the anemometer misses pulses in high wind, lower C to
  0.047 µF. If rain still double-counts, raise it to 0.47 µF. Keep τ under
  about 10 ms.
- Keep software debounce while awake as well (for example, ignore anemometer
  pulses less than 5 ms apart).
- **Optional:** buffer the rain line through a 74HC14 Schmitt-trigger gate
  (powered from 3V3) for a guaranteed clean edge.
- Mount the caps close to the Feather's header pins and run the reed leads as
  twisted pairs (signal + GND).

### Before crimping

Cable colors on the kit can vary, so check each RJ11 pair with a multimeter:

- **Rain and anemometer pairs** should beep when you trip the reed switch by hand.
- **Vane pair** should show a different resistance at each detent as you rotate it.

Cross-check against the
[SparkFun hookup guide](https://learn.sparkfun.com/tutorials/weather-meter-hookup-guide/hardware-overview)
pin tables.

## Testing caveats

- **Test on battery, not USB.** When USB is connected, the Feather does a "fake"
  deep sleep and `alarm.wake_alarm` may not be set on wake
  ([adafruit/circuitpython#5794](https://github.com/adafruit/circuitpython/issues/5794)).
- RP2040 dormant mode has no RTC without an external clock, so timed sleeps use
  somewhat more power than pin-only sleeps.

## Development

`uv` and `pyproject.toml` are here only for local tooling. The firmware itself
runs as CircuitPython `.py` / `.mpy` files copied to the device.

```sh
uv sync
```

## References

- [SparkFun Weather Meter hookup guide](https://learn.sparkfun.com/tutorials/weather-meter-hookup-guide)
- [Adafruit: Deep Sleep with CircuitPython](https://learn.adafruit.com/deep-sleep-with-circuitpython)
- [CircuitPython `alarm` module docs](https://docs.circuitpython.org/en/latest/shared-bindings/alarm/)

## License

- [MIT License](LICENSE)
