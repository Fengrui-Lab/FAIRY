"""Eight deterministic, offline tools for the HIT GUI demonstration.

No ARE, GEE, LLM, GIS library, clock sleeps, or network calls are used here.
Every instance is an isolated run; an oracle invokes the same public tools a
future agent would invoke. Generated images are fixtures, not live analyses.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any


START = "2025-08-14T09:00:00+08:00"
DEFINITIONS = [
    ("acquire_remote_sensing_images_gee", "Acquire satellite imagery", "equipment", "Satellite", "Return a prepared HIT smart farm image without connecting to Google Earth Engine.", {"locality": "string", "date_from": "string", "date_to": "string"}),
    ("identify_crop_type", "Classify crops", "processing", "Satellite", "Return prepared rice, maize, soybean and other land-cover classes with area statistics.", {"image_id": "string"}),
    ("post_process_results", "Post-process results", "processing", "Satellite", "Provide the clipped classification, transparent mask, legend and farm boundary.", {"classification_id": "string"}),
    ("show_remote_sensing_results", "Present satellite results", "presentation", "Satellite", "Present the satellite background, classification mask and crop statistics.", {"product_id": "string"}),
    ("send_drone_start_signal", "Start drone survey", "equipment", "Drone", "Simulate a survey of the selected rice area and return prepared image observations.", {"drone_id": "string", "roi_id": "string"}),
    ("raw_images_to_visible_orthomosaic", "Build orthomosaic", "processing", "Drone", "Return a prepared orthomosaic anchored to the selected rice survey area.", {"mission_id": "string"}),
    ("identify_field_distribution", "Identify fields & lodging", "processing", "Drone", "Return field, rice and lodging layers with areas recalculated after simulated placement.", {"orthomosaic_id": "string"}),
    ("show_drone_results", "Present drone results", "presentation", "Drone", "Present the orthomosaic, field, rice and lodging layers with summary statistics.", {"analysis_id": "string"}),
]


def tool_catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": name, "title": title, "category": category,
            "equipment": equipment, "description": description,
            "schema": {"type": "function", "function": {
                "name": name, "description": description,
                "parameters": {"type": "object", "properties": {
                    key: {"type": kind} for key, kind in parameters.items()
                }, "required": list(parameters), "additionalProperties": False},
            }},
        }
        for name, title, category, equipment, description, parameters in DEFINITIONS
    ]


class HITSimulationTools:
    """A stateful mock collection with strict prerequisites and fixture IDs."""

    def __init__(self, scene: dict[str, Any]):
        self.scene = deepcopy(scene)
        self.events: list[dict[str, Any]] = []
        self.frames = [self._frame()]

    def _validate(self, name: str, arguments: dict[str, Any]) -> None:
        if len(self.events) >= len(DEFINITIONS):
            raise ValueError("This run is complete; create a new instance to replay.")
        expected = DEFINITIONS[len(self.events)]
        if name != expected[0]:
            raise ValueError(f"Prerequisite not met: expected {expected[0]}, got {name}")
        parameters = expected[5]
        if set(arguments) != set(parameters):
            raise ValueError(f"{name} requires exactly {list(parameters)}")
        for key, value in arguments.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{key} must be a nonempty string")

    def call(self, name: str, **arguments: Any) -> dict[str, Any]:
        """Dispatch a registered tool through the same contract as direct calls."""
        if name not in {item[0] for item in DEFINITIONS}:
            raise ValueError(f"Unknown tool: {name}")
        return getattr(self, name)(**arguments)

    def _record(self, name: str, arguments: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        self._validate(name, arguments)
        index = len(self.events)
        _, title, category, equipment, _, _ = DEFINITIONS[index]
        sequence = index + 1
        event_id = f"hit-{sequence:02d}"
        result = {"status": "completed", "simulated": True, **deepcopy(result)}
        self.events.append({
            "sequence": sequence, "id": event_id, "title": title,
            "tool_name": name, "category": category, "equipment": equipment,
            "arguments": deepcopy(arguments), "result": result,
            "datetime_after": (datetime.fromisoformat(START) + timedelta(minutes=sequence * 2)).isoformat(),
            "depends_on": [self.events[-1]["id"]] if self.events else [],
            "duration_seconds": 120,
        })
        self.frames.append(self._frame())
        return deepcopy(result)

    @staticmethod
    def _require(actual: str, expected: str, name: str) -> None:
        if actual != expected:
            raise ValueError(f"{name} must reference {expected!r}")

    def acquire_remote_sensing_images_gee(self, locality: str, date_from: str, date_to: str) -> dict[str, Any]:
        self._require(locality, "HIT智慧农场", "locality")
        self._require(date_from, "2025-08-10", "date_from")
        self._require(date_to, "2025-08-20", "date_to")
        return self._record(DEFINITIONS[0][0], dict(locality=locality, date_from=date_from, date_to=date_to), {
            "image_id": "hit-satellite-20250814", "acquired_at": "2025-08-14",
            "rgb_url": self.scene["assets"]["satelliteRgb"], "bounds": self.scene["farm"]["bounds"],
            "source": "Local Sentinel fixture", "message": "Local satellite imagery from 2025-08-14 is ready.",
        })

    def identify_crop_type(self, image_id: str) -> dict[str, Any]:
        self._require(image_id, "hit-satellite-20250814", "image_id")
        return self._record(DEFINITIONS[1][0], dict(image_id=image_id), {
            "classification_id": "hit-crop-classification", "crops": self.scene["crops"],
            "preview_url": self.scene["assets"]["processingClassify"],
            "mask_url": self.scene["assets"]["satelliteMask"], "message": "Rice, maize, soybean and other land cover have been classified.",
        })

    def post_process_results(self, classification_id: str) -> dict[str, Any]:
        self._require(classification_id, "hit-crop-classification", "classification_id")
        return self._record(DEFINITIONS[2][0], dict(classification_id=classification_id), {
            "product_id": "hit-remote-sensing-product", "boundary": self.scene["farm"]["boundary"],
            "preview_url": self.scene["assets"]["processingPostprocess"],
            "mask_url": self.scene["assets"]["satelliteMask"], "legend_url": self.scene["assets"]["legend"],
            "message": "Farm clipping, classification colors and legend are ready.",
        })

    def show_remote_sensing_results(self, product_id: str) -> dict[str, Any]:
        self._require(product_id, "hit-remote-sensing-product", "product_id")
        return self._record(DEFINITIONS[3][0], dict(product_id=product_id), {
            "presentation_id": "hit-rs-presentation", "layers": ["satellite-rgb", "satellite-mask"],
            "selected_roi_id": self.scene["roi"]["id"], "message": "Satellite results are presented and the rice survey area is selected.",
        })

    def send_drone_start_signal(self, drone_id: str, roi_id: str) -> dict[str, Any]:
        self._require(drone_id, "DRONE_RICE_001", "drone_id")
        self._require(roi_id, self.scene["roi"]["id"], "roi_id")
        return self._record(DEFINITIONS[4][0], dict(drone_id=drone_id, roi_id=roi_id), {
            "mission_id": "hit-drone-mission", "drone_id": drone_id, "mission_status": "completed",
            "route": self.scene["routes"]["drone"], "raw_images_id": "hit-drone-raw-fixture",
            "message": "The simulated drone survey of the selected rice area is complete.",
        })

    def raw_images_to_visible_orthomosaic(self, mission_id: str) -> dict[str, Any]:
        self._require(mission_id, "hit-drone-mission", "mission_id")
        return self._record(DEFINITIONS[5][0], dict(mission_id=mission_id), {
            "orthomosaic_id": "hit-drone-orthomosaic", "image_url": self.scene["assets"]["orthomosaic"],
            "roi_id": self.scene["roi"]["id"], "bounds": self.scene["roi"]["bounds"],
            "message": "The orthomosaic is anchored to the selected rice survey area.",
        })

    def identify_field_distribution(self, orthomosaic_id: str) -> dict[str, Any]:
        self._require(orthomosaic_id, "hit-drone-orthomosaic", "orthomosaic_id")
        return self._record(DEFINITIONS[6][0], dict(orthomosaic_id=orthomosaic_id), {
            "analysis_id": "hit-drone-analysis", "layers": ["field", "rice", "lodging"],
            "preview_url": self.scene["assets"]["processingFields"],
            "metrics": self.scene["droneMetrics"], "mask_url": self.scene["assets"]["droneMask"],
            "message": "Field, rice and lodging analysis is complete.",
        })

    def show_drone_results(self, analysis_id: str) -> dict[str, Any]:
        self._require(analysis_id, "hit-drone-analysis", "analysis_id")
        return self._record(DEFINITIONS[7][0], dict(analysis_id=analysis_id), {
            "presentation_id": "hit-drone-presentation", "image_url": self.scene["assets"]["droneResult"],
            "mask_url": self.scene["assets"]["droneMask"], "metrics": self.scene["droneMetrics"],
            "message": "Drone imagery, analysis layers and lodging statistics are presented.",
        })

    def _frame(self) -> dict[str, Any]:
        n = len(self.events)
        center = self.scene["roi"]["center"]
        satellite_route = self.scene["routes"]["satellite"]
        drone_route = self.scene["routes"]["drone"]
        layers = ["farm", "crop-geometry"]
        if n >= 1:
            layers.append("satellite-rgb")
        if n >= 3:
            layers.append("satellite-mask")
        if n >= 5:
            layers.extend(["roi", "drone-route"])
        if n >= 6:
            layers.append("orthomosaic")
        if n >= 7:
            layers.append("drone-mask")
        return {
            "index": n, "sequence": n,
            "datetime": self.events[-1]["datetime_after"] if n else START,
            "label": self.events[-1]["title"] if n else "HIT smart farm · Ready",
            "completedTools": [event["tool_name"] for event in self.events],
            "visibleLayers": layers,
            "equipment": {
                "Satellite": {"status": "completed" if n else "ready", "progress": 1 if n else 0, "position": satellite_route[-1] if n else satellite_route[0]},
                "Drone": {"status": "completed" if n >= 5 else "ready", "progress": 1 if n >= 5 else 0, "position": drone_route[-1] if n >= 5 else drone_route[0]},
            },
            "artifacts": {
                "satellite": n >= 1, "classification": n >= 2, "remoteSensingPresented": n >= 4,
                "orthomosaic": n >= 6, "droneAnalysis": n >= 7, "dronePresented": n >= 8,
            },
            "metrics": {"crops": deepcopy(self.scene["crops"]) if n >= 2 else [], "drone": deepcopy(self.scene["droneMetrics"]) if n >= 7 else None},
            "selectedRoi": self.scene["roi"]["id"] if n >= 4 else None,
            "focus": center if n >= 5 else [0.5, 0.5],
        }

    def run_oracle(self) -> dict[str, Any]:
        if self.events:
            raise ValueError("run_oracle requires a fresh run")
        image = self.acquire_remote_sensing_images_gee("HIT智慧农场", "2025-08-10", "2025-08-20")
        classification = self.identify_crop_type(image["image_id"])
        processed = self.post_process_results(classification["classification_id"])
        selected = self.show_remote_sensing_results(processed["product_id"])
        mission = self.send_drone_start_signal("DRONE_RICE_001", selected["selected_roi_id"])
        ortho = self.raw_images_to_visible_orthomosaic(mission["mission_id"])
        analysis = self.identify_field_distribution(ortho["orthomosaic_id"])
        self.show_drone_results(analysis["analysis_id"])
        result = deepcopy(self.scene)
        result.update(events=deepcopy(self.events), frames=deepcopy(self.frames), tools=tool_catalog())
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path(__file__).with_name("scenario.json"))
    parser.add_argument("--output", type=Path, help="Optional JSON export; without it only a summary is printed.")
    args = parser.parse_args()
    scene = json.loads(args.input.read_text(encoding="utf-8"))
    for key in ("events", "frames", "tools"):
        scene.pop(key, None)
    result = HITSimulationTools(scene).run_oracle()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({"scenario": result["id"], "tools": len(result["tools"]), "events": len(result["events"]), "frames": len(result["frames"]), "offline": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
