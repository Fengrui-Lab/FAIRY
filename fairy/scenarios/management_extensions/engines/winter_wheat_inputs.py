"""Input contracts and units for a single, cross-calendar-year wheat crop.

Only Python's standard library is required here. No crop growth is synthesized.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping

UPSTREAM_COMMIT = "1ca91d7dbb5aaf6b41462162de03a8254812d3a5"
WHEAT_URL = f"https://raw.githubusercontent.com/ajwdewit/WOFOST_crop_parameters/{UPSTREAM_COMMIT}/wheat.yaml"

def number(
    value: Any,
    label: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label}: booleans are not numerical quantities")
    try:
        n = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}: expected a finite number") from exc
    if not math.isfinite(n):
        raise ValueError(f"{label}: NaN/Infinity/missing values are forbidden")
    if minimum is not None and n < minimum:
        raise ValueError(f"{label}: must be >= {minimum}")
    if maximum is not None and n > maximum:
        raise ValueError(f"{label}: must be <= {maximum}")
    return n


def json_safe(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_safe(v) for v in value]
    if hasattr(value, "item"):
        return json_safe(value.item())
    if isinstance(value, float):
        number(value, "JSON number")
    return value


def fingerprint(value: Any) -> str:
    raw = json.dumps(
        json_safe(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def verified_file(root: Path, record: Mapping[str, str]) -> Path:
    root = root.resolve()
    path = (root / record["path"]).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Input file must remain under its bundle directory")
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing input: {path}; fetch the versioned winter-wheat input bundle"
        )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != record["sha256"]:
        raise ValueError(f"SHA-256 mismatch for {path.name}")
    return path


@dataclass(frozen=True)
class Season:
    start: date
    sowing_open: date
    sowing_close: date
    deadline: date
    timezone: str = "Asia/Shanghai"

    def __post_init__(self) -> None:
        if not self.start <= self.sowing_open <= self.sowing_close < self.deadline:
            raise ValueError("Invalid preparation/sowing/deadline ordering")
        if self.deadline.year != self.start.year + 1:
            raise ValueError(
                "This winter-wheat season must cross exactly one calendar year"
            )
        if self.timezone != "Asia/Shanghai":
            raise ValueError("This v1 Chinese scenario uses Asia/Shanghai explicitly")

    @property
    def crop_year(self) -> int:
        """Harvest year, NOT the autumn sowing year."""
        return self.deadline.year

    def check_sowing(self, day: date) -> None:
        if not self.sowing_open <= day <= self.sowing_close:
            raise ValueError("Sowing outside the declared experimental sowing window")

    def as_dict(self) -> dict:
        return json_safe(asdict(self))


@dataclass(frozen=True)
class WeatherDay:
    day: date
    tmin_c: float
    tmax_c: float
    tmean_c: float
    rain_mm: float
    radiation_mj_m2: float
    wind_2m_m_s: float
    rh_pct: float

    def __post_init__(self) -> None:
        for name in ("tmin_c", "tmax_c", "tmean_c"):
            number(getattr(self, name), name, minimum=-70, maximum=65)
        if not self.tmin_c <= self.tmean_c <= self.tmax_c:
            raise ValueError("Temperature must satisfy Tmin <= Tmean <= Tmax")
        number(self.rain_mm, "rain_mm", minimum=0, maximum=1000)
        number(self.radiation_mj_m2, "radiation_mj_m2", minimum=0, maximum=60)
        number(self.wind_2m_m_s, "wind_2m_m_s", minimum=0, maximum=100)
        number(self.rh_pct, "rh_pct", minimum=0.01, maximum=100)

    def as_dict(self) -> dict:
        return json_safe(asdict(self))


class WeatherSeries:
    """Exact-date forcing. Missing winter/leap days are an error, not a climatology fallback."""

    def __init__(self, rows: list[WeatherDay]):
        self.rows = {}
        for row in rows:
            if row.day in self.rows:
                raise ValueError(f"Duplicate weather day: {row.day}")
            self.rows[row.day] = row
        if not self.rows:
            raise ValueError("Empty weather series")
        self.sha256 = fingerprint([self.rows[d].as_dict() for d in sorted(self.rows)])

    @classmethod
    def from_csv(cls, path: Path) -> "WeatherSeries":
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            expected = set(WeatherDay.__dataclass_fields__)
            if set(reader.fieldnames or ()) != expected:
                raise ValueError(f"Expected CSV columns exactly {sorted(expected)}")
            rows = [
                WeatherDay(
                    day=date.fromisoformat(r["day"]),
                    **{k: number(r[k], k) for k in expected - {"day"}},
                )
                for r in reader
            ]
        return cls(rows)

    def require(self, start: date, end: date) -> None:
        if end < start:
            raise ValueError("Reversed weather interval")
        missing = []
        day = start
        while day <= end:
            if day not in self.rows:
                missing.append(day.isoformat())
            day += timedelta(days=1)
        if missing:
            raise ValueError(
                f"Missing daily weather ({len(missing)}): {', '.join(missing[:8])}"
            )

    def __getitem__(self, day: date) -> WeatherDay:
        try:
            return self.rows[day]
        except KeyError as exc:
            raise ValueError(f"No weather for {day}; no fallback permitted") from exc


def stage_from_native(values: Mapping[str, Any], *, sown: bool) -> str:
    """Do not invent wheat jointing/heading or map wheat to soybean R1/R8."""
    if not sown:
        return "BARE"
    if values.get("DOM") is not None:
        return "MATURE"
    if values.get("DOE") is None:
        return "SOWN_NOT_EMERGED"
    if values.get("DOA") is not None or float(values.get("DVS") or 0) >= 1:
        return "POST_ANTHESIS"
    return "VEGETATIVE"


def dry_to_moist_mass(dry_kg: float, moisture_fraction: float) -> float:
    dry = number(dry_kg, "dry mass", minimum=0)
    moisture = number(moisture_fraction, "moisture fraction", minimum=0, maximum=0.99)
    return dry / (1 - moisture)


def irrigation_m3(mm: float, area_ha: float) -> float:
    return (
        number(mm, "irrigation mm", minimum=0)
        * number(area_ha, "area ha", minimum=0)
        * 10
    )


def validate_wheat_parameters(p: Mapping[str, Any]) -> None:
    required = {
        "IDSL",
        "DLO",
        "DLC",
        "VERNBASE",
        "VERNSAT",
        "VERNDVS",
        "VERNRTB",
        "TSUMEM",
        "TSUM1",
        "TSUM2",
        "DVSEND",
        "TDWI",
        "NFIX_FR",
    }
    if missing := required - set(p):
        raise ValueError(f"Missing winter-wheat parameters: {sorted(missing)}")
    if number(p["IDSL"], "IDSL") != 2:
        raise ValueError(
            "Winter wheat must use native photoperiod + vernalisation (IDSL=2)"
        )
    if not number(p["DLO"], "DLO") > number(p["DLC"], "DLC"):
        raise ValueError("Winter wheat requires DLO > DLC")
    if not 0 <= number(p["VERNBASE"], "VERNBASE") < number(p["VERNSAT"], "VERNSAT"):
        raise ValueError("Invalid vernalisation requirements")
    if number(p["NFIX_FR"], "NFIX_FR") != 0 or number(p["DVSEND"], "DVSEND") != 2:
        raise ValueError("Require NFIX_FR=0 and DVSEND=2 for this wheat adapter")
    for name in ("TSUMEM", "TSUM1", "TSUM2", "TDWI"):
        if number(p[name], name) <= 0:
            raise ValueError(f"{name} must be positive")
    table = p["VERNRTB"]
    if not isinstance(table, list) or len(table) < 4 or len(table) % 2:
        raise ValueError("VERNRTB must be a nonempty x/y table")
    xs = [number(x, "VERNRTB temperature") for x in table[::2]]
    if any(a >= b for a, b in zip(xs, xs[1:])):
        raise ValueError("VERNRTB temperatures must strictly increase")
    for rate in table[1::2]:
        number(rate, "VERNRTB rate", minimum=0, maximum=1)
