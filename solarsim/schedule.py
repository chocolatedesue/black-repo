"""Energy-availability traces and bounds for energy-aware compute scheduling.

This module exists to answer one question in the form a scheduler can consume:
*how much energy is available for computation, at what times, and what are the
hard limits?*  It deliberately stops at the power-system boundary -- what the
workload does with the energy is the scheduler's problem, not this model's.

Three products:

``PowerTrace``
    A per-timestep series of generated power, housekeeping draw, and the
    surplus available to the payload.  Written as CSV or JSON, this is the
    input a slot-based scheduler iterates over.

``sustainable_power``
    The steady-state bound: the highest *continuous* payload power the orbit
    can support indefinitely, accounting for battery round-trip losses.  A
    schedule whose mean payload draw exceeds this bound cannot be feasible over
    the long run regardless of how cleverly it is arranged.

``burst_envelope``
    The transient bound: how long the payload can run above the sustainable
    level, given the usable battery energy and the depth-of-discharge limit.

Together the two bounds define the feasible region a scheduler works inside,
and they are what a paper should report alongside any scheduling result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np

from .attitude import ARRAY_MODELS
from .constants import SOLAR_CONSTANT
from .orbit import CircularOrbit, orbit_normal
from .power import PowerSystem
from .shadow import illumination_fraction
from .solar import irradiance, sun_vector_eci


@dataclass
class PowerTrace:
    """Per-timestep energy availability over a span of orbits."""

    t_s: np.ndarray              # seconds from epoch
    nu: np.ndarray               # fractional illumination in [0, 1]
    p_gen_w: np.ndarray          # array output
    p_house_w: float             # constant housekeeping draw
    dt_s: float
    nodal_period_s: float
    system: PowerSystem
    label: str = ""

    @property
    def p_surplus_w(self) -> np.ndarray:
        """Power available to the payload before battery losses.

        Negative during eclipse: that deficit must come out of the battery.
        """
        return self.p_gen_w - self.p_house_w

    @property
    def eclipsed(self) -> np.ndarray:
        return self.nu < 1.0

    def energy_wh(self, power_w: np.ndarray) -> float:
        """Trapezoidal integral of a power series over the trace, in Wh."""
        return float(np.trapezoid(power_w, dx=self.dt_s) / 3600.0)

    def to_csv(self, path) -> None:
        """Write the trace as CSV: one row per scheduling slot."""
        header = "t_s,nu,eclipsed,p_gen_w,p_house_w,p_surplus_w"
        rows = np.column_stack([
            self.t_s,
            np.round(self.nu, 6),
            self.eclipsed.astype(int),
            np.round(self.p_gen_w, 4),
            np.full(self.t_s.size, self.p_house_w),
            np.round(self.p_surplus_w, 4),
        ])
        np.savetxt(path, rows, delimiter=",", header=header, comments="",
                   fmt=["%.1f", "%.6f", "%d", "%.4f", "%.2f", "%.4f"])

    def summary(self) -> dict:
        n_orbits = self.t_s[-1] / self.nodal_period_s
        return {
            "label": self.label,
            "span_hours": float(self.t_s[-1] / 3600.0),
            "n_orbits": float(n_orbits),
            "dt_s": self.dt_s,
            "n_slots": int(self.t_s.size),
            "p_gen_mean_w": float(np.mean(self.p_gen_w)),
            "p_gen_max_w": float(np.max(self.p_gen_w)),
            "eclipse_slot_fraction": float(np.mean(self.eclipsed)),
            "energy_generated_wh": self.energy_wh(self.p_gen_w),
            "energy_housekeeping_wh": self.energy_wh(
                np.full_like(self.p_gen_w, self.p_house_w)
            ),
        }


def power_trace(
    orbit: CircularOrbit,
    system: Optional[PowerSystem] = None,
    n_orbits: float = 3.0,
    dt_s: float = 10.0,
    h_atm: float = 90.0,
    label: str = "",
) -> PowerTrace:
    """Sample generated power on a uniform grid, ready for slot-based scheduling.

    ``dt_s`` is the scheduling slot length.  Ten seconds resolves the penumbral
    ramp adequately and gives a few hundred slots per orbit; coarser slots are
    fine for planning horizons of days, since the eclipse boundary is the only
    fast feature.
    """
    system = system or PowerSystem()
    if system.array_model not in ARRAY_MODELS:
        raise KeyError(f"unknown array model {system.array_model!r}")

    T = orbit.nodal_period_s
    t = np.arange(0.0, n_orbits * T + dt_s, dt_s)

    r_sat = orbit.position_eci(t)
    jd = orbit.jd_at(t)
    r_sun = sun_vector_eci(jd)
    s_hat = r_sun / np.linalg.norm(r_sun, axis=-1, keepdims=True)
    raan_t, _ = orbit.elements_at(t)
    h_hat = orbit_normal(raan_t, orbit.inc_rad)

    nu = illumination_fraction(r_sat, r_sun, h_atm)
    kappa = ARRAY_MODELS[system.array_model](r_sat, s_hat, h_hat)
    scale = irradiance(jd) / SOLAR_CONSTANT

    p_gen = system.array_gain_w * nu * scale * kappa

    return PowerTrace(
        t_s=t,
        nu=nu,
        p_gen_w=p_gen,
        p_house_w=system.housekeeping_w,
        dt_s=dt_s,
        nodal_period_s=T,
        system=system,
        label=label or f"h={orbit.altitude_km:.0f}km",
    )


# ---------------------------------------------------------------------------
# The two bounds a scheduler needs
# ---------------------------------------------------------------------------
def _soc_trajectory(trace: "PowerTrace", p_payload: float):
    """Battery energy over the trace for a constant payload draw, starting full.

    Charging saturates at the capacity -- surplus generation beyond a full
    battery is simply lost, which is what a real charge controller does and
    what makes the steady-state condition below meaningful.
    """
    sys = trace.system
    cap = sys.battery_capacity_wh
    dt_h = trace.dt_s / 3600.0
    demand = sys.housekeeping_w + p_payload

    b = cap
    lowest = cap
    for g in trace.p_gen_w:
        delta = g - demand
        step = (delta * sys.charge_efficiency if delta > 0.0
                else delta / sys.discharge_efficiency)
        b = min(cap, max(0.0, b + step * dt_h))
        if b < lowest:
            lowest = b
    return b, lowest


def sustainable_power(trace: PowerTrace) -> dict:
    """Highest continuous payload power the orbit supports indefinitely.

    Two conditions must hold together, and either can bind first:

    *Energy neutrality* -- over a whole number of revolutions the battery has to
    return to where it started, so generation must cover the load plus the
    round-trip losses on whatever had to be stored to cross the eclipse.

    *Depth of discharge* -- the battery must never fall below its design limit
    at any instant, which is a far tighter constraint than the energy balance
    whenever the battery is sized for cycle life rather than for capacity.  In
    LEO, where a five-year mission is some 27 000 eclipse cycles, the depth-of-
    discharge limit is usually the binding one, and a bound derived from the
    energy balance alone overstates the available payload power.

    Both are evaluated by simulating the state of charge, so the exact shape of
    the generation profile is respected rather than assumed square, and charge
    saturation is accounted for.
    """
    sys = trace.system
    floor = sys.battery_capacity_wh * (1.0 - sys.dod_limit)

    def feasible(p: float) -> bool:
        final, lowest = _soc_trajectory(trace, p)
        return lowest >= floor - 1e-9 and final >= sys.battery_capacity_wh - 1e-6

    if not feasible(0.0):
        return {
            "sustainable_payload_w": 0.0,
            "feasible": False,
            "deficit_w": float(sys.housekeeping_w - np.mean(trace.p_gen_w)),
        }

    hi0 = float(np.max(trace.p_gen_w)) + sys.housekeeping_w

    def bisect(test) -> float:
        lo, hi = 0.0, hi0
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            if test(mid):
                lo = mid
            else:
                hi = mid
        return lo

    # Each condition solved on its own, so the result can say which one binds
    # rather than guess.  The joint bound is by construction the smaller.
    p_energy = bisect(
        lambda p: _soc_trajectory(trace, p)[0] >= sys.battery_capacity_wh - 1e-6
    )
    p_dod = bisect(lambda p: _soc_trajectory(trace, p)[1] >= floor - 1e-9)
    p_star = bisect(feasible)

    return {
        "sustainable_payload_w": p_star,
        "feasible": True,
        "p_gen_mean_w": float(np.mean(trace.p_gen_w)),
        "housekeeping_w": sys.housekeeping_w,
        "energy_balance_bound_w": p_energy,
        "dod_bound_w": p_dod,
        "binding_constraint": "depth_of_discharge" if p_dod <= p_energy
        else "energy_balance",
        # The estimate a study gets from "orbit-average generation minus
        # housekeeping".  It ignores both the round-trip loss on stored energy
        # and the depth-of-discharge limit, so it is optimistic on both counts.
        "naive_estimate_w": float(np.mean(trace.p_gen_w)) - sys.housekeeping_w,
    }


def burst_envelope(
    trace: PowerTrace,
    payload_levels_w: Sequence[float],
) -> list:
    """How long the payload can hold each power level on battery alone.

    Answers the transient question: starting from a full usable battery and
    running through the worst part of the orbit, for how long can the payload
    draw ``P_p`` before the depth-of-discharge limit is reached?  This is the
    bound on burst-mode inference or any deadline-driven batch the scheduler
    might want to place.
    """
    sys = trace.system
    usable_wh = sys.battery_capacity_wh * sys.dod_limit
    out = []
    for p in payload_levels_w:
        demand = sys.housekeeping_w + p
        deficit = np.clip(demand - trace.p_gen_w, 0.0, None) / sys.discharge_efficiency
        if not np.any(deficit > 0.0):
            out.append({
                "payload_w": float(p),
                "battery_limited": False,
                "max_duration_s": float("inf"),
                "note": "generation covers this level at every point in the orbit",
            })
            continue
        # Longest window whose cumulative deficit stays inside the usable energy.
        cum = np.concatenate([[0.0], np.cumsum(deficit) * trace.dt_s / 3600.0])
        best = 0
        j = 0
        for i in range(cum.size):
            while cum[i] - cum[j] > usable_wh:
                j += 1
            best = max(best, i - j)
        out.append({
            "payload_w": float(p),
            "battery_limited": True,
            "max_duration_s": float(best * trace.dt_s),
            "usable_battery_wh": usable_wh,
            "peak_deficit_w": float(np.max(demand - trace.p_gen_w)),
        })
    return out


def compute_yield(
    sustainable_w: float,
    joules_per_unit: float,
    period_s: float,
    unit_name: str = "inference",
) -> dict:
    """Translate a sustainable power budget into workload throughput.

    ``joules_per_unit`` is the measured energy cost of one unit of work on the
    target accelerator -- it must come from a measurement on the actual
    hardware, not from this model.  Provided so that the energy bound can be
    reported in the units a scheduling paper actually optimises.
    """
    if joules_per_unit <= 0.0:
        raise ValueError("joules_per_unit must be positive")
    per_s = sustainable_w / joules_per_unit
    return {
        "unit": unit_name,
        "joules_per_unit": joules_per_unit,
        "sustainable_payload_w": sustainable_w,
        "units_per_second": per_s,
        "units_per_orbit": per_s * period_s,
        "units_per_day": per_s * 86400.0,
    }


# ---------------------------------------------------------------------------
# The reference schedule: what an optimiser can actually achieve
# ---------------------------------------------------------------------------
def optimal_schedule(trace: PowerTrace, weights: Optional[np.ndarray] = None) -> dict:
    """Solve the slot-scheduling LP and return the achievable payload profile.

    This is the linear program in its standard form -- payload power ``p``,
    battery inflow ``c`` and outflow ``d`` as separate non-negative variables,
    so the asymmetric charge and discharge efficiencies stay linear:

        max   sum_k w[k] p[k] dt
        s.t.  G[k] + d[k] = P_h + p[k] + c[k]            (power balance)
              b[k] = b[k-1] + dt (eta_c c[k] - d[k]/eta_d)
              (1-D) B <= b[k] <= B
              b[K] >= b[0]                                (periodicity)
              p, c, d >= 0

    ``c[k] d[k] = 0`` holds automatically at the optimum, because simultaneous
    charge and discharge only burns energy, so no complementarity constraint is
    needed and the problem stays an LP.

    The value of this over the constant-draw bound of :func:`sustainable_power`
    is precisely the headroom that energy-aware scheduling exists to capture: a
    constant draw must curtail generation whenever the battery is already full,
    while a schedule free to vary can spend that surplus as it arrives.

    Requires SciPy.  Returns the optimal payload series and its mean.
    """
    try:
        from scipy.optimize import linprog
        from scipy.sparse import csr_matrix, eye, hstack, vstack
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError(
            "optimal_schedule needs SciPy: pip install scipy"
        ) from exc

    sys_ = trace.system
    G = trace.p_gen_w
    K = G.size
    dt_h = trace.dt_s / 3600.0
    cap = sys_.battery_capacity_wh
    floor = cap * (1.0 - sys_.dod_limit)
    w = np.ones(K) if weights is None else np.asarray(weights, dtype=float)

    # The LP is degenerate when every slot is worth the same: charging early and
    # charging late cost identically, so the simplex is free to return any of a
    # large family of optima, and the one it picks chatters between zero and full
    # power from slot to slot.  The mean is correct but the profile is not a
    # schedule anyone would run.  A tie-break of order 1e-6 that very slightly
    # prefers spending earlier selects the interpretable member of that family --
    # run at full power after sunrise, then throttle back to bank what the eclipse
    # needs -- without moving the objective.  Caller-supplied weights are left
    # alone, since they express a real preference already.
    if weights is None:
        w = w * (1.0 + 1e-6 * np.linspace(1.0, 0.0, K))

    # Variable order: p[0..K-1], c[0..K-1], d[0..K-1]
    I = eye(K, format="csr")
    Z = csr_matrix((K, K))

    # Power balance:  p + c - d = G - P_h
    A_eq = hstack([I, I, -I], format="csr")
    b_eq = G - sys_.housekeeping_w

    # State of charge is a running sum, so the level constraints are a
    # lower-triangular system in (c, d):
    #   b[k] = cap + dt (eta_c sum c - sum d / eta_d)
    L = csr_matrix(np.tril(np.ones((K, K))))
    soc_coeff = hstack(
        [Z, L * (sys_.charge_efficiency * dt_h), L * (-dt_h / sys_.discharge_efficiency)],
        format="csr",
    )
    # floor <= cap + soc_coeff x <= cap   ->   two inequality blocks
    A_ub = vstack([-soc_coeff, soc_coeff], format="csr")
    b_ub = np.concatenate([
        np.full(K, cap - floor),        # -(soc change) <= cap - floor
        np.zeros(K),                    #  (soc change) <= 0   (cannot exceed full)
    ])

    # Periodicity: the final level must return to full, i.e. soc change >= 0
    # for the last row.  That row is already in A_ub as <= 0, so pinning it to
    # equality is the cleanest statement.
    A_eq = vstack([A_eq, soc_coeff.getrow(K - 1)], format="csr")
    b_eq = np.concatenate([b_eq, [0.0]])

    res = linprog(
        c=-np.concatenate([w * trace.dt_s, np.zeros(2 * K)]),
        A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
        bounds=[(0.0, None)] * (3 * K),
        method="highs",
    )
    if not res.success:  # pragma: no cover - reported rather than raised
        return {"success": False, "message": res.message}

    p = res.x[:K]
    const = sustainable_power(trace)["sustainable_payload_w"]
    mean_p = float(np.mean(p))
    return {
        "success": True,
        "payload_w": p,
        "mean_payload_w": mean_p,
        "constant_draw_bound_w": const,
        "headroom_pct": float(100.0 * (mean_p / const - 1.0)) if const > 0 else None,
        "energy_wh": float(np.sum(p) * dt_h),
        "peak_payload_w": float(np.max(p)),
    }
