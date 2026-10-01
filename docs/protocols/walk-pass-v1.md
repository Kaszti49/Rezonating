# Protocol: walk-pass-v1

Recording protocol for the `footstep-id` pack. The sidecar's `protocol` field
must say `walk-pass-v1`.

## Before

- Written consent from everyone recorded. Assign each a pseudonym (P1, P2, …);
  the name list stays off the repo.
- Sensor positions measured in metres and written into the sidecar.
- 60 s of silence recorded at the start of every session.

## Passes per person, per floor

| Pace | Shoes | Passes |
| --- | --- | --- |
| Normal | On | 50 |
| Normal | Off | 20 |
| Slow | On | 10 |
| Fast | On | 10 |

Each pass: walk a marked 4 m line past the sensors, stop, wait 3 s. Mark start
and end times live (phone button or spoken marks), never afterwards from memory.

## Rules

- At least two floor types across the dataset.
- Never test and train on the same day's recordings: evaluation splits by
  session.
