"""The new shared forcing must remain an exact copy of the archived NASA data."""
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path


DATA = Path(__file__).resolve().parents[1] / 'fairy/physics/data/wofost/research/thionville_nasa2019_v1'


def test_archived_and_normalized_weather_hashes_match_provenance():
    manifest = json.loads((DATA / 'manifest.json').read_text())
    for kind in ('raw', 'weather'):
        content = (DATA / manifest[f'{kind}_path']).read_bytes()
        assert hashlib.sha256(content).hexdigest() == manifest[f'{kind}_sha256']
        assert len(content) == manifest[f'{kind}_byte_count']


def test_all_275_days_and_six_values_equal_the_original_response():
    manifest = json.loads((DATA / 'manifest.json').read_text())
    raw = json.loads((DATA / manifest['raw_path']).read_text())
    weather = json.loads((DATA / manifest['weather_path']).read_text())
    dates = [date(2019, 3, 1) + timedelta(days=n) for n in range(275)]
    assert [row['date'] for row in weather['daily']] == [d.isoformat() for d in dates]
    assert dates[-1] == date(2019, 11, 30)
    mapping = {'T2M_MIN':'tmin_c','T2M_MAX':'tmax_c','RH2M':'relative_humidity_pct',
               'WS2M':'wind_2m_m_s','PRECTOTCORR':'rain_mm','ALLSKY_SFC_SW_DWN':'shortwave_mj_m2_day'}
    assert raw['messages'] == []
    for source, target in mapping.items():
        series = raw['properties']['parameter'][source]
        assert set(series) == {d.strftime('%Y%m%d') for d in dates}
        assert weather['units'][target] == raw['parameters'][source]['units']
        for day, row in zip(dates, weather['daily']):
            assert row[target] == series[day.strftime('%Y%m%d')]
            assert row[target] != raw['header']['fill_value']
    assert weather['units']['shortwave_mj_m2_day'] == 'MJ/m^2/day'


def test_same_point_and_unshifted_lst_labels_are_explicit():
    manifest = json.loads((DATA / 'manifest.json').read_text())
    raw = json.loads((DATA / manifest['raw_path']).read_text())
    weather = json.loads((DATA / manifest['weather_path']).read_text())
    assert raw['geometry']['coordinates'] == [6.2,49.4,277.87]
    assert weather['location'] == manifest['location']
    assert (weather['location']['longitude'], weather['location']['latitude']) == (6.2,49.4)
    assert raw['header']['time_standard'] == weather['time_standard'] == 'LST'
    assert manifest['weather_period']['day_count'] == 275
    assert manifest['normalization']['missing_value_fill'] is None
    assert manifest['normalization']['radiation_adjustment'] is None
    assert manifest['normalization']['rainfall_redistribution'] is None


def test_both_regional_crop_sources_remain_pinned_and_unmodified():
    manifest = json.loads((DATA / 'manifest.json').read_text())
    crops = {row['variety_name']:row for row in manifest['crop_references']}
    assert set(crops) == {'Soybean_901','Grain_maize_201'}
    for row in crops.values():
        assert hashlib.sha256((DATA / row['crop_path']).read_bytes()).hexdigest() == row['crop_sha256']
        assert row['upstream_commit'] == '1ca91d7dbb5aaf6b41462162de03a8254812d3a5'
        assert row['site_validation'] is False
    assert crops['Soybean_901']['official_coverage_region'] == 'Northern-France'
    assert crops['Grain_maize_201']['official_coverage_region'] == 'Germany, Luxembourg'
