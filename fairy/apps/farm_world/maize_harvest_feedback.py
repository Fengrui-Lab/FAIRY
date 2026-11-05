"""Maize-only, read-only operational guidance; never a native growth forecast.

The reference is the existing public crop_profile calendar, not oracle traces,
future weather, or hidden WOFOST state. Actual maturity remains authoritative.
"""
from math import isfinite


def rain_feedback():
    return {
        "guidance": "Query WeatherApp__get_forecast(days=7) to find a possible dry day. "
        "Choose an appropriate time advance, then recheck current weather, field "
        "trafficability, maturity and grain moisture before harvesting. A dry "
        "forecast alone does not guarantee harvestability; changing ridges does "
        "not remove the current rain restriction.",
    }


def maturity_feedback(world, ridge_ids):
    profile = world.crop_profile
    reference = next((day for day, stage in profile.stage_thresholds
                      if stage == profile.mature_stage), None)
    ages = [world.get_ridge(i).days_since_planted for i in ridge_ids]
    valid = reference is not None and all(
        isinstance(age, (int, float)) and not isinstance(age, bool)
        and isfinite(age) and age >= 0 for age in ages)
    # Calendar assumptions are not cultivar-specific native WOFOST predictions.
    remaining = [max(0, reference - age) for age in ages] if valid else []
    estimate = [min(remaining), max(remaining)] if remaining and min(remaining) > 0 else None
    return {
        "guidance": (
            f"Rough calendar estimate: about {estimate[0]:g}-{estimate[1]:g} days "
            "remaining to reference maturity. " if estimate else
            "Remaining time to maturity is uncertain; the reference calendar "
            "is unavailable or already reached. "
        ) + "This is not a harvest date or a WOFOST prediction. Advance to a "
        "suitable management/recheck window, not blindly to the estimate; "
        "continue required crop care. Recheck actual maturity, grain moisture "
        "and weather before harvesting.",
        "estimated_days_to_reference_maturity_range": estimate,
        "reference_maturity_days_after_planting": reference,
        "estimate_basis": "public crop_profile calendar minus observed days_since_planted; "
        "generic, uncalibrated for native cultivars; weather and stress may shift maturity",
    }
