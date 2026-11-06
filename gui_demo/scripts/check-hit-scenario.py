#!/usr/bin/env python3
"""Read-only, standard-library acceptance checks for the local HIT demo.

Reads generated data, assets and the copied source package. No network,
temporary files, bytecode, source updates or cleanup operations are used.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path, PurePosixPath
import sys

sys.dont_write_bytecode = True

EXPECTED_TOOLS = (
    "acquire_remote_sensing_images_gee", "identify_crop_type",
    "post_process_results", "show_remote_sensing_results",
    "send_drone_start_signal", "raw_images_to_visible_orthomosaic",
    "identify_field_distribution", "show_drone_results",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"Duplicate JSON key {key!r} in {path.name}")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)


def local_file(root, relative):
    require(isinstance(relative, str) and bool(relative), "Expected a relative file path")
    parsed = PurePosixPath(relative)
    require(not parsed.is_absolute() and ".." not in parsed.parts and ":" not in relative and "\\" not in relative, f"Unsafe relative path: {relative}")
    path = (root / relative).resolve()
    require(path.is_relative_to(root.resolve()), f"Path leaves its local directory: {relative}")
    require(path.is_file(), f"Missing local file: {relative}")
    return path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def number(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def ring_area(ring):
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]))) / 2


def inside(point, ring):
    """Ray casting with a small boundary tolerance for rounded coordinates."""
    x, y = point
    result = False
    for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1]):
        cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
        if abs(cross) < 1e-9 and min(ax, bx) - 1e-8 <= x <= max(ax, bx) + 1e-8 and min(ay, by) - 1e-8 <= y <= max(ay, by) + 1e-8:
            return True
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            result = not result
    return result


def validate_ring(ring, label):
    require(isinstance(ring, list) and len(ring) >= 4 and ring[0] == ring[-1], f"{label} is not a closed polygon ring")
    require(all(len(p) == 2 and all(number(v) and -1e-7 <= v <= 1 + 1e-7 for v in p) for p in ring), f"{label} has invalid normalized coordinates")
    require(ring_area(ring) > 0, f"{label} has no area")


def rejected_without_mutation(run, operation, label):
    before = deepcopy(run.__dict__)
    try:
        operation()
    except (ValueError, TypeError):
        pass
    else:
        raise ValueError(f"Invalid input was accepted: {label}")
    require(run.__dict__ == before, f"Rejected input mutated run state: {label}")


def check(scenario_path, source_override=None):
    root = scenario_path.resolve().parent
    scene = read_json(scenario_path)
    tools, events, frames = scene["tools"], scene["events"], scene["frames"]
    require((len(tools), len(events), len(frames)) == (8, 8, 9), "Expected 8 tools, 8 events and 9 frames")
    require(tuple(item["name"] for item in tools) == EXPECTED_TOOLS, "Unexpected tool catalog/order")
    require(tuple(event["tool_name"] for event in events) == EXPECTED_TOOLS, "Unexpected executed tool order")
    require(Counter(event["category"] for event in events) == {"equipment": 2, "processing": 4, "presentation": 2}, "Expected category counts 2/4/2")
    expected_categories = ("equipment", "processing", "processing", "presentation", "equipment", "processing", "processing", "presentation")
    for index, (tool, event) in enumerate(zip(tools, events), start=1):
        require(event["id"] == f"hit-{index:02d}" and event["sequence"] == index, "Event IDs or sequence are not contiguous")
        require(event["depends_on"] == ([f"hit-{index - 1:02d}"] if index > 1 else []), f"Broken predecessor at event {index}")
        require(event["equipment"] == ("Satellite" if index <= 4 else "Drone"), f"Wrong equipment at event {index}")
        require(tool["category"] == event["category"] == expected_categories[index - 1], f"Wrong category at event {index}")
        require(tool["schema"]["function"]["name"] == tool["name"], f"Schema name mismatch at tool {index}")
        require(event["result"].get("simulated") is True, f"Event {index} is not marked simulated")
    for index, input_key, previous_output in [
        (1, "image_id", "image_id"), (2, "classification_id", "classification_id"),
        (3, "product_id", "product_id"), (4, "roi_id", "selected_roi_id"),
        (5, "mission_id", "mission_id"), (6, "orthomosaic_id", "orthomosaic_id"),
        (7, "analysis_id", "analysis_id"),
    ]:
        require(events[index]["arguments"][input_key] == events[index - 1]["result"][previous_output], f"Broken artifact reference at event {index + 1}")

    module_spec = importlib.util.spec_from_file_location("hit_acceptance_tools", local_file(root, "tools.py"))
    require(module_spec is not None and module_spec.loader is not None, "Cannot import local mock tools")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    require(module.HITSimulationTools(scene).run_oracle() == scene, "Fresh oracle differs from the checked-in bundle")
    require(module.HITSimulationTools(scene).run_oracle() == scene, "Repeated fresh oracle is not deterministic")
    run = module.HITSimulationTools(scene)
    rejected_without_mutation(run, lambda: run.call("unknown_tool"), "unknown tool")
    rejected_without_mutation(run, lambda: run.identify_crop_type("hit-satellite-20250814"), "classification before acquisition")
    rejection_count = 2
    for index, event in enumerate(events):
        arguments = deepcopy(event["arguments"])
        # Test the public tool dispatcher with an unknown fixture/artifact ID
        # at every stage, not merely compare implementation-generated metadata.
        key = "roi_id" if index == 4 else next(iter(arguments))
        invalid = {**arguments, key: "__unknown_fixture_id__"}
        rejected_without_mutation(run, lambda e=event, a=invalid: run.call(e["tool_name"], **a), f"unknown ID at step {index + 1}")
        rejected_without_mutation(run, lambda e=event, a=arguments: run.call(e["tool_name"], **a, unexpected="value"), f"extra argument at step {index + 1}")
        rejection_count += 2
        result = run.call(event["tool_name"], **arguments)
        require(result == event["result"], f"Public call returned different output at step {index + 1}")
        rejected_without_mutation(run, lambda e=event, a=arguments: run.call(e["tool_name"], **a), f"duplicate step {index + 1}")
        rejection_count += 1
    rejected_without_mutation(run, run.run_oracle, "oracle restart on completed instance")
    rejection_count += 1

    for index, frame in enumerate(frames):
        require(frame["index"] == frame["sequence"] == index, f"Bad frame index {index}")
        require(frame["completedTools"] == list(EXPECTED_TOOLS[:index]), f"Future/completed tools leaked into frame {index}")
        layers, artifacts = frame["visibleLayers"], frame["artifacts"]
        require(("satellite-mask" in layers) == (index >= 3), f"Satellite mask gate violated in frame {index}")
        require(("drone-mask" in layers) == (index >= 7), f"Drone mask gate violated in frame {index}")
        require(artifacts["remoteSensingPresented"] == (index >= 4), f"Satellite presentation gate violated in frame {index}")
        require(artifacts["dronePresented"] == (index >= 8), f"Drone presentation gate violated in frame {index}")
        for field, threshold in [("satellite", 1), ("classification", 2), ("orthomosaic", 6), ("droneAnalysis", 7)]:
            require(artifacts[field] == (index >= threshold), f"Premature {field} artifact in frame {index}")
        require((frame["metrics"]["crops"] == scene["crops"]) if index >= 2 else frame["metrics"]["crops"] == [], f"Premature/missing crop metrics in frame {index}")
        require((frame["metrics"]["drone"] == scene["droneMetrics"]) if index >= 7 else frame["metrics"]["drone"] is None, f"Premature/missing drone metrics in frame {index}")

    asset_root = (root / "assets").resolve()
    for asset in scene["assets"].values():
        require(local_file(root, asset).is_relative_to(asset_root), f"Asset is outside local assets/: {asset}")
    preview_assets = {"identify_crop_type": "processingClassify", "post_process_results": "processingPostprocess", "raw_images_to_visible_orthomosaic": "orthomosaic", "identify_field_distribution": "processingFields"}
    require(set(scene["processingPreviews"]) == set(preview_assets), "Expected four processing previews")
    for name, asset_key in preview_assets.items():
        require(scene["processingPreviews"][name]["asset"] == asset_key and asset_key in scene["assets"], f"Wrong processing asset for {name}")
    farm, roi, metrics = scene["farm"], scene["roi"], scene["droneMetrics"]
    validate_ring(farm["boundary"], "Farm boundary")
    validate_ring(roi["polygon"], "Survey ROI")
    for start, end in zip(roi["polygon"], roi["polygon"][1:]):
        for fraction in (0, .25, .5, .75, 1):
            point = [a + (b - a) * fraction for a, b in zip(start, end)]
            require(inside(point, farm["boundary"]), "Survey ROI leaves farm boundary")
    for layer in scene["droneLayers"]:
        geometry = layer["geometry"]
        require(geometry["type"] in ("Polygon", "MultiPolygon"), "Unsupported drone vector shape")
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        for polygon in polygons:
            for ring in polygon:
                validate_ring(ring, f"Drone {layer['id']} ring")
                require(all(inside(point, roi["polygon"]) for point in ring), f"Drone {layer['id']} leaves the survey ROI")
    raster_area = farm["width_m"] * farm["height_m"]
    require(all(number(v) and v > 0 for v in [farm["area_m2"], roi["area_m2"], raster_area]), "Invalid farm/ROI area")
    require(abs(ring_area(farm["boundary"]) * raster_area / farm["area_m2"] - 1) < .03, "Farm area is inconsistent with its shape")
    require(abs(ring_area(roi["polygon"]) * raster_area / roi["area_m2"] - 1) < .03, "ROI area is inconsistent with its shape")
    require(0 < metrics["lodging_area_m2"] <= metrics["rice_area_m2"] <= metrics["field_area_m2"] <= roi["area_m2"] < farm["area_m2"], "Drone area relationships are invalid")
    require(abs(metrics["lodging_percent"] - metrics["lodging_area_m2"] / metrics["rice_area_m2"] * 100) <= .02, "Lodging percentage disagrees with areas")
    grid = scene["cropGrid"]
    require(len(grid["values"]) == grid["width"] * grid["height"], "Crop grid dimensions mismatch")
    require(set(grid["values"]) <= {0, 1, 2, 3, 4}, "Unknown crop class")
    counts = Counter(grid["values"])
    for crop in scene["crops"]:
        require(crop["pixel_count"] == counts[crop["classId"]], "Crop counts disagree with classification grid")
        expected_area = counts[crop["classId"]] / len(grid["values"]) * raster_area
        require(abs(crop["area_m2"] / expected_area - 1) < .03, f"Crop area disagrees with grid for {crop['id']}")
    definitions = scene["metricDefinitions"]
    expected_metrics = {"farmArea": farm["area_m2"] / 10000, "satelliteRiceArea": next(c["area_m2"] for c in scene["crops"] if c["classId"] == 1) / 10000, "surveyFootprint": roi["area_m2"] / 10000, "droneRiceArea": metrics["rice_area_m2"] / 10000, "droneLodgingArea": metrics["lodging_area_m2"], "lodgingRate": metrics["lodging_percent"]}
    for key, expected in expected_metrics.items():
        require(abs(definitions[key]["value"] - expected) < 1e-5 and all(definitions[key].get(field) for field in ("scope", "source", "formula", "description")), f"Missing or inconsistent metric definition: {key}")
    ortho = scene["orthomosaicMetadata"]
    require(abs(ortho["width_px"] / ortho["height_px"] - ortho["aspect_ratio"]) < .005, "Orthomosaic preview aspect is distorted")
    require(abs(ortho["display_aspect_ratio"] - ortho["aspect_ratio"]) < .02, "Drone footprint does not preserve source aspect")
    require(abs(ortho["footprint_width_m"] * ortho["footprint_height_m"] / roi["area_m2"] - 1) < .01, "Orthomosaic footprint area disagrees with ROI")
    terrain = scene["surfaceHints"]
    require("illustrative" in terrain["method"].lower(), "RGB surface hints must be described as illustrative")
    require(terrain["buildings"] and terrain["roads"] and terrain["fieldSamples"], "Missing illustrated building, road or field samples")
    require(terrain["fieldSamples"] == scene["cropSamples"], "Scene and surface crop samples disagree")
    surface_by_position = {(sample["x"], sample["y"]): sample for sample in terrain["surfaceSamples"]}
    for sample in scene["cropSamples"]:
        require(sample["classId"] in (1, 2, 3), "Other land cover must not become planted crop instances")
        require(surface_by_position.get((sample["x"], sample["y"]), {}).get("kind") == "vegetation", "A building, road or bare patch contains crop instances")
        row, column = int(sample["y"] * grid["height"]), int(sample["x"] * grid["width"])
        require(grid["values"][row * grid["width"] + column] == sample["classId"], "Crop sample does not match its source class")
    for layer in scene["droneLocalLayers"]:
        geometry = layer["geometry"]
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        for polygon in polygons:
            for ring in polygon:
                validate_ring(ring, f"Local drone {layer['id']}")

    provenance = scene["provenance"]
    manifest_path = local_file(root, provenance["source_manifest"])
    require(sha256(manifest_path) == provenance["source_manifest_sha256"], "Source manifest digest differs from scene provenance")
    manifest = read_json(manifest_path)
    require(manifest["algorithm"] == "sha256", "Unexpected source hash algorithm")
    source = (source_override or root / "source").resolve()
    require(source.is_dir(), "Local source package is missing")
    manifest_names = [entry["path"] for entry in manifest["files"]]
    require(len(set(manifest_names)) == len(manifest_names), "Duplicate source manifest paths")
    require(set(provenance["source_files"]) <= set(manifest_names), "Provenance references an unhashed source file")
    require({path.relative_to(source).as_posix() for path in source.rglob("*") if path.is_file()} == set(manifest_names), "Source package files differ from the manifest")
    for entry in manifest["files"]:
        path = local_file(source, entry["path"])
        require(path.stat().st_size == entry["bytes"] and sha256(path) == entry["sha256"], f"Source hash mismatch: {entry['path']}")
    manifest_hashes = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
    for asset_key, source_name in [("processingClassify", "Classify crops.png"), ("processingPostprocess", "Post-process results.png"), ("processingFields", "Identify fields & lodging.png")]:
        require(sha256(local_file(root, scene["assets"][asset_key])) == manifest_hashes[source_name], f"Historical processing image was altered: {source_name}")
    return {"ok": True, "tools": 8, "events": 8, "frames": 9, "rejected_invalid_calls": rejection_count, "assets": len(scene["assets"]), "verified_source_files": len(manifest_names), "checks": ["fixed_order", "fresh_oracle_matches", "invalid_input_no_mutation", "no_premature_results", "local_assets", "geometry_and_areas", "metric_scopes", "processing_image_integrity", "illustrative_surface_samples", "source_sha256"], "read_only": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path(__file__).resolve().parents[1] / "scenarios/hit/scenario.json")
    parser.add_argument("--source", type=Path, help="Optional local source package override")
    args = parser.parse_args()
    try:
        result = check(args.scenario, args.source)
    except (ValueError, KeyError, TypeError, OSError, ImportError, AttributeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
