EXTERNAL MATERIALS FOR THE FAIRY DEMO

Place optional image, model or data files in this directory. Nothing is required
here for the replay: the numeric simulation record is already in data/.

Edit the corresponding entry in assets/catalog.json. For example:
  url: assets/media/soybean-before.jpg
  source_type: actual_photo or demo_illustration
  caption: a concise English description, source and limitations
  acquired_at: an ISO 8601 timestamp with timezone, or null if unknown

Paths are relative to the gui_demo web root. Use stable, simple filenames.
Do not overwrite an unrelated asset. Keep the original source and usage rights.

Respect each catalog entry's inclusive from_step/to_step interval. Frame 0 is
the initial state; frame N follows event N. Do not present a later photograph
as evidence available earlier in the replay. Static crop/equipment references
must stay labelled reference-only, not current observations.

The simulator produces numeric drone and ground-inspection results. It does
not produce RGB/thermal images, bounding boxes, masks, raw spectra, device GPS
tracks or laboratory pesticide-residue concentrations. Mark external artwork
as a demo illustration. Do not label chemical residual protection days as a
measured pesticide-residue result.

Use raw zero-based ridge IDs 0-63 for both farm plots. The treatment zone is
20-39 inclusive. Ground disease samples cover 28-31 and 32-35 only.
soybean_field means farm plot A; maize_field means farm plot B.

See MATERIALS_NEEDED.txt and assets/catalog.json for the actual event IDs,
dates, scope and missing fields for each optional material.
