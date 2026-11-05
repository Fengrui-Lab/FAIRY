# Soybean disease and maize water stress

Registered ID: `scenario_two_farm_soybean_maize_disease_water`.

This scenario composes existing repository mechanisms into a new full-season
reference. It does not replace either source scenario. It requires the legacy
backend, uses no Agent/LLM, and keeps observation results separate from simulation
truth. The maize cultivar is a reduced, uncalibrated model.

## Plot and crop configuration

| Setting | farm plot A | farm plot B |
|---|---|---|
| Internal ID | `soybean_field` | `maize_field` |
| Crop / cultivar | soybean / HEINONG84 | maize / MAIZE_EARLY_2026 |
| Ridges and length | 64 × 268 m | 64 × 268 m |
| Ridge width / rows | 1.1 m / two | 0.65 m / one |
| Spacing / sowing depth | 8 cm / 4 cm | 25 cm / 5 cm |
| Planted area | 1.88672 ha | 1.11488 ha |
| Seed demand | 428800 | 68608 |
| Approximate planting density | 22.73 plants/m² | 6.15 plants/m² |
| Implements | soybean_planter, harvester | maize_planter, maize_header |
| Base / topdress product | 200 kg / 128 kg | 200 kg / 384 kg |
| Seasonal fertilizer product cap | 400 kg | 650 kg |
| Seasonal water cap | 20 field-equivalent mm | 30 field-equivalent mm |
| Harvest requirement | R8, grain moisture ≤18% | R6, grain moisture ≤30% |
| Storage moisture limit | ≤13.5%; reference target 13% | ≤14% |

Both plots share regional weather, the simulation clock, Warehouse, Tractor,
Mavic3M, Matrice4T and Robot0. Sensors and irrigation are bound separately.
Two 64-ridge plots do not have equal areas. Fertilizer values are product mass,
not elemental nitrogen. Grain batches retain their crop, cultivar and origin.

## Source traceability

The mixed-crop base is
`fairy/scenarios/two_farm/scenario_two_farm_maize_soybean_full_season.py`.
Its crop geometry, seed accounting, equipment, nutrition, maturity, drying and
batch provenance are reused. The new file explicitly owns its English briefing,
added actions, schedule changes and acceptance checks.

The anomaly source is
`fairy/scenarios/two_farm/scenario_two_farm_full_season_hn84_disease_water.py`:

- The same seed-1628 regional climate, four June 14–17 rain events of 18 mm each,
  and August 1–16 dry spell are retained. Both plots receive the same weather.
- The source's forced profile outbreaks are removed. Soybean ridges 20–39 start
  with latent disease pressure 0.20, versus 0.02 elsewhere. Disease then evolves
  through the existing engine; it is not injected on the treatment date.
- Deep black-soil parameters and lower-water-holding parameters are copied
  unchanged. The latter move from the source's second soybean plot to maize
  ridges 20–39. This crop assignment is a new integration, independently tested.
- Disease management retains multispectral localization, ground samples 28–31
  and 32–35, two ten-ridge fungicide passes at 3.8 L/ridge, 76 L total, and a
  seven-day follow-up. Shared chemical stock is the source's 320 L.
- Water management retains two week-separated 4-hour local irrigations
  (20 mm/ridge), immediate surface observations and next-day soil/crop rechecks.
  This replaces the mixed base's whole-field irrigation. Total use is
  2 × 20 ridges × 20 mm / 64 = 12.5 field-equivalent mm, all on maize.

No new biological recovery rule, weather magnitude, chemical dose or yield
assignment is introduced. The new integration is not claimed to inherit the
source scenarios' verification results.

## Verified reference chronology

The start remains May 15 from the mixed-crop base. The source's management
windows are reached by tool execution and explicit shared-clock waits.

| Date in 2026 | Reference operation |
|---|---|
| May 26 / June 1 | Early dry-weather survey / actual emergence revisit |
| July 20 | Soybean diagnosis and targeted fungicide |
| July 27 | Same-sample disease follow-up |
| August 2 / 3 | First maize irrigation / next-day recheck |
| August 9 / 10 | Reassessment, second irrigation / next-day recheck |
| September 17 | Soybean harvest, drying and storage |
| October 18 | Maize harvest, drying and storage |

Maize is observed in its own R2_BLISTER/R3_MILK stages during the water branch;
soybean stage labels are not reused for maize. September 10 soybean grain was
still above 18%, and October 17 was rainy; the integration waits for valid
conditions without changing harvest gates or overriding weather.

The Oracle is a fixed reference for this synthetic forcing. Other weather,
crop configurations or schedules require a new execution and verification.

## Acceptance and tests

The source disease/water scenario has no task validator. This new scene checks
both full seasons and the actual intervention evidence: correct targets/doses,
ground diagnosis before fungicide, same-sample follow-up, recent soil/stage/
weather evidence before each irrigation, delayed soil/crop rechecks, independent
operation logs, resource accounts and complete safe storage.

Acceptance conventions are explicit: the confidence cutoff 0.6 follows
`tests/test_wofost_wet_disease_v2.py`; disease follow-up allows 7–9 days,
water follow-up 24–48 hours, prior evidence up to two days, and irrigation
separation 6–8 days. These are validation tolerances, not new physical rules.
Validation reads existing state and does not advance the clock or sample sensors.

Tests cover pure plan export, a fresh JSON replay, per-crop provenance, missing
diagnosis/follow-ups, wrong targets, malformed receipts, renamed workflow nodes,
and equal-duration controls that omit fungicide or irrigation. The controls show
higher soybean disease pressure without fungicide and lower maize root water
without irrigation at the same checkpoints, with the other plot unchanged.

## Run without an Agent

With this checkout's Python dependencies available, from the repository root:

```sh
python -B scripts/run_two_farm_soybean_maize_disease_water.py \
  --output-dir /tmp/fairy-soybean-maize-disease-water
```

The destination must be absent or empty; the runner never deletes existing files.
It exports the plan, executed workflow, validation summary, intervention
checkpoints and file hashes. It uses Engine directly rather than the CLI cleanup
path. No PCSE, API key or model server is needed for this legacy reference.

The seed-0 reference executes 374 steps using 42 distinct tool names; both
64-ridge harvests and 32 stored batches pass validation. Stored masses are
8235.99 kg soybean at 13% standard moisture and 10619.72 kg maize at 14%.
These are simulation outputs, not calibrated field predictions.

Checkpoint observations retain the tools' original numeric results. Separate
passive truth records include root/surface water and disease pressure. Disease
pressure is an index, not a diseased-leaf percentage; residual protection is not
a pesticide-residue concentration. Images and full UI replay snapshots are a
subsequent data-export task, not fabricated by this scenario.
