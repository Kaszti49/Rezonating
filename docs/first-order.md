# First order

The minimum to build the first rig: one node recording two geophones to
microSD. About **€250 before VAT and shipping**. Prices checked on 2026-10-01
where a link is given; "approx." means estimated, check at checkout.

Run the free phone kill test (`docs/protocols/kill-test-phone.md`) before
ordering the geophones: they are 60% of the cost.

| # | Item | Qty | Price each | Where | Why |
| --- | --- | --- | --- | --- | --- |
| 1 | SparkFun SM-24 geophone (SEN-11744) | 2 | €78.95 excl. VAT | [Opencircuit](https://opencircuit.shop/product/geophone-sm-24-with-insulating-disc) (or [SparkFun](https://www.sparkfun.com/geophone-sm-24-with-insulating-disc.html), $69.95) | The sensor; 2 lets you compare positions |
| 2 | ESP32-S3-DEV-N16R8 dev board | 2 | 3,521 Ft net | [HESTORE](https://www.hestore.hu/prod_10048179.html) | Node + spare; must be N16R8 |
| 3 | TI ADS131M04IPWR (TSSOP-20) | 3 | $4.69 | [LCSC](https://www.lcsc.com/product-detail/C2862562.html); also check TME or Mouser for an EU invoice | The ADC; spares for soldering mistakes |
| 4 | TSSOP-20 → DIP-20 adapter board | 3 | ~€2–5 approx. | Electrokit, Mikroe or HESTORE | Puts the ADC on a breadboard |
| 5 | 8.192 MHz 3.3 V CMOS oscillator | 2 | ~€2–5 approx. | TME, Mouser or DigiKey | Required ADC clock |
| 6 | microSD SPI breakout board | 1 | ~€3 approx. | HESTORE | Recording |
| 7 | microSD card, high endurance, 32–64 GB | 1 | ~€12 approx. | Any shop | Survives constant writing |
| 8 | Breadboard + jumper wire kit | 1 | ~€10 approx. | HESTORE | Skip if the school has one |
| 9 | Capacitors (100 nF, 10 µF), resistors (10 Ω, 1 kΩ) | 1 lot | ~€8 approx. | HESTORE | Supply filtering, geophone shunt |
| 10 | Solder flux pen | 1 | ~€8 approx. | HESTORE | For the 0.65 mm-pitch ADC; skip if you have one |

**Borrow, don't buy:** crash mat and a 20–40 kg sandbag (PE department),
oscilloscope, soldering station, multimeter (school lab).

## Second order, after the first rig records clean steps

| Item | Qty | Why |
| --- | --- | --- |
| SM-24 geophone | 2 | Four sensors for localization and better person ID |
| ADXL355 breakout board | 1 | Appliance pack |
| AT24C02 EEPROM | 6 | Head ID chips |
| TCA9548A I2C mux board | 1 | Same EEPROM address on every port |
| RJ45 jack breakout | 6 | Head ports |
| Cat5e cable | 20 m | Head cables |
