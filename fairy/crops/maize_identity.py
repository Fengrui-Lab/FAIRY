"""Authoritative native WOFOST maize identity. No legacy-model aliases."""
MAIZE_WOFOST_VARIANTS = {
    "MAIZE_201": "Grain_maize_201",
    "MAIZE_202": "Grain_maize_202",
    "MAIZE_203": "Grain_maize_203",
    "MAIZE_204": "Grain_maize_204",
    "MAIZE_205": "Grain_maize_205",
}

def native_variety(seed):
    if seed not in MAIZE_WOFOST_VARIANTS:
        raise ValueError(f"Unknown native maize seed {seed!r}")
    return MAIZE_WOFOST_VARIANTS[seed]

def public_seed(variety):
    for seed, expected in MAIZE_WOFOST_VARIANTS.items():
        if variety == expected:
            return seed
    raise ValueError(f"Unknown native maize variety {variety!r}")
