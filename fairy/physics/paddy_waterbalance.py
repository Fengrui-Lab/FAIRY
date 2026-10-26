"""Ponded CWB extension: one ledger from land preparation through harvest.

PCSE's two-zone balance supplies infiltration, root redistribution, evaporation
and transpiration. This extension adds metered surface inflow/drainage and
puddling. It is a bucket approximation, not a groundwater/submergence model.
Native lengths are cm; the public metering interface uses mm.
"""
import math


def _load_native_classes():
    from pcse.base import SimulationObject
    from pcse.decorators import prepare_states
    from pcse.exceptions import WaterBalanceError
    from pcse.soil.classic_waterbalance import WaterbalanceFD
    from pcse.soil.soil_wrappers import SoilModuleWrapper_NWLP_CWB_CNB
    from pcse.soil.n_soil_dynamics import N_Soil_Dynamics
    from pcse.traitlets import Float

    class PaddyWaterBalance(WaterbalanceFD):
        drained_cm = Float(0.0)
        bund_loss_cm = Float(0.0)

        @prepare_states
        def meter_water(self, amount_mm, *, drain=False, leak=False):
            if not math.isfinite(amount_mm) or amount_mm < 0:
                raise ValueError("Water depth must be finite and nonnegative")
            s = self.states
            amount = amount_mm / 10.0
            if drain:
                actual = min(amount, max(0.0, s.SS))
                s.SS -= actual
                if leak:
                    self.bund_loss_cm += actual
                else:
                    self.drained_cm += actual
            else:
                actual = amount
                overflow = max(0.0, s.SS + amount - self.params.SSMAX)
                s.SS += amount - overflow
                s.TOTIRR += amount
                s.TSR += overflow
            self.audit()
            return actual * 10.0

        def puddle(self, percolation_cm_day, subsoil_loss_cm_day):
            """Change rates, never water stocks; values are scenario assumptions."""
            for value in (percolation_cm_day, subsoil_loss_cm_day):
                if not math.isfinite(value) or value <= 0:
                    raise ValueError("Puddled hydraulic rates must be positive")
            self.params.SOPE = percolation_cm_day
            self.params.KSUB = subsoil_loss_cm_day

        def ledger(self):
            s = self.states
            initial = s.SSI + s.WI + s.WLOWI
            stored = s.SS + s.W + s.WLOW
            incoming = s.RAINT + s.TOTIRR
            outgoing = s.EVWT + s.EVST + s.WTRAT + s.TSR + s.LOSST + self.drained_cm + self.bund_loss_cm
            return {"surface_water_mm": s.SS * 10, "root_vwc": s.SM,
                    "soil_storage_mm": (s.W + s.WLOW) * 10,
                    "initial_storage_mm": initial * 10, "rain_mm": s.RAINT * 10,
                    "irrigation_mm": s.TOTIRR * 10, "drainage_mm": self.drained_cm * 10,
                    "bund_loss_mm": self.bund_loss_cm * 10,
                    "overflow_mm": s.TSR * 10, "seepage_mm": s.LOSST * 10,
                    "evaporation_mm": (s.EVWT + s.EVST) * 10,
                    "transpiration_mm": s.WTRAT * 10,
                    "balance_residual_mm": (initial + incoming - stored - outgoing) * 10}

        def audit(self):
            result = self.ledger()
            if abs(result["balance_residual_mm"]) > 1e-6:
                raise WaterBalanceError(f"Paddy water ledger does not close: {result}")
            if min(self.states.SS, self.states.W, self.states.WLOW) < -1e-8:
                raise WaterBalanceError("Negative paddy water storage")
            return result

        @prepare_states
        def finalize(self, day):
            s = self.states
            s.WBALRT = (s.TOTINF + s.WI + s.WDRT - s.EVST - s.WTRAT
                         - s.PERCT - s.W + sum(self._increments_W))
            s.WBALTT = self.audit()["balance_residual_mm"] / 10
            if abs(s.WBALRT) > 1e-4:
                raise WaterBalanceError("Paddy root-zone water balance does not close")
            SimulationObject.finalize(self, day)


    class PaddyNitrogenBalance(N_Soil_Dynamics):
        """Classic native N bucket plus explicitly empirical transport loss.

        No ammonium/nitrate speciation, nitrification or denitrification is
        claimed. Applied product N, unrecovered N, transport, crop uptake and
        background input are accounted independently in kg N/ha.
        """
        applied_n = Float(0.)
        unrecovered_n = Float(0.)
        transported_n = Float(0.)
        uptake_n = Float(0.)
        background_n = Float(0.)

        @prepare_states
        def fertilize(self, amount, recovery):
            if not math.isfinite(amount) or amount < 0 or not 0 <= recovery <= 1:
                raise ValueError("Invalid nitrogen application")
            self.applied_n += amount
            self.unrecovered_n += amount * (1 - recovery)
            self.states.NAVAIL += amount * recovery

        @prepare_states
        def transport(self, outgoing_mm):
            lost = max(0., self.states.NAVAIL) * min(.10, max(0., outgoing_mm) * .0005)
            self.states.NAVAIL -= lost
            self.transported_n += lost

        @prepare_states
        def integrate(self, day, delt=1.):
            self.uptake_n += max(0., self.params.BG_N_SUPPLY - self.rates.RNSOIL - self.rates.RNAVAIL) * delt
            self.background_n += self.params.BG_N_SUPPLY * delt
            # PCSE descriptors cache bound methods by name; calling the base
            # decorated integrate would replace this override on the instance.
            self.states.NSOIL += self.rates.RNSOIL * delt
            self.states.NAVAIL += self.rates.RNAVAIL * delt
            self.audit()

        def audit(self):
            initial = self.params.NAVAILI + self.params.NSOILBASE
            residual = (initial + self.applied_n + self.background_n - self.unrecovered_n
                        - self.transported_n - self.uptake_n - self.states.NAVAIL - self.states.NSOIL)
            if abs(residual) > 1e-6 or min(self.states.NAVAIL, self.states.NSOIL) < -1e-6:
                raise ValueError("Paddy nitrogen ledger does not close")
            return {"initial_n_kg_ha": initial, "available_n_kg_ha": self.states.NAVAIL,
                    "reserve_n_kg_ha": self.states.NSOIL, "applied_n_kg_ha": self.applied_n,
                    "unrecovered_n_kg_ha": self.unrecovered_n, "transported_n_kg_ha": self.transported_n,
                    "crop_uptake_n_kg_ha": self.uptake_n, "background_n_kg_ha": self.background_n,
                    "balance_residual_n_kg_ha": residual}

    class PaddySoilWrapper(SoilModuleWrapper_NWLP_CWB_CNB):
        waterbalance_class = PaddyWaterBalance
        nutrientbalance_class = PaddyNitrogenBalance

    return {"PaddyWaterBalance": PaddyWaterBalance, "PaddySoilWrapper": PaddySoilWrapper}


def __getattr__(name):
    # Keep package discovery and legacy scenarios usable without the optional PCSE extra.
    if name not in {"PaddyWaterBalance", "PaddySoilWrapper"}:
        raise AttributeError(name)
    native = _load_native_classes()
    globals().update(native)
    return native[name]
