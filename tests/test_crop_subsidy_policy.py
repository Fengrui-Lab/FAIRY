"""Policy mechanism fixtures; these do not claim that an agricultural season ran."""

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from fairy.apps.farm_world import FarmWorldApp
from fairy.scenarios.management_extensions.apps.crop_subsidy_app import CropSubsidyApp
from fairy.time_manager import SimulationTimeManager
from fairy.scenarios.management_extensions.china_market_prices import usd


@pytest.fixture
def subject():
    farm = FarmWorldApp(
        crop_type="soybean", num_ridges=16, field_length_m=268.0, ridge_width_m=0.75
    )
    farm.simulation_timezone = ZoneInfo("Asia/Shanghai")
    for ridge in farm._ridges:
        ridge.planted = True
    clock = SimulationTimeManager()
    cycle = SimpleNamespace(closed=[])
    documents = json.loads(
        (
            Path(__file__).parents[1]
            / "fairy/scenarios/management_extensions/data/jilin_2025_policy/notices.json"
        ).read_text()
    )
    app = CropSubsidyApp(
        farm,
        cycle,
        county="榆树市",
        year=2025,
        documents=documents,
        application_from="2025-05-01",
        application_until="2025-06-30",
        payment_from="2025-09-11",
        payment_until="2025-10-31",
    )
    for item in (farm, app):
        item.register_time_manager(clock)

    def at(day):
        clock.reset(
            datetime.fromisoformat(day)
            .replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            .timestamp()
        )

    at("2025-05-06T07:00:00")
    return farm, cycle, app, at


def apply(app, **kwargs):
    return app.apply_for_subsidy(
        **{
            "year": 2025,
            "crop_id": "soybean",
            "county": "榆树市",
            "document_id": "jilin_2025_march_program",
            **kwargs,
        }
    )


def test_future_documents_and_post_planting_final_rate_are_not_retrieved_early(subject):
    _, _, app, at = subject
    at("2024-10-01T07:00:00")
    assert app.search_policies(2025, "榆树市")["documents"] == []
    at("2025-03-24T12:00:00")
    assert app.search_policies(2025, "榆树市")["documents"] == []
    at("2025-03-25T07:00:00")
    docs = app.search_policies(2025, "榆树市")["documents"]
    assert len(docs) == 1 and docs[0]["rates_yuan_per_mu"]["maize"] is None
    at("2025-09-11T07:00:00")
    assert len(app.search_policies(2025, "榆树市")["documents"]) == 2


@pytest.mark.parametrize("change", [{"county": "通榆县"}, {"year": 2024}])
def test_wrong_county_or_year_cannot_claim_and_has_no_cash_effect(subject, change):
    _, _, app, _ = subject
    app.search_policies(2025, "榆树市")
    before = deepcopy(app.get_state())
    with pytest.raises(ValueError):
        apply(app, **change)
    assert app.get_state() == before and app.paid_income() == 0


def test_scope_search_reports_actual_county_rate(subject):
    _, _, app, _ = subject
    assert (
        app.search_policies(2025, "通榆县")["documents"][0]["rates_yuan_per_mu"][
            "soybean"
        ]
        == 410.0
    )
    with pytest.raises(ValueError, match="Retrieve"):
        apply(app)


def test_real_area_not_user_declared_area_and_duplicate_application_payment_are_idempotent(
    subject,
):
    farm, cycle, app, at = subject
    app.search_policies(2025, "榆树市")
    receipt = apply(app)
    assert receipt["area_mu"] == pytest.approx(farm.field_area_m2 * 15 / 10000)
    assert apply(app) == receipt
    assert app.paid_income() == 0
    cycle.closed = [{"year": 2025, "crop_id": "soybean"}]
    at("2025-09-11T07:00:00")
    app.search_policies(2025, "榆树市")
    paid = app.collect_subsidy(2025)
    expected = round(farm.field_area_m2 * 15 / 10000 * 550.0, 4)
    assert paid["currency"] == "USD" and paid["amount_usd"] == pytest.approx(usd(expected))
    assert app.paid_income_yuan() == expected
    assert paid["amount_yuan"] == expected and app.paid_income() == pytest.approx(usd(expected))
    assert (
        app.collect_subsidy(2025)["additional_payment_yuan"] == 0
        and app.paid_income() == pytest.approx(usd(expected))
    )
    saved = deepcopy(app.get_state())
    app.load_state(saved)
    assert app.get_state() == saved


def test_retrieval_alone_and_application_without_harvest_never_pay(subject):
    _, _, app, at = subject
    app.search_policies(2025, "榆树市")
    at("2025-09-11T07:00:00")
    with pytest.raises(ValueError, match="No registered"):
        app.collect_subsidy(2025)
    at("2025-05-06T07:00:00")
    apply(app)
    at("2025-09-11T07:00:00")
    app.search_policies(2025, "榆树市")
    with pytest.raises(ValueError, match="actual harvested"):
        app.collect_subsidy(2025)
    assert app.paid_income() == 0


def test_late_application_is_refused_without_mutating_accounts(subject):
    _, _, app, at = subject
    app.search_policies(2025, "榆树市")
    at("2025-07-01T07:00:00")
    before = deepcopy(app.get_state())
    with pytest.raises(ValueError, match="application window"):
        apply(app)
    assert app.get_state() == before
