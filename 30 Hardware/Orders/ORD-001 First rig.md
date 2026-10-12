---
type: order
id: ORD-001
status: draft
date: 2026-10-06
ordered:
delivered:
supplier: several
paid_by: company
---
# ORD-001 First rig

The minimum to build the first rig: one node recording two geophones (through the [[ADC 15 Click board]]) and one ADXL355 accelerometer (on I2C) to microSD. Boards are wired directly; no breadboard ([[D-015 Prototype ADC on ADC 15 Click]]). Parts already in the lab (oscillator, breadboard kit, microSD breakout and card) are not on this order. The phone kill test was dropped on 2026-10-05.

```dataviewjs
await dv.view("90 Meta/Views/rz", {section: "orderLines"})
```

**Borrow, don't buy:** crash mat, 20–40 kg sandbag, oscilloscope, soldering station, multimeter.

## Notes
- Prices with a link were checked on 2026-10-01; the rest are estimates. ADC, oscillator and ADXL355 rechecked 2026-10-06.
- **2026-10-06:** ADC changed to the ADC 15 Click from Farnell (Kaszti, after talking with the boss); the TSSOP and oscillator adapters are no longer needed. ADXL355 I²C at 2000 Hz confirmed by Kaszti. [[D-015 Prototype ADC on ADC 15 Click]] accepted.
