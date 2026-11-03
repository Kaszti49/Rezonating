---
type: build
status: done
owner: kaszti
date: 2026-11-03
---
# Load cell on the ADC 15 Click

**What:** the [[YZC-133 load cell 5 kg]] read directly by the [[ADC 15 Click board]] (ADS131M02, screw CH1) on the bench rig, without the [[HX711 load cell amplifier board]]. Press test passed on 2026-11-03 on pc-10. The boss asked why we do it this way and whether the HX711 can go; this note is the answer. A Hungarian version for the boss: [Mérlegcella az ADC 15 Clicken](https://claude.ai/artifact/R2bLmX6z56e3N8uHDJRNaL).

## Wiring
| From | To | Note |
| --- | --- | --- |
| ESP32 3V3 | 470 Ω + 220 Ω in series (690 Ω) → red (E+) | joints insulated |
| black (E−) | GND | |
| green (S+) | Click CH1 + | |
| white (S−) | Click CH1 − | |
| Click CH2 + and − | GND | noise-floor channel |

Calculated levels with the cell's E+/E− resistance of about 1070–1120 Ω: bridge (red–black) 2.01–2.04 V, green and white about 1.0 V to GND. Not yet confirmed with the meter. A single 480 Ω would also do (2.28–2.31 V, sense lines about 1.15 V).

## Result (measured, 2026-11-03)
- `adc_dec` at 997.96 Hz, 0 losses, gain 128.
- **Screw CH1 = ADC ch0, confirmed** by the press test.
- ch0 rests at about −20 µV; presses step to +400 … +900 µV and return on release (about 1–2 kg at 0.4 mV/kg, calculated from the shop listing, not calibrated).
- **Open:** short negative spikes of −3 to −4.5 mV and at least one hit at negative full scale (−9375 µV) while handling. Suspects: a loose green/white contact or a knock. Wiggle test the wires while watching ch0, and bolt one end of the cell down.

## Why the Click and not the HX711
The load cell is a **known test signal** for the whole chain (sensor → ADC → firmware → link → Lab) before the SM-24 geophones arrive. It is not a product sensor.

| | HX711 | ADC 15 Click (ADS131M02) |
| --- | --- | --- |
| Speed | 10 or 80 SPS | 2 kSPS, 1 kSPS to the packs ([[D-016 ADC records at 2 kSPS]]); up to 64 kSPS |
| Channels | one at a time (A or B, multiplexed) | 2, sampled simultaneously |
| Gain | fixed: 128/64 (A), 32 (B) | 1–128 per channel |
| Interface | own bit-banged 2-wire protocol | SPI with CRC on every frame, DRDY |
| Future | dead end | same family as the ADS131M04 on our PCB ([[D-015 Prototype ADC on ADC 15 Click]]) |

- **Speed decides.** Footsteps, falls and appliances carry signal up to a few hundred Hz. At 80 SPS the HX711 sees only below 40 Hz (Nyquist).
- **Simultaneous channels:** the time difference between two heads (two geophones) is information.
- **Count every sample:** DRDY and CRC let the firmware count and timestamp every sample; the HX711 gives neither.
- **The work carries over** to the ADS131M04; HX711 code does not.
- **Where the HX711 is better:** pure weighing. It powers the bridge itself and measures ratiometrically, so supply drift cancels. The Click uses its fixed 1.2 V reference, so noise and drift on the 3.3 V rail show up in the reading. That doesn't matter for vibration; it would for absolute weight.

## Why the series resistor
- At gain 128 each ADS131M02 input must stay between about AGND − 1.3 V and AVDD − 1.8 V (≈ 1.5 V at 3.3 V), per the ADS131M02 datasheet.
- A bridge's sense lines sit at half its supply: straight from 3.3 V that is **1.65 V, above the limit**.
- The resistor and the cell's ≈ 1100 Ω form a divider: 3.3 V × 1100 / (1100 + 690) ≈ 2.0 V on the bridge, sense lines ≈ 1.0 V (0.5 V margin).
- Cost: the signal scales with excitation (1.0 mV/V): 2.0 mV at 5 kg instead of 3.3 mV, still well inside ±9.375 mV at gain 128.
- **Why not a lower gain instead:** at gain 4 the full scale is ±300 mV, so a 2–3 mV signal would use about 1 % of it and drown in ADC noise.
- **Why the HX711 needs no resistor:** it is built for bridges (its own E+ supply, inputs sized for that level). The Click has no excitation terminal, so we adapt the level ourselves.

## What went wrong first
The part fitted as "680 Ω" was **680 kΩ** (blue-grey-yellow): the bridge got about 5 mV, so 3.3 V on the ESP end and 0 V on the cell end, and no signal. No 680 Ω in stock, so 470 Ω + 220 Ω in series.

## HX711: can it go?
Yes. Nothing in the product or the Year 1 packs depends on it, and the Click reads the cell on its own. It currently reads 8388607 (top of its range), so its input does nothing useful, and if it's still wired to the cell it can load the bridge.
- [ ] Disconnect it from the cell and from the ESP32 (VCC, GND, DT on GPIO 34, SCK on GPIO 32).
- [ ] Check the first text lines once: the bring-up firmware should print `[HX] HX711 not found`, then `hx711 absent` each second. GPIO 34 has no pull-up and floats when empty, so confirm the "not found" rather than assume it.
- No code change is needed. Dropping the HX711 code from the bring-up firmware is a later clean-up.

## Log
- 2026-11-03 Claude: created from the session with Kaszti (680 kΩ found, 690 Ω fitted, press test passed, boss's questions answered).
