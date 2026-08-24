"""Electrical power subsystem model and orbit-by-orbit energy balance.

The model follows the standard EPS sizing chain of Wertz & Larson, *Space
Mission Analysis and Design*, Ch. 11, refined so that the illumination input
comes from the fractional-occultation integral rather than from a binary
sunlit/eclipse flag:

    P_gen(t) = nu(t) . S(t) . A_cell . eta_cell . f_pack . f_deg . kappa(t)
             . eta_ppt

    E_gen(k) = \\int_{rev k} P_gen dt
             = S_0 . A_cell . eta_cell . f_pack . f_deg . eta_ppt
               . [ \\int nu (S/S_0) kappa dt ]_k

so that the entire orbital-mechanics contribution is carried by the single
per-revolution quantity ``array_integral_s`` produced by
:func:`solarsim.simulate.simulate_orbit`.

The battery is propagated as an energy reservoir with separate charge and
discharge efficiencies and a depth-of-discharge limit; the within-revolution
depth of discharge is computed from the eclipse duration directly, because the
load is (by assumption) constant across the eclipse.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np

from .constants import SOLAR_CONSTANT
from .simulate import OrbitSimulation


@dataclass
class PowerSystem:
    """Electrical power subsystem parameters.

    Defaults describe a representative ~150 kg LEO smallsat with a
    triple-junction GaAs array, sized in the class of platforms used for
    on-board edge computing.
    """

    array_area_m2: float = 4.0
    cell_efficiency: float = 0.30       # triple-junction GaAs, BOL
    packing_factor: float = 0.90        # cell area / substrate area
    degradation_bol_eol: float = 0.85   # end-of-life radiation + UV losses
    ppt_efficiency: float = 0.93        # MPPT / PCDU conversion
    array_model: str = "single_axis_pitch"

    battery_capacity_wh: float = 400.0
    dod_limit: float = 0.30             # design limit for LEO cycle life
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.97
    initial_soc: float = 1.0

    housekeeping_w: float = 25.0        # bus, ADCS, TT&C, thermal
    payload_w: float = 60.0             # nominal continuous payload draw
    payload_duty: float = 1.0           # fraction of the orbit the payload runs

    @property
    def array_gain_w(self) -> float:
        """Watts produced per unit of the illumination integral (W at 1 AU, kappa=1)."""
        return (
            SOLAR_CONSTANT
            * self.array_area_m2
            * self.cell_efficiency
            * self.packing_factor
            * self.degradation_bol_eol
            * self.ppt_efficiency
        )

    @property
    def peak_power_w(self) -> float:
        """Array output in full sun at normal incidence."""
        return self.array_gain_w

    @property
    def load_w(self) -> float:
        return self.housekeeping_w + self.payload_w * self.payload_duty

    @property
    def usable_battery_wh(self) -> float:
        return self.battery_capacity_wh * self.dod_limit


@dataclass
class EnergyBalance:
    """Per-revolution energy budget and battery state trajectory."""

    e_gen_wh: np.ndarray        # generated energy per revolution
    e_load_wh: np.ndarray       # consumed energy per revolution
    e_net_wh: np.ndarray        # net into the battery (after conversion losses)
    soc: np.ndarray             # state of charge at the end of each revolution
    dod_rev: np.ndarray         # depth of discharge incurred within each revolution
    p_gen_avg_w: np.ndarray     # orbit-average generated power
    system: PowerSystem
    sim: OrbitSimulation

    def summary(self) -> dict:
        n_year = 365.25 * 86400.0 / self.sim.nodal_period_s
        worst = int(np.argmin(self.soc))
        return {
            "array_model": self.system.array_model,
            "peak_power_w": self.system.peak_power_w,
            "load_w": self.system.load_w,
            "p_gen_mean_w": float(np.mean(self.p_gen_avg_w)),
            "p_gen_min_w": float(np.min(self.p_gen_avg_w)),
            "p_gen_max_w": float(np.max(self.p_gen_avg_w)),
            "margin_mean": float(np.mean(self.p_gen_avg_w) / self.system.load_w - 1.0),
            "margin_worst": float(np.min(self.p_gen_avg_w) / self.system.load_w - 1.0),
            "energy_positive_rev_fraction": float(np.mean(self.e_net_wh > 0.0)),
            "soc_min": float(np.min(self.soc)),
            "soc_min_rev": worst,
            "soc_min_day": float(self.sim.rev_start_s[worst] / 86400.0),
            "dod_max": float(np.max(self.dod_rev)),
            "dod_mean": float(np.mean(self.dod_rev)),
            "dod_limit_violated": bool(np.max(self.dod_rev) > self.system.dod_limit),
            "battery_wh_required_for_dod_limit": float(
                np.max(self.dod_rev) * self.system.battery_capacity_wh
                / self.system.dod_limit
            ),
            "eclipse_cycles_per_year": float(
                np.mean(self.sim.eclipse_s > 0.0) * n_year
            ),
            "surplus_energy_wh_per_year": float(
                np.sum(np.maximum(self.e_gen_wh - self.e_load_wh, 0.0))
                * (n_year / max(len(self.e_gen_wh), 1))
            ),
        }


def energy_balance(
    sim: OrbitSimulation,
    system: Optional[PowerSystem] = None,
) -> EnergyBalance:
    """Propagate the energy budget over the simulated revolutions."""
    system = system or PowerSystem()
    if system.array_model not in sim.array_integral_s:
        raise KeyError(
            f"simulation does not carry the array model {system.array_model!r}; "
            f"available: {sorted(sim.array_integral_s)}"
        )

    integral_s = sim.array_integral_s[system.array_model]
    e_gen_wh = system.array_gain_w * integral_s / 3600.0
    e_load_wh = system.load_w * sim.nodal_period_s / 3600.0 * np.ones_like(e_gen_wh)
    p_gen_avg = system.array_gain_w * integral_s / sim.nodal_period_s

    # Battery propagation with asymmetric conversion efficiency.
    net = np.where(
        e_gen_wh >= e_load_wh,
        (e_gen_wh - e_load_wh) * system.charge_efficiency,
        (e_gen_wh - e_load_wh) / system.discharge_efficiency,
    )
    soc = np.empty_like(net)
    s = system.initial_soc
    cap = system.battery_capacity_wh
    for k in range(net.size):
        s = min(1.0, max(0.0, s + net[k] / cap))
        soc[k] = s

    # Within-revolution depth of discharge: the load runs on battery power for
    # the whole geometric eclipse.  Array output during the penumbra is not
    # credited, which is conservative; the penumbra is a few tens of seconds
    # against eclipses of tens of minutes, so the bias is below 1 % (quantified
    # by the penumbra statistics reported alongside every simulation).
    eclipse_deficit_wh = system.load_w * sim.eclipse_s / 3600.0
    dod_rev = eclipse_deficit_wh / (system.discharge_efficiency * cap)

    return EnergyBalance(
        e_gen_wh=e_gen_wh,
        e_load_wh=e_load_wh,
        e_net_wh=net,
        soc=soc,
        dod_rev=dod_rev,
        p_gen_avg_w=p_gen_avg,
        system=system,
        sim=sim,
    )


def size_battery(
    sim: OrbitSimulation,
    system: PowerSystem,
    margin: float = 1.0,
) -> float:
    """Battery capacity [Wh] needed to hold the worst-case revolution within `dod_limit`."""
    worst_eclipse_s = float(np.max(sim.eclipse_s))
    return (
        margin
        * system.load_w
        * worst_eclipse_s
        / 3600.0
        / (system.discharge_efficiency * system.dod_limit)
    )


def size_array(
    sim: OrbitSimulation,
    system: PowerSystem,
    margin: float = 1.1,
) -> float:
    """Array area [m^2] needed for a non-negative energy balance in the worst revolution."""
    integral_s = sim.array_integral_s[system.array_model]
    worst = float(np.min(integral_s))
    if worst <= 0.0:
        return float("inf")
    required_gain = (
        margin
        * system.load_w
        * sim.nodal_period_s
        / (worst * system.charge_efficiency)
    )
    per_m2 = system.array_gain_w / system.array_area_m2
    return required_gain / per_m2
