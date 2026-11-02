L3: two-crop joint operating margin

Scenario class: ScenarioJointCropOperatingMargin
ID: scenario_l3_joint_maize_soybean_operating_margin
Registration is explicitly owned by the parent management_extensions catalog.

This scene has two independent fields: maize 16 x 268m x 0.75m = 3216m2,
soybean 16 x 268m x 1.1m = 4716.8m2. These are stated small operating plots,
not a claim of 64-ridge production scale. One tractor, warehouse and common
clock are shared. Every operation advances both crop worlds. Stationary
irrigation controllers share one real 900m3 seasonal supply and retain each
field's original 180mm limit. Native soil/crop/weather rules are reused from
management_extensions without modifying those modules or their defaults.

Operating objective
Both contracted fields must be planted, reach native maturity, be harvested,
and have complete crop/ridge-provenance grain batches safely stored by
November 30. Within those constraints, maximize fixed-price stored-grain value
minus actually consumed inputs. There is NO pre-filled yield target or 99%
yield gate. Evaluation success denotes physical/operational feasibility;
margin_regret separately compares economic quality with the searched reference.
Different crops' kg are never added to form a yield objective. Marginal maximum
crop yields are reported separately and are not claimed jointly attainable.

Prices are synthetic DEMO assumptions, fixed before exploration:
maize grain .25/kg; soybean grain .45/kg; maize seed .002/seed; soybean seed
.0003/seed; fertilizer product .8/kg; fuel 1.5/L; water .20/m3; actual drying
throughput .03/kg. Stored-grain valuation is not a sale or cash receipt. Endowed
inputs have opportunity costs only when consumed. Machine loading is transfer,
not consumption. Unused inputs remain assets. Costs exclude land, labour,
equipment depreciation, taxes, and financing. No market-price claim is made.

Agronomic scope
Pinned Thionville 2019 NASA weather and existing native reference cultivars,
soil assumptions, sowing geometry and densities are retained. Soybean has no
added N in the candidate space; this is a search restriction, not a universal
recommendation. Maize N product is split equally between planting and June10.
Water dates use the original crop-specific July/August windows. Harvest checks
public crop stage, grain moisture and rainfall from September windows and waits
when these are not satisfied, subject to the real tool constraints/deadline.
No local field-trial calibration is claimed. Carbon, methane, SCN and actual
nitrogen-leaching impacts are not invented; water/fertilizer consumption are
reported directly.

Search and evidence
Coarse grid: maize fertilizer [0,300,600] kg product/ha x maize irrigation
[0,60,120,180]mm x soybean irrigation [0,60,120,180]mm, all 48 candidates.
Infeasible shared-water candidates remain as failed tool traces. One axial
refinement follows, then two-start full adjacent dose-combination exploration:
75kg/ha fertilizer steps, 15mm water steps, time alternatives -7/0/+7 days.
Both the high-margin and zero-fertilizer branches continue until no evaluated
neighbor improves margin. Exact scope, all selected values, local stopping
certificates and hashes of every candidate are in reference.json. This is a
best-tested/local optimum on a declared grid, never a global field optimum.

Frozen exploration result (2026-11-02)
122 distinct candidates: 83 physically feasible, 39 refused by the shared-water
constraint. Both search branches reached a fully evaluated neighborhood with no
improvement: 450/165/75/0 (28 neighbors) and 0/165/75/0 (19 neighbors), where the
coordinates are maize fertilizer kg product/ha, maize water mm, soybean water
mm, and irrigation shift days. The selected profit reference is the former:
  maize safe storage:        4184.44 kg
  soybean safe storage:      1960.04 kg
  shared water:               884.40 m3
  fertilizer product:         144.72 kg
  fuel:                        44.090909 L
  stored-grain value:         1928.128000 DEMO
  actual operating cost:      642.608364 DEMO
  net operating margin:      1285.519636 DEMO
The maximum tested joint grain value uses 600/165/75/0: 1965.038 DEMO value,
685.629564 cost and 1279.408436 margin. Thus higher production value does not
maximize profit at the prices frozen before exploration. The cropwise marginal
maxima are maize 4350.20kg and soybean 2031.52kg, not a jointly feasible target.
The no-added-fertilizer/no-irrigation candidate remains feasible but yields only
611.264291 DEMO margin; lower inputs alone do not maximize the stated objective.
57 nondominated candidates remain on the value/cost/water Pareto frontier.
Evidence lives at validation_runs/management_v2_development_20261102/l3/.
The frozen tool workflow has 160 steps, including observations and time advances.

Reproduction (from repository root; use fresh output dirs for new experiments)
export PYTHONPATH=.
export PYTHONHASHSEED=0
.venv/bin/python -m fairy.scenarios.management_extensions.v2.l3.calibrate --output validation_runs/l3_joint/coarse --workers 4
.venv/bin/python -m fairy.scenarios.management_extensions.v2.l3.refine --coarse validation_runs/l3_joint/coarse --output validation_runs/l3_joint/refinement --workers 4
.venv/bin/python -m fairy.scenarios.management_extensions.v2.l3.improve --coarse validation_runs/l3_joint/coarse --refinement validation_runs/l3_joint/refinement --output validation_runs/l3_joint/local_search --workers 4 --publish
.venv/bin/python -m fairy.scenarios.management_extensions.v2.l3.verify --output validation_runs/l3_joint/verification
.venv/bin/python -m pytest -q fairy/scenarios/management_extensions/v2/l3/tests

After explicit registry integration, the ordinary CLI can export/replay/evaluate:
.venv/bin/python -m fairy.cli --scenario scenario_l3_joint_maize_soybean_operating_margin --build-oracle --replay --evaluate --output-dir validation_runs/l3_joint/cli

The generic single-farm Oracle baseline/FOS script does not define the economic
multi-crop objective. Use run_report.evaluation.validation.metadata for crop
storage, costs, net margin, feasibility and reference regret; reference.json
is the family-local economic/crop/Pareto baseline. No generic multi-crop
YieldLoss support is claimed by this change.

This development run additionally used /tmp/fairy-pcse-settings only for local
PCSE logging configuration. It is not a required package or scenario input.
