"""L4: winter wheat, explicit fallow, next-year spring beet on identical land."""

from fairy.types import EventRegisterer
from ..common import capture_step, finish_capture
from ..sugarbeet.scenario import SugarBeetScenario


class ScenarioWheatSugarBeetRotation(SugarBeetScenario):
    scenario_id = "scenario_l4_wheat_sugarbeet_rotation"
    variant = "rotation"
    level = "L4"
    rotation = True
    objective_metric = "rotation_yield"

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
                    self.system.advance_time(days=4),
                    "beet_00000",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.attach_implement(implement="grader"),
                    "beet_00001",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=1),
                    "beet_00002",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.prepare_field(),
                    "beet_00003",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.detach_implement(),
                    "beet_00004",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.attach_implement(implement="seeder"),
                    "beet_00005",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                    "beet_00006",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=0, end_block=0, depth_cm=3.0),
                    "beet_00007",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                    "beet_00008",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=1, end_block=1, depth_cm=3.0),
                    "beet_00009",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                    "beet_00010",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=2, end_block=2, depth_cm=3.0),
                    "beet_00011",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                    "beet_00012",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=3, end_block=3, depth_cm=3.0),
                    "beet_00013",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                    "beet_00014",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=4, end_block=4, depth_cm=3.0),
                    "beet_00015",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                    "beet_00016",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=5, end_block=5, depth_cm=3.0),
                    "beet_00017",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                    "beet_00018",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=6, end_block=6, depth_cm=3.0),
                    "beet_00019",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                    "beet_00020",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=7, end_block=7, depth_cm=3.0),
                    "beet_00021",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                    "beet_00022",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=8, end_block=8, depth_cm=3.0),
                    "beet_00023",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                    "beet_00024",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=9, end_block=9, depth_cm=3.0),
                    "beet_00025",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                    "beet_00026",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=10, end_block=10, depth_cm=3.0),
                    "beet_00027",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                    "beet_00028",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=11, end_block=11, depth_cm=3.0),
                    "beet_00029",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                    "beet_00030",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=12, end_block=12, depth_cm=3.0),
                    "beet_00031",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                    "beet_00032",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=13, end_block=13, depth_cm=3.0),
                    "beet_00033",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                    "beet_00034",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=14, end_block=14, depth_cm=3.0),
                    "beet_00035",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                    "beet_00036",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=15, end_block=15, depth_cm=3.0),
                    "beet_00037",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=249304.0),
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
                    self.system.advance_time(days=3),
                    "beet_00041",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_fertilizer(kg=182.6086956521739),
                    "beet_00042",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.fertilize(
                        start_block=0, end_block=7, kg_per_block=11.41304347826087
                    ),
                    "beet_00043",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.fertilize(
                        start_block=8, end_block=15, kg_per_block=11.41304347826087
                    ),
                    "beet_00044",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=257580.0),
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
                    self.system.advance_time(days=3),
                    "beet_00075",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00076",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00077",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00078",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00079",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00080",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00081",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00082",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00083",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00084",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00085",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00086",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00087",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00088",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00089",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00090",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00091",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00092",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_fertilizer(kg=136.95652173913044),
                    "beet_00093",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.fertilize(
                        start_block=0, end_block=7, kg_per_block=8.559782608695652
                    ),
                    "beet_00094",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.fertilize(
                        start_block=8, end_block=15, kg_per_block=8.559782608695652
                    ),
                    "beet_00095",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=257580.0),
                    "beet_00096",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00097",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00098",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00099",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00100",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00101",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00102",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00103",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00104",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_fertilizer(kg=136.95652173913044),
                    "beet_00105",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.fertilize(
                        start_block=0, end_block=7, kg_per_block=8.559782608695652
                    ),
                    "beet_00106",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.fertilize(
                        start_block=8, end_block=15, kg_per_block=8.559782608695652
                    ),
                    "beet_00107",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=257580.0),
                    "beet_00108",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00109",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00110",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00111",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00112",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00113",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00114",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00115",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00116",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00117",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00118",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00119",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00120",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00121",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00122",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00123",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00124",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00125",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00126",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00127",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00128",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00129",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00130",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00131",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00132",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00133",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00134",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00135",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00136",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00137",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00138",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00139",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00140",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00141",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.detach_implement(),
                    "beet_00142",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.attach_implement(implement="harvester"),
                    "beet_00143",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.refuel(liters=80.3595658073272),
                    "beet_00144",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=1),
                    "beet_00145",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=1),
                    "beet_00146",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=1),
                    "beet_00147",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=1),
                    "beet_00148",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=1),
                    "beet_00149",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_blocks(start_block=0, end_block=0),
                    "beet_00150",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.unload_grain(batch_id="wheat_2020:grain:0"),
                    "beet_00151",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.dry_grain(
                        batch_id="wheat_2020:grain:0", target_moisture_pct=12.5
                    ),
                    "beet_00152",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.store_grain(batch_id="wheat_2020:grain:0"),
                    "beet_00153",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_blocks(start_block=1, end_block=1),
                    "beet_00154",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.unload_grain(batch_id="wheat_2020:grain:1"),
                    "beet_00155",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.dry_grain(
                        batch_id="wheat_2020:grain:1", target_moisture_pct=12.5
                    ),
                    "beet_00156",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.store_grain(batch_id="wheat_2020:grain:1"),
                    "beet_00157",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_blocks(start_block=2, end_block=2),
                    "beet_00158",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.unload_grain(batch_id="wheat_2020:grain:2"),
                    "beet_00159",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.dry_grain(
                        batch_id="wheat_2020:grain:2", target_moisture_pct=12.5
                    ),
                    "beet_00160",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.store_grain(batch_id="wheat_2020:grain:2"),
                    "beet_00161",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_blocks(start_block=3, end_block=3),
                    "beet_00162",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.unload_grain(batch_id="wheat_2020:grain:3"),
                    "beet_00163",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.dry_grain(
                        batch_id="wheat_2020:grain:3", target_moisture_pct=12.5
                    ),
                    "beet_00164",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.store_grain(batch_id="wheat_2020:grain:3"),
                    "beet_00165",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_blocks(start_block=4, end_block=4),
                    "beet_00166",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.unload_grain(batch_id="wheat_2020:grain:4"),
                    "beet_00167",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.dry_grain(
                        batch_id="wheat_2020:grain:4", target_moisture_pct=12.5
                    ),
                    "beet_00168",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.store_grain(batch_id="wheat_2020:grain:4"),
                    "beet_00169",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_blocks(start_block=5, end_block=5),
                    "beet_00170",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.unload_grain(batch_id="wheat_2020:grain:5"),
                    "beet_00171",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.dry_grain(
                        batch_id="wheat_2020:grain:5", target_moisture_pct=12.5
                    ),
                    "beet_00172",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.store_grain(batch_id="wheat_2020:grain:5"),
                    "beet_00173",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_blocks(start_block=6, end_block=6),
                    "beet_00174",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.unload_grain(batch_id="wheat_2020:grain:6"),
                    "beet_00175",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.dry_grain(
                        batch_id="wheat_2020:grain:6", target_moisture_pct=12.5
                    ),
                    "beet_00176",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.store_grain(batch_id="wheat_2020:grain:6"),
                    "beet_00177",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_blocks(start_block=7, end_block=7),
                    "beet_00178",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.unload_grain(batch_id="wheat_2020:grain:7"),
                    "beet_00179",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.dry_grain(
                        batch_id="wheat_2020:grain:7", target_moisture_pct=12.5
                    ),
                    "beet_00180",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.store_grain(batch_id="wheat_2020:grain:7"),
                    "beet_00181",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_blocks(start_block=8, end_block=8),
                    "beet_00182",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.unload_grain(batch_id="wheat_2020:grain:8"),
                    "beet_00183",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.dry_grain(
                        batch_id="wheat_2020:grain:8", target_moisture_pct=12.5
                    ),
                    "beet_00184",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.store_grain(batch_id="wheat_2020:grain:8"),
                    "beet_00185",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_blocks(start_block=9, end_block=9),
                    "beet_00186",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.unload_grain(batch_id="wheat_2020:grain:9"),
                    "beet_00187",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.dry_grain(
                        batch_id="wheat_2020:grain:9", target_moisture_pct=12.5
                    ),
                    "beet_00188",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.store_grain(batch_id="wheat_2020:grain:9"),
                    "beet_00189",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_blocks(start_block=10, end_block=10),
                    "beet_00190",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.unload_grain(batch_id="wheat_2020:grain:10"),
                    "beet_00191",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.dry_grain(
                        batch_id="wheat_2020:grain:10", target_moisture_pct=12.5
                    ),
                    "beet_00192",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.store_grain(batch_id="wheat_2020:grain:10"),
                    "beet_00193",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_blocks(start_block=11, end_block=11),
                    "beet_00194",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.unload_grain(batch_id="wheat_2020:grain:11"),
                    "beet_00195",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.dry_grain(
                        batch_id="wheat_2020:grain:11", target_moisture_pct=12.5
                    ),
                    "beet_00196",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.store_grain(batch_id="wheat_2020:grain:11"),
                    "beet_00197",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_blocks(start_block=12, end_block=12),
                    "beet_00198",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.unload_grain(batch_id="wheat_2020:grain:12"),
                    "beet_00199",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.dry_grain(
                        batch_id="wheat_2020:grain:12", target_moisture_pct=12.5
                    ),
                    "beet_00200",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.store_grain(batch_id="wheat_2020:grain:12"),
                    "beet_00201",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_blocks(start_block=13, end_block=13),
                    "beet_00202",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.unload_grain(batch_id="wheat_2020:grain:13"),
                    "beet_00203",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.dry_grain(
                        batch_id="wheat_2020:grain:13", target_moisture_pct=12.5
                    ),
                    "beet_00204",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.store_grain(batch_id="wheat_2020:grain:13"),
                    "beet_00205",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_blocks(start_block=14, end_block=14),
                    "beet_00206",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.unload_grain(batch_id="wheat_2020:grain:14"),
                    "beet_00207",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.dry_grain(
                        batch_id="wheat_2020:grain:14", target_moisture_pct=12.5
                    ),
                    "beet_00208",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.store_grain(batch_id="wheat_2020:grain:14"),
                    "beet_00209",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_blocks(start_block=15, end_block=15),
                    "beet_00210",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.unload_grain(batch_id="wheat_2020:grain:15"),
                    "beet_00211",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.dry_grain(
                        batch_id="wheat_2020:grain:15", target_moisture_pct=12.5
                    ),
                    "beet_00212",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.warehouse.store_grain(batch_id="wheat_2020:grain:15"),
                    "beet_00213",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.return_supplies(),
                    "beet_00214",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=23402880.0),
                    "beet_00215",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.farm.begin_next_cycle(),
                    "beet_00216",
                    "Same field: preserve native water/N and shared stores",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=12),
                    "beet_00217",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.detach_implement(),
                    "beet_00218",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.attach_implement(implement="grader"),
                    "beet_00219",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.prepare_field(),
                    "beet_00220",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.detach_implement(),
                    "beet_00221",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.attach_implement(implement="seeder"),
                    "beet_00222",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00223",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=0, end_block=0, depth_cm=2.5),
                    "beet_00224",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00225",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=1, end_block=1, depth_cm=2.5),
                    "beet_00226",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00227",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=2, end_block=2, depth_cm=2.5),
                    "beet_00228",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00229",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=3, end_block=3, depth_cm=2.5),
                    "beet_00230",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00231",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=4, end_block=4, depth_cm=2.5),
                    "beet_00232",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00233",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=5, end_block=5, depth_cm=2.5),
                    "beet_00234",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00235",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=6, end_block=6, depth_cm=2.5),
                    "beet_00236",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00237",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=7, end_block=7, depth_cm=2.5),
                    "beet_00238",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00239",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=8, end_block=8, depth_cm=2.5),
                    "beet_00240",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00241",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=9, end_block=9, depth_cm=2.5),
                    "beet_00242",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00243",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=10, end_block=10, depth_cm=2.5),
                    "beet_00244",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00245",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=11, end_block=11, depth_cm=2.5),
                    "beet_00246",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00247",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=12, end_block=12, depth_cm=2.5),
                    "beet_00248",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00249",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=13, end_block=13, depth_cm=2.5),
                    "beet_00250",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00251",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=14, end_block=14, depth_cm=2.5),
                    "beet_00252",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00253",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=15, end_block=15, depth_cm=2.5),
                    "beet_00254",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00255",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=227404.0),
                    "beet_00256",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00257",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_fertilizer(kg=156.52173913043478),
                    "beet_00258",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.fertilize(
                        start_block=0, end_block=7, kg_per_block=9.782608695652174
                    ),
                    "beet_00259",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.fertilize(
                        start_block=8, end_block=15, kg_per_block=9.782608695652174
                    ),
                    "beet_00260",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=257580.0),
                    "beet_00261",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00262",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00263",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00264",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00265",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00266",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00267",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00268",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00269",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_fertilizer(kg=117.39130434782608),
                    "beet_00270",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.fertilize(
                        start_block=0, end_block=7, kg_per_block=7.33695652173913
                    ),
                    "beet_00271",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.refuel(liters=84.09090909090929),
                    "beet_00272",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.fertilize(
                        start_block=8, end_block=15, kg_per_block=7.33695652173913
                    ),
                    "beet_00273",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=257580.0),
                    "beet_00274",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00275",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00276",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00277",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00278",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00279",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00280",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00281",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00282",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00283",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00284",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00285",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00286",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_fertilizer(kg=117.39130434782608),
                    "beet_00287",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.fertilize(
                        start_block=0, end_block=7, kg_per_block=7.33695652173913
                    ),
                    "beet_00288",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.fertilize(
                        start_block=8, end_block=15, kg_per_block=7.33695652173913
                    ),
                    "beet_00289",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=257580.0),
                    "beet_00290",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00291",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00292",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00293",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00294",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00295",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00296",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00297",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00298",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00299",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00300",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00301",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00302",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00303",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00304",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00305",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00306",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00307",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00308",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00309",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00310",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00311",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00312",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00313",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00314",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00315",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00316",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00317",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00318",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00319",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00320",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00321",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00322",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00323",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00324",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00325",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00326",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00327",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00328",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00329",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00330",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00331",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00332",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00333",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00334",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00335",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00336",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00337",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.detach_implement(),
                    "beet_00338",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.attach_implement(implement="beet_harvester"),
                    "beet_00339",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=0, end_block=0, operation_id="lift:beet_2021:0"
                    ),
                    "beet_00340",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:0",
                        net_kg=2711.684583356931,
                        operation_id="trip:beet_2021:1",
                    ),
                    "beet_00341",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=1, end_block=1, operation_id="lift:beet_2021:1"
                    ),
                    "beet_00342",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:1",
                        net_kg=2711.684583356931,
                        operation_id="trip:beet_2021:2",
                    ),
                    "beet_00343",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=2, end_block=2, operation_id="lift:beet_2021:2"
                    ),
                    "beet_00344",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:2",
                        net_kg=2711.684583356931,
                        operation_id="trip:beet_2021:3",
                    ),
                    "beet_00345",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=3, end_block=3, operation_id="lift:beet_2021:3"
                    ),
                    "beet_00346",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:3",
                        net_kg=2711.684583356931,
                        operation_id="trip:beet_2021:4",
                    ),
                    "beet_00347",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=4, end_block=4, operation_id="lift:beet_2021:4"
                    ),
                    "beet_00348",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:4",
                        net_kg=2711.684583356931,
                        operation_id="trip:beet_2021:5",
                    ),
                    "beet_00349",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=49125.0),
                    "beet_00350",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=5, end_block=5, operation_id="lift:beet_2021:5"
                    ),
                    "beet_00351",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:5",
                        net_kg=2711.684583356931,
                        operation_id="trip:beet_2021:6",
                    ),
                    "beet_00352",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=6, end_block=6, operation_id="lift:beet_2021:6"
                    ),
                    "beet_00353",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:6",
                        net_kg=2711.684583356931,
                        operation_id="trip:beet_2021:7",
                    ),
                    "beet_00354",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=7, end_block=7, operation_id="lift:beet_2021:7"
                    ),
                    "beet_00355",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:7",
                        net_kg=2711.684583356931,
                        operation_id="trip:beet_2021:8",
                    ),
                    "beet_00356",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=8, end_block=8, operation_id="lift:beet_2021:8"
                    ),
                    "beet_00357",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:8",
                        net_kg=2711.684583356931,
                        operation_id="trip:beet_2021:9",
                    ),
                    "beet_00358",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=9, end_block=9, operation_id="lift:beet_2021:9"
                    ),
                    "beet_00359",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:9",
                        net_kg=2711.684583356931,
                        operation_id="trip:beet_2021:10",
                    ),
                    "beet_00360",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=49125.0),
                    "beet_00361",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=1),
                    "beet_00362",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=1),
                    "beet_00363",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=1),
                    "beet_00364",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=10, end_block=10, operation_id="lift:beet_2021:10"
                    ),
                    "beet_00365",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:10",
                        net_kg=2711.684583356931,
                        operation_id="trip:beet_2021:11",
                    ),
                    "beet_00366",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=11, end_block=11, operation_id="lift:beet_2021:11"
                    ),
                    "beet_00367",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:11",
                        net_kg=2711.684583356931,
                        operation_id="trip:beet_2021:12",
                    ),
                    "beet_00368",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=12, end_block=12, operation_id="lift:beet_2021:12"
                    ),
                    "beet_00369",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:12",
                        net_kg=2711.684583356931,
                        operation_id="trip:beet_2021:13",
                    ),
                    "beet_00370",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=13, end_block=13, operation_id="lift:beet_2021:13"
                    ),
                    "beet_00371",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:13",
                        net_kg=2711.684583356931,
                        operation_id="trip:beet_2021:14",
                    ),
                    "beet_00372",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=14, end_block=14, operation_id="lift:beet_2021:14"
                    ),
                    "beet_00373",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:14",
                        net_kg=2711.684583356931,
                        operation_id="trip:beet_2021:15",
                    ),
                    "beet_00374",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=49125.0),
                    "beet_00375",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=15, end_block=15, operation_id="lift:beet_2021:15"
                    ),
                    "beet_00376",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:15",
                        net_kg=2711.684583356931,
                        operation_id="trip:beet_2021:16",
                    ),
                    "beet_00377",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.return_supplies(),
                    "beet_00378",
                    "Apply declared policy using public observations",
                )
        return finish_capture(self, events)
