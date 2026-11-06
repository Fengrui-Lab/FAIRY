"""L3 beet nitrogen_limit; shared block tools and actual native simulation."""

from fairy.types import EventRegisterer
from ..common import capture_step, finish_capture
from ..sugarbeet.scenario import SugarBeetScenario


class ScenarioSugarBeetNitrogenLimit(SugarBeetScenario):
    scenario_id = "scenario_l3_sugarbeet_nitrogen_limit"
    variant = "nitrogen_limit"
    level = "L3"

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
                    self.system.advance_time(days=12),
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
                    self.tractor.prepare_field(),
                    "beet_00002",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.detach_implement(),
                    "beet_00003",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.attach_implement(implement="seeder"),
                    "beet_00004",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00005",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=0, end_block=0, depth_cm=2.5),
                    "beet_00006",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00007",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=1, end_block=1, depth_cm=2.5),
                    "beet_00008",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00009",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=2, end_block=2, depth_cm=2.5),
                    "beet_00010",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00011",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=3, end_block=3, depth_cm=2.5),
                    "beet_00012",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00013",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=4, end_block=4, depth_cm=2.5),
                    "beet_00014",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00015",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=5, end_block=5, depth_cm=2.5),
                    "beet_00016",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00017",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=6, end_block=6, depth_cm=2.5),
                    "beet_00018",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00019",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=7, end_block=7, depth_cm=2.5),
                    "beet_00020",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00021",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=8, end_block=8, depth_cm=2.5),
                    "beet_00022",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00023",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=9, end_block=9, depth_cm=2.5),
                    "beet_00024",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00025",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=10, end_block=10, depth_cm=2.5),
                    "beet_00026",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00027",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=11, end_block=11, depth_cm=2.5),
                    "beet_00028",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00029",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=12, end_block=12, depth_cm=2.5),
                    "beet_00030",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00031",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=13, end_block=13, depth_cm=2.5),
                    "beet_00032",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00033",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=14, end_block=14, depth_cm=2.5),
                    "beet_00034",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_seeds(seed_type="SUGARBEET_601", count=6250),
                    "beet_00035",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.sow(start_block=15, end_block=15, depth_cm=2.5),
                    "beet_00036",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00037",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=227404.0),
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
                    self.tractor.load_fertilizer(kg=100.0),
                    "beet_00040",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.fertilize(
                        start_block=0, end_block=7, kg_per_block=6.25
                    ),
                    "beet_00041",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.fertilize(
                        start_block=8, end_block=15, kg_per_block=6.25
                    ),
                    "beet_00042",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=257580.0),
                    "beet_00043",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00044",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
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
                    self.tractor.load_fertilizer(kg=75.0),
                    "beet_00052",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.fertilize(
                        start_block=0, end_block=7, kg_per_block=4.6875
                    ),
                    "beet_00053",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.fertilize(
                        start_block=8, end_block=15, kg_per_block=4.6875
                    ),
                    "beet_00054",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=257580.0),
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
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00059",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
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
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00066",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
                    "beet_00067",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.load_fertilizer(kg=75.0),
                    "beet_00068",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.fertilize(
                        start_block=0, end_block=7, kg_per_block=4.6875
                    ),
                    "beet_00069",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.fertilize(
                        start_block=8, end_block=15, kg_per_block=4.6875
                    ),
                    "beet_00070",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=257580.0),
                    "beet_00071",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00072",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
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
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00078",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
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
                    self.irrigation.irrigate(
                        start_block=0, end_block=15, depth_mm=30.0
                    ),
                    "beet_00081",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=237300.0),
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
                    self.system.advance_time(days=3),
                    "beet_00093",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00094",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00095",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
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
                    self.system.advance_time(days=3),
                    "beet_00105",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00106",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00107",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
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
                    self.system.advance_time(days=3),
                    "beet_00114",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
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
                    self.system.advance_time(days=3),
                    "beet_00117",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=3),
                    "beet_00118",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.detach_implement(),
                    "beet_00119",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.attach_implement(implement="beet_harvester"),
                    "beet_00120",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.refuel(liters=80.3595658073272),
                    "beet_00121",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=0, end_block=0, operation_id="lift:beet_2021:0"
                    ),
                    "beet_00122",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:0",
                        net_kg=2830.767380110854,
                        operation_id="trip:beet_2021:1",
                    ),
                    "beet_00123",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=1, end_block=1, operation_id="lift:beet_2021:1"
                    ),
                    "beet_00124",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:1",
                        net_kg=2830.767380110854,
                        operation_id="trip:beet_2021:2",
                    ),
                    "beet_00125",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=2, end_block=2, operation_id="lift:beet_2021:2"
                    ),
                    "beet_00126",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:2",
                        net_kg=2830.767380110854,
                        operation_id="trip:beet_2021:3",
                    ),
                    "beet_00127",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=3, end_block=3, operation_id="lift:beet_2021:3"
                    ),
                    "beet_00128",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:3",
                        net_kg=2830.767380110854,
                        operation_id="trip:beet_2021:4",
                    ),
                    "beet_00129",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=4, end_block=4, operation_id="lift:beet_2021:4"
                    ),
                    "beet_00130",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:4",
                        net_kg=2830.767380110854,
                        operation_id="trip:beet_2021:5",
                    ),
                    "beet_00131",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=49125.0),
                    "beet_00132",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=5, end_block=5, operation_id="lift:beet_2021:5"
                    ),
                    "beet_00133",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:5",
                        net_kg=2830.767380110854,
                        operation_id="trip:beet_2021:6",
                    ),
                    "beet_00134",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=6, end_block=6, operation_id="lift:beet_2021:6"
                    ),
                    "beet_00135",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:6",
                        net_kg=2830.767380110854,
                        operation_id="trip:beet_2021:7",
                    ),
                    "beet_00136",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=7, end_block=7, operation_id="lift:beet_2021:7"
                    ),
                    "beet_00137",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:7",
                        net_kg=2830.767380110854,
                        operation_id="trip:beet_2021:8",
                    ),
                    "beet_00138",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=8, end_block=8, operation_id="lift:beet_2021:8"
                    ),
                    "beet_00139",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:8",
                        net_kg=2830.767380110854,
                        operation_id="trip:beet_2021:9",
                    ),
                    "beet_00140",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=9, end_block=9, operation_id="lift:beet_2021:9"
                    ),
                    "beet_00141",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:9",
                        net_kg=2830.767380110854,
                        operation_id="trip:beet_2021:10",
                    ),
                    "beet_00142",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=49125.0),
                    "beet_00143",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(days=1),
                    "beet_00144",
                    "Advance native crop AND fallow soil through elapsed time",
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
                    self.tractor.harvest_roots(
                        start_block=10, end_block=10, operation_id="lift:beet_2021:10"
                    ),
                    "beet_00147",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:10",
                        net_kg=2830.767380110854,
                        operation_id="trip:beet_2021:11",
                    ),
                    "beet_00148",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=11, end_block=11, operation_id="lift:beet_2021:11"
                    ),
                    "beet_00149",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:11",
                        net_kg=2830.767380110854,
                        operation_id="trip:beet_2021:12",
                    ),
                    "beet_00150",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=12, end_block=12, operation_id="lift:beet_2021:12"
                    ),
                    "beet_00151",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:12",
                        net_kg=2830.767380110854,
                        operation_id="trip:beet_2021:13",
                    ),
                    "beet_00152",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=13, end_block=13, operation_id="lift:beet_2021:13"
                    ),
                    "beet_00153",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:13",
                        net_kg=2830.767380110854,
                        operation_id="trip:beet_2021:14",
                    ),
                    "beet_00154",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=14, end_block=14, operation_id="lift:beet_2021:14"
                    ),
                    "beet_00155",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:14",
                        net_kg=2830.767380110854,
                        operation_id="trip:beet_2021:15",
                    ),
                    "beet_00156",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.system.advance_time(seconds=49125.0),
                    "beet_00157",
                    "Advance native crop AND fallow soil through elapsed time",
                )
                previous = capture_step(
                    previous,
                    self.tractor.harvest_roots(
                        start_block=15, end_block=15, operation_id="lift:beet_2021:15"
                    ),
                    "beet_00158",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.delivery.deliver_roots(
                        batch_id="beet_2021:block:15",
                        net_kg=2830.767380110854,
                        operation_id="trip:beet_2021:16",
                    ),
                    "beet_00159",
                    "Apply declared policy using public observations",
                )
                previous = capture_step(
                    previous,
                    self.tractor.return_supplies(),
                    "beet_00160",
                    "Apply declared policy using public observations",
                )
        return finish_capture(self, events)
