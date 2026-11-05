FAIRY 2.0 — Local recorded-season demo

START
  Requires Python 3.10 or newer and a modern browser. 3D requires WebGL support.
  No pip/npm install, Agent service, simulator, or model server is needed to view
  the bundled recording. JavaScript, Three.js, the logo and data are local.

  From the cloned FAIRY repository directory:
    macOS / Linux:  python3 gui_demo/serve.py
    Windows:        py -3 gui_demo\serve.py
  On Windows, use python instead of py -3 if Python 3 is installed without py.
  Alternatively, run start-demo.command with sh on macOS/Linux, or double-click
  start-demo.bat on Windows. macOS also supports double-clicking the executable
  start-demo.command. Launchers resolve their own directory, including spaces.
  From inside gui_demo, python3 serve.py (Windows: py -3 serve.py) also works.

  Open http://127.0.0.1:4177 in the browser. Stop the server with Ctrl+C.
  Add --port 4178 to any launcher/server command if 4177 is in use.
  Do not open index.html directly: browser modules and JSON need local HTTP.
  The server listens on this computer's loopback interface only.

CONTENTS
  index.html                Farm and agent UI
  README.html               Usage guide and data interpretation
  materials.html            Fillable material links; saved in your browser
  MATERIALS_NEEDED.txt       Fillable checklist for sharing links
  assets/catalog.json       Material slots and event applicability
  assets/media/             Optional local images
  assets/survey-maps/       13 standalone survey SVGs and their index.json
  supplementary_data/       Existing user-supplied material folder, if present
  data/                     374 executed calls and 375 post/initial states
  data/audit-snapshots.jsonl.gz  Full passive audit; not loaded by the UI
  screenshots/              Browser-verified preview images
  scripts/check-demo.mjs    Optional data/provenance checks (Node required)
  scripts/check-portability.py  Relocation and static HTTP checks (Python only)
  start-demo.bat            Windows launcher; uses py -3 or python
  scripts/export_demo.py    Regenerate recording using the repo Python environment

SUPPLY MATERIALS
  Add image links in materials.html, then export completed links and share the JSON.
  The form does not write catalog.json automatically. Exported records can later
  replace assets/catalog.json after review. Local links may point into
  assets/media/ or supplementary_data/. Reload the demo after changing links.
  Direct image links can render in the picture-in-picture viewer. Data files,
  models and GIS are collected for later integration; they are not parsed yet.
  Keep captions in English and distinguish real images, external measurements
  and demo illustrations. No photographic evidence is supplied in this version.

RECORDING
  farm plot A: soybean, 64 ridges; disease diagnosis, treatment and follow-up.
  farm plot B: maize, 64 ridges; water stress, two irrigations and follow-ups.
  Time span: 15 May–18 October 2026. Both crops are harvested and stored.
  73 runtime tools, 72 exposed to an Agent, 42 executed in this recording.
  The UI reads static results. It does not communicate with a live backend.
  Values are recorded simulation results. Maize uses reference soybean
  parameters rather than a field-calibrated maize model.
  Geometry, plants and equipment locations are schematic; ridge dimensions and
  crop states come from the scene. Formal output JSON Schemas are not declared.

VALIDATION
  Optional data checks: node scripts/check-demo.mjs
  Portable serving check: python3 scripts/check-portability.py
  On Windows, replace python3 with py -3. The portability check copies the demo
  into a path containing spaces, retains that copy for inspection, and checks
  static HTTP responses without opening a listening socket. It does not test
  browser rendering; the POSIX launcher check runs on macOS/Linux only.
  See VALIDATION.json for the recorded data and browser checks.

CLONE AND SHARE
  Keep the complete gui_demo directory and its relative layout. A Git clone
  contains only committed files: add gui_demo/ before committing and pushing
  the branch. Include JS/CSS/HTML, serve.py, both launchers, data/, vendor/,
  assets/ and any supplied supplementary_data/ files. No source-machine path
  is required to view the recording, and no build step is needed.
  Optional user-provided image URLs may require network access; the bundled
  demo itself does not. Material links saved only in a browser do not travel
  with Git: export and review them before updating assets/catalog.json.
  Regenerating data is separate from viewing it: it needs the FAIRY repository
  and its Python dependencies. scripts/export_demo.py finds that repository
  relative to gui_demo; --repo can explicitly select another checkout.

UI REFINEMENT
  The global simulation/observation switch is replaced by one field view.
  Main moisture masks use root-zone simulation values. The same ridge popup
  includes the latest surface-probe reading, zone, acquisition time and age.
  Recorded targets drive schematic device trips; the same deterministic
  animation drives 2D and 3D. Device positions are a UI convention, not GPS.
  Crop clicks include a stage/condition illustration. Drone clicks show a
  ridge-by-ridge NDVI field map with a canopy-temperature mode. Both display
  recorded survey values; neither is photographic evidence.
  Sidebar links to supplementary materials and the guide have been removed;
  these pages remain available directly at /materials.html and /README.html.

DEVICE REPLAY AND BACKEND SEMANTICS
  Each successful field operation is illustrated as a trip from a fixed home
  to its recorded targets and back. Idle devices appear at their fixed homes.
  The return does not automatically unload grain, return supplies or charge.
  Those effects occur only when their actual tool calls are recorded.
  Replay operation runs a 12-second illustration. It does not advance world
  time, consume resources, or add tool events; values remain the selected
  recorded post-operation state. Recorded coverage constrains the work shown.
  Reduced-motion preferences suppress automatic animation. An explicit click
  on Replay operation can still play it. Controls occupy a reserved vertical
  rail on the right, outside the 2D/3D field canvas.

  The backend models operation duration, fuel/material use, battery and charging,
  but has no persistent device position, hover, landing or docking state.
  Drone documentation describes automatic early return on low battery and
  sending a drone to its charging station with charge. Neither includes a
  recorded route or station coordinates. Normal successful completion does
  not specify whether the device remains aloft or lands. Fixed-home return
  is therefore a display convention, not a recorded physical transition.

  Backend source pointers, relative to the FAIRY repository:
  fairy/apps/farm_world/drone_operations.py:43,79,193
  fairy/apps/farm_world/shared_drone_app.py:45
  fairy/apps/farm_world/tractor_operations.py:225
  fairy/apps/farm_world/shared_tractor_app.py:171,965
  fairy/controllers/engine.py:596

SURVEY MAP
  The survey result uses a ridge-by-ridge map as its main view, with NDVI and
  canopy-temperature modes. Colors use a shared scale for comparison across
  recorded surveys, not an automatic per-survey stretch. Optional NDVI Detail
  uses the narrower 0.75–0.90 display range and is labelled separately; it does
  not change the returned values. Unsurveyed or missing values stay distinct.
  Only completed surveys available by the selected time are shown. The map is
  a schematic rendering of numeric survey values, not an aerial photograph.
  The three requested supporting images have not been supplied. Existing
  plant illustrations and recorded numeric evidence remain available.
  The 13 standalone SVG maps are in assets/survey-maps/; index.json lists
  their event, farm, scale and coverage. To regenerate these optional exports,
  run node scripts/export-survey-maps.mjs from gui_demo. Node is required only
  for that export command, not for viewing the demo or the existing SVGs.
