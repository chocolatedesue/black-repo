"""E10 -- energy heterogeneity across the planes of a Walker shell, and what it
can and cannot support in the way of per-plane role specialisation.

The question this experiment exists to answer is whether a Walker Delta shell
used as a distributed compute resource can give different orbital planes
different standing duties -- an "always-on" tier, a "batch" tier -- the way a
terrestrial fleet gives different racks different roles.

That is an energy question with three parts, and this experiment measures all
three on the model that E1-E9 already validate:

1. **How different are the planes?**  Annual energy per plane, and the
   instantaneous spread across planes, are very different numbers.  Which one
   governs depends entirely on how long a role assignment has to hold.
2. **How long does a plane hold its state?**  The eclipse-free census: how many
   of the ``P`` planes are in continuous sunlight at once, and for how long a
   stretch.  This is the lifetime of any role keyed to "this plane has surplus
   energy".
3. **What is it worth in watts?**  The constant-draw bound and the LP optimum
   for the reference bus, swept over the beta cycle, so the spread is reported
   in payload watts rather than in duty cycle.

A fourth section places the energy on the fixed 2D torus of crosslinks (see
:mod:`solarsim.topology`): how deep in hops and in milliseconds the shadow is,
and how many links cross its boundary.  The topology is not a variable here --
it is the standard ``+Grid``, rigid for the life of the constellation -- but
where the energy sits *on* it decides whether surplus in one place is reachable
from a deficit in another.

Comparators: the same shell against a dawn-dusk sun-synchronous plane, which is
the only way found here to obtain a *persistent* energy difference between
groups of satellites.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

from typing import Optional

from solarsim.constants import DEG, H_ATM_DEFAULT, R_EARTH, SEC_PER_DAY
from solarsim.constellation import WalkerConstellation
from solarsim.orbit import CircularOrbit, raan_from_ltan, sso_inclination
from solarsim.power import PowerSystem
from solarsim.schedule import optimal_schedule, power_trace, sustainable_power
from solarsim.shadow import beta_star, illumination_fraction
from solarsim.solar import sun_vector_eci
from solarsim.timeutil import datetime_to_jd
from solarsim.topology import GridTopology, snapshot

RESULTS = Path(__file__).resolve().parent.parent / "results"
EPOCH = dt.datetime(2024, 1, 1)
JD0 = datetime_to_jd(EPOCH)
YEAR_DAYS = 366

#: Sampling of the illumination integral for the per-plane daily duty cycle.
#: Thirty seconds over a whole day averages every revolution of that day, which
#: is the same quantity E5 reports; the cross-check against E5 is printed and
#: stored, and agrees to better than 1e-3.
DUTY_DT_S = 30.0

#: The shell under study.  Same design as E5's ``starlink_shell1`` so that the
#: two experiments can be read against each other.
SHELL = dict(altitude_km=550.0, inc_deg=53.0, n_total=1584, n_planes=72, phasing_f=17)

#: The reference bus of E9: 2 m^2 array, 600 Wh battery, 45 W housekeeping.
#: ``single_axis_pitch`` is the array model E9 uses for the i = 53 deg shell.
SYSTEM = PowerSystem(array_model="single_axis_pitch")


def _log(msg: str) -> None:
    print(msg, flush=True)


def _write(name: str, payload: dict) -> None:
    path = RESULTS / f"{name}.json"
    path.write_text(json.dumps(payload, separators=(",", ":")))
    _log(f"wrote {path.name}  ({path.stat().st_size/1024:.0f} kB)")


def _runs(mask: np.ndarray) -> np.ndarray:
    """Lengths of the runs of True in a boolean series."""
    m = np.asarray(mask, dtype=bool)
    if not m.any():
        return np.zeros(0, dtype=int)
    d = np.diff(np.concatenate(([0], m.view(np.int8), [0])))
    return np.flatnonzero(d < 0) - np.flatnonzero(d > 0)


# ---------------------------------------------------------------------------
# 1. Per-plane energy over the year
# ---------------------------------------------------------------------------
def plane_energy(const: WalkerConstellation) -> dict:
    """Daily duty cycle and beta angle of every plane, for a full year.

    Every plane is propagated at :data:`DUTY_DT_S` for the whole year and the
    illumination integral is averaged per day, so the result is the same
    quantity E5 reports but for all ``P`` planes rather than a subsample of 24.
    """
    ref = const.reference_orbit()
    raans = const.plane_raans_deg() * DEG
    n_per_day = int(round(SEC_PER_DAY / DUTY_DT_S))
    t = np.arange(YEAR_DAYS * n_per_day, dtype=float) * DUTY_DT_S

    # The Sun does not depend on the plane, so it is evaluated once and reused.
    r_sun = sun_vector_eci(ref.jd_at(t))

    from solarsim.orbit import _perifocal_to_eci

    duty = np.empty((const.n_planes, YEAR_DAYS))
    beta = np.empty((const.n_planes, YEAR_DAYS))
    u = ref.u0_rad + ref.u_rate_rad_s * t
    for p, raan0 in enumerate(raans):
        raan = raan0 + ref.raan_rate_rad_s * t
        nu = np.empty(t.size)
        step = 1_000_000
        for k in range(0, t.size, step):
            sl = slice(k, min(k + step, t.size))
            r = _perifocal_to_eci(ref.a_km, raan[sl], ref.inc_rad, u[sl])
            nu[sl] = illumination_fraction(r, r_sun[sl])
        duty[p] = nu.reshape(YEAR_DAYS, n_per_day).mean(axis=1)
        from solarsim.geometry import beta_angle

        beta[p] = np.degrees(
            beta_angle(raan.reshape(YEAR_DAYS, n_per_day)[:, 0], ref.inc_rad,
                       ref.jd_at(t.reshape(YEAR_DAYS, n_per_day)[:, 0]))
        )
        if p % 12 == 0:
            _log(f"    plane {p:3d}/{const.n_planes}")
    return {"duty_daily": duty, "beta_daily": beta,
            "raan_deg": const.plane_raans_deg()}


def heterogeneity(duty: np.ndarray) -> dict:
    """How different the planes are, at every timescale that matters.

    The annual mean and the daily spread are the two numbers a role assignment
    has to be read against: the first says what a *permanent* assignment could
    exploit, the second what an assignment refreshed each day could.
    """
    annual = duty.mean(axis=1)
    daily_spread = duty.max(axis=0) - duty.min(axis=0)

    # Rank persistence: how long a plane keeps its position in the energy
    # ordering.  Spearman correlation of the per-day rank vector against itself
    # at a lag, averaged over the year.
    rank = np.argsort(np.argsort(duty, axis=0), axis=0).astype(float)
    def rank_corr(lag: int) -> float:
        if lag == 0:
            return 1.0
        a, b = rank[:, :-lag], rank[:, lag:]
        a = a - a.mean(axis=0)
        b = b - b.mean(axis=0)
        num = (a * b).sum(axis=0)
        den = np.sqrt((a * a).sum(axis=0) * (b * b).sum(axis=0))
        return float(np.mean(num / den))

    # Turnover of the best-energy quartile.
    top = duty >= np.quantile(duty, 0.75, axis=0, keepdims=True)
    def overlap(lag: int) -> float:
        return float(np.mean((top[:, :-lag] & top[:, lag:]).sum(0)
                             / np.maximum(top[:, :-lag].sum(0), 1)))

    lags = [1, 2, 3, 5, 7, 10, 14, 21, 30, 45, 60]
    return {
        "annual_duty_min": float(annual.min()),
        "annual_duty_max": float(annual.max()),
        "annual_duty_mean": float(annual.mean()),
        "annual_spread_pct_of_mean": float(100 * (annual.max() - annual.min()) / annual.mean()),
        "daily_spread_mean": float(daily_spread.mean()),
        "daily_spread_min": float(daily_spread.min()),
        "daily_spread_max": float(daily_spread.max()),
        "daily_duty_min": float(duty.min()),
        "daily_duty_max": float(duty.max()),
        "rank_corr_lags_days": lags,
        "rank_corr": [rank_corr(l) for l in lags],
        "top_quartile_overlap": [overlap(l) for l in lags],
        "annual_duty_by_plane": annual.tolist(),
    }


# ---------------------------------------------------------------------------
# 2. How long a plane holds its energy state
# ---------------------------------------------------------------------------
def eclipse_free_census(const: WalkerConstellation, dt_s: float = 1800.0) -> dict:
    """How many planes are eclipse-free at once, and for how long a stretch.

    A plane is eclipse-free while ``|beta| >= beta*``, with ``beta*`` taken
    against the same occulting sphere (R_earth + 90 km) the shadow model uses,
    so the census is consistent with the duty cycles above.
    """
    ref = const.reference_orbit()
    bs = math.degrees(beta_star(const.altitude_km, H_ATM_DEFAULT))
    t = np.arange(0.0, YEAR_DAYS * SEC_PER_DAY, dt_s)
    beta = const.plane_beta_deg(t)
    free = np.abs(beta) >= bs

    episodes = np.concatenate([_runs(free[:, p]) for p in range(const.n_planes)])
    ep_h = episodes * dt_s / 3600.0
    count = free.sum(axis=1)
    return {
        "beta_star_deg": bs,
        "sample_dt_s": dt_s,
        "planes_free_mean": float(count.mean()),
        "planes_free_min": int(count.min()),
        "planes_free_max": int(count.max()),
        "sats_free_mean": float(count.mean() * const.n_per_plane),
        "time_fraction_per_plane": float(free.mean()),
        "days_per_year_per_plane": float(free.mean() * YEAR_DAYS),
        "episode_mean_days": float(ep_h.mean() / 24.0),
        "episode_max_days": float(ep_h.max() / 24.0),
        "episodes_per_year_all_planes": int(episodes.size),
        "planes_free_series": count.tolist()[::4],
        "series_dt_s": dt_s * 4,
    }


def dwell(const: WalkerConstellation, dt_s: float = 5.0) -> dict:
    """Continuous sunlit and eclipse dwell of a single satellite, over the year.

    This is the timescale a workload actually sees: how long a node can draw on
    its array before it has to draw on its battery, and for how long.  Sampled
    once a fortnight so the beta cycle is covered without simulating the year at
    5 s resolution.
    """
    ref = const.reference_orbit()
    sun_min, ecl_min = [], []
    for day in range(0, YEAR_DAYS, 14):
        t = day * SEC_PER_DAY + np.arange(0.0, 4.0 * ref.nodal_period_s, dt_s)
        nu = illumination_fraction(ref.position_eci(t), sun_vector_eci(ref.jd_at(t)))
        lit = nu > 0.5
        # Drop the first and last run: both are truncated by the window.
        rs, re = _runs(lit), _runs(~lit)
        if rs.size > 2:
            sun_min.extend((rs[1:-1] * dt_s / 60.0).tolist())
        if re.size > 2:
            ecl_min.extend((re[1:-1] * dt_s / 60.0).tolist())
    s, e = np.array(sun_min), np.array(ecl_min)
    return {
        "sample_dt_s": dt_s,
        "nodal_period_min": ref.nodal_period_s / 60.0,
        "sunlit_dwell_min_mean": float(s.mean()),
        "sunlit_dwell_min_p05": float(np.percentile(s, 5)),
        "sunlit_dwell_min_max": float(s.max()),
        "eclipse_dwell_min_mean": float(e.mean()),
        "eclipse_dwell_min_max": float(e.max()),
        "n_samples": int(s.size),
    }


# ---------------------------------------------------------------------------
# 3. What the spread is worth in payload watts
# ---------------------------------------------------------------------------
#: Scheduling slots per nodal revolution.  Chosen so the slot length is close to
#: the 10 s the rest of the study uses while dividing the nodal period exactly:
#: the horizon is then a whole number of revolutions *on the sample grid*, not
#: merely in exact arithmetic.
SLOTS_PER_REV = 574


def _eclipse_entry_s(o: CircularOrbit) -> Optional[float]:
    """Epoch of the first eclipse entry after ``o``'s own epoch, or None.

    Located on a coarse grid and then refined by bisection on the continuous
    shadow function, the same way :mod:`solarsim.simulate` refines the eclipse
    boundaries it reports, so the anchor does not inherit the grid.
    """
    t = np.arange(0.0, o.nodal_period_s, 5.0)
    lit = illumination_fraction(o.position_eci(t), sun_vector_eci(o.jd_at(t))) > 0.5
    idx = np.flatnonzero(lit[:-1] & ~lit[1:])
    if idx.size == 0:
        return None
    lo, hi = float(t[idx[0]]), float(t[idx[0] + 1])
    for _ in range(45):
        mid = 0.5 * (lo + hi)
        one = np.array([mid])
        if illumination_fraction(o.position_eci(one), sun_vector_eci(o.jd_at(one)))[0] > 0.5:
            lo = mid
        else:
            hi = mid
    return lo


def _orbit_at_day(const: WalkerConstellation, day: int, back_off_s: float = 0.0
                  ) -> CircularOrbit:
    """The shell's reference plane as it stands on `day`, anchored before sunset.

    Two corrections, both of which move the answer by more than the effects this
    experiment is about, so neither is optional.

    **The plane has moved.**  Re-anchoring at ``jd_epoch + day`` with the *epoch*
    RAAN freezes the plane in inertial space and lets the Sun do all the work:
    beta then sweeps only +/-29 deg instead of the +/-76 deg the plane really
    sees.  The node is therefore propagated with the same secular rate the rest
    of the model uses.

    **The revolution has a phase, and the bound is not phase-invariant.**
    :func:`sustainable_power` starts the state of charge full and asks whether it
    ends full.  That question is only well posed from a phase at which a healthy
    battery *is* full, which is the end of the sunlit arc.  Started anywhere else
    on a whole number of revolutions the bound is wrong, and not by a little: on
    this shell it reads 0 W from inside the eclipse, climbs through 36, 95, 142,
    180, 212, 239 W across the recharge, and only reaches its true 254.7 W in the
    last tenth of the sunlit arc.  This is a *second* trap, distinct from the
    fractional-horizon one the README documents -- that one needs a whole number
    of revolutions, this one needs the right phase, and satisfying the first does
    nothing for the second.

    The trace is therefore anchored ``back_off_s`` before the bisection-refined
    eclipse entry.  One slot is enough and ten slots gives the same answer to
    under 1 %, which :func:`payload_power_over_beta_cycle` asserts; exactly zero
    is the razor edge, where the final sample lands in the first instant of
    eclipse and the bound collapses.  On an eclipse-free revolution the battery
    never discharges, every phase agrees, and the epoch is left alone.
    """
    ref = const.reference_orbit()
    t0 = day * SEC_PER_DAY
    o = CircularOrbit(
        const.altitude_km,
        ref.inc_rad,
        ref.raan0_rad + ref.raan_rate_rad_s * t0,
        ref.u0_rad + ref.u_rate_rad_s * t0,
        ref.jd_epoch + day,
    )
    entry = _eclipse_entry_s(o)
    if entry is None:
        return o
    shift = max(entry - back_off_s, 0.0)
    return CircularOrbit(
        const.altitude_km,
        o.inc_rad,
        o.raan0_rad + o.raan_rate_rad_s * shift,
        o.u0_rad + o.u_rate_rad_s * shift,
        o.jd_epoch + shift / SEC_PER_DAY,
    )


def payload_power_over_beta_cycle(const: WalkerConstellation, stride_days: int = 5) -> dict:
    """Constant-draw bound and LP optimum for the reference bus, over the year.

    Every plane of a Delta shell traverses the *same* beta cycle, offset in
    phase, so one plane's year-long curve is the whole constellation's role map:
    the payload power available to plane ``p`` today is the value this curve
    takes at a shifted argument.  That is why a single orbit is swept here and
    not seventy-two.

    Two array architectures are swept, because they decompose the answer.  A
    two-axis gimbal isolates the *illumination* term -- available power then
    rises with ``|beta|`` exactly as the eclipse shortens.  A single-axis pitch
    drive, the architecture E9 assumes for this shell, adds a cosine loss that
    also grows with ``|beta|`` and works against it.  Which of the two a
    constellation flies decides whether its most-sunlit planes are also its most
    powerful ones, and that is the whole question for per-plane role assignment.
    """
    from solarsim.geometry import beta_angle

    ref = const.reference_orbit()
    dt_s = ref.nodal_period_s / SLOTS_PER_REV
    days = list(range(0, YEAR_DAYS, stride_days))
    cases, phase_checks = {}, []
    for model in ("two_axis", "single_axis_pitch"):
        sysm = PowerSystem(array_model=model)
        out, have_scipy = [], True
        for day in days:
            o = _orbit_at_day(const, day, back_off_s=dt_s)
            tr = power_trace(o, sysm, n_orbits=3.0, dt_s=dt_s)
            sus = sustainable_power(tr)
            assert sus["periodicity_valid"], f"non-integer horizon at day {day}"
            assert sus["feasible"], (
                f"{model} day {day}: the reference bus cannot carry its own "
                f"housekeeping, which is a result, not an error -- report it "
                f"rather than asserting it away if it ever fires legitimately")
            row = {
                "day": day,
                "beta_deg": float(np.degrees(beta_angle(o.raan0_rad, o.inc_rad, o.jd_epoch))),
                "duty_cycle": float((tr.p_gen_w > 0).mean()),
                "gen_mean_w": float(np.mean(tr.p_gen_w)),
                "sustainable_w": float(sus["sustainable_payload_w"]),
                "naive_w": float(sus["naive_estimate_w"]),
                "binding": sus["binding_constraint"],
            }
            if have_scipy:
                try:
                    opt = optimal_schedule(tr)
                except ImportError:
                    have_scipy = False
                else:
                    assert opt["success"], opt.get("message")
                    row["optimal_w"] = float(opt["mean_payload_w"])
            out.append(row)

            # Phase robustness: ten slots earlier must give the same answer.
            if day % 60 == 0:
                o10 = _orbit_at_day(const, day, back_off_s=10.0 * dt_s)
                alt = sustainable_power(power_trace(o10, sysm, n_orbits=3.0, dt_s=dt_s))
                v0, v1 = row["sustainable_w"], alt["sustainable_payload_w"]
                rel = abs(v1 - v0) / max(v0, 1e-9)
                phase_checks.append({"day": day, "array_model": model,
                                     "one_slot_w": v0, "ten_slots_w": float(v1),
                                     "rel_diff": float(rel)})
                assert rel < 0.03, f"anchor not converged at day {day}: {v0} vs {v1}"

        sus_w = np.array([r["sustainable_w"] for r in out])
        entry = {
            "array_model": model,
            "series": out,
            "sustainable_min_w": float(sus_w.min()),
            "sustainable_max_w": float(sus_w.max()),
            "sustainable_mean_w": float(sus_w.mean()),
            "sustainable_spread_pct_of_mean": float(
                100 * (sus_w.max() - sus_w.min()) / sus_w.mean()),
        }
        opt_w = np.array([r["optimal_w"] for r in out if "optimal_w" in r])
        if opt_w.size:
            base = np.array([r["sustainable_w"] for r in out if "optimal_w" in r])
            entry.update(optimal_min_w=float(opt_w.min()), optimal_max_w=float(opt_w.max()),
                         optimal_mean_w=float(opt_w.mean()),
                         headroom_mean_pct=float(100 * np.mean(opt_w / base - 1.0)))
        cases[model] = entry
        _log(f"    {model:18s} sustainable {entry['sustainable_min_w']:6.1f} - "
             f"{entry['sustainable_max_w']:6.1f} W  "
             f"(spread {entry['sustainable_spread_pct_of_mean']:.0f}% of mean)")
    return {
        "stride_days": stride_days,
        "slots_per_revolution": SLOTS_PER_REV,
        "slot_s": dt_s,
        "anchor": "one slot before the bisection-refined eclipse entry",
        "array_m2": SYSTEM.array_area_m2,
        "battery_wh": SYSTEM.battery_capacity_wh,
        "housekeeping_w": SYSTEM.housekeeping_w,
        "dod_limit": SYSTEM.dod_limit,
        "cases": cases,
        "phase_robustness": phase_checks,
    }


def dawn_dusk_comparator() -> dict:
    """The same bus on a dawn-dusk sun-synchronous orbit, for contrast.

    A Delta plane's energy state rotates; a sun-synchronous plane's does not.
    This is the only construction in the study that yields a *persistent*
    energy difference between groups of satellites, so it is the honest
    comparator for any proposal to give one group of satellites a standing duty
    the others do not have.
    """
    inc = sso_inclination(R_EARTH + 550.0)
    rows = []
    for ltan, label in ((6.0, "dawn-dusk 06:00"), (10.5, "LTAN 10:30")):
        model = "single_axis_yaw" if ltan == 6.0 else "single_axis_pitch"
        sysm = PowerSystem(array_model=model)
        year = []
        sso_shell = WalkerConstellation(550.0, math.degrees(inc), 12, 12, 0, "star",
                                        math.degrees(raan_from_ltan(JD0, ltan)),
                                        jd_epoch=JD0)
        dt_s = sso_shell.reference_orbit().nodal_period_s / SLOTS_PER_REV
        for day in range(0, YEAR_DAYS, 15):
            od = _orbit_at_day(sso_shell, day, back_off_s=dt_s)
            tr = power_trace(od, sysm, n_orbits=3.0, dt_s=dt_s)
            sus = sustainable_power(tr)
            assert sus["periodicity_valid"]
            year.append((day, float((tr.p_gen_w > 0).mean()),
                         float(sus["sustainable_payload_w"])))
        duty = np.array([r[1] for r in year])
        w = np.array([r[2] for r in year])
        rows.append({
            "ltan_hours": ltan, "label": label, "array_model": model,
            "duty_mean": float(duty.mean()), "duty_min": float(duty.min()),
            "sustainable_mean_w": float(w.mean()), "sustainable_min_w": float(w.min()),
            "sustainable_max_w": float(w.max()),
            "series": [{"day": d, "duty": u, "sustainable_w": p} for d, u, p in year],
        })
    return {"altitude_km": 550.0, "inc_deg": math.degrees(inc), "cases": rows}


# ---------------------------------------------------------------------------
# 4. Where the energy sits on the fixed torus
# ---------------------------------------------------------------------------
def energy_on_the_torus(const: WalkerConstellation, stride_days: int = 7,
                        phases: int = 6) -> dict:
    """Depth of the shadow in the crosslink graph, sampled over the year.

    The topology is the fixed ``+Grid`` torus; what varies is which of its nodes
    are generating.  Two numbers decide whether a surplus is reachable from a
    deficit: how far the deepest eclipsed node is from a generating one, and how
    many links cross the boundary -- the latter bounding the aggregate rate at
    which work can be moved into the sunlight, whatever the routing.
    """
    topo = GridTopology(const)
    assert topo.is_connected()
    ref = const.reference_orbit()
    snaps = []
    for day in range(0, YEAR_DAYS, stride_days):
        for k in range(phases):
            t = day * SEC_PER_DAY + k * ref.nodal_period_s / phases
            snaps.append(snapshot(topo, t))
        if day % 70 == 0:
            _log(f"    day {day:3d}  hops_max {snaps[-1]['hops_to_sun_max']}"
                 f"  cut {snaps[-1]['cut_n_links']}")

    def col(k):
        return np.array([s[k] for s in snaps], dtype=float)

    return {
        "n_snapshots": len(snaps),
        "stride_days": stride_days,
        "phases_per_revolution": phases,
        "seam_shift": topo.seam_shift,
        "n_links": int(topo.edge_i.size),
        "degree": 4,
        "intra_plane_range_km": float(topo.intra_plane_range_km),
        "intra_plane_latency_ms": float(topo.intra_plane_range_km / 299792.458 * 1e3),
        "inter_plane_range_min_km": float(col("inter_range_min_km").min()),
        "inter_plane_range_max_km": float(col("inter_range_max_km").max()),
        "min_link_clearance_km": float(col("min_clearance_km").min()),
        "sunlit_fraction_min": float(col("sunlit_fraction").min()),
        "sunlit_fraction_mean": float(col("sunlit_fraction").mean()),
        "sunlit_fraction_max": float(col("sunlit_fraction").max()),
        "hops_to_sun_mean": float(col("hops_to_sun_mean").mean()),
        "hops_to_sun_max": int(col("hops_to_sun_max").max()),
        "latency_to_sun_mean_ms": float(col("latency_to_sun_mean_ms").mean()),
        "latency_to_sun_max_ms": float(col("latency_to_sun_max_ms").max()),
        "cut_links_mean": float(col("cut_n_links").mean()),
        "cut_links_min": int(col("cut_n_links").min()),
        "cut_links_max": int(col("cut_n_links").max()),
        "cut_links_per_eclipsed_sat": float(col("cut_links_per_eclipsed_sat").mean()),
        # The eclipsed set is normally one connected blob -- the night side of
        # the shell -- so "move the work into the sunlight" always means moving
        # it outward across a single boundary.  It occasionally splits when a
        # plane at high |beta| passes clear of the shadow, which is worth
        # recording rather than asserting away.
        "eclipsed_single_component_fraction": float(
            np.mean([len(s["eclipsed_component_sizes"]) == 1 for s in snaps])),
        "eclipsed_components_max": int(
            max(len(s["eclipsed_component_sizes"]) for s in snaps)),
        "eclipsed_second_component_max": int(max(
            (s["eclipsed_component_sizes"][1] for s in snaps
             if len(s["eclipsed_component_sizes"]) > 1), default=0)),
        "snapshots": snaps[: 6 * 8],
    }


def cross_check_against_e5(duty: np.ndarray, const: WalkerConstellation) -> dict:
    """Agreement of the sampled duty cycles with E5's bisection-refined ones.

    E5 integrates each revolution with grid-free eclipse boundaries; this
    experiment averages a 30 s sample of the whole day.  They are different
    numerical routes to the same quantity, so their difference is a check on
    both.
    """
    path = RESULTS / "e5_constellations.json"
    if not path.exists():
        return {"available": False}
    e5 = json.loads(path.read_text())["constellations"]["starlink_shell1"]
    diffs = []
    for pl in e5["planes"]:
        p = pl["plane_index"]
        if p < duty.shape[0]:
            diffs.append(np.abs(np.array(pl["duty_daily"]) - duty[p]))
    d = np.concatenate(diffs)
    return {"available": True, "n_planes_compared": len(diffs),
            "max_abs_diff": float(d.max()), "rms_diff": float(np.sqrt((d**2).mean()))}


def main() -> None:
    t0 = time.time()
    const = WalkerConstellation(**SHELL, pattern="delta", raan0_deg=0.0, jd_epoch=JD0)
    _log(f"E10  energy heterogeneity and role assignment -- {const.name}")

    _log("  per-plane energy over the year")
    pe = plane_energy(const)
    duty = pe["duty_daily"]

    _log("  heterogeneity")
    het = heterogeneity(duty)

    _log("  eclipse-free census")
    census = eclipse_free_census(const)

    _log("  dwell")
    dw = dwell(const)

    _log("  payload power over the beta cycle")
    pw = payload_power_over_beta_cycle(const)

    _log("  dawn-dusk comparator")
    dd = dawn_dusk_comparator()

    _log("  energy on the torus")
    tor = energy_on_the_torus(const)

    _log("  cross-check against E5")
    xc = cross_check_against_e5(duty, const)
    _log(f"    max |duty - E5 duty| = {xc.get('max_abs_diff', float('nan')):.2e}")

    payload = {
        "epoch": EPOCH.isoformat(),
        "duration_days": YEAR_DAYS,
        "constellation": {
            "name": const.name, **SHELL, "pattern": const.pattern,
            "n_per_plane": const.n_per_plane,
            "nodal_period_min": const.reference_orbit().nodal_period_s / 60.0,
        },
        "power_system": {
            "array_m2": SYSTEM.array_area_m2, "battery_wh": SYSTEM.battery_capacity_wh,
            "dod_limit": SYSTEM.dod_limit, "housekeeping_w": SYSTEM.housekeeping_w,
            "array_model": SYSTEM.array_model,
        },
        "duty_sample_dt_s": DUTY_DT_S,
        "planes": [
            {"plane_index": p, "raan_deg": float(pe["raan_deg"][p]),
             "duty_daily": [round(v, 5) for v in duty[p].tolist()],
             "beta_daily": [round(v, 3) for v in pe["beta_daily"][p].tolist()]}
            for p in range(const.n_planes)
        ],
        "heterogeneity": het,
        "eclipse_free": census,
        "dwell": dw,
        "payload_power": pw,
        "dawn_dusk_comparator": dd,
        "torus": tor,
        "cross_check_e5": xc,
    }
    _write("e10_roles", payload)
    _log(f"E10 done in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    sys.exit(main())
