#!/usr/bin/env python3
"""Build local HIT demo fixtures, then execute eight offline mock tools.

Only the output directory is written. The source directory is read-only input.
Requires rasterio, numpy, Pillow, geopandas, shapely and pyproj for asset building;
the generated demo and scenarios/hit/tools.py do not require those packages.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True

import geopandas as gpd
import numpy as np
from PIL import Image, ImageDraw
from pyproj import Geod
import rasterio
from rasterio.enums import Resampling
from shapely.geometry import Polygon, mapping
from shapely.ops import transform as transform_geometry


GUI_ROOT = Path(__file__).resolve().parents[1]
GEOD = Geod(ellps="WGS84")
CROPS = [(1, "rice", "Rice", "#ca3c3c"), (2, "maize", "Maize", "#2edada"), (3, "soybean", "Soybean", "#7214d6"), (4, "other", "Other", "#bceb8d")]


def geodesic_area(geometry) -> float:
    # orient polygons before measuring to keep holes and multipolygons consistent.
    from shapely.geometry.polygon import orient
    if geometry.geom_type == "Polygon":
        return abs(GEOD.geometry_area_perimeter(orient(geometry, sign=1.0))[0])
    return sum(geodesic_area(part) for part in geometry.geoms)


def rice_survey_window(classes: np.ndarray, image_aspect: float, pixel_aspect: float):
    """A rice-dense window preserving the drone image's physical aspect ratio.

    A mixed boundary is intentional: this is a survey footprint placed into
    existing coarse satellite classes, not a claim that all pixels are rice.
    """
    rows = 12
    columns = max(2, round(rows * image_aspect / pixel_aspect))
    def window_sums(mask):
        integral = np.pad(mask.astype(int), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
        return integral[rows:, columns:] - integral[:-rows, columns:] - integral[rows:, :-columns] + integral[:-rows, :-columns]
    rice = window_sums(classes == 1)
    valid = window_sums(classes != 0)
    rice[valid < rows * columns] = -1
    row, column = np.unravel_index(rice.argmax(), rice.shape)
    if rice[row, column] <= 0:
        raise ValueError("No rice survey footprint fits inside the farm classification")
    return (column, row, column + columns, row + rows), float(rice[row, column] / (rows * columns))


def polygon_parts(geometry):
    return [geometry] if geometry.geom_type == "Polygon" else list(geometry.geoms)


def svg_path(geometry) -> str:
    commands = []
    for polygon in polygon_parts(geometry):
        for ring in [polygon.exterior, *polygon.interiors]:
            coordinates = list(ring.coords)
            commands.append("M" + " L".join(f"{x:.7f},{y:.7f}" for x, y in coordinates) + " Z")
    return " ".join(commands)


def surface_hints(rgb_path: Path, classes: np.ndarray) -> dict:
    """Coarse scene styling from existing RGB, not an inference/model output.

    Crop classes 1-3 remain authoritative for crop identity. Class 4 is not
    interpreted as planted land: bright roof-like cells become low gray blocks,
    gray cells become road-like surfaces, and only green cells get vegetation.
    """
    image = np.asarray(Image.open(rgb_path).convert("RGB"), dtype=float)
    height, width = classes.shape
    if image.shape[:2] != classes.shape:
        raise ValueError("Satellite RGB must align with the classification grid")
    red, green, blue = image.transpose(2, 0, 1)
    maximum, minimum = image.max(axis=2), image.min(axis=2)
    brightness = image.mean(axis=2)
    saturation = (maximum - minimum) / np.maximum(maximum, 1)
    valid = classes > 0
    known_crop = (classes >= 1) & (classes <= 3)
    green_tint = (green >= red * 1.08) & (green >= blue * 1.07) & (green - red >= 2)
    dark_field = known_crop & (brightness < 65) & (green >= red * .95) & (blue <= green * 1.2)
    vegetation = valid & (green_tint | dark_field)
    roof_like = valid & ~vegetation & ((brightness > 95) | ((maximum > 130) & (saturation > .35)))
    gray = valid & ~vegetation & (brightness > 30) & (saturation < .30)
    building_mask = np.zeros_like(valid)
    buildings = []
    for row in range(0, height - 3, 4):
        for column in range(0, width - 3, 4):
            patch = np.s_[row:row + 4, column:column + 4]
            if valid[patch].mean() < 1 or (classes[patch] == 4).mean() < .5:
                continue
            if roof_like[patch].mean() < .25 or vegetation[patch].mean() > .4:
                continue
            building_mask[patch] = True
            buildings.append({"x": (column + 2) / width, "y": (row + 2) / height, "width": 3.0 / width, "height": 2.8 / height, "height_m": round(5 + min(float(brightness[patch].mean()) / 50, 4), 2), "color": "#9aa3a6", "kind": "building", "illustrative": True})
    road_mask = gray & ~building_mask & (brightness < 130)
    samples, roads, field_samples = [], [], []
    crop_names = {1: "rice", 2: "maize", 3: "soybean"}
    for row in range(1, height, 3):
        for column in range(1, width, 3):
            class_id = int(classes[row, column])
            if not class_id:
                continue
            x, y = (column + .5) / width, (row + .5) / height
            if building_mask[row, column]:
                kind, color = "building", "#9aa3a6"
            elif vegetation[row, column]:
                kind, color = "vegetation", "#456b39"
            elif road_mask[row, column]:
                kind, color = "road", "#929996"
            else:
                kind, color = "bare", "#77725e"
            sample = {"x": x, "y": y, "width": 3 / width, "height": 3 / height, "kind": kind, "color": color, "classId": class_id}
            samples.append(sample)
            if kind == "road":
                roads.append({**sample, "illustrative": True})
            if class_id in crop_names and kind == "vegetation":
                field_samples.append({"x": x, "y": y, "cropId": crop_names[class_id], "classId": class_id})
    return {"method": "Illustrative local RGB brightness/green/gray heuristics; not a building or road classification product.", "coordinates": "Satellite-normalized image XY; rectangle x/y denote centers.", "buildings": buildings, "roads": roads, "surfaceSamples": samples, "fieldSamples": field_samples, "statistics": {"building_blocks": len(buildings), "road_samples": len(roads), "planted_samples": len(field_samples), "surface_samples": len(samples)}}


def build(source: Path, destination: Path) -> dict:
    source = source.resolve()
    destination = destination.resolve()
    if source == destination or source in destination.parents:
        raise ValueError("Output must not be inside the read-only source directory")
    assets = destination / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    # Accept the user's compact three-folder package as well as the original
    # input/output hierarchy without moving or modifying any supplied files.
    rs = source / "clip_result" if (source / "clip_result").is_dir() else source / "output/clip_result"
    uav = source / "Drone_Graphical_Results" if (source / "Drone_Graphical_Results").is_dir() else source / "output/Drone_Graphical_Results"
    aoi_directory = source / "HIT智慧农场" if (source / "HIT智慧农场").is_dir() else source / "input/aoi/HIT智慧农场"
    aoi = aoi_directory / "HIT_SmartFarm.shp"
    required = [aoi_directory / f"HIT_SmartFarm.{extension}" for extension in ["shp", "shx", "dbf", "prj"]]
    required.extend([rs / "CropType_HITSmartFarm_clipped.tif", rs / "CropType_HITSmartFarm_clipped_color.png", rs / "CropType_HITSmartFarm_clipped_legend.png", rs / "CropType_HITSmartFarm_clipped_satellite_rgb.png", uav / "odm_orthophoto_competition_site.tif", uav / "Drone_Analysis_Result_Image.jpg"])
    processing_sources = {"processingClassify": ("Classify crops.png", "processing-classify.png"), "processingPostprocess": ("Post-process results.png", "processing-postprocess.png"), "processingFields": ("Identify fields & lodging.png", "processing-fields.png")}
    required.extend(source / name for name, _ in processing_sources.values())
    for stem in ["field_distribution", "rice_distribution", "rice_lodging_distribution"]:
        required.extend(uav / f"{stem}.{extension}" for extension in ["shp", "shx", "dbf", "prj"])
    missing = [str(path.relative_to(source)) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing local source fixtures:\n" + "\n".join(missing))

    for original, target in [
        (rs / "CropType_HITSmartFarm_clipped_color.png", "satellite-mask.png"),
        (rs / "CropType_HITSmartFarm_clipped_legend.png", "legend.png"),
        (rs / "CropType_HITSmartFarm_clipped_satellite_rgb.png", "satellite-rgb.png"),
        (uav / "Drone_Analysis_Result_Image.jpg", "drone-result.jpg"),
    ]:
        shutil.copyfile(original, assets / target)
    for name, target in processing_sources.values():
        shutil.copyfile(source / name, assets / target)

    with rasterio.open(rs / "CropType_HITSmartFarm_clipped.tif") as dataset:
        classes = dataset.read(1)
        width, height = dataset.width, dataset.height
        west, south, east, north = dataset.bounds
        if dataset.crs.to_epsg() != 4326:
            raise ValueError("The fixed HIT fixture must use EPSG:4326")

    def normalized(x, y, z=None):
        return (np.asarray(x) - west) / (east - west), (north - np.asarray(y)) / (north - south)

    def geographic(x, y, z=None):
        return west + np.asarray(x) * (east - west), north - np.asarray(y) * (north - south)

    aoi_frame = gpd.read_file(aoi).to_crs(4326)
    farm_geo = aoi_frame.geometry.union_all()
    farm_norm = transform_geometry(normalized, farm_geo)
    farm_polygon = max(polygon_parts(farm_norm), key=lambda p: p.area)
    farm_area = geodesic_area(farm_geo)
    farm_width = GEOD.inv(west, (north + south) / 2, east, (north + south) / 2)[2]
    farm_height = GEOD.inv((west + east) / 2, south, (west + east) / 2, north)[2]
    with rasterio.open(uav / "odm_orthophoto_competition_site.tif") as dataset:
        image_aspect = dataset.width / dataset.height
    (left, top, right, bottom), rice_fraction = rice_survey_window(classes, image_aspect, (farm_width / width) / (farm_height / height))
    x0, y0, x1, y1 = left / width, top / height, right / width, bottom / height
    roi = Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
    roi_area = geodesic_area(transform_geometry(geographic, roi))
    counts = Counter(int(value) for value in classes.flat)
    crop_areas = {crop[0]: 0.0 for crop in CROPS}
    for row in range(height):
        corners = [geographic(x / width, y / height) for x, y in [(0, row), (1, row), (1, row + 1), (0, row + 1)]]
        pixel_area = abs(GEOD.polygon_area_perimeter([float(c[0]) for c in corners], [float(c[1]) for c in corners])[0])
        row_counts = Counter(int(value) for value in classes[row])
        for class_id in crop_areas:
            crop_areas[class_id] += pixel_area * row_counts[class_id]
    crops = [{"id": crop_id, "classId": class_id, "class_id": class_id, "label": label, "color": color, "area_m2": round(crop_areas[class_id], 2), "pixel_count": counts[class_id]} for class_id, crop_id, label, color in CROPS]

    with rasterio.open(uav / "odm_orthophoto_competition_site.tif") as dataset:
        uav_bounds = dataset.bounds
        source_width, source_height = dataset.width, dataset.height
        target_height = 960
        target_width = round(dataset.width * target_height / dataset.height)
        bands = dataset.read(out_shape=(dataset.count, target_height, target_width), resampling=Resampling.bilinear)
        rgb = bands[:3]
        if rgb.dtype != np.uint8:
            scaled = []
            for band in rgb:
                valid = band[band > 0]
                low, high = np.percentile(valid, (1, 99)) if valid.size else (0, 1)
                scaled.append(np.clip((band - low) / max(high - low, 1) * 255, 0, 255).astype(np.uint8))
            rgb = np.stack(scaled)
        alpha = bands[3].astype(np.uint8) if dataset.count >= 4 else dataset.dataset_mask(out_shape=(target_height, target_width), resampling=Resampling.nearest)
        rgba = np.dstack([*rgb, alpha])
        Image.fromarray(rgba, "RGBA").save(assets / "orthomosaic.png", optimize=True)

    def anchored(x, y, z=None):
        local_x = (np.asarray(x) - uav_bounds.left) / (uav_bounds.right - uav_bounds.left)
        local_y = (uav_bounds.top - np.asarray(y)) / (uav_bounds.top - uav_bounds.bottom)
        return x0 + local_x * (x1 - x0), y0 + local_y * (y1 - y0)

    overlay_layers = []
    local_layers = []
    source_vector_areas = {}
    drone_metrics = {}
    for key, filename, color, opacity in [
        ("field", "field_distribution", "#f3d17b", 0.34),
        ("rice", "rice_distribution", "#31ba82", 0.60),
        ("lodging", "rice_lodging_distribution", "#fb795f", 0.96),
    ]:
        vectors = gpd.read_file(uav / f"{filename}.shp").to_crs(4326)
        original = vectors.geometry.union_all()
        source_vector_areas[key] = round(geodesic_area(original), 2)
        transformed = transform_geometry(anchored, original)
        area = geodesic_area(transform_geometry(geographic, transformed))
        drone_metrics[f"{key}_area_m2"] = round(area, 2)
        display_geometry = transformed.simplify(0.00008, preserve_topology=True)
        overlay_layers.append({"id": key, "color": color, "opacity": opacity, "geometry": mapping(display_geometry)})
        local_geometry = transform_geometry(lambda x, y, z=None: ((np.asarray(x) - x0) / (x1 - x0), (np.asarray(y) - y0) / (y1 - y0)), display_geometry)
        local_layers.append({"id": key, "color": color, "opacity": opacity, "geometry": mapping(local_geometry)})
    drone_metrics["lodging_percent"] = round(drone_metrics["lodging_area_m2"] / drone_metrics["rice_area_m2"] * 100, 2)
    drone_metrics["roi_area_m2"] = round(roi_area, 2)
    drone_metrics["area_method"] = "WGS84 geodesic area after simulated placement"

    from shapely.geometry import shape
    svg_parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1132" height="588" viewBox="0 0 1 1" preserveAspectRatio="none">']
    mask = Image.new("RGBA", (width * 4, height * 4))
    for layer in overlay_layers:
        geometry = shape(layer["geometry"])
        svg_parts.append(f'<path d="{svg_path(geometry)}" fill="{layer["color"]}" fill-opacity="{layer["opacity"]}" fill-rule="evenodd" stroke="{layer["color"]}" stroke-width="0.0007"/>')
        color = tuple(int(layer["color"][offset:offset + 2], 16) for offset in (1, 3, 5))
        # Render each layer separately to preserve holes over preceding layers.
        layer_image = Image.new("RGBA", mask.size)
        layer_draw = ImageDraw.Draw(layer_image)
        for polygon in polygon_parts(geometry):
            layer_draw.polygon([(x * mask.width, y * mask.height) for x, y in polygon.exterior.coords], fill=(*color, round(layer["opacity"] * 255)))
            for ring in polygon.interiors:
                layer_draw.polygon([(x * mask.width, y * mask.height) for x, y in ring.coords], fill=(0, 0, 0, 0))
        mask = Image.alpha_composite(mask, layer_image)
    svg_parts.append("</svg>")
    (assets / "drone-mask.svg").write_text("\n".join(svg_parts), encoding="utf-8")
    mask.save(assets / "drone-mask.png", optimize=True)

    route = []
    for row in range(6):
        y = y0 + (y1 - y0) * (0.08 + row * 0.168)
        left, right = x0 + (x1 - x0) * 0.08, x1 - (x1 - x0) * 0.08
        route.extend([[left, y], [right, y]] if row % 2 == 0 else [[right, y], [left, y]])
    drone_route = [[x0 - (x1 - x0) * 0.24, y1 + (y1 - y0) * 0.12], *route]
    drone_route.append(drone_route[0])
    terrain = surface_hints(assets / "satellite-rgb.png", classes)
    samples = terrain["fieldSamples"]
    orthomosaic_metadata = {"width_px": target_width, "height_px": target_height, "source_width_px": source_width, "source_height_px": source_height, "aspect_ratio": source_width / source_height, "source_bounds": list(uav_bounds), "display_bounds": [x0, y0, x1, y1], "footprint_width_m": round((x1 - x0) * farm_width, 2), "footprint_height_m": round((y1 - y0) * farm_height, 2), "display_aspect_ratio": (x1 - x0) * farm_width / ((y1 - y0) * farm_height), "placement": "Simulated anchored survey footprint, not the original capture location"}
    metric_definitions = {
        "farmArea": {"value": round(farm_area / 10000, 6), "unit": "ha", "scope": "Whole farm boundary", "source": "HIT_SmartFarm.shp", "formula": "WGS84 geodesic polygon area / 10000", "description": "The entire AOI, including fields, buildings, roads and other land cover."},
        "satelliteRiceArea": {"value": round(crop_areas[1] / 10000, 6), "unit": "ha", "scope": "Whole farm satellite classification", "source": "CropType_HITSmartFarm_clipped.tif, class 1", "formula": "Sum of WGS84 areas of the 2189 class-1 pixels / 10000", "description": "Rice pixels across the entire clipped farm; not the drone survey area."},
        "surveyFootprint": {"value": round(roi_area / 10000, 6), "unit": "ha", "scope": "Selected drone image footprint", "source": "17 x 12 pixel rice-dense satellite window", "formula": "WGS84 area of the selected ROI rectangle / 10000", "description": "The whole survey rectangle, including mixed edge classes and the drone image background. This is not rice area."},
        "droneRiceArea": {"value": round(drone_metrics["rice_area_m2"] / 10000, 6), "unit": "ha", "scope": "Simulated anchored drone rice polygons", "source": "rice_distribution.shp placed inside the selected ROI", "formula": "WGS84 area of the re-anchored rice polygons / 10000", "description": "Prepared UAV rice shapes are rescaled to the survey footprint; this is a simulated demonstration measurement, not the original source-area constant."},
        "droneLodgingArea": {"value": drone_metrics["lodging_area_m2"], "unit": "m2", "scope": "Simulated anchored lodging polygons", "source": "rice_lodging_distribution.shp placed using the same transform", "formula": "WGS84 area of the re-anchored lodging polygons", "description": "Lodged subset within the re-anchored UAV rice shapes."},
        "lodgingRate": {"value": drone_metrics["lodging_percent"], "unit": "%", "scope": "Drone rice area only", "source": "Re-anchored lodging and rice polygon areas", "formula": "lodging_area_m2 / rice_area_m2 * 100", "description": "Denominator is drone rice area, not the entire ROI footprint or satellite rice area."},
    }
    source_entries = []
    for source_file in sorted(path for path in source.rglob("*") if path.is_file()):
        source_file.resolve().relative_to(source)
        digest = hashlib.sha256()
        with source_file.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        source_entries.append({"path": source_file.relative_to(source).as_posix(), "bytes": source_file.stat().st_size, "sha256": digest.hexdigest()})
    source_manifest = {"version": 1, "algorithm": "sha256", "files": source_entries}
    manifest_bytes = (json.dumps(source_manifest, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    (destination / "source-manifest.json").write_bytes(manifest_bytes)
    scene = {
        "id": "hit-single-field", "title": "HIT smart farm · Satellite & drone survey", "version": 1,
        "description": "Eight fixed simulation tools: acquire, classify, post-process and present satellite imagery; survey, build an orthomosaic, identify fields and present drone results.",
        "mode": "offline-simulation", "imagery_date": "2025-08-14",
        "farm": {"id": "hit-smart-farm", "label": "HIT smart farm", "boundary": [[round(x, 8), round(y, 8)] for x, y in farm_polygon.exterior.coords], "bounds": [west, south, east, north], "area_m2": round(farm_area, 2), "width_m": round(farm_width, 2), "height_m": round(farm_height, 2)},
        "roi": {"id": "hit-rice-roi", "label": "Rice survey area", "polygon": [[round(x, 8), round(y, 8)] for x, y in roi.exterior.coords], "bounds": [x0, y0, x1, y1], "center": [(x0 + x1) / 2, (y0 + y1) / 2], "area_m2": round(roi_area, 2), "rice_fraction": round(rice_fraction, 4), "selection": "Rice-dense survey window with mixed edge pixels; preserves the drone orthomosaic aspect ratio"},
        "crops": crops,
        "cropGrid": {"width": width, "height": height, "values": classes.astype(int).ravel().tolist(), "noData": 0},
        "cropSamples": samples,
        "surfaceHints": terrain,
        "orthomosaicMetadata": orthomosaic_metadata,
        "assets": {"satelliteRgb": "assets/satellite-rgb.png", "satelliteMask": "assets/satellite-mask.png", "legend": "assets/legend.png", "droneResult": "assets/drone-result.jpg", "droneMask": "assets/drone-mask.png", "droneMaskSvg": "assets/drone-mask.svg", "orthomosaic": "assets/orthomosaic.png", **{key: "assets/" + target for key, (_, target) in processing_sources.items()}},
        "processingPreviews": {"identify_crop_type": {"asset": "processingClassify", "kind": "historical-log", "caption": "Historical classification log; the current demo statistics come from the clipped local raster."}, "post_process_results": {"asset": "processingPostprocess", "kind": "historical-log", "caption": "Historical post-processing log from the prepared source workflow."}, "raw_images_to_visible_orthomosaic": {"asset": "orthomosaic", "kind": "prepared-image", "caption": "Prepared orthomosaic; its placement in the satellite farm is simulated."}, "identify_field_distribution": {"asset": "processingFields", "kind": "historical-log", "caption": "Historical source log. Its old mock area constants differ from the re-anchored areas shown in this demo."}},
        "routes": {"satellite": [[-0.12, 0.38], [1.12, 0.62]], "drone": drone_route},
        "droneLayers": overlay_layers,
        "droneLocalLayers": local_layers,
        "droneMetrics": drone_metrics,
        "metricDefinitions": metric_definitions,
        "sourceVectorAreas_m2": source_vector_areas,
        "provenance": {"imagery": "Prepared local ARE demonstration outputs", "source_files": [str(path.relative_to(source)) for path in required], "source_manifest": "source-manifest.json", "source_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "registration": "Simulated anchored survey: the UAV image and vectors are intentionally placed into a rice-dense window of the satellite classification; mixed class pixels are retained.", "coordinates": "All scene XY use satellite image normalized coordinates: upper left [0,0], lower right [1,1].", "statistics": "Farm, crop and anchored UAV areas are calculated on the WGS84 ellipsoid; raster pixel areas and polygon boundaries may differ slightly.", "offline": True},
    }
    module_spec = importlib.util.spec_from_file_location("hit_simulation_tools", GUI_ROOT / "scenarios/hit/tools.py")
    if module_spec is None or module_spec.loader is None:
        raise ImportError("Cannot load local HIT tools")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    scene = module.HITSimulationTools(scene).run_oracle()
    (destination / "scenario.json").write_text(json.dumps(scene, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return scene


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=GUI_ROOT / "scenarios/hit/source", help="Read-only local package with HIT智慧农场/, clip_result/ and Drone_Graphical_Results/ (original input/output layout also supported).")
    parser.add_argument("--output", type=Path, default=GUI_ROOT / "scenarios/hit")
    args = parser.parse_args()
    scene = build(args.source, args.output)
    print(json.dumps({"output": str(args.output / "scenario.json"), "events": len(scene["events"]), "frames": len(scene["frames"]), "tools": len(scene["tools"]), "farm_area_m2": scene["farm"]["area_m2"], "roi_area_m2": scene["roi"]["area_m2"], "drone_metrics": scene["droneMetrics"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
