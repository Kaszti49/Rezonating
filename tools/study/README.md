# Rezonating study site

A local learning site for Kaszti and Viktor: how the Rezonating system works, and electronics from
zero up to designing our own PCB. It is built on our own parts and bench measurements. It replaces
`docs/study-guide.html`.

```bash
python tools/study/serve.py          # http://127.0.0.1:8790, opens the browser
python tools/study/serve.py --port 8791 --no-browser
```

Python 3.10+ standard library only. The browser loads Three.js and the fonts from a CDN, so the 3D
views need internet. So does the tutor.

## What's in it

| Section | What you do |
| --- | --- |
| **How the system works** (S01–S08) | the chain from floor vibration to a pack's decision |
| **Electronics, zero to PCB** (E01–E20) | charge and Ohm's law up to mixed-signal PCB layout |
| **Parts in 3D** | all 18 parts of `30 Hardware/Parts`: rotate, explode, hover every pin, dimensions |
| **Build it** | step-by-step 3D assembly of the bench rig, the Year-1 node (S3 pins are a *proposal*) and the HX711 rig |
| **Fault cases** | real bench faults: choose measurements, then diagnose |
| **Flashcards** | spaced repetition. Cards from each lesson you open, plus the terms you looked up |
| **Glossary** | every hover term in both languages |

Each lesson follows the teaching style the two of you chose on 2026-11-03:
- a **bench problem** first;
- **three depth layers** (Intuition / Engineer / Datasheet);
- **live diagrams**;
- **predict, then reveal**;
- **calculations with our numbers**;
- a quiz and cards.

EN/HU switch at the top.

## Claude tutor

The **Ask Claude** panel and the "Ask Claude for more" button on hover terms run the Claude Code CLI on
*this* machine with *your* subscription: `claude -p`, no tools, no project files, from an empty
temporary folder. The current page is sent as context.

| Mode | Model | For |
| --- | --- | --- |
| Quick | `haiku` | hover terms, short definitions |
| Tutor (default) | `sonnet`, effort medium | questions about the lesson |
| Deep | `opus`, effort high | long or hard questions (uses more of the plan) |

`claude` must be on PATH and logged in (`claude` once, interactively). The persona and project facts
it gets are in `tutor_context.md`: update it when the bench changes. The server listens on 127.0.0.1
only and refuses API calls from other web pages.

## Progress in Obsidian

Choose **Kaszti** or **Viktor** at the top. The site writes `10 Project/Study/<Name>.md`:
- properties for lessons done, quiz average, cards known and due, cases solved and parts studied;
- a lesson table;
- recent activity;
- the full state as a JSON block at the end.

`90 Meta/Bases/Study.base` shows both of you side by side, and is embedded in each note. Obsidian
Git syncs the notes between machines like any other note. Don't edit them by hand, and commit them
in vault commits, not code commits.

## Changing content

All content is JSON + Markdown in `web/content/`. See `CONTENT.md`. No build step: edit and reload.

## Files

```
serve.py            server: static files, /api/ask (claude -p, SSE), /api/progress/<person>
tutor_context.md    system prompt for the tutor
CONTENT.md          how to write lessons, cases, glossary, parts
tests/              pytest for the server
web/index.html      shell (Three.js through an import map)
web/css/study.css   design: light, low-saturation, dotted engineering paper
web/js/             app shell, views, Markdown renderer, glossary hover, progress, widgets/, three/
web/content/        curriculum, lessons, glossary, parts, builds, cases
```

## Known limits

- Sizes marked **≈** in the 3D views are typical or estimated: the PDFs weren't readable when the
  models were made (`60 Research/Study site part geometry.md`). Measure with calipers and update
  `web/js/three/parts3d.js` and `parts.json`.
- The EVAL-ADXL355Z header pin order is estimated; the signal names are verified.
- The ADS131M02 (Click) pinout isn't modelled; the ADS131M04 pinout is (TI Table 5-1).
