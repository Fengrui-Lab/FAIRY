"""Isolated protocol fixtures: never impersonate an installed PCSE or FAIRY package."""

import ast
from copy import deepcopy
from datetime import date, timedelta
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[2]
EXT = ROOT / "fairy/scenarios/management_extensions"
if not EXT.is_dir():
    ROOT = Path(__file__).resolve().parents[3]
    EXT = ROOT / "fairy/scenarios/management_extensions"


def load(name, path):
    spec = spec_from_file_location(name, path)
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pkg = ModuleType("isolated_beet_review")
pkg.__path__ = [str(EXT / "sugarbeet")]
sys.modules[pkg.__name__] = pkg
contracts = load("isolated_beet_review.contracts", EXT / "sugarbeet/contracts.py")


@pytest.fixture
def C():
    return contracts


@pytest.fixture
def beet(C):
    return C.CropCycle(
        "beet_2021",
        "sugarbeet",
        "Sugarbeet_601",
        date(2021, 3, 20),
        date(2021, 4, 1),
        date(2021, 4, 20),
        date(2021, 9, 25),
        date(2021, 10, 31),
        date(2021, 7, 15),
        180,
        2.5,
        100000,
        20,
        1000,
    )


@pytest.fixture
def wheat(C):
    return C.CropCycle(
        "wheat_2020",
        "winter_wheat",
        "Winter_wheat_104",
        date(2019, 10, 1),
        date(2019, 10, 5),
        date(2019, 10, 25),
        date(2020, 6, 1),
        date(2020, 7, 31),
        date(2020, 5, 1),
        240,
        3,
        4000000,
        0,
        2000,
    )


@pytest.fixture
def Backend(C):
    # Exercise actual adapter methods against a no-growth protocol stub. Constructor
    # imports and native agronomic behavior are deliberately NOT represented here.
    path = EXT / "engines/sugarbeet_wofost.py"
    tree = ast.parse(path.read_text())
    tree.body = [
        x for x in tree.body if not isinstance(x, (ast.Import, ast.ImportFrom))
    ]
    namespace = dict(
        deepcopy=deepcopy,
        date=date,
        timedelta=timedelta,
        WinterWheatBackend=SimpleNamespace(_weather_container=lambda *x: None),
        fingerprint=C.digest,
        number=lambda x, label, minimum=None, maximum=None: C.finite(
            x,
            label,
            0 if minimum is None else minimum,
            float("inf") if maximum is None else maximum,
        ),
        json_safe=lambda x: __import__("json").loads(
            __import__("json").dumps(x, default=lambda v: v.isoformat())
        ),
        stage_from_native=lambda v, sown: "MATURE" if v.get("DOM") else "VEGETATIVE",
    )
    exec(compile(tree, str(path), "exec"), namespace)
    return namespace["SugarBeetBackend"]


class ProtocolModel:
    """No growth formulas. Numeric values are fixed test fixtures, NOT crop predictions."""

    def __init__(self, day):
        self.day = day
        self.crop = None
        self.soil = object()
        self.calls = []
        self.values = {
            "SM": 0.25,
            "NAVAIL": 40.0,
            "NSOIL": 40.0,
            "TWSO": 0.0,
            "DOE": None,
            "DOM": None,
        }

    def get_variable(self, key):
        return self.values.get(key)

    def _get_driving_variables(self, day):
        return object()

    def _send_signal(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["signal"] == "start":
            self.crop = object()

    def _finish_cropsimulation(self, day):
        self.crop = None

    def calculate_current_day(self):
        self.calls.append({"phase": "calculate"})

    def run(self, days):
        self.day += timedelta(days=days)
        self.calls.append({"phase": "run"})


@pytest.fixture
def make_backend(Backend, C):
    def make(cycles, day=None):
        b = Backend.__new__(Backend)
        b.cycle_index = 0
        b.next_day = day or cycles[0].sowing_open
        b.bundle = SimpleNamespace(
            cycles=cycles,
            season=SimpleNamespace(
                deadline=cycles[-1].harvest_close + timedelta(days=5)
            ),
            weather=SimpleNamespace(require=lambda *a: None),
            identity="protocol-fixture-only",
        )
        b.model = ProtocolModel(b.next_day)
        b._soil_object_id = id(b.model.soil)
        b.runtime = {
            "signals": SimpleNamespace(
                crop_start="start",
                crop_finish="finish",
                irrigate="water",
                apply_n="nitrogen",
            )
        }
        b.sown = False
        b.maturity = None
        b.pending = []
        b.receipts = {}
        b.events = []
        b.harvests = {}
        b.failed = None
        b.n_by_cycle = {c.cycle_id: 0.0 for c in cycles}
        b.last_irrigation = None
        b.sowing_day = None
        b.efficiency = 0.85
        b.n_recovery = 0.7
        b.values = b._read()
        b.rotation_audit = []
        b.version = "PROTOCOL_STUB_NOT_PCSE"
        b.parameter_hash = "fixture"
        return b

    return make
