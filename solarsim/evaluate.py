"""A common harness for scoring energy-aware scheduling policies.

A scheduling paper needs three things from its evaluation, and getting any of
them slightly wrong invalidates the comparison:

1. **A feasibility check that is not the policy's own.**  A policy that quietly
   violates the depth-of-discharge limit will look excellent.  Here every policy
   is replayed through the same battery simulation, and any violation is
   reported rather than clipped away.
2. **Baselines computed on identical inputs.**  The constant-power baseline is
   not a guess; it is the largest fixed draw that survives the orbit, solved in
   :mod:`solarsim.schedule`.
3. **An optimality gap, not just a win over a baseline.**  Beating a weak
   baseline says little.  The LP of :func:`solarsim.schedule.optimal_schedule`
   is the true ceiling for a given objective, so the honest headline number is
   how close a policy gets to it.

A policy is any callable

    policy(k, ctx) -> payload power for slot k, in watts

where ``ctx`` carries what an online scheduler could legitimately know at slot
``k``: the trace, the current state of charge, and the platform parameters.
Policies that look at ``ctx.trace.p_gen_w[k+1:]`` are clairvoyant; that is
allowed and is sometimes the point, but the harness records it so the
comparison stays honest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional

import numpy as np

from .power import PowerSystem
from .schedule import PowerTrace, optimal_schedule, sustainable_power


@dataclass
class SlotContext:
    """What a policy may legitimately consult when deciding slot ``k``."""

    trace: PowerTrace
    system: PowerSystem
    soc_wh: float                 # battery energy at the start of the slot
    soc_floor_wh: float           # depth-of-discharge floor
    capacity_wh: float
    p_gen_w: float                # generation in this slot
    p_house_w: float              # housekeeping draw *in this slot*, not the mean

    @property
    def headroom_wh(self) -> float:
        """Energy that may still be drawn from the battery this orbit."""
        return max(0.0, self.soc_wh - self.soc_floor_wh)


Policy = Callable[[int, SlotContext], float]


@dataclass
class PolicyResult:
    """Outcome of replaying one policy through the battery simulation."""

    name: str
    payload_w: np.ndarray
    soc_wh: np.ndarray
    mean_payload_w: float
    steady_state_mean_payload_w: float
    energy_wh: float
    soc_start_wh: float
    soc_end_wh: float
    soc_min_wh: float
    dod_violation_wh: float       # how far below the floor it went, 0 if feasible
    unmet_demand_wh: float        # demand the battery could not supply
    curtailed_wh: float           # generation discarded with a full battery
    periodic: bool                # ends at least as charged as it started
    feasible: bool

    def summary(self) -> dict:
        return {
            "name": self.name,
            "mean_payload_w": self.mean_payload_w,
            "steady_state_mean_payload_w": self.steady_state_mean_payload_w,
            "energy_wh": self.energy_wh,
            "soc_start_wh": self.soc_start_wh,
            "soc_end_wh": self.soc_end_wh,
            "soc_min_wh": self.soc_min_wh,
            "dod_violation_wh": self.dod_violation_wh,
            "unmet_demand_wh": self.unmet_demand_wh,
            "curtailed_wh": self.curtailed_wh,
            "periodic": self.periodic,
            "feasible": self.feasible,
        }


def run_policy(trace: PowerTrace, policy: Policy, name: str = "policy") -> PolicyResult:
    """Replay ``policy`` through the battery dynamics and score it.

    The simulation is deliberately unforgiving: a request the battery cannot
    meet is recorded as unmet demand rather than silently reduced, and dipping
    below the depth-of-discharge floor is recorded rather than prevented.  A
    policy is feasible only if it did neither.

    Feasibility also requires **periodicity**.  A policy that ends the horizon
    with less charge than it started has borrowed from the battery, and its mean
    payload is not something it could sustain -- run it for enough orbits and it
    hits the floor.  The obvious myopic policy ("spend all surplus in sunlight,
    idle in eclipse") does exactly this: it never banks anything, so it drains
    by one eclipse's worth of housekeeping every orbit and looks like it beats
    the LP optimum over a short window.  ``steady_state_mean_payload_w`` removes
    that borrowing by debiting the net drawdown at the discharge efficiency, and
    it is the figure the optimality gap is computed from.
    """
    sys_ = trace.system
    cap = sys_.battery_capacity_wh
    floor = cap * (1.0 - sys_.dod_limit)
    dt_h = trace.dt_s / 3600.0

    house = trace.p_house_series

    n = trace.t_s.size
    payload = np.zeros(n)
    soc = np.zeros(n)

    b = cap
    violation = 0.0
    unmet = 0.0
    curtailed = 0.0

    for k in range(n):
        ctx = SlotContext(
            trace=trace, system=sys_, soc_wh=b, soc_floor_wh=floor,
            capacity_wh=cap, p_gen_w=float(trace.p_gen_w[k]),
            p_house_w=float(house[k]),
        )
        p = max(0.0, float(policy(k, ctx)))
        payload[k] = p

        delta = trace.p_gen_w[k] - (house[k] + p)
        if delta >= 0.0:
            raw = b + delta * sys_.charge_efficiency * dt_h
            if raw > cap:
                curtailed += (raw - cap) / sys_.charge_efficiency
                raw = cap
            b = raw
        else:
            draw = -delta / sys_.discharge_efficiency * dt_h
            if b - draw < 0.0:
                unmet += (draw - b)
                b = 0.0
            else:
                b -= draw
            if b < floor:
                violation = max(violation, floor - b)
        soc[k] = b

    energy_wh = float(np.sum(payload) * dt_h)
    drawdown_wh = cap - b                     # positive if it ended lower
    # Energy taken out of storage would not be there in a repeating orbit;
    # discharging it yields only eta_d of load energy, so debit it at that rate.
    steady_energy_wh = energy_wh - drawdown_wh * sys_.discharge_efficiency
    span_h = float(trace.t_s[-1]) / 3600.0

    return PolicyResult(
        name=name,
        payload_w=payload,
        soc_wh=soc,
        mean_payload_w=float(np.mean(payload)),
        steady_state_mean_payload_w=steady_energy_wh / span_h if span_h > 0 else 0.0,
        energy_wh=energy_wh,
        soc_start_wh=cap,
        soc_end_wh=float(b),
        soc_min_wh=float(np.min(soc)),
        dod_violation_wh=float(violation),
        unmet_demand_wh=float(unmet),
        curtailed_wh=float(curtailed),
        periodic=bool(drawdown_wh <= 1e-6),
        feasible=violation <= 1e-9 and unmet <= 1e-9 and drawdown_wh <= 1e-6,
    )


# ---------------------------------------------------------------------------
# Reference policies
# ---------------------------------------------------------------------------
def constant_policy(level_w: float) -> Policy:
    """Draw a fixed payload power regardless of state.  The usual baseline."""
    return lambda k, ctx: level_w


def sunlight_only_policy(system: Optional[PowerSystem] = None) -> Policy:
    """Consume all available generation in sunlight, nothing in eclipse.

    Myopic and causal: it looks only at the current slot.  With uniform task
    value this is close to optimal, because a round trip through the battery
    costs energy -- which is worth demonstrating rather than asserting.
    """
    def p(k, ctx: SlotContext) -> float:
        return max(0.0, ctx.p_gen_w - ctx.p_house_w)
    return p


def bank_then_spend_policy(target_soc_wh: Optional[float] = None) -> Policy:
    """Recharge to a target state of charge, then spend all further surplus.

    Causal, one parameter, and periodic by construction: after each eclipse the
    battery is below target, so the policy banks until it is refilled and only
    then lets the payload have the surplus.  With the target at capacity this is
    the simplest policy that is both feasible and close to optimal, which makes
    it the right thing for a paper to beat rather than a constant draw.

    Setting the target below capacity trades a little steady-state throughput
    for a deeper reserve, and is worth sweeping if the workload has bursts.
    """
    def p(k, ctx: SlotContext) -> float:
        surplus = ctx.p_gen_w - ctx.p_house_w
        if surplus <= 0.0:
            return 0.0
        target = ctx.capacity_wh if target_soc_wh is None else target_soc_wh
        return surplus if ctx.soc_wh >= target - 1e-9 else 0.0
    return p


def deadline_policy(min_payload_w: float) -> Policy:
    """Hold a floor of payload power at all times, spending surplus on top.

    Stands in for a workload with a latency or coverage requirement that cannot
    simply pause through eclipse.  Infeasible settings are reported by the
    harness rather than clipped, which is the point: it shows what a latency
    target actually costs.
    """
    def p(k, ctx: SlotContext) -> float:
        surplus = max(0.0, ctx.p_gen_w - ctx.p_house_w)
        return max(min_payload_w, surplus)
    return p


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
def evaluate(
    trace: PowerTrace,
    policies: Dict[str, Policy],
    include_bounds: bool = True,
) -> dict:
    """Score every policy against the constant baseline and the LP optimum.

    Returns a dict with one entry per policy plus, when ``include_bounds``, the
    two reference points.  ``optimality_gap_pct`` is the honest headline: how
    much of the achievable energy a policy leaves on the table.
    """
    out = {"policies": {}, "trace": trace.summary()}

    baseline_w = None
    optimum_w = None
    if include_bounds:
        sus = sustainable_power(trace)
        baseline_w = sus["sustainable_payload_w"]
        out["constant_baseline"] = sus
        try:
            opt = optimal_schedule(trace)
            if opt.get("success"):
                optimum_w = opt["mean_payload_w"]
                out["lp_optimum"] = {
                    k: v for k, v in opt.items() if k != "payload_w"
                }
        except ImportError:
            out["lp_optimum"] = {"unavailable": "SciPy is not installed"}

    for name, pol in policies.items():
        res = run_policy(trace, pol, name)
        s = res.summary()
        # Both comparisons use the steady-state figure, so a policy that spends
        # its initial charge cannot appear to beat a bound that assumes it does
        # not.
        ss = res.steady_state_mean_payload_w
        if baseline_w:
            s["vs_constant_baseline_pct"] = 100.0 * (ss / baseline_w - 1.0)
        if optimum_w:
            # Only meaningful for a policy that actually closed its energy
            # cycle.  For one that ended down, the steady-state figure is a
            # correction rather than an equivalence, and comparing it to a bound
            # that assumes periodicity would invite a spurious negative gap.
            s["optimality_gap_pct"] = (
                100.0 * (1.0 - ss / optimum_w) if res.periodic else None
            )
        out["policies"][name] = s

    return out


def format_table(report: dict) -> str:
    """Render an :func:`evaluate` report as a plain-text table for a terminal."""
    rows = report["policies"]
    head = (
        f"{'policy':<22} {'mean P (W)':>11} {'steady (W)':>11} "
        f"{'vs base':>9} {'gap to LP':>10} {'feasible':>9}  note"
    )
    lines = [head, "-" * len(head)]
    for name, s in rows.items():
        note = []
        if s["dod_violation_wh"] > 1e-9:
            note.append(f"DoD breached by {s['dod_violation_wh']:.1f} Wh")
        if s["unmet_demand_wh"] > 1e-9:
            note.append(f"{s['unmet_demand_wh']:.1f} Wh demand unmet")
        if not s["periodic"]:
            note.append(
                f"non-periodic: ends {s['soc_start_wh'] - s['soc_end_wh']:.0f} Wh down")
        if s["curtailed_wh"] > 1e-6:
            note.append(f"{s['curtailed_wh']:.0f} Wh curtailed")
        g = s.get("optimality_gap_pct")
        gap = f"{g:7.1f}%" if g is not None else "--"
        lines.append(
            f"{name:<22} {s['mean_payload_w']:11.1f} "
            f"{s['steady_state_mean_payload_w']:11.1f} "
            f"{s.get('vs_constant_baseline_pct', float('nan')):+8.1f}% "
            f"{gap:>9} "
            f"{'yes' if s['feasible'] else 'NO':>9}  {'; '.join(note)}"
        )
    if "constant_baseline" in report:
        lines.append("")
        lines.append(
            f"constant baseline {report['constant_baseline']['sustainable_payload_w']:.1f} W "
            f"(binding: {report['constant_baseline'].get('binding_constraint', '?')})"
        )
    if "lp_optimum" in report and "mean_payload_w" in report["lp_optimum"]:
        lines.append(f"LP optimum        {report['lp_optimum']['mean_payload_w']:.1f} W")
    return "\n".join(lines)
