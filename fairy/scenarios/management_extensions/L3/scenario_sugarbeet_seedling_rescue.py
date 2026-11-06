"""L3: take over a dry, already sown beet crop with intact resource history."""

from datetime import timedelta

from ..apps.sugarbeet_farm_app import SugarBeetFarm
from ..sugarbeet.oracle import Policy, PublicController
from fairy.types import EventRegisterer
from ..common import capture_step, finish_capture
from ..sugarbeet.scenario import SugarBeetScenario


class DrySeedbedFarm(SugarBeetFarm):
    def block_inputs(self, block_id):
        return self.bundle.with_soil_profile(
            site={"WAV": 16.0},
            description="Engineering dry seedbed: initial available water 16 cm; uncalibrated",
        )


class ScenarioSugarBeetSeedlingRescue(SugarBeetScenario):
    scenario_id = "scenario_l3_sugarbeet_seedling_rescue"
    variant = "seedling_rescue"
    farm_class = DrySeedbedFarm
    yield_management = True

    def initialize_management_history(self):
        controller = PublicController(self)
        info = controller.call("ArableField", "get_field_info")
        sowed = controller.sow_cycle(info, Policy())
        controller.nitrogen(72.0, info)
        controller.until(sowed + timedelta(days=17))
        self.initialization_history = controller.trace
        self.farm.mission_context = dict(
            decision_start=controller.now().isoformat(),
            history="Prepared and sown through public tools; 72 kg pure N/ha applied; no irrigation before takeover",
            public_tool_history=[
                step
                for step in self.initialization_history
                if step["tool"]
                not in {
                    "get_current_time",
                    "get_status",
                    "get_inventory",
                    "get_field_info",
                    "inspect_blocks",
                }
            ],
            initial_soil_status="Engineering benchmark, not a measured drought episode",
        )

    def build_events_flow(self):
        """Capture this scene's complete, verified public-tool Oracle workflow."""
        if self.reference_file is not None:
            return self._build_reference_events_flow()
        self._validate_oracle_reference()
        with EventRegisterer.capture_mode() as events:
            previous = capture_step(
                None,
                self.aui.send_message_to_agent(self.scenario_input),
                "task",
                "Read crop and resource constraints",
            )
            if self.ORACLE_REFERENCE is not None:
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00000",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00001",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00002",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00003",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00004",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00005",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00006",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00007",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_fertilizer(kg=117.39130434782605),
                    "beet_00008",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.fertilize(
                        start_block=0, end_block=7, kg_per_block=7.336956521739128
                    ),
                    "beet_00009",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.fertilize(
                        start_block=8, end_block=15, kg_per_block=7.336956521739128
                    ),
                    "beet_00010",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=257580.0),
                    "beet_00011",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00012",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00013",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00014",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00015",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00016",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00017",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00018",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00019",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00020",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00021",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00022",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_fertilizer(kg=117.39130434782611),
                    "beet_00023",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.fertilize(
                        start_block=0, end_block=7, kg_per_block=7.336956521739132
                    ),
                    "beet_00024",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.fertilize(
                        start_block=8, end_block=15, kg_per_block=7.336956521739132
                    ),
                    "beet_00025",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=257580.0),
                    "beet_00026",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00027",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00028",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00029",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00030",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00031",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00032",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00033",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00034",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00035",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00036",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00037",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00038",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00039",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00040",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00041",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00042",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00043",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00044",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00045",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00046",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00047",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00048",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00049",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00050",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00051",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00052",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00053",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00054",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00055",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00056",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00057",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00058",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00059",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00060",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00061",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00062",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00063",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00064",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00065",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00066",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00067",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00068",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00069",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00070",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00071",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00072",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00073",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00074",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.detach_implement(),
                    "beet_00075",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.attach_implement(implement="beet_harvester"),
                    "beet_00076",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.refuel(liters=80.3595658073272),
                    "beet_00077",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=1),
                    "beet_00078",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=1),
                    "beet_00079",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=1),
                    "beet_00080",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=0, end_block=0, operation_id="lift:beet_2021:0"
                    ),
                    "beet_00081",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:0",
                        net_kg=2979.3310694649454,
                        operation_id="trip:beet_2021:1",
                    ),
                    "beet_00082",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=1, end_block=1, operation_id="lift:beet_2021:1"
                    ),
                    "beet_00083",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:1",
                        net_kg=2979.3310694649454,
                        operation_id="trip:beet_2021:2",
                    ),
                    "beet_00084",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=2, end_block=2, operation_id="lift:beet_2021:2"
                    ),
                    "beet_00085",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:2",
                        net_kg=2979.3310694649454,
                        operation_id="trip:beet_2021:3",
                    ),
                    "beet_00086",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=3, end_block=3, operation_id="lift:beet_2021:3"
                    ),
                    "beet_00087",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:3",
                        net_kg=2979.3310694649454,
                        operation_id="trip:beet_2021:4",
                    ),
                    "beet_00088",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=4, end_block=4, operation_id="lift:beet_2021:4"
                    ),
                    "beet_00089",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:4",
                        net_kg=2979.3310694649454,
                        operation_id="trip:beet_2021:5",
                    ),
                    "beet_00090",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=49125.0),
                    "beet_00091",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=5, end_block=5, operation_id="lift:beet_2021:5"
                    ),
                    "beet_00092",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:5",
                        net_kg=2982.006023562964,
                        operation_id="trip:beet_2021:6",
                    ),
                    "beet_00093",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=6, end_block=6, operation_id="lift:beet_2021:6"
                    ),
                    "beet_00094",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:6",
                        net_kg=2982.006023562964,
                        operation_id="trip:beet_2021:7",
                    ),
                    "beet_00095",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=7, end_block=7, operation_id="lift:beet_2021:7"
                    ),
                    "beet_00096",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:7",
                        net_kg=2982.006023562964,
                        operation_id="trip:beet_2021:8",
                    ),
                    "beet_00097",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=8, end_block=8, operation_id="lift:beet_2021:8"
                    ),
                    "beet_00098",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:8",
                        net_kg=2982.006023562964,
                        operation_id="trip:beet_2021:9",
                    ),
                    "beet_00099",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=9, end_block=9, operation_id="lift:beet_2021:9"
                    ),
                    "beet_00100",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:9",
                        net_kg=2982.006023562964,
                        operation_id="trip:beet_2021:10",
                    ),
                    "beet_00101",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=49125.0),
                    "beet_00102",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=10, end_block=10, operation_id="lift:beet_2021:10"
                    ),
                    "beet_00103",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:10",
                        net_kg=2984.559939752288,
                        operation_id="trip:beet_2021:11",
                    ),
                    "beet_00104",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=11, end_block=11, operation_id="lift:beet_2021:11"
                    ),
                    "beet_00105",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:11",
                        net_kg=2984.559939752288,
                        operation_id="trip:beet_2021:12",
                    ),
                    "beet_00106",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=12, end_block=12, operation_id="lift:beet_2021:12"
                    ),
                    "beet_00107",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:12",
                        net_kg=2984.559939752288,
                        operation_id="trip:beet_2021:13",
                    ),
                    "beet_00108",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=13, end_block=13, operation_id="lift:beet_2021:13"
                    ),
                    "beet_00109",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:13",
                        net_kg=2984.559939752288,
                        operation_id="trip:beet_2021:14",
                    ),
                    "beet_00110",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=14, end_block=14, operation_id="lift:beet_2021:14"
                    ),
                    "beet_00111",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:14",
                        net_kg=2984.559939752288,
                        operation_id="trip:beet_2021:15",
                    ),
                    "beet_00112",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=49125.0),
                    "beet_00113",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=15, end_block=15, operation_id="lift:beet_2021:15"
                    ),
                    "beet_00114",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:15",
                        net_kg=2987.2069711262475,
                        operation_id="trip:beet_2021:16",
                    ),
                    "beet_00115",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.return_supplies(),
                    "beet_00116",
                    "Apply declared policy using public observations",
                )
        return finish_capture(self, events)
