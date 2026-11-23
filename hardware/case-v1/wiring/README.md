# Wiring guide, OTIO node

The source of `../Rezon_Wiring_Guide_OTIO.html`: a step-by-step 3D soldering guide for the
ESP32-S3-DevKitC-1, the ADC 15 Click and two SM-24 geophones on the full 150 × 90 mm perfboard
(33 columns × 54 rows), powered over USB-C, inside case v1. It is the hackathon guide
(`../../hackathon/wiring_source/`) stripped of the SIM868, audio, power bank, step-down and lid board.

```bash
python gen.py                                  # holes, pins, nets, routes -> out/data.json
python build.py ../Rezon_Wiring_Guide_OTIO.html
```

- **`gen.py`** is the single source of truth. It holds the pin positions, the links (routed on the
  solder side, never through the Ø12 mm keep-out at the board centre) and the geophone wires.
  `case_v1.py` places its ESP32-S3 and Click dummies from the same holes.
- **`template.html`** draws the board, the modules, the case and the steps. It loads three.js from
  cdnjs, so the page needs internet.
- **Hole names:** the board prints A–Z, A–Z, A, B along the long side. The guide calls the second
  round AA–AZ and the third BA, BB.
- **Pin map** (the hackathon firmware's `rezon.ino`): SCK 12, MISO 13, MOSI 14, CS 11, CS2 9,
  DRDY 10, RST 8.
