"""Explicit import of the author's XLSX tables, with no guessed column semantics."""

from __future__ import annotations

from datetime import date, datetime
from hashlib import md5
from io import BytesIO
import json
import math
import re
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from ..engines.winter_wheat_inputs import (
    ZENODO_DOI,
    ZENODO_FILES,
    date_from_doy,
    number,
)

EXPECTED_MEMBERS = {
    "Phenology data.zip": {
        "Phenology data_calibration.xlsx": "calibration",
        "Phenology data_validation.xlsx": "validation",
    },
    "Yield data.zip": {
        "Yield data_calibration.xlsx": "calibration",
        "Yield data_validation.xlsx": "validation",
        "Yield data_overall.xlsx": "overall",
    },
}


def _coordinate(value, axis):
    match = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s*°?\s*([NSEW])?\s*", str(value))
    if match is None:
        raise ValueError(f"Unrecognized published coordinate: {value!r}")
    degree = float(match.group(1))
    direction = match.group(2)
    if direction and direction not in (
        {"E", "W"} if axis == "longitude" else {"N", "S"}
    ):
        raise ValueError("Coordinate direction disagrees with its column")
    if direction in {"W", "S"}:
        degree = -abs(degree)
    limit = 180 if axis == "longitude" else 90
    return number(degree, axis, minimum=-limit, maximum=limit)


def _archive(root: Path, name: str) -> ZipFile:
    if name not in ZENODO_FILES:
        raise ValueError("Only the two identified DOI archives are accepted")
    content = (root / name).read_bytes()
    if md5(content).hexdigest() != ZENODO_FILES[name]:
        raise ValueError(f"Official Zenodo MD5 mismatch: {name}")
    return ZipFile(BytesIO(content))


def _member(archive: ZipFile, basename: str) -> str:
    names = [
        n
        for n in archive.namelist()
        if PurePosixPath(n).name == basename and not n.startswith("__MACOSX/")
    ]
    if len(names) != 1:
        raise ValueError(f"Expected one exact workbook {basename}, found {len(names)}")
    info = archive.getinfo(names[0])
    if info.file_size > 30_000_000:
        raise ValueError("Unexpectedly large observation workbook")
    return names[0]


def inspect_archives(root: str | Path) -> dict:
    from openpyxl import load_workbook

    result = {"doi": ZENODO_DOI, "column_semantics": "not inferred", "workbooks": []}
    for archive_name, members in EXPECTED_MEMBERS.items():
        with _archive(Path(root), archive_name) as archive:
            for name, split in members.items():
                member = _member(archive, name)
                workbook = load_workbook(
                    BytesIO(archive.read(member)), read_only=True, data_only=True
                )
                try:
                    sheets = []
                    for sheet in workbook:
                        samples = [
                            [
                                v.isoformat() if isinstance(v, (date, datetime)) else v
                                for v in row
                            ]
                            for row in sheet.iter_rows(
                                min_row=1, max_row=6, values_only=True
                            )
                        ]
                        sheets.append(
                            {
                                "name": sheet.title,
                                "max_row": sheet.max_row,
                                "first_6_rows": samples,
                            }
                        )
                    result["workbooks"].append(
                        {
                            "archive": archive_name,
                            "member": member,
                            "split": split,
                            "sheets": sheets,
                        }
                    )
                finally:
                    workbook.close()
    return result


def import_published_summaries(root: str | Path) -> dict:
    """Import actual published county/year summaries without inventing annual plots.

    County sheets have no year column; fractional phenology values remain day
    statistics. The overall sheet has years but unspecified spatial weights and
    grain moisture. These records cannot calibrate the example single field.
    """
    from openpyxl import load_workbook

    records = []
    for archive_name, members in EXPECTED_MEMBERS.items():
        with _archive(Path(root), archive_name) as archive:
            for name, split in members.items():
                member = _member(archive, name)
                workbook = load_workbook(
                    BytesIO(archive.read(member)), read_only=True, data_only=True
                )
                try:
                    if len(workbook.sheetnames) != 1:
                        raise ValueError(f"Published workbook layout changed: {name}")
                    sheet = workbook[workbook.sheetnames[0]]
                    rows = sheet.iter_rows(values_only=True)
                    headers = next(rows)
                    index = {
                        str(value): i
                        for i, value in enumerate(headers)
                        if value is not None
                    }
                    overall = split == "overall"
                    phenology = archive_name == "Phenology data.zip"
                    required = (
                        {"Year", "Observation (kg/ha)"}
                        if overall
                        else {"Counties", "Longitude", "Latitude"}
                        | (
                            {"Observation_Heading (day)", "Observation_Maturity (day)"}
                            if phenology
                            else {"Observation (kg/ha)"}
                        )
                    )
                    if not required <= index.keys():
                        raise ValueError(f"Actual published headers differ in {name}")
                    for row_number, row in enumerate(rows, 2):
                        if all(value is None for value in row):
                            continue
                        entity = (
                            "north_china_plain_published_aggregate"
                            if overall
                            else str(row[index["Counties"]])
                        )
                        year = None
                        if overall:
                            raw_year = number(
                                row[index["Year"]], "year", minimum=1900, maximum=2100
                            )
                            if not raw_year.is_integer():
                                raise ValueError(
                                    "Published overall year is not integral"
                                )
                            year = int(raw_year)
                        common = {
                            "source_doi": ZENODO_DOI,
                            "archive": archive_name,
                            "member": member,
                            "sheet": sheet.title,
                            "row": row_number,
                            "split": split,
                            "entity_type": "region" if overall else "county",
                            "entity_id": entity,
                            "harvest_year": year,
                            "native_comparable": False,
                            "aggregation": "published summary; constituent years/weights not supplied",
                            "not_comparable_reason": "Missing annual county identities, aggregation weights and/or grain moisture; not matched to the example field",
                        }
                        if not overall:
                            common["longitude"] = _coordinate(
                                row[index["Longitude"]], "longitude"
                            )
                            common["latitude"] = _coordinate(
                                row[index["Latitude"]], "latitude"
                            )
                        if phenology:
                            for column, metric in [
                                ("Observation_Heading (day)", "heading_day_statistic"),
                                (
                                    "Observation_Maturity (day)",
                                    "maturity_day_statistic",
                                ),
                            ]:
                                value = number(
                                    row[index[column]], column, minimum=1, maximum=366
                                )
                                records.append(
                                    {
                                        **common,
                                        "metric": metric,
                                        "value_days": value,
                                        "source_column": column,
                                        "raw_value": str(row[index[column]]),
                                        "calendar_date": None,
                                        "interpretation": "Reported fractional day statistic, not an observed calendar date or native anthesis",
                                    }
                                )
                        else:
                            column = "Observation (kg/ha)"
                            value = number(
                                row[index[column]], "reported yield", minimum=0
                            )
                            records.append(
                                {
                                    **common,
                                    "metric": "yield",
                                    "yield_kg_ha": value,
                                    "source_column": column,
                                    "raw_value": str(row[index[column]]),
                                    "moisture_fraction": None,
                                    "dry_yield_kg_ha": None,
                                }
                            )
                finally:
                    workbook.close()
    return {
        "schema": "fairy.winter_wheat.observations.v1",
        "source_doi": ZENODO_DOI,
        "split_rule": "Author file splits preserved; overall is not an independent validation set",
        "import_status": "published_summaries_imported_not_annual_calibration_data",
        "records": records,
    }


def _date_value(value, encoding: str, year: int) -> str:
    if encoding == "doy":
        return date_from_doy(year, value).isoformat()
    if encoding == "iso":
        return date.fromisoformat(str(value)).isoformat()
    if encoding == "excel_date":
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        raise ValueError(
            "Expected a decoded Excel date, not an unexplained serial number"
        )
    raise ValueError("Dates require explicit encoding: doy, iso, or excel_date")


def normalize(root: str | Path, mapping_file: str | Path) -> dict:
    """Caller maps ACTUAL inspected headers and states year/unit/spatial semantics."""
    from openpyxl import load_workbook

    mapping = json.loads(Path(mapping_file).read_text(encoding="utf-8"))
    if mapping.get("schema") != "fairy.winter_wheat.observation_mapping.v1":
        raise ValueError("Unsupported observation mapping")
    if "REPLACE_" in json.dumps(mapping, ensure_ascii=False):
        raise ValueError(
            "Mapping still contains unverified example placeholders; inspect the real workbooks first"
        )
    if not mapping.get("workbooks"):
        raise ValueError(
            "Map actual workbook columns after running inspect-observations"
        )
    records = []
    seen = set()
    for spec in mapping["workbooks"]:
        archive_name, basename = spec["archive"], spec["member"]
        split = EXPECTED_MEMBERS.get(archive_name, {}).get(basename)
        if not split:
            raise ValueError("Workbook is not a known author split")
        if "year_to_harvest_offset" not in spec or spec[
            "year_to_harvest_offset"
        ] not in {0, 1}:
            raise ValueError(
                "Declare year_to_harvest_offset: 0=harvest year, 1=sowing year"
            )
        if not spec.get("semantic_notes") or spec.get("entity_type") not in {
            "station",
            "county",
            "region",
            "plot",
        }:
            raise ValueError(
                "Declare spatial support and evidence for column interpretations"
            )
        with _archive(Path(root), archive_name) as archive:
            member = _member(archive, basename)
            workbook = load_workbook(
                BytesIO(archive.read(member)), read_only=True, data_only=True
            )
            try:
                sheet = workbook[spec["sheet"]]
                header_row = int(spec["header_row"])
                headers = next(
                    sheet.iter_rows(
                        min_row=header_row, max_row=header_row, values_only=True
                    )
                )
                header_index = {}
                for i, h in enumerate(headers):
                    if h is None:
                        continue
                    if str(h) in header_index:
                        raise ValueError(
                            f"Duplicate header {h!r}; resolve manually before import"
                        )
                    header_index[str(h)] = i

                def cell(row, name):
                    if name not in header_index:
                        raise ValueError(
                            f"Actual header {name!r} not found in {basename}/{sheet.title}"
                        )
                    return row[header_index[name]]

                for row_number, row in enumerate(
                    sheet.iter_rows(min_row=header_row + 1, values_only=True),
                    header_row + 1,
                ):
                    if all(v is None for v in row):
                        continue
                    entity = cell(row, spec["entity_column"])
                    year_value = number(
                        cell(row, spec["year_column"]),
                        "year",
                        minimum=1900,
                        maximum=2100,
                    )
                    if entity is None or not year_value.is_integer():
                        raise ValueError(
                            f"Missing entity or non-integral year at {member}:{row_number}"
                        )
                    crop_year = int(year_value) + spec["year_to_harvest_offset"]
                    for metric in spec["metrics"]:
                        value = cell(row, metric["column"])
                        if value is None:
                            raise ValueError(
                                f"Missing observation {member}:{row_number}:{metric['column']}; no imputation"
                            )
                        name = metric["metric"]
                        record = {
                            "source_doi": ZENODO_DOI,
                            "archive": archive_name,
                            "member": member,
                            "sheet": sheet.title,
                            "row": row_number,
                            "split": split,
                            "entity_id": str(entity),
                            "entity_type": spec["entity_type"],
                            "harvest_year": crop_year,
                            "metric": name,
                            "raw_value": str(value),
                        }
                        if name in {
                            "sowing_date",
                            "emergence_date",
                            "anthesis_date",
                            "maturity_date",
                            "heading_date",
                        }:
                            if "year_offset_from_harvest" not in metric:
                                raise ValueError(
                                    "Declare date year relative to harvest, especially autumn dates"
                                )
                            offset = metric["year_offset_from_harvest"]
                            if offset not in {-1, 0}:
                                raise ValueError("Date year offset must be -1 or 0")
                            record["date"] = _date_value(
                                value, metric["encoding"], crop_year + offset
                            )
                            if (
                                date.fromisoformat(record["date"]).year
                                != crop_year + offset
                            ):
                                raise ValueError(
                                    "Observed date contradicts the declared harvest-year alignment"
                                )
                            record["native_comparable"] = name in {
                                "emergence_date",
                                "anthesis_date",
                                "maturity_date",
                            }
                        elif name == "yield":
                            factors = {"kg/ha": 1.0, "t/ha": 1000.0, "kg/mu": 15.0}
                            if (
                                metric.get("unit") not in factors
                                or "moisture_fraction" not in metric
                            ):
                                raise ValueError(
                                    "Yield requires explicit unit and moisture_fraction (null=unknown)"
                                )
                            y = (
                                number(value, "yield", minimum=0)
                                * factors[metric["unit"]]
                            )
                            moisture = metric["moisture_fraction"]
                            if moisture is not None:
                                moisture = number(
                                    moisture,
                                    "observed moisture fraction",
                                    minimum=0,
                                    maximum=0.99,
                                )
                            record.update(
                                yield_kg_ha=y,
                                moisture_fraction=moisture,
                                dry_yield_kg_ha=None
                                if moisture is None
                                else y * (1 - moisture),
                                native_comparable=moisture is not None,
                            )
                        else:
                            raise ValueError(f"Unsupported/unmapped metric: {name}")
                        key = (split, spec["entity_type"], str(entity), crop_year, name)
                        if key in seen:
                            raise ValueError(
                                f"Duplicate observation identity: {key}; do not silently average replicates"
                            )
                        seen.add(key)
                        records.append(record)
            finally:
                workbook.close()
    return {
        "schema": "fairy.winter_wheat.observations.v1",
        "source_doi": ZENODO_DOI,
        "split_rule": "author calibration/validation retained; overall is not an independent test set",
        "mapping": mapping,
        "records": records,
    }


def compare(observations: dict, predictions: dict, split: str = "validation") -> dict:
    if split not in {"calibration", "validation"}:
        raise ValueError(
            "The author's overall file is not an independent evaluation split"
        )
    if observations.get("schema") != "fairy.winter_wheat.observations.v1":
        raise ValueError("Normalize observations explicitly first")
    if predictions.get("schema") != "fairy.winter_wheat.predictions.v1":
        raise ValueError("Unsupported prediction schema")
    if split == "validation" and "validation" in predictions.get("fitted_splits", []):
        raise ValueError("Validation data were used to fit these predictions")
    if not predictions.get("input_fingerprint") or not predictions.get(
        "spatial_matching_evidence"
    ):
        raise ValueError(
            "Predictions require input identity and justified spatial matching"
        )
    index = {}
    for p in predictions["records"]:
        key = (p["entity_type"], p["entity_id"], p["harvest_year"], p["metric"])
        if key in index:
            raise ValueError(f"Duplicate prediction {key}")
        index[key] = p
    errors, excluded, matches = {}, [], []
    for o in observations["records"]:
        if o["split"] != split:
            continue
        key = (o["entity_type"], o["entity_id"], o["harvest_year"], o["metric"])
        if not o.get("native_comparable") or key not in index:
            excluded.append(
                {
                    "key": key,
                    "reason": "unknown yield basis, unsupported heading date, or unmatched identity",
                }
            )
            continue
        p = index[key]
        if o["metric"] == "yield":
            predicted = number(p["dry_yield_kg_ha"], "predicted dry yield", minimum=0)
            actual = number(o["dry_yield_kg_ha"], "observed dry yield", minimum=0)
            error, unit = predicted - actual, "kg dry matter/ha"
        else:
            error = (date.fromisoformat(p["date"]) - date.fromisoformat(o["date"])).days
            unit = "days"
        errors.setdefault((o["metric"], unit), []).append(error)
        matches.append({"key": key, "error": error, "unit": unit})
    if not matches:
        raise ValueError(
            "No scientifically comparable, identity-matched observations; no accuracy metric calculated"
        )
    metrics = [
        {
            "metric": metric,
            "unit": unit,
            "n": len(e),
            "mae": sum(abs(x) for x in e) / len(e),
            "rmse": math.sqrt(sum(x * x for x in e) / len(e)),
            "bias": sum(e) / len(e),
        }
        for (metric, unit), e in errors.items()
    ]
    return {
        "split": split,
        "metrics": metrics,
        "matched": matches,
        "excluded": excluded,
        "spatial_matching_evidence": predictions["spatial_matching_evidence"],
        "note": "Accuracy applies only to these matched observations and declared input/model versions",
    }
