"""Generate the full result set of the illumination / energy-availability study.

Six experiments, all over one full year (2024-01-01 to 2025-01-01) so that the
complete seasonal cycle of the solar declination and of the beta-angle drift is
covered:

E1  Reference orbits          -- three canonical cases, full per-revolution series.
E2  SSO local-time x altitude -- the LTAN/altitude design grid.
E3  Inclination sweep         -- non-sun-synchronous LEO at fixed altitude.
E4  Altitude sweep            -- fixed inclination, varying altitude.
E5  Walker constellations     -- per-plane heterogeneity and constellation-level
                                 aggregate sunlit capacity.
E6  Energy balance and model  -- EPS sizing outcomes, array-pointing comparison,
                                 and the cost of the shadow-model assumption.

Results are written to ``results/*.json``.  Run with

    python -m experiments.run_study            # everything
    python -m experiments.run_study E1 E5      # selected experiments
"""

from __future__ import annotations

import datetime as dt
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solarsim.attitude import ARRAY_LABELS
from solarsim.constants import DEG, R_EARTH
from solarsim.constellation import WalkerConstellation, sso_walker
from solarsim.orbit import (
    CircularOrbit,
    ltan_from_raan,
    raan_from_ltan,
    sso_inclination,
)
from solarsim.power import PowerSystem, energy_balance, size_array, size_battery
from solarsim.shadow import beta_star
from solarsim.simulate import simulate_orbit
from solarsim.timeutil import datetime_to_jd

RESULTS = Path(__file__).resolve().parents[1] / "results"
RESULTS.mkdir(exist_ok=True)

EPOCH = dt.datetime(2024, 1, 1)
JD0 = datetime_to_jd(EPOCH)
YEAR_DAYS = 366.0                  # 2024 is a leap year
H_ATM = 90.0
ARRAYS = ("two_axis", "single_axis_pitch", "single_axis_yaw", "body_box6_norm")

# Sampling density: eclipse durations are grid-independent by construction
# (boundaries are bisected), and the insolation integral is converged to
# ~10 ppm at 1024 samples per revolution -- see experiments/validate.py.
N_FINE = 2048                      # reference cases
N_SWEEP = 1024                     # design sweeps
N_CONSTELLATION = 512              # per-plane runs in large constellations


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _write(name: str, payload: dict) -> None:
    path = RESULTS / f"{name}.json"
    path.write_text(json.dumps(payload, separators=(",", ":")))
    _log(f"wrote {path.name}  ({path.stat().st_size/1024:.0f} kB)")


def _daily(sim, values: np.ndarray, reduce="mean") -> list:
    """Aggregate a per-revolution series into per-day values."""
    day = (sim.rev_start_s // 86400.0).astype(int)
    n_days = int(day.max()) + 1
    out = np.zeros(n_days)
    for d in range(n_days):
        v = values[day == d]
        if v.size == 0:
            out[d] = np.nan
        elif reduce == "mean":
            out[d] = v.mean()
        elif reduce == "max":
            out[d] = v.max()
        elif reduce == "sum":
            out[d] = v.sum()
    return np.round(out, 5).tolist()


def _sso_orbit(h_km: float, ltan: float) -> CircularOrbit:
    inc = sso_inclination(R_EARTH + h_km)
    return CircularOrbit(h_km, inc, raan_from_ltan(JD0, ltan), 0.0, JD0)


# ---------------------------------------------------------------------------
# E1  Reference orbits
# ---------------------------------------------------------------------------
def e1_reference() -> None:
    _log("E1  reference orbits")
    cases = [
        ("sso_1030", "SSO 550 km, LTAN 10:30", _sso_orbit(550.0, 10.5), 10.5),
        ("sso_dawn_dusk", "SSO 550 km, LTAN 06:00 (dawn-dusk)", _sso_orbit(550.0, 6.0), 6.0),
        (
            "leo_53",
            "LEO 550 km, i = 53 deg (Walker Delta shell)",
            CircularOrbit(550.0, 53.0 * DEG, 0.0, 0.0, JD0),
            None,
        ),
        (
            "leo_iss",
            "LEO 420 km, i = 51.6 deg (ISS-like)",
            CircularOrbit(420.0, 51.6 * DEG, 0.0, 0.0, JD0),
            None,
        ),
    ]
    out = {"epoch": EPOCH.isoformat(), "duration_days": YEAR_DAYS, "cases": {}}
    for key, title, orb, ltan in cases:
        t0 = time.time()
        sim = simulate_orbit(
            orb,
            duration_days=YEAR_DAYS,
            samples_per_rev=N_FINE,
            h_atm=H_ATM,
            label=title,
            ltan_hours=ltan,
            array_models=ARRAYS,
        )
        s = sim.summary()
        s["beta_star_deg"] = math.degrees(beta_star(orb.altitude_km, H_ATM))
        out["cases"][key] = {
            "title": title,
            "summary": s,
            "daily": {
                "beta_deg": _daily(sim, sim.beta_deg),
                "eclipse_min": _daily(sim, sim.eclipse_s / 60.0),
                "eclipse_max_min": _daily(sim, sim.eclipse_s / 60.0, "max"),
                "sunlit_min": _daily(sim, sim.sunlit_s / 60.0),
                "duty_cycle": _daily(sim, sim.duty_cycle),
                "insolation_w_m2": _daily(
                    sim, sim.insolation_int_s / sim.nodal_period_s * 1361.0
                ),
                **{
                    f"array_{n}_w_m2": _daily(
                        sim, sim.array_integral_s[n] / sim.nodal_period_s * 1361.0
                    )
                    for n in ARRAYS
                },
            },
            "rev_series": {
                "eclipse_min": np.round(sim.eclipse_s[::6] / 60.0, 4).tolist(),
                "beta_deg": np.round(sim.beta_deg[::6], 4).tolist(),
                "decimation": 6,
            },
        }
        _log(f"   {title}: {time.time()-t0:.0f}s, "
             f"eclipse {s['eclipse_mean_min']:.1f} min mean / "
             f"{s['eclipse_max_min']:.1f} max, "
             f"beta {s['beta_min_deg']:.1f}..{s['beta_max_deg']:.1f} deg")
    _write("e1_reference", out)


# ---------------------------------------------------------------------------
# E2  SSO local time x altitude
# ---------------------------------------------------------------------------
def e2_sso_grid() -> None:
    _log("E2  SSO local-time x altitude grid")
    altitudes = [400.0, 500.0, 600.0, 700.0, 800.0]
    ltans = [6.0, 7.0, 8.0, 9.0, 10.0, 10.5, 11.0, 12.0]
    out = {"altitudes_km": altitudes, "ltan_hours": ltans, "grid": [], "epoch": EPOCH.isoformat()}
    for h in altitudes:
        row = []
        for lt in ltans:
            sim = simulate_orbit(
                _sso_orbit(h, lt),
                duration_days=YEAR_DAYS,
                samples_per_rev=N_SWEEP,
                h_atm=H_ATM,
                ltan_hours=lt,
                label=f"SSO {h:.0f} km LTAN {lt:g}",
                array_models=ARRAYS,
            )
            s = sim.summary()
            s["inc_deg"] = float(np.degrees(sso_inclination(R_EARTH + h)))
            s["beta_star_deg"] = math.degrees(beta_star(h, H_ATM))
            s["beta_daily"] = _daily(sim, sim.beta_deg)
            s["eclipse_daily_min"] = _daily(sim, sim.eclipse_s / 60.0)
            row.append(s)
            _log(
                f"   h={h:.0f} LTAN={lt:4.1f}  |beta|max={s['beta_abs_max_deg']:5.1f} "
                f"ecl_mean={s['eclipse_mean_min']:5.2f} min  "
                f"ecl_free={s['eclipse_free_days']:5.1f} d  "
                f"duty={s['duty_cycle_mean']:.4f}"
            )
        out["grid"].append(row)
    _write("e2_sso_grid", out)


# ---------------------------------------------------------------------------
# E3  Inclination sweep
# ---------------------------------------------------------------------------
def e3_inclination() -> None:
    _log("E3  inclination sweep at 550 km")
    incs = [0.0, 20.0, 28.5, 40.0, 45.0, 51.6, 53.0, 60.0, 70.0, 80.0, 87.9, 97.6]
    out = {"altitude_km": 550.0, "cases": [], "epoch": EPOCH.isoformat()}
    for i in incs:
        sim = simulate_orbit(
            CircularOrbit(550.0, i * DEG, 0.0, 0.0, JD0),
            duration_days=YEAR_DAYS,
            samples_per_rev=N_SWEEP,
            h_atm=H_ATM,
            label=f"i = {i:g} deg",
            array_models=ARRAYS,
        )
        s = sim.summary()
        s["beta_daily"] = _daily(sim, sim.beta_deg)
        s["eclipse_daily_min"] = _daily(sim, sim.eclipse_s / 60.0)
        s["duty_daily"] = _daily(sim, sim.duty_cycle)
        s["beta_cycle_days"] = _beta_cycle_days(550.0, i)
        out["cases"].append(s)
        _log(
            f"   i={i:5.1f}  beta {s['beta_min_deg']:6.1f}..{s['beta_max_deg']:5.1f}  "
            f"ecl {s['eclipse_mean_min']:5.2f} min  free {s['eclipse_free_days']:5.1f} d  "
            f"cycle {s['beta_cycle_days']:6.1f} d"
        )
    _write("e3_inclination", out)


def _beta_cycle_days(h_km: float, inc_deg: float) -> float:
    """Period over which the Sun-orbit geometry repeats.

    The beta angle is driven by the node's motion relative to the Sun's right
    ascension, so the cycle closes when the nodal regression has gained (or
    lost) a full revolution on the Sun.  A sun-synchronous orbit has an
    infinite cycle by construction, reported here as the seasonal year.
    """
    from solarsim.constants import SSO_NODAL_RATE
    from solarsim.orbit import raan_rate

    rel = raan_rate(R_EARTH + h_km, inc_deg * DEG) - SSO_NODAL_RATE
    if abs(rel) < 1e-12:
        return 365.2422
    return abs(2.0 * math.pi / rel) / 86400.0


# ---------------------------------------------------------------------------
# E4  Altitude sweep
# ---------------------------------------------------------------------------
def e4_altitude() -> None:
    _log("E4  altitude sweep at i = 53 deg")
    alts = [300.0, 340.0, 400.0, 450.0, 500.0, 550.0, 600.0, 700.0, 800.0, 1000.0, 1200.0]
    out = {"inc_deg": 53.0, "cases": [], "epoch": EPOCH.isoformat()}
    for h in alts:
        sim = simulate_orbit(
            CircularOrbit(h, 53.0 * DEG, 0.0, 0.0, JD0),
            duration_days=YEAR_DAYS,
            samples_per_rev=N_SWEEP,
            h_atm=H_ATM,
            label=f"h = {h:g} km",
            array_models=ARRAYS,
        )
        s = sim.summary()
        s["beta_star_deg"] = math.degrees(beta_star(h, H_ATM))
        out["cases"].append(s)
        _log(
            f"   h={h:6.0f}  T={s['nodal_period_min']:5.1f} min  "
            f"ecl {s['eclipse_mean_min']:5.2f} min "
            f"({100*s['eclipse_fraction_mean']:5.2f} %)  "
            f"beta* {s['beta_star_deg']:5.1f} deg"
        )
    _write("e4_altitude", out)


# ---------------------------------------------------------------------------
# E5  Walker constellations
# ---------------------------------------------------------------------------
def e5_constellations() -> None:
    _log("E5  Walker constellations")
    designs = [
        (
            "starlink_shell1",
            "Walker Delta 53.0 deg: 1584/72/17, h = 550 km",
            WalkerConstellation(550.0, 53.0, 1584, 72, 17, "delta", 0.0, jd_epoch=JD0),
        ),
        (
            "oneweb",
            "Walker Star 87.9 deg: 588/12/1, h = 1200 km",
            WalkerConstellation(1200.0, 87.9, 588, 12, 1, "star", 0.0, jd_epoch=JD0),
        ),
        (
            "iridium",
            "Walker Star 86.4 deg: 66/6/2, h = 780 km",
            WalkerConstellation(780.0, 86.4, 66, 6, 2, "star", 0.0, jd_epoch=JD0),
        ),
        (
            "sso_walker",
            "SSO Walker Star 97.8 deg: 40/8/1, h = 600 km, LTAN 06:00-18:00",
            sso_walker(600.0, 40, 8, 6.0, 1, JD0),
        ),
    ]
    out = {"epoch": EPOCH.isoformat(), "constellations": {}}
    for key, title, const in designs:
        t0 = time.time()
        planes = const.plane_orbits()
        n_sim = min(len(planes), 24)          # subsample very large plane counts
        stride = max(1, len(planes) // n_sim)
        sel = list(range(0, len(planes), stride))
        plane_rows = []
        for pi in sel:
            sim = simulate_orbit(
                planes[pi],
                duration_days=YEAR_DAYS,
                samples_per_rev=N_CONSTELLATION,
                h_atm=H_ATM,
                label=f"{title} plane {pi}",
                array_models=ARRAYS,
            )
            s = sim.summary()
            s["plane_index"] = pi
            s["raan_deg"] = float(np.degrees(planes[pi].raan0_rad) % 360.0)
            s["ltan_hours"] = ltan_from_raan(JD0, planes[pi].raan0_rad)
            s["beta_daily"] = _daily(sim, sim.beta_deg)
            s["eclipse_daily_min"] = _daily(sim, sim.eclipse_s / 60.0)
            s["duty_daily"] = _daily(sim, sim.duty_cycle)
            plane_rows.append(s)

        # Instantaneous constellation-level sunlit capacity over three days.
        t_grid = np.arange(0.0, 3.0 * 86400.0, 60.0)
        nu = const.illumination_grid(t_grid)
        sunlit_frac = nu.mean(axis=1)
        out["constellations"][key] = {
            "title": title,
            "pattern": const.pattern,
            "altitude_km": const.altitude_km,
            "inc_deg": const.inc_deg,
            "n_total": const.n_total,
            "n_planes": const.n_planes,
            "phasing_f": const.phasing_f,
            "planes_simulated": sel,
            "planes": plane_rows,
            "aggregate": {
                "t_hours": np.round(t_grid / 3600.0, 4).tolist(),
                "sunlit_fraction": np.round(sunlit_frac, 5).tolist(),
                "mean": float(sunlit_frac.mean()),
                "min": float(sunlit_frac.min()),
                "max": float(sunlit_frac.max()),
                "peak_to_peak": float(sunlit_frac.max() - sunlit_frac.min()),
            },
            "plane_spread": {
                "eclipse_mean_min": [p["eclipse_mean_min"] for p in plane_rows],
                "duty_cycle_mean": [p["duty_cycle_mean"] for p in plane_rows],
                "beta_abs_max_deg": [p["beta_abs_max_deg"] for p in plane_rows],
                "eclipse_free_days": [p["eclipse_free_days"] for p in plane_rows],
                "raan_deg": [p["raan_deg"] for p in plane_rows],
            },
        }
        duty = np.array([p["duty_cycle_mean"] for p in plane_rows])
        _log(
            f"   {title}: {time.time()-t0:.0f}s, {len(sel)}/{len(planes)} planes, "
            f"duty {duty.min():.4f}..{duty.max():.4f} "
            f"(spread {100*(duty.max()-duty.min())/duty.mean():.1f} % of mean), "
            f"instantaneous sunlit {sunlit_frac.min():.3f}..{sunlit_frac.max():.3f}"
        )
    _write("e5_constellations", out)


# ---------------------------------------------------------------------------
# E6  Energy balance and shadow-model sensitivity
# ---------------------------------------------------------------------------
def e6_energy() -> None:
    _log("E6  energy balance and shadow-model sensitivity")
    cases = [
        ("sso_1030", "SSO 550 km, LTAN 10:30", _sso_orbit(550.0, 10.5)),
        ("sso_dawn_dusk", "SSO 550 km, LTAN 06:00", _sso_orbit(550.0, 6.0)),
        ("leo_53", "LEO 550 km, i = 53 deg", CircularOrbit(550.0, 53.0 * DEG, 0.0, 0.0, JD0)),
    ]
    out = {"epoch": EPOCH.isoformat(), "cases": {}, "power_system": {}, "shadow_model": {}}

    base = PowerSystem()
    out["power_system"] = {
        "array_area_m2": base.array_area_m2,
        "cell_efficiency": base.cell_efficiency,
        "packing_factor": base.packing_factor,
        "degradation_bol_eol": base.degradation_bol_eol,
        "ppt_efficiency": base.ppt_efficiency,
        "peak_power_w": base.peak_power_w,
        "battery_capacity_wh": base.battery_capacity_wh,
        "dod_limit": base.dod_limit,
        "housekeeping_w": base.housekeeping_w,
        "payload_w": base.payload_w,
        "load_w": base.load_w,
        "array_labels": ARRAY_LABELS,
    }

    for key, title, orb in cases:
        sim = simulate_orbit(
            orb,
            duration_days=YEAR_DAYS,
            samples_per_rev=N_FINE,
            h_atm=H_ATM,
            label=title,
            array_models=ARRAYS,
        )
        entry = {"title": title, "arrays": {}}
        for model in ARRAYS:
            ps = PowerSystem(array_model=model)
            eb = energy_balance(sim, ps)
            s = eb.summary()
            s["battery_wh_required"] = size_battery(sim, ps)
            s["array_m2_required"] = size_array(sim, ps)
            s["soc_daily"] = _daily(sim, eb.soc)
            s["p_gen_daily_w"] = _daily(sim, eb.p_gen_avg_w)
            s["dod_daily"] = _daily(sim, eb.dod_rev, "max")
            entry["arrays"][model] = s
            _log(
                f"   {title:34s} {model:18s} "
                f"P_gen {s['p_gen_mean_w']:6.1f} W  min {s['p_gen_min_w']:6.1f} W  "
                f"margin {100*s['margin_worst']:+6.1f} %  DoD_max {100*s['dod_max']:5.1f} %"
            )
        out["cases"][key] = entry

    # What does the choice of shadow model cost?
    orb = _sso_orbit(550.0, 10.5)
    ref = None
    for model in ("cylindrical", "conical", "fractional"):
        sim = simulate_orbit(
            orb,
            duration_days=YEAR_DAYS,
            samples_per_rev=N_FINE,
            h_atm=H_ATM,
            shadow_model=model,
            array_models=ARRAYS,
        )
        s = sim.summary()
        annual_wh = (
            PowerSystem().array_gain_w
            * float(np.sum(sim.array_integral_s["single_axis_pitch"]))
            / 3600.0
        )
        rec = {
            "eclipse_mean_min": s["eclipse_mean_min"],
            "duty_cycle_mean": s["duty_cycle_mean"],
            "annual_energy_wh": annual_wh,
        }
        if ref is None:
            ref = annual_wh
        rec["annual_energy_delta_pct"] = 100.0 * (annual_wh - ref) / ref
        out["shadow_model"][model] = rec
        _log(
            f"   shadow model {model:12s} ecl {s['eclipse_mean_min']:6.3f} min  "
            f"duty {s['duty_cycle_mean']:.5f}  annual {annual_wh/1000:8.2f} kWh  "
            f"({rec['annual_energy_delta_pct']:+.3f} % vs cylindrical)"
        )

    # Atmosphere-height sensitivity on the same orbit.
    out["h_atm_sensitivity"] = {}
    for h_atm in (0.0, 50.0, 90.0, 120.0):
        sim = simulate_orbit(
            orb, duration_days=YEAR_DAYS, samples_per_rev=N_SWEEP, h_atm=h_atm,
            array_models=("single_axis_pitch",),
        )
        s = sim.summary()
        out["h_atm_sensitivity"][f"{h_atm:.0f}"] = {
            "eclipse_mean_min": s["eclipse_mean_min"],
            "duty_cycle_mean": s["duty_cycle_mean"],
        }
    _write("e6_energy", out)


EXPERIMENTS = {
    "E1": e1_reference,
    "E2": e2_sso_grid,
    "E3": e3_inclination,
    "E4": e4_altitude,
    "E5": e5_constellations,
    "E6": e6_energy,
}


def main(argv: list[str]) -> int:
    selected = [a.upper() for a in argv[1:]] or list(EXPERIMENTS)
    unknown = [s for s in selected if s not in EXPERIMENTS]
    if unknown:
        print(f"unknown experiment(s): {unknown}; choose from {list(EXPERIMENTS)}")
        return 2
    t0 = time.time()
    for key in selected:
        EXPERIMENTS[key]()
    _log(f"done in {time.time()-t0:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
