HIT satellite and drone demo: local data and simulated tools
===========================================================

Runtime
-------
The browser reads scenario.json and assets/ only. It does not read another
repository, connect to Google Earth Engine, load an LLM, or execute GIS tools.
The result viewer requests OpenStreetMap background tiles over the network.
Satellite images, classification overlays and UAV results remain local.

From FAIRY, start the existing server:
  python3 gui_demo/serve.py --port 4180
Open http://127.0.0.1:4180/?scenario=hit or choose
"HIT smart farm · Satellite & drone" in the Scenario selector.
Use Play to replay all eight steps; Color layer switches the available masks.
Equipment details and presentation nodes share the same result viewers.
Image-processing nodes display the supplied reference run screenshots or the
prepared orthomosaic, with links to their complete images.

tools.py is an independent, standard-library-only mock collection with eight
public tools. Every run validates tool order, required arguments and artifact
IDs. The deterministic oracle emits eight events and nine cumulative frames.

From FAIRY/gui_demo:
  python3 scenarios/hit/tools.py
  python3 scenarios/hit/tools.py --output /tmp/hit-oracle.json

Run the read-only, standard-library acceptance checker from FAIRY/gui_demo:
  python3 scripts/check-hit-scenario.py

It checks the fixed workflow, rejected invalid calls without state changes,
result visibility gates, local assets, basic geometry/area consistency, and
the SHA256 of every copied source file against source-manifest.json and the
manifest digest recorded in scenario.json provenance. It writes no files.

Rebuild assets after copying source material
-------------------------------------------
Put the material package under scenarios/hit/source/, preserving this layout:

  Classify crops.png
  Post-process results.png
  Identify fields & lodging.png

  HIT智慧农场/
    HIT_SmartFarm.shp
    HIT_SmartFarm.shx
    HIT_SmartFarm.dbf
    HIT_SmartFarm.prj
    (keep any .cpg/.fix files supplied with this boundary)

  clip_result/
    CropType_HITSmartFarm_clipped.tif
    CropType_HITSmartFarm_clipped_color.tif
    CropType_HITSmartFarm_clipped_color.png
    CropType_HITSmartFarm_clipped_legend.png
    CropType_HITSmartFarm_clipped_satellite_rgb.png

  Drone_Graphical_Results/
    odm_orthophoto_competition_site.tif
    Drone_Analysis_Result_Image.jpg
    field_distribution.shp/.shx/.dbf/.prj
    rice_distribution.shp/.shx/.dbf/.prj
    rice_lodging_distribution.shp/.shx/.dbf/.prj

Use a Python environment containing numpy, rasterio, Pillow, geopandas,
shapely and pyproj, then run from FAIRY/gui_demo:
  PYTHONDONTWRITEBYTECODE=1 python3 scripts/build-hit-scenario.py

The default input is scenarios/hit/source/ with the three folders above.
The original input/aoi/... and output/... hierarchy is also accepted without
moving or rewriting the supplied files. An explicit --source PATH may be
used for a different material package; input is always read-only. The builder
only writes local scenario.json, source-manifest.json and assets/. It never deletes source files,
imports the old ARE tools, launches authentication or runs a remote service.

Data contract
-------------
All scene coordinates are normalized to the satellite image: upper left [0,0]
and lower right [1,1]. farm.bounds is the image extent in WGS84 longitude and
latitude, ordered [west,south,east,north]. roi.bounds is normalized XY ordered
[left,top,right,bottom]. assets paths are relative to scenarios/hit/.

cropGrid.values is a row-major 283 x 147 grid. Classes: 0 background/no data,
1 rice, 2 maize, 3 soybean, 4 other. cropSamples provides sparse positions for
the procedural 3D field. It includes only classes 1-3 over vegetation-like RGB
pixels. Class 4 is not automatically treated as planted land. surfaceHints
provides low gray building blocks, road-like gray patches, bare ground and
vegetation using coarse RGB styling heuristics. These are illustrative scene
objects, not additional classification or building-detection results. They do
not change classification masks, source pixels, or any area statistics.
The satellite RGB and classification PNG are aligned.

orthomosaic.png uses its own local image coordinates and fills roi.bounds.
drone-mask.png and drone-mask.svg are transparent overlays covering the entire
satellite image extent. droneLayers has the same normalized coordinate system.
drone-result.jpg is the prepared source presentation image, not a georeferenced
overlay; display it without cropping or assigning it satellite bounds.
orthomosaicMetadata gives the original image aspect and the simulated footprint
dimensions. droneLocalLayers maps the same vector overlays into the UAV image's
own [0,1] coordinates for a magnified inset. Enlarging that inset is a display
operation; it does not enlarge the actual ROI or change the area metrics.

The UAV image and vectors are intentionally re-anchored to a rice-dense window
of the satellite classification for this simulated demonstration. Edge pixels
may belong to other classes. This is a simulated survey placement, not a claim
that the original satellite and UAV sources were captured at the same place.
Farm, crop and placed UAV areas are recalculated on the WGS84 ellipsoid.

Metric scopes and historical screenshots
----------------------------------------
The six metricDefinitions in scenario.json document each numerator, denominator,
source and spatial scope. With the supplied source package:

* Farm: 1,925,628.04 m2 / 10,000 = 192.562804 ha, measured from the AOI polygon.
  This includes fields, buildings, roads and other land cover inside the AOI.
* Satellite rice: the sum of the 2,189 class-1 pixel areas in the clipped raster,
  153,040.11 m2 / 10,000 = 15.304011 ha. This covers the whole farm.
* Survey ROI: the full selected 17 x 12 pixel rectangle, 14,261.73 m2 = 1.426173 ha.
  It is the image/survey footprint, NOT rice area; its coarse satellite pixels
  include mixed classes and the orthomosaic contains background outside fields.
* UAV rice: rice polygons after simulated placement inside that footprint,
  4,653.82 m2 = 0.465382 ha. Original source shapes have been relocated and rescaled using the same
  affine transform for the demonstration; this is not an original capture-area claim.
* UAV lodging: the similarly placed lodging polygons, 156.27 m2.
* Lodging rate: 156.27 / 4,653.82 x 100 = 3.36%, using UAV rice as denominator,
  not the entire ROI or the whole-farm satellite rice area.

The three supplied processing PNGs are copied byte-for-byte and used as
historical reference screenshots. Classify crops.png records an earlier
unmasked count of 2,686 rice pixels, while the current clipped source has 2,189.
Identify fields & lodging.png shows old fixed mock areas (125,000 / 97,250 m2).
Those historical figures are not the live demo metrics. Current original-vector
areas are field 14,452.11 m2, rice 13,926.63 m2 and lodging 467.66 m2 before the
simulated placement; re-anchoring produces the smaller UAV figures above.
The actual local mock pipeline does not rerun the screenshot's model or logs.
Use the caption: Reference run screenshot - Figures may differ from this
simulated placement.

Frames and presentation
-----------------------
Frame 0 is the initial state; frame N follows tool N. Satellite classification
is available after tool 2, its map mask after tool 3, and its result panel after
tool 4. Drone analysis is available with its mask after tool 7, and its result
panel after tool 8. Tools are sequential. Equipment animation is presentation
only and does not call a live device or change the deterministic result.

The source package is only required for rebuilding. The checked-in generated
assets are enough to use the standalone browser demo and to rerun the oracle.
