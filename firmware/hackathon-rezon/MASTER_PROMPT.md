# REZON firmware: master prompt


I'm Kaszti. You are writing the software that runs on our fall detector for the HARMAN Hackathon final. The build window is about 17 hours and the stage demo is one attempt, so I need working and testable before clever. Read this fully, then read the files I list, then show me your plan before writing code.

**1. What the device is**

A geophone on the floor feeds a 24-bit ADC. An ESP32-S3 reads it 1000 times a second, decides whether someone fell, asks "Mari néni, jól van?" through a speaker, and phones for help through a 2G modem if nobody presses the "I'm OK" button.

Read these first. They are the ground truth for hardware and for what already works:
- `Rezon_How_It_Works.pdf` and `explainer_source/template.html`: the whole system, pin map, maths.
- `practice/geophone_test/geophone_test.ino`: working ADC driver (ADS131M02 + LTC6903 clock). Reuse it.
- `practice/sim868_call_test/sim868_call_test.ino`: working modem code. Reuse it.
- `practice/geo_viz/index.html`: the detection logic we tuned today. Port its filters, hum canceller, envelope and thresholds; do not reinvent them.
- `uploads/geophone_2026-11-12T*.csv`: four real recordings at 1000 samples/s.
- `wiring_source/gen.py`: the final pin map. If it disagrees with this prompt, the wiring file wins; tell me.

Final pins (ESP32-S3): SPI SCK 12, MISO 13, MOSI 14, ADC CS 11, clock-chip CS 9, DRDY 10, ADC reset 8. I²S BCK 4, LCK 5, DIN 6. Button 7 (low = pressed). LED data 15. Modem PWRKEY 16, TX 17, RX 18. Battery ÷ 2 on GPIO 1. The practice sketches use a classic ESP32 with different pins.

**2. The part I care about most: the detection logic**

I want it built from maths and feature vectors, not a black box. Three things must hold:
- A fall is detected even while several people are walking.
- A person lying on the floor and moving is never counted as walking.
- People who were already walking when the fall happened can never cancel the alarm.

Build it in these layers.

*Layer 1, signal.* Port from the tuning tool: offset removal, impact path 10–45 Hz, step path 18–60 Hz with the adaptive hum canceller, 15 ms envelopes, background follower. Convert counts to mm/s with gain 4 and 20.9 V per m/s.

*Layer 2, events.* Cut the stream into events. Start when the 50 ms variance exceeds 3× the background level, end when it falls under 1.5× (this is how the University of Georgia system does it; compare it with our current 60 %-of-peak rule on the recordings and keep whichever segments better). Keep the last 2 s of both paths in a ring buffer so an event's samples are available when it ends.

*Layer 3, feature vector per event.* Compute at least: log peak, log energy, duration, number of sub-impacts (envelope peaks at least 40 % of the maximum and 80 ms apart), rise time, decay time to 30 %, low-band to high-band energy ratio (about 10–20 Hz against 20–60 Hz), spectral centroid, and the peak relative to the typical step peak of the walkers currently tracked. Also build a **signature vector** that is normalised by the event's energy so distance does not change it: duration, centroid, band ratio, rise, decay and an 8-point envelope shape.

*Layer 4, fall score.* Fall score = weights · features + bias. Researchers at Shenzhen University found a fall is two or more impacts in a row (knee then hands, or hip then hands), longer and more energetic than a step; the features above are chosen to capture exactly that. Hard gates apply whatever the weights say: the peak must pass the impact minimum, and the peak must clearly exceed what the tracked walkers produce, so two people stepping at the same instant is not a fall.

*Layer 5, walker tracks.* Keep up to four tracks. Each has a step period, the time of its last step, a running-average signature and a typical amplitude. A new step joins the track where both the timing fits (within about 25 % of the expected moment) and the signature matches (cosine similarity); otherwise it may start a new track. A track needs three steady steps to be confirmed and expires after about 2.5 periods of silence.

*Layer 6, after a fall-shaped event.* Ignore the first 1.2 s as floor ringing, but extrapolate the existing tracks through it. Then classify everything that follows:
- A step that continues a track which was running before the impact and never broke rhythm: **bystander**. It never cancels.
- An event with no rhythm, or with a floor-contact signature (longer, lower-frequency, irregular): **movement on the floor**. It never cancels. Log it.
- A **new** confirmed track that begins after the impact, or the resumption of a track that stopped at the impact, with four steady steps: **got up**. This cancels.
- The button cancels at any time.

*Weights.* Write a small laptop script that reads labelled events, fits the weights with regularised logistic regression, checks them by leaving one recording out, and writes a header file. Fix the sign of each weight to what physics says (more energy, more impacts and longer duration can only raise the score). Our recordings have no labels in them: list every candidate event with its time and peak and ask me to label them. We will record more on the real stage floor. If there is too little data to fit, use hand-set weights and say so plainly.

Be honest about limits. One sensor cannot always separate two people; where the logic is guessing, log it and tell me.

**3. Test before flashing**

The detection core must be portable C++ with no Arduino includes, so the same files compile on the laptop. Build a replay tool that feeds the four CSV recordings through the core and prints every event, its features, its track and the decision. Check whether a C++ compiler is installed before you rely on one; ask me before installing anything. Then build synthetic tests by mixing recordings: add a walking segment on top of a fall segment at several offsets, to prove a fall is found under other people's steps and that bystanders do not cancel it. Show me the numbers: falls found, false alarms, steps assigned to the right track.

**4. The rest of the firmware**

- **Sampling never stalls.** The ADC read and the detection core run in their own high-priority task. Audio and modem work must not block it.
- **Alarm sequence.** Green: watching. Fall detected: amber, play the question. Wait for the button. No press: red, dial. Keep every time in one config struct with two profiles: *home* (5 s to get up, then ask, 10 s for the button) and *stage* (ask immediately, 3 s for the button).
- **Audio.** Convert the clip to 16-bit mono with a script and store it in flash. Ask me which file to use. Keep the level about 21 dB below full scale; the amplifier's fixed gain would otherwise overdrive the 1 W speaker.
- **Modem.** Power it at boot, wait for registration, keep it ready. Check SIM, signal and registration, and show a clear LED pattern if it is not ready. Dial with `ATD…;`. If the call fails, retry once.
- **The phone number never goes in git.** This repository is public. Put it in a header that is git-ignored and give me a template file.
- **Calibration on the real floor.** A serial command runs a short routine: 30 s of quiet, ten steps, three test impacts. It sets the thresholds and stores them in flash. The stage floor is unknown until we stand on it.
- **Live view.** Keep the serial output compatible with `practice/geo_viz` and add event lines, so we can watch decisions live while tuning.
- **Panic by hand.** Holding the button for 2 s starts the alarm sequence. Tell me if you think this is a bad idea.
- **Battery.** Read GPIO 1, warn on the LED below about 3.5 V.

**5. How we work**

- Phases, and stop for my OK after each: (0) read everything and show the plan; (1) detection core and replay results; (2) hardware bring-up on the S3; (3) alarm sequence end to end; (4) calibration and stage profile.
- Ask before installing tools or libraries. Prefer what the ESP32 Arduino core already has.
- Code goes in `firmware/`. Do not touch the film project or `C:\Work\Projects\Enterpartner\Rezonating`.
- Do not commit or push unless I ask.
- Log decisions and open questions in `NOTES.md`.
- Report results as they are. If a test fails or you skipped something, say it.
- If anything here is unclear or contradicts the files, ask me before guessing.
