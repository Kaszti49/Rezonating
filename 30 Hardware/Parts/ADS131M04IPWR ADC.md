---
type: part
status: later
category: adc
qty: 3
price_eur: 5.91
price_note: "DigiKey reference price EUR 5.91 each net (4.55 at 10), but DigiKey AT and DE have 0 in stock until 2027-01-04. LCSC has 2,039 in stock at USD 4.69 (4.18 at 10), checked 2026-10-06"
supplier: "LCSC (ships from China; only in-stock source seen)"
url: "https://www.lcsc.com/product-detail/C2862562.html"
datasheet: "https://www.ti.com/lit/ds/symlink/ads131m04.pdf"
order:
---
# ADS131M04IPWR ADC

**Why we need it:** 4-channel simultaneous 24-bit ADC. Three, because hand-soldering 0.65 mm pitch can fail.

## Notes
- **Stock, checked 2026-10-06** (verifier and researcher):
  - DigiKey AT and DE: **0 in stock**, 2,000 expected 2027-01-04, lead time 20 weeks. EUR 5.91 / 4.55 (10) / 3.83 (100) net.
  - LCSC: **2,039 in stock**, USD 4.69 / 4.18 (10) / 3.85 (30). Ships from China, so import VAT and customs apply. Shipping fee, delivery time and a company invoice are not checked yet (check at checkout).
  - Mouser (de, com, eu, at), Farnell and TME (HTTP 403) did not load for the agents. RS, Conrad and Reichelt were not checked.
  - Earlier readings of 4, 82 and 3.4K in stock (2026-10-05) are superseded.
- **Decision (Kaszti, 2026-10-06):** order from LCSC. Chinese suppliers are fine; the team orders from them regularly.
- **Fallback modules:** no ready-made ADS131M04 breakout found. Only the TI ADS131M04EVM (with a PHI controller board) exists, at EUR 257.33 net at DigiKey AT: too expensive for the EUR 500 budget.
- Package TSSOP-20, 0.65 mm pitch; goes on the [[TSSOP-20 to DIP-20 adapter]].
- **2026-10-06:** not in ORD-001 any more. The prototype uses the [[ADC 15 Click board]] (ADS131M02, 2 channels), see [[D-015 Prototype ADC on ADC 15 Click]]. The ADS131M04 returns with our own PCB.
