## Hardware: SIM800L → SIM868 (2026-11-12)

- New modem on hand: **Waveshare Pico-SIM868-GSM/GPRS/GNSS** board (photo `uploads/NewSIM.jpg`), shipped with a Pico H, a 600 mAh Li-po, a speaker and a male header strip.
- The black part in the photo is the **speaker**, not an antenna. All three u.FL sockets (GNSS, GSM, BT) are empty: the GSM antenna is mandatory and must come from the box or be bought.
- Decision (pending Kaszti's OK): keep the ESP32-S3 and use the SIM868 board as a modem only. The Pico H comes off. 5 M-F jumpers go from H2 (J29–J33) into the board's Pico sockets: pin 1 RXD ← GPIO17, pin 2 TXD → GPIO18, pin 3 GND, pin 19 PWRKEY ← GPIO16 (HIGH 1.5 s), pin 36 3V3 ← ESP32 3V3. Power comes from the 18650 (L35/L33) into the board's PH2.0 battery socket, with the board's switch on battery.
- Verified from Waveshare's schematic and demo code: UART0 GP0/GP1, PWR_EN GP14 drives an NPN on PWRKEY, and a TXB0104 level shifter on 3V3 (pin 36). Its VBUS/VSYS circuitry stays unused.
- Dropped: SIM800L sockets, the R2/R3 divider, C2 and the nano→micro adapter. C1 (1000 µF) stays at the take-off.
- The board (76 × 24 mm) stands on edge in a printed cradle at the back wall, with the antenna edge up and the GSM antenna stuck on the wall at the back left. The printed base needs the two cradle clips added.
- To buy: a PH2.0 2-pin plug with leads (not in Hestore stock), plus a u.FL GSM antenna if the box has none.
- Regenerated `Rezon_Wiring_Guide.html` and `Rezon_Wiring_List.pdf` (`wiring_source/`), plus `Rezon_Hackathon_Parts_List_SM24.pdf` and `Hackathon_shopping_list_SM24.csv` (new source: `parts_source/parts.py`).
- 2G in Hungary: still on air. Telekom's 2G moved onto Yettel's network in 2026, and a switch-off around 2030 has been reported.

### SIM868 call test on the practice ESP32 (2026-11-12)
- Kaszti asked to test a single call now. Sketch: `practice/sim868_call_test/sim868_call_test.ino` (classic ESP32 DevKit V1, the practice board).
- Practice pins differ from the final S3 map on purpose: TX D25 → board pin 1, RX D26 ← pin 2, PWRKEY D27 → pin 19, 3V3 → pin 36, GND → pin 3. D16/D17 are taken by the geophone-test Click wiring, so that wiring can stay in place.
- Power for the test: the 600 mAh Li-po that came in the box (already on the board's battery socket), so no PH2.0 plug is needed yet.
- Blocker to check: the GSM antenna (none in the photo).
- Result (2026-11-12): first outgoing call placed from the practice rig. Fixes on the way: D26/D27 jumpers were swapped (D26 sat in pin 19, D27 in pin 2), D25 needed reseating in hole 1. Modem at 115200, signal CSQ 30–31, registered on "vodafone", battery 3.99 V. The SIM still has its PIN on: it was unlocked for the session with AT+CPIN, so after every power-up it asks again. For the finished device, switch the PIN off in a phone.
- Diagnostic sketch: `practice/sim868_diag/sim868_diag.ino` (tries both RX/TX orders and 5 bauds, reads idle line levels, pulses PWRKEY only when SIM TXD is low = modem off).
- Incoming call (2026-11-12): Kaszti's phone called Rezon. Caller ID showed (+CLIP), answered with ATA on the 2nd RING, connected ~65 s until the caller hung up (NO CARRIER). Speaker from the Waveshare box on the board, AT+CLVL=100, AT+CMIC=0,10. Both directions work.

## Firmware master prompt (2026-11-12)
- Prompt for the firmware session saved as `firmware/MASTER_PROMPT.md`. Explainer PDF: `Rezon_How_It_Works.pdf` (source `explainer_source/`).
- Kaszti's decisions: fall score = feature vector · weights fitted offline on our recordings (device does vector maths only); one geophone; the button always cancels, walking cancels only as a NEW steady rhythm after the impact (people already walking never cancel); the prompt covers the whole firmware.
- Research behind it: G-Fall (Shenzhen Univ.), Clemente et al. (Univ. of Georgia), FootprintID (CMU/Stanford, SM-24), Liu et al., Shao et al. No usable repo, Hugging Face model or public fall dataset for floor vibration was found.

## Firmware phase 1: detection core, tools, two pages (2026-11-13)

Kaszti's answers: stage link = USB first, Wi-Fi later as an option · speaker gets NEW clips with the blob's words („Minden rendben van?" / „Hívok segítséget!") · device not wired yet, laptop tests only · the "I'm OK" button works in code but is not part of the stage flow.

**What exists** (all in `firmware/`, nothing committed):
- `rezon/src/core/` portable C++ (no Arduino includes): `rezon_core` (layers 1–6 of the master prompt), `rezon_alarm.h` (sequence, home/stage profiles), `rezon_proto.h` (serial lines), `rezon_weights.h` (written by `tools/fit`).
- `rezon/rezon.ino` ESP32-S3 firmware. Compiles with the IDE's arduino-cli (`esp32:esp32:esp32s3`, core 3.3.8): 389 kB flash, 79 kB RAM. **Never run on hardware.**
- `tools/replay.cpp`, `tools/fit.cpp`, `build.bat`, `train.bat`, `mixtest.sh`. Built with the g++ already on this PC.
- `ui/live.html` (stage screen) and `ui/train.html` (recording, labelling, settings). Single files, Web Serial, no internet.
- `data/labels.tsv` (provisional), `data/demo_fall.log` (one real fall with alarm lines, for rehearsing `live.html`).

**Decisions**
- Detection runs only on the device. Pages draw and record; they never decide. Exception: `live.html` has a display-only impact trigger for streams without alarm lines (old practice sketch) and for the demo.
- Events are analysed from 5 ms frames in a 4 s ring, so the work per sample is constant.
- End rule: variance rule (3× / 1.5× background) and 60 %-of-peak rule both implemented (`segMode`). Both find the same 7 falls; the peak rule finds more steps in the soft-shoe recording (22 against 11) → default = peak rule.
- An impact-sized event is analysed over a fixed 900 ms window (or until the floor is quiet). Decision arrives 0.3–0.7 s after the impact.
- A start needs a rise (last 20 ms ≥ 2× the quietest 20 ms just before), so decaying floor ringing cannot start events.
- Spectral features come from a 4-band filter bank (10–20, 20–30, 30–45, 45–65 Hz) with the background power subtracted.
- Fit tool is C++ (no Python on this PC): class-balanced logistic regression, L2, sign-constrained, leave-one-recording-out.
- Alarm order: question → countdown → "calling" clip → dial. The clip ends before dialling (power bank ≈ 1 A).

**Differences from the master prompt, wiring guide wins**
- No battery measurement (power bank build, R4/R5 dropped). Button uses the internal pull-up.
- Amp is the ZK-502M with a volume knob, so the fixed −21 dB rule no longer applies: `volume` setting, default 10 %.
- **Gain conflict:** the jumper guide says "gain 32 in firmware", the master prompt says 4. Gain 32 clips at ±1.8 mm/s and the recorded falls reach 3.9 mm/s. Firmware default = 4. Kaszti to confirm.

**Results on the recordings (2026-11-13)**
- Recordings 2 + 3: 7 of 7 impact-sized events flagged fall-shaped, 0 other alarms. Recording 4 (walking): 0 alarms.
- Fit: 7 falls / 145 others, leave-one-recording-out 7/7, 0 false alarms. **Labels are provisional** (the 7 big impacts are assumed to be the "7 known falls") and the falls are 2× stronger than anything else, so this proves little.
- Walking added on top (recording 4 at 5 offsets, 10 runs): 35/35 falls found, 0 extra alarms; added walking cancelled a fall in 1 run. With the walking doubled in level: 10 extra alarms in 10 runs.
- Sub-impact count was 1 for every event, so that feature carries no weight yet.

**Known weak points**
- Walker tracking: soft-shoe steps sit at the threshold, signatures are noisy, few tracks get confirmed. So the "walkers" gate and bystander recognition rarely engage. Needs labelled walking recordings.
- A NEW walker who starts after a fall cancels it like someone getting up (the prompt's own rule; one sensor cannot tell them apart).
- Recording 1 (gain 32, clipped): 4 fall-shaped + 12 impacts between 2.7 and 10.5 s, nature unknown.

**Open**
- Kaszti: label the events (list in the chat), confirm gain 4, deliver the two voice clips (WAV), put the number in `firmware/rezon/secrets.h`.
- Not written yet: calibration routine (`!cal`), clip converter, Wi-Fi link, hardware bring-up.

## Firmware on the real device: first upload (2026-11-14)

Device wired, on USB (COM4, CH343 = the DevKit's UART port). `firmware/rezon` compiled with arduino-cli (`esp32:esp32:esp32s3`, build in `firmware/build/`) and uploaded.

**Measured over serial**
- ADC: ID 0x2205, 998 samples/s, 0 CRC errors, 0 dropped lines at 460800 baud. Gain ×4.
- Geophone channel (ch1): quiet, sd ≈ 390 counts (≈ 0.0007 mm/s), DC offset ≈ 26 400 counts. No events while nobody touched it. **Not yet tapped**, so the geophone itself is unproven.
- ch2 is open and swings up to full scale. The firmware ignores it.
- Settings (`!get`) answer; flash defaults are the compiled ones.
- Alarm rehearsal (`!test`): ASK 1300 → WAIT 3000 → ANNOUNCE 1100 → CALL → FAIL → WATCH. FAIL is expected: no `secrets.h`, so it never dials.
- **SIM868: no answer.** Diagnostic sketch (S3 pins 17/18/16): SIM TXD (GPIO18) floats (follows the pull-up and the pull-down), 0 bytes in both wire orders at 5 bauds, before and after a PWRKEY pulse. So the modem is off or unpowered, not a swapped RX/TX. First suspect: no 4.0 V at the PH2.0 plug (the guide has the rocker OFF while on USB, and the step-down hangs behind the rocker).

**Bug fixed**
- `!test` jumped straight from ASK to WAIT. `handleLine()` took its own `millis()`, 1 ms ahead of `loop()`'s `now`, so `tick()` saw a negative (wrapped) age. The command handler now gets `loop()`'s `now`. Falls and the button were not affected (they already used it).

**Not verified (needs eyes, ears and hands)**
- LED colour, the two placeholder tones on the speaker, the button, a tap on the table, and `train.html` connecting (Web Serial needs a click on the port chooser).

## Normalised fall rule from the stage test (2026-11-14)

Kaszti's stage recording (`uploads/session_2026-11-14T01-41-28.log`, copied to `firmware/data/`, labels in `labels.tsv`): walking near 0–11 s, mid 12–30 s, far 31–43 s; falls near 43.7 s / mid 51.5 s / far 60.4 s; then 3 jumps (64.3, 70.1, 74.8 s). Gain ×2. Settings on the device were walkerMargin 1.5, impactMin 30, stepRef 8.
Kaszti's goal: a fall at the far end of the room must alarm, a hard step next to Rezon must not, even when the step is louder.

**What the old absolute rule did:** the far fall (impact-path peak ≈ 19 mm/s) never reached impactMin 30, and the 250 ms refractory swallowed its main peak, so it was split into "steps". Two jumps were flagged as falls. Near/mid falls and all jumps clip the ADC at gain ×2.

**Rule 1 (normalised), now the default (`rule = 1`):**
1. Impact-sized only when the peak ≥ `relMin` (4) × the **step level** = the second-loudest step-like event from 8 s to 1 s before the onset (`levelMs`, `levelGapMs`; `stepRef` when none). The last second is left out because each fall started with smaller hits (stumble/knee) that otherwise raised the level. `impactMin` is now only an absolute floor.
2. Fall-shaped only when the impact envelope stays ≥ 30 % of its own peak (`holdFrac`) for ≥ `holdMin` (0.25 s) within −300…+600 ms of the peak. Impact events stay open until 600 ms after the peak for this.
Both numbers ignore distance: a near step is no louder than the walking around it, and a far fall is far louder than that person's own steps and lasts.

**Results (replay):** stage session 3/3 falls (×23.8 / ×15.4 / ×9.3, hold 365 / 315 / 425 ms), 3/3 jumps rejected (hold 165–195 ms), loudest non-impact event ×3.3. Stable for relMin 4–8 and holdMin 0.20–0.30. Old recordings: walking-only still 0 alarms; 2 of the 7 *provisional* falls are now "impact" (hold 125 and 145 ms; one is 1.8 s after a detected fall). Mix test (walking added): 30/42 at ×1, 33/35 at ×2, 2 extra alarms in total.
Rule 0 (old absolute rule) is still there: `!set rule 0`.

**New settings:** rule, relMin, holdMin, holdFrac, levelMs, levelGapMs (`!set`, train page). Protocol: E lines end with `,hold,rel,level`; S lines end with `,level,impactThreshold`. The train page shows ×lvl and hold per event, plus the step level.

**Weak points / open**
- One recording, one person, one floor: 3 falls and 3 jumps. Needs more falls (different people, sitting down, dropped objects) before it is trusted.
- Two people: a loud walker near Rezon raises the level and can hide a far fall of someone who was not walking.
- Clipping at gain ×2 lengthens the measured hold of near events (falls and jumps alike). Try gain ×1 on stage and record again.
- For the stage, set `impactMin` back to a floor (6 mm/s fits this floor), not 30.

**Flashed 2026-11-14.** The board now enumerates as **COM15** (CH343); COM4 is a Bluetooth port on this laptop, so uploads to COM4 time out. Device reports rule 1 and the new settings. Settings kept in flash: stepMin 1.5, impactMin 18, walkerMargin 1.5, stepRef 8, gain ×2. Replay with exactly these: 3/3 falls, 3/3 jumps rejected. The far fall's peak (19.1) is only just above impactMin 18. Suggested: impactMin 6.
- impactMin set to 6 and stored in flash (2026-11-14), confirmed with !get.

## Calling after a confirmed fall (2026-11-14)

- `secrets.h` created locally (git-ignored) with the number and the SIM PIN. Neither goes into git or these notes.
- Modem task: switches the modem on at boot and, if it gets power later (rocker switched on after boot), retries once a minute. Enters `REZON_SIM_PIN` once per boot only (3 wrong tries = PUK). Logs SIM / registration state.
- Diagnostics: boot line "restart reason: …" (power-on, BROWNOUT, WATCHDOG, CRASH, …); the sampling task is on the task watchdog (a hang restarts the board instead of freezing).
- train.html: keeps reading through serial glitches, skips a bad line instead of stopping, shows "NO DATA" / "device lost".
- The "freeze" on a strong fall was a loose contact (the board lost power), fixed temporarily by Kaszti.
- **Power conflict:** the modem only gets 4.0 V with power bank + rocker ON, and the guide says rocker OFF while USB is in. Call test = power bank only, no laptop. Running both on stage needs a hardware decision (e.g. USB cable without VBUS); check the board before trying.
- Compiled, not flashed yet (Kaszti: "not yet").

**First call from Rezon (2026-11-14):** the modem never switched on because the SIM868 board's switch was on "USB" instead of "VBAT". With the 600 mAh Li-po in the board's battery socket (rocker off, ESP32 on laptop USB): PIN accepted from secrets.h, registered, CSQ 20, battery 3.99 V. `!test` ran ASK → WAIT → ANNOUNCE → dialling → INCALL; the phone rang, the call ended after ~28 s (hung up on the phone side), DONE → WATCH.
- New commands: `!pwr` (PWRKEY pulse now: it TOGGLES, so it switches a running modem off) and `!pwrhold [s]` (hold GPIO16 high to measure it; the pin reads itself back).
- Opening the serial port restarts the ESP32 but not the modem; the boot check sees it answering and sends no pulse.
- Li-po on the SIM board = modem independent of the rocker, so laptop + live page + calls work together (no 5 V conflict). The Li-po is not charged in this setup (the board charges only from the Pico's VBUS): check `!modem` → +CBC.

## Speaker, voice clips and Bluetooth (2026-11-14)

- Speaker chain works (I2S → PCM5102A → ZK-502M → speaker). The amp is on the power bank's 5 V line behind the rocker, so it is silent on laptop USB. `volume` is 100 % (stored); the rest is the ZK-502M knob.
- Start-up chime: two neutral notes ~1.5 s after power-up (`chime` setting, 1/0). Never the voice.
- Speaker test commands: `!play q|c`, `!tone [Hz] [s]`, `!stop` (no alarm, no call).
- Voice clips from the team's MP3s (`Minden_Rendben.mp3` → question, `Segitseget_Hivok.mp3` → calling) are in `firmware/rezon/clips.h`: 1.18 s and 1.39 s at 16 kHz. Regenerate with `firmware/tools/mkclips.js` (instructions in its header).
- Shaking the box does not trigger an alarm, by design (each shake counts as a step and lifts the level). Test with a 2 s button hold or a real fall.
- **Bluetooth LE link** (Nordic UART service, name REZON): every line goes to USB and BLE; samples travel as `B,<base64>` lines (20 × 3-byte samples, ~4 kB/s). Train page: "Bluetooth" button (recordings store them as D lines, so replay works). Live page: key B. Tested: connected, `!get` round-trips over BLE, no dropped bytes. Firmware is 749 kB (57 %).
- Stage setup now: power bank, rocker on (modem, amp, calls live), laptop pages over Bluetooth. No USB needed, so no 5 V conflict.
