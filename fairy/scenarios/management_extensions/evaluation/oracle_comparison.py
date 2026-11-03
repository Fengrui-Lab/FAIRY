"""Signed Agent/Oracle comparisons in the final scenario report.

The requested denominator is Oracle itself (including a negative Oracle), never
its absolute value or a clipped score. Zero denominators remain undefined.
"""


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
    crops = {}
    for crop, oracle in selected.get("stored_kg_by_crop", {}).items():
        if crop in account.get("stored_kg_by_crop", {}):
            crops[crop] = relative_difference(
                account["stored_kg_by_crop"][crop], oracle, unit="kg", better="higher"
            )
    seasons = []
    for row in agent_seasons:
        year, crop = row["year"], row.get("crop_id", "maize")
        reference = next(
            (
                r
                for r in oracle_seasons
                if r["year"] == year and r.get("crop_id", "maize") == crop
            ),
            None,
        )
        seasons.append(
            {
                "year": year,
                "crop_id": crop,
                "yield": (
                    relative_difference(
                        row["stored_grain_kg"],
                        reference["stored_grain_kg"],
                        unit="kg",
                        better="higher",
                    )
                    if reference
                    else None
                ),
                "not_comparable_reason": (
                    None
                    if reference
                    else "Oracle grew another crop or has no matching season"
                ),
            }
        )
    account["yield_loss_pct_by_crop"] = {
        crop: (
            None
            if row["relative_difference_pct"] is None
            else -row["relative_difference_pct"]
        )
        for crop, row in crops.items()
    }
    account["oracle_comparison"] = {
        "formula": "(agent - oracle) / oracle",
        "percentage_formula": "100 * (agent - oracle) / oracle",
        "metrics": metrics,
        "stored_kg_by_crop": crops,
        "seasons": seasons,
        "interpretation": "Positive means more; higher cost is worse, higher yield/margin is better. Assess direction from the absolute difference if Oracle is negative.",
    }
