# Writing content for the study site

Everything the site teaches lives in `tools/study/web/content/` as plain JSON and Markdown. No build
step: edit, reload the browser.

| File | What |
| --- | --- |
| `curriculum.json` | Tracks and lesson list (id, code, title, minutes, outline). A lesson without files shows its outline. |
| `lessons/<id>.json` | Lesson data: title, goal, parts, predict, calc, quiz, cards, cases |
| `lessons/<id>.en.md`, `lessons/<id>.hu.md` | Lesson prose, one file per language |
| `glossary.json` | Hover terms (`[[id]]`), both languages |
| `parts.json` | The 18 parts: role, summary, facts, pins, 3D feature texts |
| `builds.json` | 3D assemblies and their steps |
| `cases.json` | Fault-finding cases |

The model `lessons/e02.*` is the reference lesson: copy its shape.

## Teaching style (chosen by Kaszti and Viktor, 2026-11-03)

1. **Bench-problem first.** Every lesson opens (`## @bench`) with a real situation from *our* rig: a
   measurement, a fault, a question the boss asked, a number from the vault. Short (2–4 sentences),
   ends with what the lesson will let you do.
2. **Three depth layers**, each a full path through the topic, not a continuation:
   - `## @intuition`: pictures and analogies, almost no formulas. Say where an analogy breaks.
   - `## @engineer`: formulas, worked with **our** numbers (3.3 V, 690 Ω, 1100 Ω bridge, gain 128,
     2 kSPS, 28.8 V/(m/s), −0.21 % clock …). Tables of our values.
   - `## @datasheet`: the real document: which datasheet, which table/parameter, what the limit means
     for us. Never invent a page or table number; name the section ("Absolute Maximum Ratings",
     "Pin Functions") instead if the page isn't known.
3. **Live diagrams** where a slider teaches more than a paragraph (`{{w:…}}`).
4. **Predict, then reveal** (`{{predict:N}}`): a question *before* the explanation, with tempting
   wrong options. The `why` explains every wrong option's mistake if possible.
5. **Calculate with our numbers** (`{{calc:N}}`), checked automatically.
6. **Fault cases** (`{{case:id}}`) link to `cases.json`.
7. **Flashcards**: 4–6 cards per lesson; short front, precise back.
8. **Glossary hover** on every key term the first time it appears in a layer: `[[term-id]]` or
   `[[term-id|shown text]]`. Part ids work too: `[[adc15]]`, `[[yzc133]]`.

Tone: plain, direct, second person, short sentences. No filler. Not the "usual AI explanation":
concrete, specific, and tied to the bench. Hungarian is written as Hungarian (not translated
word by word), with the English term in brackets the first time: `[[aliasing|átlapolódás]] (aliasing)`.

## Markdown extensions

| Syntax | Renders |
| --- | --- |
| `## @bench` / `## @intuition` / `## @engineer` / `## @datasheet` | section markers (required, in this order) |
| `### Heading` | heading inside a layer (don't use `##` inside a layer) |
| `[[id]]`, `[[id\|label]]` | glossary hover term (id from `glossary.json` or a part id) |
| `{{part:id}}` | chip linking to a 3D part |
| `{{w:widget key=value …}}` | live diagram (own line) |
| `{{predict:0}}`, `{{calc:1}}` | interactive block from the lesson JSON (own line, 0-based index) |
| `{{case:case-id}}` | button to a fault case (own line) |
| `$$ formula $$` | formula block (one line); or `$$` lines around several lines |
| `> text`, `> [!warn] text`, `> [!ok] text` | callouts (blue, clay, sage) |
| tables, lists, `**bold**`, `*italic*`, `` `code` ``, `[text](https://…)` | as usual |

Write formulas in plain Unicode: `V = I · R`, `fc = 1 / (2πRC)`, `20·log10(x)`, `µV`, `Ω`, `×`, `≈`, `²`.

## Live diagrams

| id | Shows | Arguments (all optional) |
| --- | --- | --- |
| `ohm` | battery + resistor, animated current, P | `v`, `r` |
| `divider` | divider with a load; our series 690 Ω and the boss's 220/470 Ω | `vin`, `r1`, `r2`, `rl`, `topo=series\|boss\|free` |
| `bridge` | YZC-133 full bridge → ADC range bar and code | `vex`, `kg`, `gain` |
| `rc` | RC low-pass Bode + waves, or step response | `mode=filter\|step`, `r`, `c`, `f` |
| `opamp` | non-inverting amplifier with bias and clipping | `rf`, `rg`, `vin`, `offset` |
| `clamp` | series R + clamp diodes vs ADS131M0x abs. max | `amp`, `r` |
| `power` | 3.3 V budget and AMS1117 heat | — |
| `sampling` | sampling, Nyquist, alias (HX711 / 1 k / 2 kSPS) | `f`, `fs`, `win` |
| `quantize` | bits, PGA gain, LSB, codes | `bits`, `gain`, `amp` (V) |
| `decimate` | FIR response, 2 kSPS → 1 kSPS folding | `f`, `taps` |
| `clock` | clock error → samples/hour (LTC6903 vs crystal) | `err` (%) |
| `geophone` | SM-24 response vs damping, output volts | `zeta`, `f`, `vel` (mm/s) |
| `spi` | SPI timing, modes, the CS-late bug | `byte=0xA5`, `master`, `device`, `bug=1` |
| `i2c` | pull-up × capacitance → rise time vs spec | `r`, `c`, `speed` |

Argument units are SI base units: ohms, farads (`c=100e-9` for 100 nF), hertz, volts (`amp=0.0004` for 400 µV); `i2c c` also accepts pF (`c=100`), `geophone vel` is mm/s, `clock err` is percent.

New diagrams go in `web/js/widgets/` and the registry `widgets/index.js`.

## Lesson JSON

```json
{
  "id": "e02", "minutes": 30,
  "title": {"en": "…", "hu": "…"},
  "goal":  {"en": "After this lesson you can …", "hu": "…"},
  "parts": ["yzc133", "passives"],
  "predict": [{"q": {…}, "options": [{…}, {…}, {…}], "answer": 2, "why": {…}}],
  "calc": [{"q": {…}, "answer": 1.844, "unit": "mA", "tol": 0.03, "hint": {…}, "solution": {…}}],
  "quiz": [{"q": {…}, "options": [{…}], "answer": 1, "why": {…}}],
  "cards": [{"id": "e02-c1", "front": {…}, "back": {…}}],
  "cases": ["case-680k"]
}
```

- Every text is `{"en": "…", "hu": "…"}` and may use the Markdown above.
- `calc.answer` is in `calc.unit`; the learner types only the number. `tol` is relative (0.03 = ±3 %).
- Card ids are `<lesson id>-c<n>`. Quiz: 3–5 questions; predict: 1–3; calc: 1–3.
- `parts`: ids from `parts.json`.

## Facts

Use only facts that are in the repo: `CLAUDE.md`, `tools/study/tutor_context.md`, the part notes in
`30 Hardware/Parts/`, `30 Hardware/Builds/`, `80 Decisions/`, `60 Research/`, daily notes, firmware
and ml code. General textbook physics and electronics are fine. If a datasheet value isn't in the
repo, write "check the datasheet" instead of a number. Never invent a measurement: say "calculated"
or "typical" when it isn't measured.
