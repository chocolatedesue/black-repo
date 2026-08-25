"""E8  Energy intensity and consumption.

The illumination study answers how much sunlight the array sees.  This
experiment answers the two questions immediately downstream of that, neither of
which the constant-efficiency, constant-load chain could address:

**How much of the intercepted sunlight actually becomes electricity?**  Not the
nameplate fraction: the array runs hot, and a triple-junction cell loses about
a quarter of a percent of its output per kelvin above its 28 C rating.  Part A
integrates the panel's temperature around the orbit and reports the derate,
sampled through the year so the beta-angle dependence is visible.  Part B sweeps
the parameters that derate is sensitive to -- above all the temperature
coefficient itself, which is vendor-specific and which this study cannot measure.

**Where does the energy go?**  Part C breaks the housekeeping load into
subsystems and gives it the shape it really has: survival heaters switched on in
eclipse, and the downlink transmitter switched on only over a ground station.
Part D asks what that shape does to the scheduling bounds, against a flat load
of the *same orbit-average* so that shape is separated from level.  Part E
closes the books with a full energy ledger for each configuration.

Writes ``results/e8_energy_intensity.json``.

    python -m experiments.run_energy            # everything
    python -m experiments.run_energy A C        # selected parts
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solarsim.constants import (
    ALBEDO_HOT,
    ALBEDO_MEAN,
    DEG,
    EARTH_IR_HOT,
    EARTH_IR_MEAN,
    R_EARTH,
)
from solarsim.load import DEFAULT_NETWORK, LoadModel, contact_mask
from solarsim.orbit import CircularOrbit, raan_from_ltan, sso_inclination
from solarsim.power import PowerSystem, energy_ledger
from solarsim.schedule import optimal_schedule, power_trace, sustainable_power
from solarsim.thermal import CellThermalResponse, ThermalPanel
from solarsim.timeutil import datetime_to_jd

RESULTS = Path(__file__).resolve().parents[1] / "results"
RESULTS.mkdir(exist_ok=True)

EPOCH = dt.datetime(2024, 1, 1)
JD0 = datetime_to_jd(EPOCH)

# Three orbits, each with the array architecture such a platform would really
# fly -- benchmarking a dawn-dusk orbit with a pitch-axis drive understates it by
# a factor of several, as E6 established.
CASES = [
    ("sso_1030", "SSO 550 km, LTAN 10:30", 10.5, "single_axis_pitch"),
    ("sso_dawn_dusk", "SSO 550 km, LTAN 06:00", 6.0, "single_axis_yaw"),
    ("leo_53", "LEO 550 km, i = 53 deg", None, "single_axis_pitch"),
]

DT_S = 10.0
N_EPOCHS = 24              # samples through the year for the seasonal sweep

# Horizon for the thermal sweep.  The panel's thermal state is periodic per
# revolution once the spin-up passes have settled, so three orbits resolve the
# derate at a given epoch; the seasonal variation is captured by sampling
# epochs, not by lengthening the window.
N_ORBITS = 3.0

# Horizon for anything involving ground contact.  The ground track only repeats
# on the order of a day, so a three-orbit window lands on an unrepresentative
# number of passes -- for the i = 53 deg case it contains *none*, which would
# silently delete the largest single housekeeping load from the bounds.  One
# full day is the shortest honest window.
# whole number of revolutions, because sustainable_power's energy-neutrality
# test is phase-dependent otherwise -- 86400 / T is 15.04 revolutions on this
# orbit and inflates the constant-draw bound by 5 %.
def _orbits_per_day(orb) -> float:
    return float(round(86400.0 / orb.nodal_period_s))


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _orbit(ltan, jd):
    if ltan is None:
        return CircularOrbit(550.0, 53.0 * DEG, 0.0, 0.0, jd)
    return CircularOrbit(550.0, sso_inclination(R_EARTH + 550.0),
                         raan_from_ltan(jd, ltan), 0.0, jd)


# ---------------------------------------------------------------------------
# A  How much of the sunlight becomes electricity
# ---------------------------------------------------------------------------
def part_a() -> dict:
    _log("A  array temperature and the thermal derate, sampled through the year")
    out = {}
    for key, title, ltan, array in CASES:
        rows = []
        for i in range(N_EPOCHS):
            day = i * 365.0 / N_EPOCHS
            jd = JD0 + day
            orb = _orbit(ltan, jd)
            system = PowerSystem(array_model=array)
            base = power_trace(orb, system, n_orbits=N_ORBITS, dt_s=DT_S)
            warm = power_trace(orb, system, n_orbits=N_ORBITS, dt_s=DT_S, thermal=True)
            g0 = float(np.mean(base.p_gen_w))
            g1 = float(np.mean(warm.p_gen_w))
            rows.append({
                "day": round(day, 2),
                "p_gen_nominal_w": g0,
                "p_gen_thermal_w": g1,
                "derate": g1 / g0 if g0 > 0 else 1.0,
                "t_sunlit_mean_c": warm.thermal_info["t_sunlit_mean_c"],
                "t_max_c": warm.thermal_info["t_max_c"],
                "t_min_c": warm.thermal_info["t_min_c"],
            })
        d = np.array([r["derate"] for r in rows])
        tmax = np.array([r["t_max_c"] for r in rows])
        tsun = np.array([r["t_sunlit_mean_c"] for r in rows])
        out[key] = {
            "title": title,
            "array_model": array,
            "samples": rows,
            "derate_mean": float(np.mean(d)),
            "derate_min": float(np.min(d)),
            "derate_max": float(np.max(d)),
            "energy_penalty_pct": float(100.0 * (1.0 - np.mean(d))),
            "t_sunlit_mean_c": float(np.mean(tsun)),
            "t_max_c": float(np.max(tmax)),
            "t_min_c": float(np.min([r["t_min_c"] for r in rows])),
            "time_constant_s": ThermalPanel().radiative_time_constant_s(320.0),
        }
        _log(f"   {title:34s} derate {np.mean(d):.4f} "
             f"({100*(1-np.mean(d)):+.2f} % energy)  "
             f"T_sunlit {np.mean(tsun):5.1f} C  T_max {np.max(tmax):5.1f} C")
    return out


# ---------------------------------------------------------------------------
# B  What the derate is sensitive to
# ---------------------------------------------------------------------------
def part_b() -> dict:
    _log("B  sensitivity of the derate to the parameters it rests on")
    key, title, ltan, array = CASES[0]
    orb = _orbit(ltan, JD0)
    system = PowerSystem(array_model=array)
    base = power_trace(orb, system, n_orbits=N_ORBITS, dt_s=DT_S)
    g0 = float(np.mean(base.p_gen_w))

    def derate(**kw) -> tuple:
        tr = power_trace(orb, system, n_orbits=N_ORBITS, dt_s=DT_S, thermal=True, **kw)
        return (float(np.mean(tr.p_gen_w)) / g0, tr.thermal_info["t_sunlit_mean_c"])

    out = {"case": title, "reference_p_gen_w": g0, "sweeps": {}}

    # The temperature coefficient: the parameter this study cannot measure and
    # the one the answer is most nearly proportional to.  Spanning -0.15 to
    # -0.35 %/K covers the range published for qualified triple-junction space
    # cells comfortably.
    rows = []
    for c in (-0.0015, -0.0020, -0.0025, -0.0030, -0.0035):
        d, t = derate(cell=CellThermalResponse(eta_ref=system.cell_efficiency,
                                               temp_coeff_per_k=c))
        rows.append({"temp_coeff_per_k": c, "derate": d,
                     "energy_penalty_pct": 100.0 * (1.0 - d)})
        _log(f"   temp coeff {100*c:+.2f} %/K -> derate {d:.4f} ({100*(1-d):+.2f} %)")
    out["sweeps"]["temperature_coefficient"] = rows

    # Optical properties: how hot the panel runs at all.  A more emissive rear
    # face is the cheapest way to buy back some of the loss, which is worth
    # showing because it is a design lever rather than a fact of nature.
    rows = []
    for a_s, e_f, e_b, note in (
        (0.92, 0.85, 0.80, "baseline"),
        (0.92, 0.85, 0.90, "more emissive rear face"),
        (0.88, 0.85, 0.80, "lower solar absorptance"),
        (0.92, 0.75, 0.70, "less emissive both faces"),
    ):
        d, t = derate(panel=ThermalPanel(alpha_solar=a_s, eps_front=e_f, eps_back=e_b))
        rows.append({"alpha_solar": a_s, "eps_front": e_f, "eps_back": e_b,
                     "note": note, "derate": d, "t_sunlit_mean_c": t,
                     "energy_penalty_pct": 100.0 * (1.0 - d)})
        _log(f"   {note:28s} alpha {a_s} eps {e_f}/{e_b} -> "
             f"T_sunlit {t:5.1f} C  derate {d:.4f}")
    out["sweeps"]["optical_properties"] = rows

    # Albedo and Earth infrared: the terms earlier versions of this model
    # excluded.  The gap between "off" and "hot case" bounds what that exclusion
    # was worth.
    rows = []
    for alb, ir, note in (
        (0.0, 0.0, "excluded (the earlier model)"),
        (ALBEDO_MEAN, EARTH_IR_MEAN, "annual mean"),
        (ALBEDO_HOT, EARTH_IR_HOT, "hot case"),
    ):
        d, t = derate(albedo=alb, earth_ir=ir)
        rows.append({"albedo": alb, "earth_ir_w_m2": ir, "note": note,
                     "derate": d, "t_sunlit_mean_c": t,
                     "energy_penalty_pct": 100.0 * (1.0 - d)})
        _log(f"   earth flux {note:28s} -> T_sunlit {t:5.1f} C  derate {d:.4f}")
    out["sweeps"]["earth_flux"] = rows

    # Heat capacity: sets the time constant, and therefore how much of the
    # post-sunrise cold spell survives.  Reported to show the transient is worth
    # integrating rather than replacing with the equilibrium temperature.
    rows = []
    for c_areal in (1000.0, 2700.0, 6000.0):
        d, t = derate(panel=ThermalPanel(heat_capacity_j_m2k=c_areal))
        rows.append({"heat_capacity_j_m2k": c_areal, "derate": d,
                     "t_sunlit_mean_c": t,
                     "time_constant_s": ThermalPanel(
                         heat_capacity_j_m2k=c_areal
                     ).radiative_time_constant_s(320.0)})
        _log(f"   heat capacity {c_areal:6.0f} J/m2K -> derate {d:.4f}")
    out["sweeps"]["heat_capacity"] = rows
    return out


# ---------------------------------------------------------------------------
# C  Where the energy goes
# ---------------------------------------------------------------------------
def part_c() -> dict:
    _log("C  the load, broken out by subsystem")
    lm = LoadModel()
    out = {
        "load_model": lm.to_dict(),
        "network": [
            {"name": s.name, "lat_deg": s.lat_deg, "lon_deg": s.lon_deg,
             "min_elevation_deg": s.min_elevation_deg}
            for s in DEFAULT_NETWORK
        ],
        "cases": {},
    }
    for key, title, ltan, array in CASES:
        orb = _orbit(ltan, JD0)
        # Contact statistics need a full day: the ground track only repeats on
        # the order of a day, so a three-orbit window would over- or under-state
        # the transmitter duty cycle depending on where it happened to start.
        t = np.arange(0.0, 86400.0, 5.0)
        r = orb.position_eci(t)
        jd = orb.jd_at(t)
        per_station = {}
        for st in DEFAULT_NETWORK:
            from solarsim.load import elevation_deg
            m = elevation_deg(r, jd, st) >= st.min_elevation_deg
            n_pass = int((np.diff(m.astype(int)) == 1).sum())
            per_station[st.name] = {
                "minutes_per_day": float(m.sum() * 5.0 / 60.0),
                "passes_per_day": n_pass,
                "max_elevation_deg": float(elevation_deg(r, jd, st).max()),
            }
        m_any = contact_mask(r, jd, DEFAULT_NETWORK)
        n_pass_any = int((np.diff(m_any.astype(int)) == 1).sum())

        tr = power_trace(orb, PowerSystem(array_model=array),
                         n_orbits=_orbits_per_day(orb), dt_s=DT_S, load=lm)
        bd = lm.breakdown_w(tr.eclipsed, tr.in_contact)
        out["cases"][key] = {
            "title": title,
            "contact_minutes_per_day": float(m_any.sum() * 5.0 / 60.0),
            "contact_fraction_of_day": float(m_any.mean()),
            "passes_per_day": n_pass_any,
            "mean_pass_minutes": (
                float(m_any.sum() * 5.0 / 60.0 / n_pass_any) if n_pass_any else 0.0
            ),
            "per_station": per_station,
            "housekeeping_breakdown_w": bd,
            "housekeeping_mean_w": tr.p_house_mean_w,
            "housekeeping_max_w": float(np.max(tr.p_house_series)),
        }
        _log(f"   {title:34s} contact {m_any.sum()*5/60:6.1f} min/day "
             f"({n_pass_any:2d} passes)  house mean {tr.p_house_mean_w:5.2f} W "
             f"peak {np.max(tr.p_house_series):5.1f} W")
    return out


# ---------------------------------------------------------------------------
# D  What it does to the bounds
# ---------------------------------------------------------------------------
def part_d() -> dict:
    _log("D  scheduling bounds under the shaped load and the thermal derate")
    lm = LoadModel()
    out = {"cases": {}}
    for key, title, ltan, array in CASES:
        orb = _orbit(ltan, JD0)
        system = PowerSystem(array_model=array)

        # The shaped trace first, because the shape-only control has to be a flat
        # load set to *its* orbit-average -- otherwise a change in the bound
        # could just be a change in how much housekeeping was demanded in total.
        n_orb = _orbits_per_day(orb)
        shaped = power_trace(orb, system, n_orbits=n_orb, dt_s=DT_S, load=lm)
        flat_equivalent = shaped.p_house_mean_w

        configs = {
            "legacy_constant_45w": power_trace(
                orb, system, n_orbits=n_orb, dt_s=DT_S),
            "flat_at_shaped_mean": power_trace(
                orb, system, n_orbits=n_orb, dt_s=DT_S,
                load=LoadModel(
                    obc_w=flat_equivalent, adcs_base_w=0.0, comms_rx_w=0.0,
                    eps_parasitic_w=0.0, thermal_base_w=0.0,
                    heater_eclipse_w=0.0, comms_tx_w=0.0,
                ), stations=()),
            "shaped": shaped,
            "shaped_plus_thermal": power_trace(
                orb, system, n_orbits=n_orb, dt_s=DT_S, load=lm, thermal=True),
        }

        entry = {"title": title, "array_model": array, "n_orbits": n_orb,
                 "horizon_hours": n_orb * orb.nodal_period_s / 3600.0,
                 "flat_equivalent_w": flat_equivalent, "configs": {}}
        for name, tr in configs.items():
            sus = sustainable_power(tr)
            opt = optimal_schedule(tr)
            led = energy_ledger(tr, payload_w=sus["sustainable_payload_w"])
            entry["configs"][name] = {
                "p_gen_mean_w": float(np.mean(tr.p_gen_w)),
                "housekeeping_mean_w": tr.p_house_mean_w,
                "housekeeping_max_w": float(np.max(tr.p_house_series)),
                "constant_bound_w": sus["sustainable_payload_w"],
                "binding_constraint": sus.get("binding_constraint"),
                "energy_balance_bound_w": sus.get("energy_balance_bound_w"),
                "dod_bound_w": sus.get("dod_bound_w"),
                "naive_estimate_w": sus.get("naive_estimate_w"),
                "lp_optimum_w": opt["mean_payload_w"] if opt.get("success") else None,
                "headroom_pct": opt.get("headroom_pct") if opt.get("success") else None,
                "curtailed_fraction_of_generated": led["curtailed_fraction_of_generated"],
                "ledger": {k: v for k, v in led.items()
                           if k != "housekeeping_breakdown_w"},
            }
            _log(f"   {title:26s} {name:22s} "
                 f"P_gen {np.mean(tr.p_gen_w):6.1f} W  "
                 f"const {sus['sustainable_payload_w']:6.1f} W  "
                 f"LP {opt['mean_payload_w']:6.1f} W  "
                 f"({opt['headroom_pct']:+5.1f} %)  "
                 f"curtailed {100*led['curtailed_fraction_of_generated']:4.1f} %")

        # A short window of the shaped trace, for the report's load-profile
        # figure.  Decimated to 30 s so the payload stays small; the eclipse
        # boundary and the contact windows both survive that comfortably, and
        # nothing is computed from it -- it is drawn, not measured.
        step = int(round(30.0 / DT_S))
        n_win = int(round(2.0 * orb.nodal_period_s / DT_S))
        sl = slice(0, n_win, step)
        entry["load_trace"] = {
            "dt_s": 30.0,
            "t_s": [round(float(x), 1) for x in shaped.t_s[sl]],
            "p_gen_w": [round(float(x), 2) for x in shaped.p_gen_w[sl]],
            "p_house_w": [round(float(x), 2) for x in shaped.p_house_series[sl]],
            "eclipsed": [int(x) for x in shaped.eclipsed[sl]],
            "in_contact": [int(x) for x in shaped.in_contact[sl]],
        }
        warm = configs["shaped_plus_thermal"]
        entry["load_trace"]["p_gen_thermal_w"] = [
            round(float(x), 2) for x in warm.p_gen_w[sl]]
        entry["load_trace"]["panel_t_c"] = [
            round(float(x) - 273.15, 2) for x in warm.panel_temperature_k[sl]]

        # The two claims this experiment exists to test.
        c = entry["configs"]
        entry["shape_only_effect"] = {
            "constant_bound_delta_w":
                c["shaped"]["constant_bound_w"] - c["flat_at_shaped_mean"]["constant_bound_w"],
            "constant_bound_delta_pct": 100.0 * (
                c["shaped"]["constant_bound_w"]
                / c["flat_at_shaped_mean"]["constant_bound_w"] - 1.0),
            "lp_optimum_delta_pct": 100.0 * (
                c["shaped"]["lp_optimum_w"] / c["flat_at_shaped_mean"]["lp_optimum_w"] - 1.0),
            "headroom_pct_flat": c["flat_at_shaped_mean"]["headroom_pct"],
            "headroom_pct_shaped": c["shaped"]["headroom_pct"],
        }
        entry["thermal_effect"] = {
            "p_gen_delta_pct": 100.0 * (
                c["shaped_plus_thermal"]["p_gen_mean_w"] / c["shaped"]["p_gen_mean_w"] - 1.0),
            "constant_bound_delta_pct": 100.0 * (
                c["shaped_plus_thermal"]["constant_bound_w"]
                / c["shaped"]["constant_bound_w"] - 1.0),
            "lp_optimum_delta_pct": 100.0 * (
                c["shaped_plus_thermal"]["lp_optimum_w"]
                / c["shaped"]["lp_optimum_w"] - 1.0),
        }
        entry["end_to_end"] = {
            "legacy_lp_optimum_w": c["legacy_constant_45w"]["lp_optimum_w"],
            "corrected_lp_optimum_w": c["shaped_plus_thermal"]["lp_optimum_w"],
            "delta_pct": 100.0 * (
                c["shaped_plus_thermal"]["lp_optimum_w"]
                / c["legacy_constant_45w"]["lp_optimum_w"] - 1.0),
        }
        out["cases"][key] = entry
    return out


PARTS = {"A": part_a, "B": part_b, "C": part_c, "D": part_d}


def main(argv: list[str]) -> int:
    selected = [a.upper() for a in argv[1:]] or list(PARTS)
    unknown = [s for s in selected if s not in PARTS]
    if unknown:
        print(f"unknown part(s): {unknown}; choose from {list(PARTS)}")
        return 2

    path = RESULTS / "e8_energy_intensity.json"
    out = json.loads(path.read_text()) if path.exists() else {}
    out["epoch"] = EPOCH.isoformat()
    out["parameters"] = {
        "n_orbits": N_ORBITS,
        "dt_s": DT_S,
        "n_epochs_per_year": N_EPOCHS,
        "panel": ThermalPanel().__dict__,
        "cell": CellThermalResponse().__dict__,
        "albedo_mean": ALBEDO_MEAN,
        "earth_ir_mean_w_m2": EARTH_IR_MEAN,
    }

    t0 = time.time()
    names = {"A": "thermal", "B": "sensitivity", "C": "load", "D": "bounds"}
    for k in selected:
        out[names[k]] = PARTS[k]()
    path.write_text(json.dumps(out, separators=(",", ":")))
    _log(f"wrote {path.name} ({path.stat().st_size/1024:.0f} kB) in {time.time()-t0:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
