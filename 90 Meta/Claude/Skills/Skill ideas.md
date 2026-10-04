---
type: project
---
# Skill ideas

Project skills Claude could get once a routine repeats at least three times. Don't build one before then.

| Skill | What it would do | Build when |
| --- | --- | --- |
| `log-experiment` | Turn raw results into an `EXP-###` note, update the pack's `best_value` | After the 3rd experiment |
| `weekly-review` | Pre-fill the weekly note: done, slipped, overdue, budget | After 3 weekly meetings |
| `order-update` | Sync part and order statuses from an order confirmation | After the 2nd order |

## Built (in `.claude/skills/`)
| Skill | What it does |
| --- | --- |
| `vault-conventions` | Exact properties for every note type (used by vault-keeper) |
| `esp-idf-build-flash` | Build, size, flash and read build errors on ESP-IDF v6 |
| `ml-training` | Splits, features shared with firmware, test vectors, logging results |
| `wrap-up` | End-of-session protocol (`/wrap-up`) |
| `retro` | Weekly agent improvement round (`/retro`) |
| `find-skills` | Find and vet third-party skills; install only after a yes |

The property checker that `vault-lint` would have been is now `.claude/scripts/vault_schema.py`.
