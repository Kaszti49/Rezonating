---
type: project
---
# Glossary

| Term | Meaning |
| --- | --- |
| Node | The ESP32-S3 board with the ADC, storage and head ports |
| Head | A sensor on a cable: geophone, accelerometer or piezo, with an ID chip |
| Pack | Software that detects one thing (`footstep-id`, `fall`, `appliance`): manifest + model + thresholds |
| Engine | Built-in algorithm a pack configures: classifier, anomaly, localizer, rule |
| Sidecar | JSON file next to each WAV recording, describing the setup and labels |
| STA/LTA | Short-term / long-term average ratio: the standard way to detect an event in a signal |
| Kill test | The cheapest test that could prove an idea wrong |
| Tier 1 / 2 / 3 | Load-bearing / replaceable / throwaway |
| PSRAM | Extra RAM on the ESP32-S3 module (8 MB on N16R8) |
| OTA | Over-the-air update (firmware or packs over Wi-Fi) |
