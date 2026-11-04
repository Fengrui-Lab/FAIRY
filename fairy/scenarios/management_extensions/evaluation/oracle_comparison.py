"""Signed Agent/Oracle comparisons in the final scenario report.

The requested denominator is Oracle itself (including a negative Oracle), never
its absolute value or a clipped score. Zero denominators remain undefined.
"""

from collections import defaultdict
from copy import deepcopy
from math import fsum


MAX_MATURITY_DAYS = 180
SECONDS_PER_DAY = 86400


def _has_immature_crop(farm):
    return any(
        ridge.planted and not ridge.harvested and not farm.is_ridge_mature(i)
        for i, ridge in enumerate(farm._ridges)
    )


def biological_grain_kg(farm, *, deadline=None):
    """Use replay maturity extrapolation on a copy within the current season."""
    timestamp = farm.physics.last_physics_sim_time
    if deadline is not None and timestamp is not None and _has_immature_crop(farm):
        days = min(MAX_MATURITY_DAYS, int((deadline - timestamp) // SECONDS_PER_DAY))
        if days > 0:
            farm = deepcopy(farm)
            for day in range(1, days + 1):
                farm.advance_physics_time(timestamp + day * SECONDS_PER_DAY)
                if not _has_immature_crop(farm):
                    break
    states = farm.physics.yield_recovery.states.values()
    return (
        fsum(state.biological_yield_g_m2 for state in states)
        * farm.ridge_area_m2
        / 1000
    )


def recovered_grain_kg(farm):
    """Harvested grain at the market moisture used by the replay FOS metric."""
    area_m2 = farm.ridge_area_m2
    return fsum(
        state.recovered_yield_g_m2_at_market_moisture * area_m2 / 1000
        for state in farm.physics.yield_recovery.states.values()
        if state.harvested
    )


def relative_difference(agent, oracle, *, unit, better):
    delta = agent - oracle
    ratio = delta / oracle if oracle != 0 else None
    return {
        "agent": agent,
        "oracle": oracle,
        "difference": delta,
        "unit": unit,
        "relative_difference": ratio,
        "relative_difference_pct": None if ratio is None else 100 * ratio,
        "better": better,
        "undefined_reason": "Oracle denominator is zero" if oracle == 0 else None,
        "negative_denominator": oracle < 0,
    }


def _kg_comparison(agent, oracle):
    if agent is None or oracle is None:
        return None
    return relative_difference(agent, oracle, unit="kg", better="higher")


def _loss_pct(comparison):
    if comparison is None or comparison["relative_difference_pct"] is None:
        return None
    return -comparison["relative_difference_pct"]


def _season_key(row):
    return row["year"], row.get("crop_id", "maize")


def _crop_yields_by_year(seasons, mass_field):
    crops = defaultdict(dict)
    for row in seasons:
        year, crop = _season_key(row)
        crops[crop][year] = row.get(mass_field)
    return crops


def _compare_crop_yields(account, selected, agent_seasons, oracle_seasons, basis):
    crop_field = f"{basis}_kg_by_crop"
    if not (agent_seasons or oracle_seasons):
        agent = account.get(crop_field, {})
        oracle = selected.get(crop_field, {})
        return {
            crop: _kg_comparison(agent.get(crop), oracle.get(crop))
            for crop in sorted(agent.keys() | oracle.keys())
        }

    mass_field = f"{basis}_grain_kg"
    agent = _crop_yields_by_year(agent_seasons, mass_field)
    oracle = _crop_yields_by_year(oracle_seasons, mass_field)
    account[crop_field] = {
        crop: fsum(years.values())
        for crop, years in agent.items()
        if None not in years.values()
    }
    comparisons = {}
    for crop in sorted(agent.keys() | oracle.keys()):
        actual, reference = agent.get(crop, {}), oracle.get(crop, {})
        comparisons[crop] = (
            _kg_comparison(fsum(actual.values()), fsum(reference.values()))
            if actual.keys() == reference.keys()
            and None not in actual.values()
            and None not in reference.values()
            else None
        )
    return comparisons


def compare_to_oracle(account, selected, *, agent_seasons=(), oracle_seasons=()):
    """Add like-for-like financial, crop and season comparisons without summing unlike crops."""
    if account.get("currency") != selected.get("currency"):
        raise ValueError("Agent and Oracle currency must match")
    metrics = {}
    for metric, better in (
        ("production_cost", "lower"),
        ("net_operating_margin", "higher"),
    ):
        if metric in account and metric in selected:
            metrics[metric] = relative_difference(
                account[metric],
                selected[metric],
                unit=account["currency"],
                better=better,
            )
    for output, choices in (
        ("stored_grain_value", ("stored_grain_value", "grain_value")),
        ("stored_grain_kg", ("stored_grain_kg", "total_stored_grain_kg")),
    ):
        agent = next((account[k] for k in choices if k in account), None)
        oracle = next((selected[k] for k in choices if k in selected), None)
        if agent is not None and oracle is not None:
            metrics[output] = relative_difference(
                agent,
                oracle,
                unit="kg" if output.endswith("kg") else account["currency"],
                better="higher",
            )
    stored = {
        crop: _kg_comparison(account["stored_kg_by_crop"][crop], oracle)
        for crop, oracle in selected.get("stored_kg_by_crop", {}).items()
        if crop in account.get("stored_kg_by_crop", {})
    }
    biological = _compare_crop_yields(
        account, selected, agent_seasons, oracle_seasons, "biological"
    )
    recovered = _compare_crop_yields(
        account, selected, agent_seasons, oracle_seasons, "recovered"
    )

    seasons = []
    reference_by_season = {_season_key(row): row for row in oracle_seasons}
    for row in agent_seasons:
        year, crop = _season_key(row)
        reference = reference_by_season.get((year, crop), {})
        stored_comparison = _kg_comparison(
            row.get("stored_grain_kg"), reference.get("stored_grain_kg")
        )
        bio_comparison = _kg_comparison(
            row.get("biological_grain_kg"), reference.get("biological_grain_kg")
        )
        recovered_comparison = _kg_comparison(
            row.get("recovered_grain_kg"), reference.get("recovered_grain_kg")
        )
        reason = None
        if not reference:
            reason = "Oracle grew another crop or has no matching season"
        elif bio_comparison is None:
            reason = "Biological yield was not recorded for this season"
        seasons.append(
            {
                "year": year,
                "crop_id": crop,
                "yield": stored_comparison,  # Existing report key for stored weight.
                "biological_grain_kg": bio_comparison,
                "recovered_grain_kg": recovered_comparison,
                "yield_loss_pct": _loss_pct(bio_comparison),
                "recovered_yield_loss_pct": _loss_pct(recovered_comparison),
                "stored_yield_loss_pct": _loss_pct(stored_comparison),
                "not_comparable_reason": reason,
            }
        )

    for field, comparisons in (
        ("yield_loss_pct", biological),
        ("recovered_yield_loss_pct", recovered),
        ("stored_yield_loss_pct", stored),
    ):
        account[f"{field}_by_crop"] = {
            crop: _loss_pct(comparison) for crop, comparison in comparisons.items()
        }
        if field != "stored_yield_loss_pct":
            account[field] = (
                _loss_pct(next(iter(comparisons.values())))
                if len(comparisons) == 1
                else None
            )
    account["oracle_comparison"] = {
        "formula": "(agent - oracle) / oracle",
        "percentage_formula": "100 * (agent - oracle) / oracle",
        "yield_loss_percentage_formula": "100 * (1 - agent_biological_kg / oracle_biological_kg)",
        "metrics": metrics,
        "recovered_yield_loss_percentage_formula": "100 * (1 - agent_recovered_kg / oracle_recovered_kg)",
        "biological_kg_by_crop": biological,
        "recovered_kg_by_crop": recovered,
        "stored_kg_by_crop": stored,
        "seasons": seasons,
        "interpretation": "Positive means more; higher cost is worse, higher yield/margin is better. Assess direction from the absolute difference if Oracle is negative.",
    }
