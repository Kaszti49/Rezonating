---
type: research
kind: paper
status: read
relevance: high
url: "https://staff.itee.uq.edu.au/jaga/proceedings/percomworkshops2020/papers/p499-akiyama.pdf"
---
# Side of a step with two nearby sensors

**Takeaway for Rezonating:** the closest published setup to ours (two sensors 15 cm apart, one floor) also found that **arrival time fails** and that **energy differences learned from data** work. It decides the direction of a whole 5-second walk rather than one step, and it needs retraining when the sensor or the floor changes. That supports dropping "first" from the Locate rule, averaging over a walk, and testing on held-out sessions. It doesn't support exact positions.

## Akiyama et al., PerCom Workshops 2020 (read in full, extracted from the PDF)
- Two piezo sensors 15 cm apart; 15 cm was chosen in their tests as the smallest that kept accuracy.
- **Arrival time (TDoA) failed.** In their pilot the far sensor often fired **before** the near one, which they put down to the floor being made of different materials. Our data shows the same: "first" was usable in 6 % of the 1 m left steps in round 1.
- They use the energy of each sensor over 5 s, the **difference left minus right**, then LDA and a simple classifier. Direction = which end a walk parallel to the sensors started from.
- 4 people, 20 walks per direction. Accuracy:
  - random 75/25 split: best 88.9 % (linear SVM)
  - 10-fold: best 75.6 % (k-NN)
  - leave one person out: 75–90 % for three people over the six algorithms, **50–55 %** for person C, who changed the way they walked on purpose
- Stated limits: retraining is needed if the sensor position or the floor changes; only walking parallel to the pair was tested.

## Other sources
- **Continual person ID on two floors** (Dong and Noh, arXiv 2502.15632, fetched as HTML): four SM-24 geophones 2 m apart, 20 people, about 90 % for 10 people per floor. Floor differences dominate the variation. The split by day or session isn't described, and no baseline is given.
- **Energy-based localization** (Alajlouni, Virginia Tech 2017, the PDF text was searched): for 162 footsteps with many accelerometers, RMSE was 1.41 m along one axis and 0.35 m along the other. It argues that time of flight is inaccurate on dispersive floors.
- **Detection** (search summary only, not opened): a ground-vibration study reports STA/LTA F1 of about 0.74; adaptive thresholds are standard because fixed ones miss steps of varying strength.
- **Geophone coupling** (search summary only, not opened): a poorly coupled sensor rocks and shows a resonance inside the band of interest; a coupling resonance also depends on the mount and the mass. Relevant to the case that may rock.

## Not found
- A published left/right result from two geophones 12 cm apart in one case.
- Front/back separation with two sensors on one line.
- Comparison of STA/LTA with a percentile noise floor on footsteps.

## Sources
- https://staff.itee.uq.edu.au/jaga/proceedings/percomworkshops2020/papers/p499-akiyama.pdf
- https://arxiv.org/html/2502.15632v1
- https://vtechworks.lib.vt.edu/server/api/core/bitstreams/424736df-fedb-4348-ba2f-a6fc5305b0bd/content
- Related: [[Footstep direction with two geophones]], [[EXP-002 Locate page first real floor run]], [[D-027 Footstep-id tells the side of a step]]
