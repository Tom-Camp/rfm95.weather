# Notes

## Using an Adafruit Feather RP2040 (https://www.adafruit.com/product/5714) how can I retain data through CircuitPythons deepsleep()?

On the RP2040, alarm.exit_and_deep_sleep_until_alarms() behaves like an extreme light sleep rather than a true power-down - SRAM survives - so the standard way to keep data across deep sleep is alarm.sleep_memory, a special bytearray that persists across deep sleep, software resets, and watchdog resets (Adafruit Deep Sleep guide, CircuitPython alarm docs).

Basic pattern - incrementing a counter across wake cycles:

```python
import alarm, time

# Check why we're running
if alarm.wake_alarm:
    print("Woke from:", type(alarm.wake_alarm))
else:
    print("Power-on / hard reset")

# Read persistent value
count = alarm.sleep_memory[0]          # sleep_memory acts like a bytearray
print("Wake count:", count)

alarm.sleep_memory[0] = (count + 1) % 256   # write it back

# Sleep 10 seconds, then restart code.py
time_alarm = alarm.time.TimeAlarm(monotonic_time=time.monotonic() + 10)
alarm.exit_and_deep_sleep_until_alarms(time_alarm)
```

Things worth knowing:

- alarm.sleep_memory is lost if power is removed (battery swap, brown-out). If you need data to survive a full power cycle, write it to microcontroller.nvm (non-volatile flash) or a file on the filesystem instead - the guide's RP2040 page shows exactly that pattern, logging to a file before sleeping.
- Don't write flash/NVM every loop if you can avoid it - flash writes have finite endurance; sleep memory is fine to update constantly.
- USB complicates testing: plugged into USB, the Feather can't truly deep sleep, so it does a "fake" deep sleep and alarm.wake_alarm may not be set on wake - a known quirk (GitHub issue adafruit/circuitpython#5794). Test on battery.
- Pin alarms on RP2040 accept any edge/level configuration, but note that with a TimeAlarm, the RP2040's dormant mode lacks RTC support without an external clock, so timed sleeps are slightly less power-efficient.

You can also mix approaches: small counters/flags in sleep_memory, larger state in microcontroller.nvm[0:N], and structured data (JSON) in a file. Want an example combining sleep memory with a pin-wake button?

_This project will be using pin alarms because it is for a weather station with reed switches for wind and rain._

Reed switches change the picture in an important way: a PinAlarm can wake the chip on a pulse, but while it's asleep, pulses don't accumulate anywhere - every tip of the rain bucket or rotation of the anemometer just boots the whole chip back into code.py. That shapes your design quite a bit.

**The core problem**

With alarm.exit_and_deep_sleep_until_alarms(pin_alarm), one reed pulse = one full CircuitPython boot. If heavy rain tips the bucket every few seconds and each gust spins the anemometer, you're rebooting constantly and each wake still only "sees" one pulse - you can't tell one tip from five that happened while asleep. And since the chip isn't technically asleep (RP2040 dormant mode), you burn almost as much power being woken 500 times as you would just staying awake.

**What tends to work for weather stations**

Rain is cumulative, so the usual pattern is: wake on the first rain pulse, then stay awake and count subsequent tips with regular interrupts/polling for a hold-off window (say, 20–60 minutes after the last tip), accumulating the count in alarm.sleep_memory or a file, then deep sleep again. Wind is the opposite - it's inherently a rate measurement, so you generally want to sample it on a fixed schedule (TimeAlarm) rather than wake on every rotation. A typical loop:

```python
import alarm, board, time, microcontroller

RAIN_PIN = board.D6  # GP6
WAKE_TIMEOUT = 30 * 60  # stay awake 30 min after last rain event

# Persisted across sleeps
tips_total = int.from_bytes(alarm.sleep_memory[0:4], "big")

if alarm.wake_alarm and isinstance(alarm.wake_alarm, alarm.pin.PinAlarm):
    tips_total += 1  # this wake was caused by one bucket tip
    last_rain = time.monotonic()
    # Stay awake counting pulses with normal interrupts, log periodically,
    # and sample wind while you're up anyway...
    ...
    if time.monotonic() - last_rain > WAKE_TIMEOUT:
        alarm.sleep_memory[0:4] = tips_total.to_bytes(4, "big")
        rain_alarm = alarm.pin.PinAlarm(pin=RAIN_PIN, value=False, edge=True, pull=False)  # external 10 kΩ pull-up
        alarm.exit_and_deep_sleep_until_alarms(rain_alarm)
else:
    # Power-on: initialize, maybe do a scheduled wind sample via TimeAlarm
    ...
```

**Practical notes for your hardware:**

- Reed switches close to ground, so you want value=False, edge=True, pull=True - wake when the pin falls to 0 as the magnet closes the switch. RP2040 accepts any pin alarm configuration, so this works fine.
- Contact bounce is real with reed switches and a tipping bucket. While awake, debounce in software; while asleep, a bouncy first pulse may register as two or three wakes instead of one. This biases your rain total slightly upward - many designs accept this, or add the RC debounce / Schmitt trigger on the bucket line so sleepy pulses are clean.
- Wind while asleep is simply lost. If you care about gusts overnight, either keep a TimeAlarm cycle (wake every N seconds/minutes and sample wind for a window - costly), or accept a daily-max approach where daytime samples dominate. Some stations use a hardware pulse counter (74HC counter IC fed by the anemometer, read over GPIO) so pulses accumulate without the MCU.
- Persist totals properly: rain totals should survive a battery swap, so mirror sleep_memory into microcontroller.nvm or a file occasionally (NVM write endurance makes it unsuitable for every single tip, but fine for periodic checkpointing).

Do you already have an anemometer/pulse-counter in mind, and is the station battery + solar? That affects whether a hybrid "wake on rain, scheduled wind sampling" budget is realistic - happy to sketch the full loop if you share the setup.

_I have the SparkFun Weather Meter Kit (https://www.sparkfun.com/weather-meter-kit.html)_

That kit's a good fit for the Feather RP2040 - all three sensors are passive, so they draw zero power while the chip sleeps. Here's how the pieces map onto the sleep strategy we discussed:

**Sensor characteristics (from the [SparkFun hookup guide](https://learn.sparkfun.com/tutorials/weather-meter-hookup-guide) and [product page](https://www.sparkfun.com/weather-meter-kit.html))**

- **Rain gauge** - self-emptying tipping bucket; one momentary reed closure per 0.011″ (0.2794 mm) of rain. This is your natural deep-sleep wake source: `PinAlarm(value=False, edge=True, pull=True)`, each wake adds 0.2794 mm to a counter you keep in `alarm.sleep_memory`.
- **Anemometer** - one closure per rotation, calibrated so 1.492 mph produces exactly one closure per second. As predicted, you can't count these asleep, so sample it on a schedule: wake via TimeAlarm, count closures for e.g. a 3–5 second window, convert with `mph = frequency × 1.492`, go back to sleep. Pulses between samples are lost - that's the fundamental tradeoff.
- **Wind vane** - a resistor ladder producing a voltage per direction (16 positions in theory, 8 cardinal directions reliable, since the magnet can close two adjacent switches at once). This one needs an **ADC pin** on the Feather (A0–A3 = GP26–GP29), and since it's a passive divider you can power it from a spare GPIO set HIGH only while measuring - no standby drain.

**A concrete architecture**

```python
import alarm, board, time, analogio, digitalio
from collections import deque

RAIN_TIP_MM = 0.2794

rain_total_mm = int.from_bytes(alarm.sleep_memory[0:4], "big") * RAIN_TIP_MM

if alarm.wake_alarm and isinstance(alarm.wake_alarm, alarm.pin.PinAlarm):
    # Woke because a bucket tipped
    tips = int.from_bytes(alarm.sleep_memory[0:4], "big") + 1
    alarm.sleep_memory[0:4] = tips.to_bytes(4, "big")
    # ...stay awake with debounced interrupt counting until quiet period...
elif isinstance(getattr(alarm, "wake_alarm", None), alarm.time.TimeAlarm):
    # Scheduled wind sample
    anemo_pwr = digitalio.DigitalInOut(board.D9)   # powers the anemometer's 10 kΩ pull-up
    anemo_pwr.direction = digitalio.Direction.OUTPUT
    anemo_pwr.value = True
    anemo = digitalio.DigitalInOut(board.D5)        # GP5 (GP7 is the BOOT button on this board)
    anemo.direction = digitalio.Direction.INPUT
    anemo.pull = None                               # external pull-up via D9
    vane_pwr = digitalio.DigitalInOut(board.D10)    # GP10
    vane_pwr.direction = digitalio.Direction.OUTPUT
    vane_pwr.value = True
    adc = analogio.AnalogIn(board.A0)               # GP26
    time.sleep(0.01)                                # let the RC caps settle

    start = time.monotonic(); pulses = 0; last = None
    while time.monotonic() - start < 3.0:   # 3-second sample window
        now = anemo.value
        if last and not now and last:
            pulses += 1                      # falling edge
        last = now
    mph = (pulses / 3.0) * 1.492
    direction = adc.value                    # compare against vane table

    vane_pwr.value = False
    anemo_pwr.value = False
    # log mph/direction, then sleep until next sample OR rain pulse
    rain_alarm = alarm.pin.PinAlarm(pin=board.D6, value=False, edge=True, pull=False)
    timer = alarm.time.TimeAlarm(monotonic_time=time.monotonic() + 60)
    alarm.exit_and_deep_sleep_until_alarms(rain_alarm, timer)
```

(Wiring-wise, all three sensors connect via RJ11 - you'll want breakout jacks or a crimped cable; the SparkFun guide shows the pinouts.)

**Two design choices to think through:**

- **Wake-on-rain vs. pure scheduling**: an alternative to pin-alarm wake is dropping the rain pin alarm entirely and letting the TimeAlarm cycle (every minute) poll the bucket. Since RP2040 dormant sleep burns nearly full-power anyway, the pin alarm buys you less than on other chips - it mainly gets you *instant* rain response instead of up-to-60-second latency, at the cost of a boot per tip in a heavy storm. Which behavior you want depends on your logging cadence.
- **Vane direction lookup**: you'll need to capture the actual ADC values for each of the 16 vane resistance combinations - the SparkFun guide publishes the resistor values so you can compute the expected divider voltages, but empirically calibrating (log raw `adc.value` while rotating the vane through each detent) is more reliable than trusting the math, since tolerances matter (the RP2040 ADC is 12-bit; CircuitPython scales readings to 16-bit).

If you tell me your logging target (SD card, LoRa/WiFi upload?) and power source, I can tighten up the duty cycle - the big open question is how often you're willing to wake for wind, since that dominates the power budget.


_Sketch out a wiring diagram_

Let me grab the exact RJ11 pinouts from the SparkFun hookup guide first so the diagram is accurate.

Got the pinouts confirmed from the [SparkFun hookup guide](https://learn.sparkfun.com/tutorials/weather-meter-hookup-guide/hardware-overview): both the rain gauge and anemometer use the two inner (center) conductors of their RJ11 plugs, and notably the anemometer cable actually plugs into the wind vane, whose cable then carries both the shared anemometer switch pair and the vane's resistor pair down to your electronics. Here's the diagram:

Here's the full wiring diagram - I've sketched it out in the canvas so you can zoom in on the connections. Key points:

- **Rain gauge -> D6 (GP6)** (center pair of its RJ11), configured as `PinAlarm(value=False, edge=True, pull=True)` to wake the Feather from deep sleep on each bucket tip
- **Anemometer -> D5 (GP5)** *(originally GP7; see update below)* (shared via the vane's RJ11 cable, since SparkFun chains the anemometer through the vane), read with a pull-up during timed sample windows - 1 pulse/sec = 1.492 mph
- **Wind vane -> A0 (GP26)** through a **10 kΩ series resistor** forming a divider powered by **D10 (GP10)**, a GPIO you switch HIGH only while actually reading the ADC so the divider draws nothing while asleep
- **Common GND** across all three sensors and the Feather

One caution I'd flag before you crimp anything: the supplied cable colors can vary, so verify each pair with a multimeter - the anemometer/rain pairs will beep when you manually trip the reed switches, while the vane pair will show varying resistance as you rotate it through its detents. The SparkFun hookup guide's hardware overview page has the official RJ11 pin tables if you want to cross-check my layout against their drawings.

Want me to annotate the diagram with the debounce components (the 0.1 µF caps and optional external pull-ups), or add the RJ11 jack breakout wiring detail showing which jack pins map to which conductors?

The diagram now has a full input-conditioning section. Each reed channel (rain -> D6 and anemometer -> D5) gets an identical RC network: a 10 kΩ external pull-up to 3V3 and a 0.1 µF cap from the node to ground, giving τ ≈ 1 ms - enough to swallow reed bounce without smearing genuine pulses.

One detail worth flagging: with the external pull-up in place, you'd set `pull=False` in the PinAlarm (the external resistor defines the idle state). Or you can keep the internal pull-up and skip the external resistor - both work, the external one is just better-defined.

The notes also cover the tuning range (shrink to 0.047 µF if you miss fast rotations, grow to 0.47 µF if rain still double-counts) and the optional 74HC14 Schmitt-trigger buffer for the rain line if you want a guaranteed clean edge on every counted tip. Anything else you'd like added - the RJ11 jack pin mapping, or a parts list?

## Update (2026-11-11): wiring corrections for the Feather RP2040 RFM95

The original diagram assumed the plain Feather RP2040. Checking CircuitPython's
pin map for `adafruit_feather_rp2040_rfm` turned up these changes (the README
wiring section is the current source of truth):

- **GP7 is the onboard BOOT/user button** on the RFM95 Feather and isn't
  broken out to the header. **The anemometer moved to D5 (GP5).**
- **Use silkscreen names in code:** `board.D6`, `board.D5`, `board.D9`,
  `board.D10`, `board.A0`. This board's `board` module has no `GPx` names.
  The radio uses GP8 and GP14–GP23, so none of these pins conflict with it.
- **Each reed switch has its own 10 kΩ pull-up to its node.** It is not in
  series with the sensor. One sensor wire goes to the node, the other to GND,
  and a 0.1 µF cap runs from the node to GND.
- **Rain pull-up stays on 3V3**, because it has to be live during sleep to
  wake the chip. Use `pull=False` in the PinAlarm, since the external resistor
  does the pull-up.
- **Anemometer pull-up is powered from D9**, driven HIGH only during the
  sample window. If the cups stop with the reed closed, a pull-up from 3V3
  would draw 0.33 mA for the whole sleep.
- The RC network mostly filters the *release* edge: the closing reed
  discharges the cap instantly. Adding ~1 kΩ between the reed and the cap
  filters both edges and is gentler on the contacts (optional).
- Keep 0.47 µF for the rain line only. The anemometer reaches ~67 Hz at
  100 mph, so a large τ would merge its pulses.
- An external 74HC14 is mostly redundant, because RP2040 input pads have
  Schmitt-trigger inputs enabled by default.
- Optional: ~1 kΩ in series at each GPIO for static protection on long
  outdoor runs.
