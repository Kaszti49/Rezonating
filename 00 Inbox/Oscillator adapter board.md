---
type: inbox
created: 2026-10-06
---
> [!info] Not needed (2026-10-06)
> The team won't breadboard: boards are wired directly, and the ADC may become a ready-made board (ADC 15 Click, being checked). Kept as a record.

# Oscillator adapter board

**Why we need it:** The [[8.192 MHz oscillator]] (QTM325) is a 3.2 × 2.5 mm leadless part that can't go on a breadboard by itself. This board takes 7050, 5032 and 3225 oscillators and brings them out to pins.

## Notes
- Listing (2026-10-06): "Convertor Board Active Crystal Oscillator Adapter Plate, suitable for 7050 5032 3225 and SMD packages", sold as 1 or 10 pieces. Check the price, the 2.54 mm pin pitch and the pin labels at checkout. Buy the 10-pack: two are needed and spares help with practice.
- Alternative: the open-source KiCad DIP14 oscillator adapter (github.com/matze79/DIP14-OSC-Adapter, MIT licence, has a 3225 footprint). It could go on our own PCB order later.
- Solder the oscillator with flux and the iron tip on each pad's exposed edge, or with hot air. Before powering up, check with a multimeter that VDD isn't shorted to GND.
- Research: [[ORD-001 open checks]].
