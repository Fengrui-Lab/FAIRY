"""Dated official-policy retrieval and simulated, eligibility-checked subsidy processing.

Rate/publication facts come from frozen government notices. The farm's registered
identity and application/payment windows are explicit scenario assumptions, not
claims about a real farm or unpublished government processing rules.
"""

from copy import deepcopy
from datetime import datetime

from fairy.apps.app import App
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered
from ..china_market_prices import CNY_PER_USD, PRICE_BOOK_ID, usd


class CropSubsidyApp(App):
    def __init__(
        self,
        farm,
        cycle,
        *,
        county,
        year,
        documents,
        application_from,
        application_until,
        payment_from,
        payment_until,
    ):
        super().__init__("CropSubsidy")
        self.farm = farm
        self.cycle = cycle
        self.county = county
        self.year = year
        self.documents = deepcopy(documents)
        self.application_from = application_from
        self.application_until = application_until
        self.payment_from = payment_from
        self.payment_until = payment_until
        self.retrieved = []
        self.applications = {}
        self.payments = {}

    def get_state(self):
        return {
            "retrieved": deepcopy(self.retrieved),
            "applications": deepcopy(self.applications),
            "payments": deepcopy(self.payments),
        }

    def load_state(self, state):
        self.retrieved = deepcopy(state["retrieved"])
        self.applications = deepcopy(state["applications"])
        self.payments = deepcopy(state["payments"])
        if any(k not in self.applications for k in self.payments):
            raise ValueError("Payment without a registered application")

    def _available(self, document):
        return (
            datetime.fromisoformat(document["published_at"]).timestamp()
            <= self.time_manager.time()
        )

    def _day(self):
        return self.farm.simulation_date(self.time_manager.time()).isoformat()

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def search_policies(self, year: int, county: str) -> dict:
        """Retrieve and record policy notices published by the current simulated time.

        Args:
            year: Calendar policy year; no published match returns empty documents.
            county: Exact county name; registered_county in the result identifies
                this farm's eligibility.

        Returns:
            dict: Registration, ISO date and documents with IDs, publication times,
            eligible crops and rates_yuan_per_mu (CNY/mu; null if unpublished).
            Application/payment windows are inclusive ISO dates with a declared
            window_source. Search again after final rates are published.
        """
        found = []
        for document in self.documents:
            if (
                document["year"] != year
                or county not in document["counties"]
                or not self._available(document)
            ):
                continue
            row = deepcopy(document)
            row["queried_county"] = county
            row["rates_yuan_per_mu"] = deepcopy(
                document.get("county_rates_yuan_per_mu", {}).get(
                    county, document["rates_yuan_per_mu"]
                )
            )
            found.append(row)
            token = [document["document_id"], county]
            if token not in self.retrieved:
                self.retrieved.append(token)
        return {
            "date": self._day(),
            "registered_county": self.county,
            "registered_year": self.year,
            "documents": found,
            "application_window": [self.application_from, self.application_until],
            "payment_window": [self.payment_from, self.payment_until],
            "window_source": "Declared simulated processing windows, separate from official rate facts",
        }

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def apply_for_subsidy(
        self, year: int, crop_id: str, county: str, document_id: str
    ) -> dict:
        """Register the fully planted crop and measured area; payment is separate.

        Prerequisites:
            Retrieve an eligible notice via search_policies and apply within its
            inclusive application window. All ridges must contain the claimed crop.
            One application per farm/year; identical retries return the receipt.

        Args:
            year: registered_year from search_policies.
            crop_id: Actual crop ID listed in the notice's eligible_crops.
            county: registered_county from search_policies.
            document_id: Applicable published document ID retrieved for this year/county.

        Returns:
            dict: Application ID, crop, year/county, measured area_m2/area_mu,
            submitted_on (ISO date) and status=registered_not_paid.
        """
        key = f"{year}-{self.farm.farm_id}"
        if key in self.applications:
            previous = self.applications[key]
            if (previous["crop_id"], previous["county"], previous["document_id"]) != (
                crop_id,
                county,
                document_id,
            ):
                raise ValueError("Cannot replace a registered subsidy application")
            return deepcopy(previous)
        if year != self.year or county != self.county:
            raise ValueError(
                "Policy year/county does not match registered farm eligibility"
            )
        document = next(
            (
                d
                for d in self.documents
                if d["document_id"] == document_id
                and d["year"] == year
                and county in d["counties"]
            ),
            None,
        )
        if (
            document is None
            or not self._available(document)
            or [document_id, county] not in self.retrieved
        ):
            raise ValueError("Retrieve a currently published applicable policy first")
        if not self.application_from <= self._day() <= self.application_until:
            raise ValueError("Outside the declared application window")
        if self.farm.crop_type != crop_id or crop_id not in document["eligible_crops"]:
            raise ValueError(
                "Claimed crop does not match the actual eligible planted crop"
            )
        if not all(r.planted for r in self.farm._ridges):
            raise ValueError(
                "Complete actual full-field planting before registering area"
            )
        area = self.farm.field_area_m2
        receipt = {
            "application_id": key,
            "year": year,
            "county": county,
            "document_id": document_id,
            "crop_id": crop_id,
            "area_m2": area,
            "area_mu": area * 15 / 10000,
            "submitted_on": self._day(),
            "status": "registered_not_paid",
        }
        self.applications[key] = receipt
        return deepcopy(receipt)

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def collect_subsidy(self, year: int) -> dict:
        """Collect a registered crop's subsidy after safe harvest and season closure.

        Prerequisites:
            Matching closed crop/area, current date within the payment window and
            final non-null rate retrieved via search_policies. Latest applicable
            retrieved notice sets the rate; repeats add no income.

        Args:
            year: Calendar year of the registered application and closed season.

        Returns:
            dict: Application/crop IDs, area_mu, CNY/mu rate, amount_yuan (CNY),
            amount_usd, fixed cny_per_usd, paid_on and source document.
            additional_payment_yuan/usd is the new payment, zero on repeat calls.
        """
        key = f"{year}-{self.farm.farm_id}"
        if key in self.payments:
            return {
                **deepcopy(self.payments[key]),
                "additional_payment_yuan": 0.0,
                "additional_payment_usd": 0.0,
            }
        application = self.applications.get(key)
        if application is None:
            raise ValueError(
                "No registered application; policy retrieval is not a claim"
            )
        if not self.payment_from <= self._day() <= self.payment_until:
            raise ValueError("Outside the declared payment window")
        season = next((s for s in self.cycle.closed if s["year"] == year), None)
        if (
            season is None
            or season["crop_id"] != application["crop_id"]
            or abs(application["area_m2"] - self.farm.field_area_m2) > 1e-7
        ):
            raise ValueError(
                "Verify actual harvested crop and unchanged field area before payment"
            )
        applicable = [
            d
            for d in self.documents
            if d["year"] == year
            and self.county in d["counties"]
            and self._available(d)
            and [d["document_id"], self.county] in self.retrieved
            and d.get("county_rates_yuan_per_mu", {})
            .get(self.county, d.get("rates_yuan_per_mu", {}))
            .get(application["crop_id"])
            is not None
        ]
        if not applicable:
            raise ValueError("No published retrieved final rate for this crop")
        policy = max(applicable, key=lambda d: d["published_at"])
        rate = policy.get("county_rates_yuan_per_mu", {}).get(
            self.county, policy["rates_yuan_per_mu"]
        )[application["crop_id"]]
        amount = round(application["area_mu"] * rate, 4)
        receipt = {
            "application_id": key,
            "crop_id": application["crop_id"],
            "area_mu": application["area_mu"],
            "rate_yuan_per_mu": rate,
            "amount_yuan": amount,
            "paid_on": self._day(),
            "source_document_id": policy["document_id"],
            "currency": "USD",
            "source_currency": "CNY",
            "amount_usd": usd(amount),
            "cny_per_usd": CNY_PER_USD,
        }
        self.payments[key] = receipt
        return {
            **deepcopy(receipt),
            "additional_payment_yuan": amount,
            "additional_payment_usd": usd(amount),
        }

    def paid_income_yuan(self):
        """Official-notice currency total retained for source audits."""
        return sum(payment["amount_yuan"] for payment in self.payments.values())

    def paid_income(self):
        """Actual paid USD income, converted once at the scenario's frozen FX rate."""
        return usd(self.paid_income_yuan())

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_subsidy_accounts(self) -> dict:
        """Read registrations and actual subsidy payments in USD and source CNY.

        Returns:
            dict: applications, payments, paid_income (USD), paid_income_yuan (CNY),
            fixed cny_per_usd and price_book_id. Application status is its original
            registration snapshot; use payments and paid_income to confirm payment.
        """
        return {
            "currency": "USD",
            "source_currency": "CNY",
            "price_book_id": PRICE_BOOK_ID,
            "cny_per_usd": CNY_PER_USD,
            "paid_income_yuan": self.paid_income_yuan(),
            "paid_income": self.paid_income(),
            "applications": deepcopy(self.applications),
            "payments": deepcopy(self.payments),
        }
