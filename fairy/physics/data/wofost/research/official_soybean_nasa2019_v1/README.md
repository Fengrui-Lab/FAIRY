# Official soybean model reference with fixed 2019 weather

This is a reproducible **model reference**, not a reconstruction of the original
crop-calibration field trials. Its acceptance criterion is numerical agreement
between the formal world and native WOFOST with identical inputs. No measured
yield is supplied for these exact location/year/management combinations.

The four original variety identities are `Soybean_901` (Northern France),
`Soybean_902` (Central France), `Soybean_903` (Northern Spain), and `Soybean_905`
(Italy). They are regional WOFOST parameter sets, not newly named commercial
cultivars. Their numeric parameters are read directly from the existing pinned
`../../soybean.yaml`; this bundle neither copies nor overrides them. The crop
source SHA and each resolved parameter dictionary SHA are in `manifest.json`.
The official metadata is reproduced there for traceability. The 2019 sowing
month/day follows that metadata: 28 April for 901/902 and 30 April for 903/905.
These are reference inputs, not an assertion about the actual 2019 farmers.

| ID | Representative point | Official variety | Sowing date |
| --- | --- | --- | --- |
| lille | 50.63 N, 3.06 E | Soybean_901 | 2019-04-28 |
| clermont_ferrand | 45.78 N, 3.08 E | Soybean_902 | 2019-04-28 |
| valladolid | 41.65 N, 4.72 W | Soybean_903 | 2019-04-30 |
| bologna | 44.49 N, 11.34 E | Soybean_905 | 2019-04-30 |

Each point has 275 contiguous daily records from 1 March to 30 November 2019.
The original NASA POWER JSON responses are preserved byte for byte in `raw/`.
Each manifest row records its exact request URL, API version, source products,
units, byte count and SHA-256. The response elevation is kept with its source;
it is not a measured field elevation. These are public gridded meteorological
products, not local station observations from the crop's calibration trial.

The normalized `weather/<id>_2019.json` contract is:

```json
{
  "schema_version": 1,
  "id": "lille",
  "location": {"latitude": 50.63, "longitude": 3.06, "elevation_m": 41.86},
  "start_date": "2019-03-01",
  "end_date": "2019-11-30",
  "time_standard": "LST",
  "daily": [
    {
      "date": "2019-03-01",
      "tmin_c": 4.5,
      "tmax_c": 10.36,
      "relative_humidity_pct": 90.06,
      "wind_2m_m_s": 2.72,
      "rain_mm": 2.18,
      "shortwave_mj_m2_day": 3.08
    }
  ]
}
```

This contract excerpt shows the first Lille record. All six normalized values
are copied without numeric changes from
the corresponding original NASA fields:

| NASA parameter | Normalized field | Original returned unit |
| --- | --- | --- |
| T2M_MIN | tmin_c | C |
| T2M_MAX | tmax_c | C |
| RH2M | relative_humidity_pct | % |
| WS2M | wind_2m_m_s | m/s at 2 m |
| PRECTOTCORR | rain_mm | mm/day |
| ALLSKY_SFC_SW_DWN | shortwave_mj_m2_day | MJ/m²/day |

The AG API response already uses MJ/m²/day for shortwave radiation. There is
no kWh conversion, radiation multiplier, rainfall redistribution, rounding,
missing-data replacement or synthetic perturbation here. `PRECTOTCORR` is
the original NASA product's variable name; this project adds no precipitation
correction. If a model needs mean temperature, use the explicitly declared
derived input `(tmin_c + tmax_c) / 2` in both executions.

Dates retain the original response's **Local Solar Time (LST)** daily labels.
They are not shifted through UTC or a civil time zone. The formal world should
map a simulation daily label to the same NASA label. This is a daily forcing
convention; it does not imply that LST equals the location's civil clock.

Soil properties, initial soil water/nitrogen, CO₂, crop calendar end conditions,
and any management must be explicit in the separate model-reference world and
shared with its native comparison. This bundle supplies no measured trial soil
or initial nitrogen. It also does not claim yield validation against field data.

Sources:

- [Official WOFOST crop-parameter repository](https://github.com/ajwdewit/WOFOST_crop_parameters)
  (`wofost81`, pinned commit `1ca91d7dbb5aaf6b41462162de03a8254812d3a5`).
- [Boons-Prins et al. (1993), original parameter-source report](https://edepot.wur.nl/308997).
- [NASA POWER Daily API and LST convention](https://power.larc.nasa.gov/docs/services/api/temporal/daily/).
- [NASA POWER energy-flux source methodology](https://power.larc.nasa.gov/docs/methodology/energy-fluxes/).

Offline checks in `tests/test_research_bundle_data.py` verify raw and normalized
hashes, original parameter identity, every daily input value and unit, complete
date coverage, and absence of silent missing-value fills. They do not run or
calibrate a crop model.
