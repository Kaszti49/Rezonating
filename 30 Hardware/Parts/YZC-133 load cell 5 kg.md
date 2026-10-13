---
type: part
status: have
category: sensor
qty: 1
price_eur:
price_note: Bought by the boss; price unknown
supplier:
url: "https://elektronicavoorjou.nl/en/?p=39155458"
datasheet:
order:
---
# YZC-133 load cell 5 kg

**Why we have it:** The boss bought it ("SP YZC-133-SCL-5 H25/6160741"). It is a 5 kg aluminium parallel-beam weighing cell, a strain-gauge Wheatstone bridge, **not a geophone**. On the rig it is a known test and timing signal ([First rig bench guide](https://claude.ai/code/artifact/53c286fe-182d-4bf3-91f6-4778f18e5648)).

![[YZC-133_load_cell.jpg]]

## Ports
- **Wires:** 4, red, black, green, white. The ends are thin and stripped short: tin them before using screw terminals.
- **Usual meaning:** red E+, black E−, green S+ (A+), white S− (A−). Shop listings only; confirm by resistance. The E+/E− pair reads highest, about 1070–1120 Ω. The S+/S− pair reads about 1000 Ω.
- **Body:** "5" stamped on the side. Two threaded holes at each end: bolt one end, load the other.

## Specs (shop listings, not a manufacturer datasheet)
- Rated output 1.0 ± 0.1 mV/V
- Zero balance ± 0.1 mV/V
- Input about 1066 Ω, output about 1000 Ω
- Excitation 3–10 V per listings. At 2.0 V it gives about 0.4 mV per kg.

## Notes
- 2026-10-13: logged from Kaszti's photos. The thread size of the holes was not measured.
