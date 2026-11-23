---
type: research
kind: article
status: read
relevance: high
url: "https://arxiv.org/html/2212.03377"
---
# Footstep direction with two geophones

**Takeaway for Rezonating:** with the two SM-24s 123 mm apart in [[OTIO case v1]], one node can give the **side** reliably, a **bearing with a front/back mirror** (θ or 180° − θ) once the floor's wave speed is calibrated, and only a **rough distance band** from loudness. It can't give a true x/y dot. Published systems that place a step on the floor use several sensors spread metres apart and still miss by 0.4–0.8 m. This isn't echolocation either: nothing is emitted. The step is the "ping", and we measure *when* and *how loud* it arrives at each geophone. Everything marked (inferred) gets tested on the real floor on 2026-11-24.

## The math

Symbols: d = 0.123 m between geophones, f_s = 1996.1 Hz measured (T_s ≈ 0.50 ms), c = wave speed in the floor, θ = angle from the perpendicular to the line joining the geophones.

**1. Time difference → bearing.** A step far away compared with d reaches the nearer geophone first by
Δt = d · sin θ / c, so θ = asin(c · Δt / d).
- The floor's wave speed is 30–300 m/s, and 70–130 m/s around a single spot (GaitVibe+). That gives Δt_max = d / c ≈ 0.4 ms (300 m/s) to 4.1 ms (30 m/s), which is **0.8 to 8 samples**. At 100 m/s it's 1.2 ms, about 2.5 samples.
- Getting Δt finer than one sample: cross-correlate the two channels (GCC-PHAT), then fit a parabola through the peak. That reaches about 0.1 sample at good SNR (inferred). At c = 100 m/s and broadside, 0.1 sample (50 µs) works out to ≈ 2.3° (dθ = c · dτ / (d · cos θ)). The error grows towards the axis of the pair.
- **The error that matters is c, not the timing.** A 30 % error in c turns a true 30° into about 40° (inferred). Fix: calibrate c on the spot with one step at a known bearing (90°, 1 m to the side): c = d / Δt.
- Dispersion: floors bend, so high frequencies run faster, and the waveform changes shape between sensors (Mirshekari et al., cited in GaitVibe+). Across 123 mm that change is small (inferred), so band-limited cross-correlation should hold up.

**2. Front/back mirror.** Two sensors on a line can't separate θ from 180° − θ. Any view has to draw both candidates, or say "left/right" only. Removing the mirror takes a third sensor off the line. The ADC 15 Click has only 2 channels; the ADS131M04 on our own PCB will have 4.

**3. Distance.** At 1 m, the geometry gives nothing: the wavefront's curvature across 123 mm is about 2 mm of path, ~20 µs at 100 m/s, buried in the noise (inferred). Distance can only come from loudness:
A ≈ F · r^(−n) · e^(−α r), where F is the strength of the step, n ≈ 0.5–1 for waves spreading over a surface (inferred), and α grows with frequency.
- The catch is F. It changes with the person, the shoe, the gait and the floor. Energy methods work around it by using many sensors (Alajlouni, VT 2017: energy-based beats time of flight on dispersive floors). With one node, F and r can't be separated.
- What one node can do (inferred): after a calibration step at 1 m, show a band (near < 1 m, 1–2 m, far > 2 m). A tracked walker gives a trend: getting louder means approaching. A second cue that doesn't depend on F: high frequencies die faster, so the high-to-low band ratio falls with distance. It does depend on the shoe.

**4. Loudness ratio between the two geophones** (helps with side): (r₁/r₂)^n. At 1 m, on the axis of the pair: 1.06 (n = 0.5) to 1.13 (n = 1). At 2 m: about 1.03. Each SM-24 is ±2.5 % in sensitivity (datasheet), so the two channels have to be gain-matched once. After that the ratio supports the timing within ~1 m.

## A caveat specific to our case (needs checking)
Both geophones sit in one rigid PLA case. The floor may move the case as a whole: it can shift up and down, or rock. Rocking moves the two cups in **opposite** directions. So the −0.99 correlation seen on 2026-11-23 might be rocking, not reversed wiring.
- **Test:** drop a coin on the centre of the lid. That doesn't rock the case, so both channels should have the same sign if the wiring is right.
- If the case does rock, the rocking itself points at the source (tilt towards the step) and could be the strongest direction cue (inferred).

## What other systems reach
| System | Sensors | Result |
| --- | --- | --- |
| Physics-based TDoA / energy methods in real buildings | several, spread out | 0.4–0.8 m average error (Wang, Sarlo, Li 2026) |
| Mirshekari TDoA baseline in GaitVibe+ | geophones 2 m apart on a 7 m structure | 0.67 m average (from a summary, not checked verbatim) |
| Poston, Goodwin Hall (VT) | 200+ accelerometers on girders | 0.6 m RMSE (slides) |
| Reservoir computing, Goodwin Hall | 11–12 accelerometers, 1024 Hz | one floor sensor: "very large" error (from a summary) |
| Single 3-component geophone (seismology) | 1 triaxial | back-azimuth from particle-motion polarisation; no footstep use found |

Footstep energy sits mostly at 10–50 Hz; GaitVibe+ detects arrivals in 150–200 Hz. Our SM-24 is flat from 10 Hz (±2.5 %) up to its spurious resonance above 240 Hz, so 10–200 Hz is our band.

## Not found
- Mirshekari's and Alajlouni's own error figures and attenuation formulas. The PDFs couldn't be read as text here.
- Any published footstep direction from one compact node.

## Sources
- GaitVibe+ (Dong, Liu, Noh), arXiv 2212.03377: wave speed 30–300 m/s, the 10–50 Hz band, an average error of about 0.4 m for TDoA methods. https://arxiv.org/html/2212.03377
- Wang, Sarlo, Li, "Can a Building Work as a Reservoir", arXiv 2603.04610: 0.4–0.8 m typical, 1024 Hz. https://arxiv.org/html/2603.04610v1
- Alajlouni, Energy-based footstep localization, Virginia Tech 2017 (abstract). https://vtechworks.lib.vt.edu/items/26aa0d4d-0e72-4294-929f-e2be69f55ce9
- Poston, I-LoViT slides. https://sigport.org/sites/all/modules/pubdlcnt/pubdlcnt.php?fid=1078
- Triaxial geophone direction of arrival. https://www.journals.pan.pl//Content/87316/PDF/08.pdf
- SM-24 datasheet: 10 Hz ±2.5 %, 28.8 V/(m/s) ±2.5 %, spurious > 240 Hz. https://proto-pic.co.uk/content/SM-24.pdf
- Related: [[SM-24 geophone]], [[FootprintID paper]], [[D-027 Footstep-id tells the side of a step]]
