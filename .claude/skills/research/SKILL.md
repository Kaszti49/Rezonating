---
name: research
description: Playbook for answering a question with sources (parts, EU suppliers and prices, datasheet values, papers, datasets, competitor products) and writing research notes in 60 Research. Load when an answer needs sources or feeds an order or a decision.
---

# Playbook: research

## How
1. Primary sources first: the manufacturer's datasheet or product page, the paper itself, the
   dataset's own page. Distributors (TME, Mouser, LCSC, Farnell, DigiKey) for price and stock.
2. Every number gets a source; prices and stock also get the date checked. Prices in EUR with VAT
   status and the shipping country.
3. Mark inferences "(inferred)". If two sources disagree, show both. Not found → say "not found".
4. Quote at most one short sentence per source; summarise in your own words.

## Note
New notes in `60 Research/` with the research frontmatter from `vault-conventions`, then `# Title`,
a one-paragraph **Takeaway for Rezonating**, then the details. Changes other notes need (parts,
work, decisions): list them and make them, or ask if they touch a decision.

## Finish
Research that feeds an order or a decision goes through the `verify` playbook: re-open 1–3 cited
sources and confirm the numbers are really there. Money, hardware and decisions: ask a person.
