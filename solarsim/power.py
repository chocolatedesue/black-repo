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

    Defaults describe a representative ~200 kg LEO smallsat carrying an
    on-board processing payload: a 2 m^2 triple-junction GaAs array, a 600 Wh
    battery, and a 265 W total load of which 220 W is payload.  The array is
    deliberately sized so that the balance is neither trivially satisfied nor
    infeasible -- an oversized array would flatten every orbit into the same
    answer and hide the effects this study is about.
    """

    array_area_m2: float = 2.0
    cell_efficiency: float = 0.30       # triple-junction GaAs, BOL
    packing_factor: float = 0.90        # cell area / substrate area
    degradation_bol_eol: float = 0.85   # end-of-life radiation + UV losses
    ppt_efficiency: float = 0.93        # MPPT / PCDU conversion
    array_model: str = "single_axis_pitch"

    battery_capacity_wh: float = 600.0
    dod_limit: float = 0.30             # design limit for LEO cycle life
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.97
    initial_soc: float = 1.0

    housekeeping_w: float = 45.0        # bus, ADCS, TT&C, thermal
    payload_w: float = 220.0            # nominal continuous payload draw
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


# ---------------------------------------------------------------------------
# Where every joule goes
# ---------------------------------------------------------------------------
def energy_ledger(
    trace,
    payload_w=None,
    cell_derate=None,
) -> dict:
    """Account for every joule from the array aperture to the load, in Wh.

    The energy balance in :func:`energy_balance` reports what the battery does.
    This reports something stricter and more useful for a paper's methodology
    section: a *closed* budget in which the sunlight intercepted by the array
    equals the sum of every loss and every delivered load, with nothing left
    over.  Anything unaccounted for shows up immediately as a non-zero residual,
    which makes the whole chain auditable rather than merely plausible.

    The chain, in order, per unit of intercepted sunlight:

    ===========================  ==================================================
    ``incident``                 ``S(t) . nu . kappa . A``, the sunlight the array
                                 aperture intercepts
    ``loss_packing``             substrate area not covered by cells
    ``loss_conversion``          photons the cell cannot convert, at its rating
    ``loss_temperature``         the extra loss from running above 28 C (negative
                                 where the array is *colder* than its rating, which
                                 happens for a while after every sunrise)
    ``loss_degradation``         end-of-life radiation and UV
    ``loss_ppt``                 MPPT and PCDU conversion
    ---------------------------  --------------------------------------------------
    ``bus_generated``            what reaches the bus: the ``p_gen_w`` of the trace
    ---------------------------  --------------------------------------------------
    ``loss_charge``              round-trip loss charging the battery
    ``loss_discharge``           round-trip loss discharging it
    ``curtailed``                generation shunted with the battery already full
    ``delivered_housekeeping``   consumed by the bus, broken out by subsystem
    ``delivered_payload``        consumed by the payload
    ``stored_delta``             net change in battery energy over the horizon
    ===========================  ==================================================

    ``payload_w`` is the payload schedule to account for; omitting it charges the
    ledger for housekeeping alone, which isolates the cost of simply keeping the
    spacecraft alive.

    The curtailment line is the one worth reading twice.  It is not a loss the
    hardware imposes -- it is generation the *schedule* failed to use, and on a
    dawn-dusk orbit with a constant load it is the largest single entry after the
    cell conversion loss.  That is the entire economic case for energy-aware
    scheduling stated as an accounting identity.
    """
    sys_ = trace.system
    dt_h = trace.dt_s / 3600.0
    house = trace.p_house_series
    p_gen = np.asarray(trace.p_gen_w, dtype=float)

    payload = (np.zeros_like(p_gen) if payload_w is None
               else np.broadcast_to(np.asarray(payload_w, dtype=float), p_gen.shape))

    # --- the array chain, unwound backwards from p_gen ---------------------
    if cell_derate is None:
        if trace.panel_temperature_k is not None:
            from .thermal import CellThermalResponse
            cell_derate = CellThermalResponse(
                eta_ref=sys_.cell_efficiency
            ).derate_at(trace.panel_temperature_k)
        else:
            cell_derate = 1.0
    derate = np.broadcast_to(np.asarray(cell_derate, dtype=float), p_gen.shape)

    eta_eff = sys_.cell_efficiency * derate
    chain = eta_eff * sys_.packing_factor * sys_.degradation_bol_eol * sys_.ppt_efficiency
    # Where the chain is zero the array is producing nothing, so nothing is
    # intercepted that is worth attributing; guard the division rather than
    # letting a 0/0 propagate a NaN into an otherwise exact ledger.
    incident = np.where(chain > 0.0, p_gen / np.where(chain > 0.0, chain, 1.0), 0.0)

    after_pack = incident * sys_.packing_factor
    loss_packing = incident - after_pack
    # Conversion loss is split at the *rating*, so that the temperature line
    # carries the whole of the correction this model adds and can be read on its
    # own.  The two sum to the true conversion loss at the actual temperature.
    loss_conversion = after_pack * (1.0 - sys_.cell_efficiency)
    loss_temperature = after_pack * sys_.cell_efficiency * (1.0 - derate)
    after_cell = after_pack * eta_eff
    loss_degradation = after_cell * (1.0 - sys_.degradation_bol_eol)
    after_deg = after_cell * sys_.degradation_bol_eol
    loss_ppt = after_deg * (1.0 - sys_.ppt_efficiency)

    # --- the bus, slot by slot --------------------------------------------
    cap = sys_.battery_capacity_wh
    b = cap
    e_charge_gross = e_charge_loss = 0.0
    e_discharge_loss = e_deficit = e_curtailed = 0.0

    for k in range(p_gen.size):
        delta = p_gen[k] - (house[k] + payload[k])
        if delta >= 0.0:
            gross = delta * dt_h
            room = (cap - b) / sys_.charge_efficiency
            used = min(gross, room)
            e_curtailed += gross - used
            e_charge_gross += used
            e_charge_loss += used * (1.0 - sys_.charge_efficiency)
            b += used * sys_.charge_efficiency
        else:
            need = -delta * dt_h
            out = need / sys_.discharge_efficiency
            out = min(out, b)                       # cannot draw what is not there
            served = out * sys_.discharge_efficiency
            e_deficit += served
            e_discharge_loss += out - served
            b -= out

    e = lambda a: float(np.sum(a) * dt_h)
    total_incident = e(incident)
    delivered_house = e(house)
    delivered_payload = e(payload)
    stored_delta = b - cap

    ledger = {
        "incident_wh": total_incident,
        "loss_packing_wh": e(loss_packing),
        "loss_conversion_wh": e(loss_conversion),
        "loss_temperature_wh": e(loss_temperature),
        "loss_degradation_wh": e(loss_degradation),
        "loss_ppt_wh": e(loss_ppt),
        "bus_generated_wh": e(p_gen),
        "loss_charge_wh": e_charge_loss,
        "loss_discharge_wh": e_discharge_loss,
        "curtailed_wh": e_curtailed,
        "delivered_housekeeping_wh": delivered_house,
        "delivered_payload_wh": delivered_payload,
        "stored_delta_wh": stored_delta,
    }

    accounted = (
        ledger["loss_packing_wh"]
        + ledger["loss_conversion_wh"]
        + ledger["loss_temperature_wh"]
        + ledger["loss_degradation_wh"]
        + ledger["loss_ppt_wh"]
        + ledger["loss_charge_wh"]
        + ledger["loss_discharge_wh"]
        + ledger["curtailed_wh"]
        + delivered_house
        + delivered_payload
        + stored_delta
    )
    ledger["accounted_wh"] = accounted
    ledger["residual_wh"] = total_incident - accounted
    ledger["residual_relative"] = (
        abs(total_incident - accounted) / total_incident if total_incident > 0 else 0.0
    )

    # Useful fraction: what the payload got, per unit of sunlight intercepted.
    ledger["end_to_end_efficiency"] = (
        delivered_payload / total_incident if total_incident > 0 else 0.0
    )
    ledger["curtailed_fraction_of_generated"] = (
        e_curtailed / ledger["bus_generated_wh"] if ledger["bus_generated_wh"] > 0 else 0.0
    )

    if trace.load is not None:
        ledger["housekeeping_breakdown_w"] = trace.load.breakdown_w(
            trace.eclipsed, trace.in_contact
        )
    return ledger
