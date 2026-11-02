"""Frozen observation randomness for this version of the L4 experiment.

These are the actual App seeds used by the initial calibration under
PYTHONHASHSEED=0. Pinning them preserves that experiment exactly while removing
its dependency on Python's process-salted hash. Weather retains its separate
physical forcing seed 101. No shared App defaults are changed.
"""

APP_SEEDS = {
    "AgentUserInterface": 3729385368,
    "FarmWorldApp": 1281893346,
    "WeatherApp": 433245120,
    "SensorApp": 1025542706,
    "Mavic3M": 695188145,
    "Robot0": 3339168823,
    "TractorApp": 2773417723,
    "FieldOpsApp": 3100517573,
    "SystemApp": 2196534512,
    "SeasonCycle": 4128923743,
}


def initialize_app_randomness(apps):
    """Apply the recorded seeds only to this scene's own application instances."""
    if {app.name for app in apps} != set(APP_SEEDS):
        raise ValueError(
            "New app composition requires an explicit observation-seed declaration"
        )
    for app in apps:
        app.seed = APP_SEEDS[app.name]
        app.rng.seed(app.seed)
