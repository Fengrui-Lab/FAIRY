FAIRY 2.0 — Local recorded-season demo

START
  Requires Python 3.10 or newer and a modern browser. 3D requires WebGL.
  No pip/npm install, build, Agent, simulator or model server is needed.
  JavaScript, Three.js, the logo, recording and demo illustrations are local.

  From the cloned FAIRY repository:
    macOS / Linux:  python3 gui_demo/serve.py
    Windows:        py -3 gui_demo\serve.py
  If Windows has Python without the py launcher, use python instead of py -3.
  From inside gui_demo, run python3 serve.py (Windows: py -3 serve.py).
  Alternatively, run start-demo.command with sh on macOS/Linux or double-click
  start-demo.bat on Windows. macOS also supports double-clicking the executable
  start-demo.command. Launchers resolve their own directory, including spaces.

  Open http://127.0.0.1:4177. Stop with Ctrl+C. Add --port 4178 if needed.
  Use local HTTP; opening index.html directly does not load modules and JSON.
  The server listens on this computer's loopback interface only.

RECORDING
  farm plot A: soybean, 64 ridges; disease diagnosis, treatment and follow-up.
  farm plot B: maize, 64 ridges; water stress, two irrigations and follow-ups.
  374 executed calls and 375 states, including the initial state.
  15 May–18 October 2026; both crops are harvested and stored.
  73 runtime tools, 72 exposed to an Agent, 42 executed in this recording.
  All numeric values remain the original recorded simulation results.
  Maize uses reference soybean parameters, not a field-calibrated maize model.
  Scenario playback reads static files and does not call a live agent backend.
  Knowledge·Guidance uses the local UI server to read and save guidance text.

KNOWLEDGE·GUIDANCE
  The shared button above Farm plots / Agent tools is available in both scenes.
  Adding Extra Guidance shows a text editor and formatted JSON preview. Save
  appends expert_guidance_000, expert_guidance_001, and so on to the shared
  Knowledge_Guidance/expert_guidance.json file relative to gui_demo.
  Check Local Knowledge lists the saved entries in numerical order.
  These entries persist after refreshing, switching scenes or restarting the
  server. Saving here stores guidance; it does not invoke or alter an agent run.
  Use serve.py (or the existing start-demo launchers) for file saving. Restart
  an already-running server after updating its Python code, then refresh the
  browser. A generic static server can display the scenes but cannot save
  guidance through this interface.

IMAGES AND EVIDENCE
  Bundled: 15 AI-generated demo illustrations — 3 NDVI-style images,
  6 soybean stages/conditions and 6 maize stages/conditions.
  Files: assets/media/simulated/
  Exact prompts, built-in tool details and original-file provenance:
    assets/media/simulated/ndvi-generation.json
    assets/media/simulated/soybean-generation.json
    assets/media/simulated/maize-generation.json

  Crop cards select an illustration for the recorded stage, condition, ridge
  and applicable time. Choose State schematic to see the code-drawn state
  view. Bare, unplanted and harvested states do not display a full green crop.
  The pictures are illustrative examples, not reconstructions of individual
  plants. Soybean disease follow-up retains spotting and early pods; maize
  water follow-up retains stress. Neither image proves measured visual recovery.

  Drone cards provide an Illustrative image / Recorded ridge map switch.
  The three NDVI-style pictures contain invented illustrative pixel patterns;
  they are not reconstructed measurements or captured aerial images. A full
  field in a picture does not extend actual survey coverage: events 159, 188
  and 201 each cover only ridges 20–39, or 20 of 64 ridges. Numeric values and
  coverage beside the image still come exclusively from the recorded tool
  response. The synthetic pixels do not alter data, diagnosis or confidence.

  Recorded ridge map colors one value per ridge. NDVI uses a fixed 0–1 scale;
  NDVI Detail uses 0.75–0.90 with an Enhanced contrast label. Temperature uses
  0–45 °C. Missing and unsurveyed ridges remain distinct. Events 110 and 115
  have no valid NDVI and show no NDVI example. Only surveys available by the
  selected time appear. There is no post-treatment soybean drone survey or
  next-day post-irrigation drone image in this recording.
  13 standalone numeric-map SVGs and index.json are in assets/survey-maps/.
  Optional regeneration: node scripts/export-survey-maps.mjs from gui_demo.

EXPLORE
  Select a farm plot for 3D; select it again to return to the 2D overview.
  Drag to orbit, scroll to zoom, and click a ridge or device for details.
  Main moisture masks use root-zone simulation VWC. Ridge details also show
  the latest surface-probe reading, zone, time and age. These differ in soil
  layer and acquisition time and are not averaged.
  Each timeline slice shows the state after its tool call; Start is before
  the first call. Plot filters change visible actions, not global world time.
  Workflow hover previews an action; clicking selects and pins it.
  Guide and material pages remain available at /README.html and /materials.html.

DEVICE REPLAY
  Successful field operations are illustrated as fixed home → recorded
  targets → fixed home. 2D and 3D share the same schematic animation.
  Replay operation takes 12 seconds without advancing world time, consuming
  resources or adding tool events. Recorded coverage limits the work shown.
  Returning home does not charge, unload grain or return supplies; only the
  corresponding recorded calls change those resources.
  Reduced-motion preferences suppress automatic animation; explicit Replay
  operation can still play. Controls occupy a separate right-side rail.
  The backend models duration, fuel, materials, battery and charging, but has
  no persistent device position, hover, landing or docking state. Fixed-home
  return and all routes are display conventions, not GPS or engine outcomes.

MATERIAL STATUS
  All 12 primary material slots are supplied with synthetic illustrations:
  3 NDVI examples, 7 event-support slots and 2 crop identity references.
  The 15 files provide additional stage variants; some slots reuse a file.
  Four optional slots remain unsupplied: measured pesticide residues,
  equipment photographs, equipment models and measured GIS plot geometry.
  Protection days are not pesticide-residue concentrations. No actual photos,
  spectral/thermal rasters, bounding boxes or segmentation masks are supplied.

  MATERIALS_NEEDED.txt lists the completed slots and optional requirements.
  materials.html accepts links and exports a catalog; browser edits do not
  write assets/catalog.json automatically. Review exported links before
  replacing the catalog. Keep captions and source descriptions in English,
  preserve event/ridge applicability, and distinguish measured data from
  illustrations. GIS, models and data files are collected, not parsed yet.

FILES AND CHECKS
  assets/catalog.json       Material slots, paths and event applicability
  data/                     Original recording, states, tool schemas and checks
  data/audit-snapshots.jsonl.gz  Full passive audit; not loaded by the browser
  screenshots/              Saved browser previews
  VALIDATION.json           Recorded validation results
  Optional data checks:       node scripts/check-demo.mjs
  Optional portability check: python3 scripts/check-portability.py
  Use py -3 instead of python3 on Windows. The portability check retains a
  copy in a path with spaces and checks static HTTP responses; it does not
  verify browser rendering. Its POSIX launcher check is macOS/Linux only.

CLONE AND SHARE
  Keep the complete gui_demo directory and relative layout, including data/,
  vendor/, assets/, launchers and any supplied supplementary_data/. Git clones
  include committed files only. No original-machine path is needed to view it.
  The bundled demo works offline; optional external image URLs may not.
  Browser-only material links do not travel with Git: export and review them.
  Regenerating the recording is separate from viewing it and requires the
  FAIRY Python environment. scripts/export_demo.py locates the repository
  relative to gui_demo; --repo can select another checkout. Export to a new
  empty output directory; the exporter refuses to replace a nonempty one.
