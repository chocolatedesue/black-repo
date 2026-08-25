"""E7 -- master curves and single-revolution illumination profiles.

Produces the two datasets that make the geometry legible rather than merely
tabulated:

* the **master curve** eclipse duration vs beta angle, for a family of
  altitudes.  Because the eclipse fraction of a circular orbit depends on the
  Sun only through beta, this single curve plus the orbit period reproduces
  every eclipse duration reported anywhere in the study, and shows the sharp
  cut-off at the critical angle beta*.
* the **illumination profile** nu(u) around one revolution at several beta
  angles, which resolves the penumbral shoulders that a binary shadow flag
  hides entirely.

Both are computed with the full model (fractional solar-disc occultation,
90 km opaque atmosphere) rather than the closed form.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solarsim.constants import DEG, R_EARTH, SOLAR_CONSTANT
from solarsim.orbit import CircularOrbit
from solarsim.shadow import beta_star, illumination_fraction
from solarsim.simulate import simulate_orbit
from solarsim.solar import (
    solar_declination,
    solar_right_ascension,
    sun_vector_eci,
)
from solarsim.timeutil import datetime_to_jd

RESULTS = Path(__file__).resolve().parents[1] / "results"
RESULTS.mkdir(exist_ok=True)

EPOCH = dt.datetime(2024, 1, 1)
JD0 = datetime_to_jd(EPOCH)
H_ATM = 90.0


def plane_for_beta(target_beta_deg: float, jd: float, inc_deg: float | None = None):
    """(inclination, RAAN) giving a requested beta angle at epoch `jd`.

    With ``inc_deg`` unset the inclination is chosen as ``90 deg - dec_sun``,
    which places the orbit normal at the Sun's declination and so makes every
    beta in [0, 90] deg reachable by a choice of RAAN alone.  The eclipse
    geometry of a circular orbit depends on the plane only through beta, so the
    inclination used to realise a given beta does not affect the result -- a
    property the master curve exists to demonstrate.
    """
    dec = float(solar_declination(jd))
    ra = float(solar_right_ascension(jd))
    inc = (math.pi / 2.0 - dec) if inc_deg is None else inc_deg * DEG
    target = math.radians(target_beta_deg)
    s = (math.sin(target) - math.sin(dec) * math.cos(inc)) / (
        math.cos(dec) * math.sin(inc)
    )
    if abs(s) > 1.0:
        return None
    return inc, ra + math.asin(s)


def master_curve() -> dict:
    """Eclipse duration and fraction vs beta, for a family of altitudes."""
    altitudes = [400.0, 550.0, 700.0, 1000.0, 1200.0]
    betas = np.arange(0.0, 90.001, 0.5)
    out = {
        "altitudes_km": altitudes,
        "beta_deg": betas.tolist(),
        "h_atm_km": H_ATM,
        "eclipse_min": [],
        "eclipse_fraction": [],
        "period_min": [],
        "beta_star_deg": [],
    }
    for h in altitudes:
        ecl_min, ecl_frac = [], []
        period = None
        for b in betas:
            plane = plane_for_beta(float(b), JD0)
            if plane is None:
                ecl_min.append(float("nan"))
                ecl_frac.append(float("nan"))
                continue
            inc, raan = plane
            orb = CircularOrbit(h, inc, raan, 0.0, JD0)
            period = orb.nodal_period_s
            sim = simulate_orbit(
                orb,
                duration_days=orb.nodal_period_s / 86400.0 * 1.001,
                samples_per_rev=2048,
                h_atm=H_ATM,
                array_models=(),
            )
            ecl_min.append(float(sim.eclipse_s[0]) / 60.0)
            ecl_frac.append(float(sim.eclipse_s[0] / sim.nodal_period_s))
        out["eclipse_min"].append(np.round(ecl_min, 4).tolist())
        out["eclipse_fraction"].append(np.round(ecl_frac, 6).tolist())
        out["period_min"].append(period / 60.0)
        out["beta_star_deg"].append(math.degrees(beta_star(h, H_ATM)))
        print(
            f"  h = {h:6.0f} km  T = {period/60:5.2f} min  "
            f"beta* = {math.degrees(beta_star(h, H_ATM)):5.2f} deg  "
            f"max eclipse = {np.nanmax(ecl_min):5.2f} min",
            flush=True,
        )
    return out


def orbit_profiles() -> dict:
    """Fractional illumination around one revolution, at several beta angles."""
    h = 550.0
    n = 4096
    u_deg = np.linspace(0.0, 360.0, n, endpoint=False)
    out = {
        "altitude_km": h,
        "h_atm_km": H_ATM,
        "u_deg": np.round(u_deg, 4).tolist(),
        "beta_star_deg": math.degrees(beta_star(h, H_ATM)),
        "cases": [],
    }
    for b in (0.0, 30.0, 55.0, 65.0, 68.0, 75.0):
        plane = plane_for_beta(b, JD0)
        inc, raan = plane
        orb = CircularOrbit(h, inc, raan, 0.0, JD0)
        T = orb.nodal_period_s
        t = u_deg / 360.0 * T
        r_sat = orb.position_eci(t)
        # Hold the Sun fixed so the profile is a clean function of u alone.
        r_sun = np.broadcast_to(sun_vector_eci(JD0), (n, 3))
        nu = illumination_fraction(r_sat, r_sun, H_ATM)
        ecl = nu < 1.0
        out["cases"].append(
            {
                "beta_deg": b,
                "period_min": T / 60.0,
                "nu": np.round(nu, 5).tolist(),
                "eclipse_min": float(ecl.sum()) / n * T / 60.0,
                "sunlit_min": float((~ecl).sum()) / n * T / 60.0,
                "eclipse_arc_deg": float(ecl.sum()) / n * 360.0,
                "eclipse_center_u_deg": (
                    float(np.mod(np.degrees(np.angle(
                        np.mean(np.exp(1j * np.radians(u_deg[ecl])))
                    )), 360.0))
                    if ecl.any()
                    else None
                ),
                "mean_nu": float(nu.mean()),
            }
        )
        c = out["cases"][-1]
        print(
            f"  beta = {b:5.1f} deg  eclipse {c['eclipse_min']:6.2f} min  "
            f"arc {c['eclipse_arc_deg']:6.2f} deg  mean nu {c['mean_nu']:.4f}",
            flush=True,
        )
    return out


def penumbra_zoom() -> dict:
    """A high-resolution look at a single shadow entry, in seconds."""
    h = 550.0
    plane = plane_for_beta(0.0, JD0)
    orb = CircularOrbit(h, plane[0], plane[1], 0.0, JD0)
    T = orb.nodal_period_s
    t = np.linspace(0.0, T, 400_001)
    r_sat = orb.position_eci(t)
    r_sun = np.broadcast_to(sun_vector_eci(JD0), (t.size, 3))
    nu = illumination_fraction(r_sat, r_sun, H_ATM)
    entry = int(np.argmax(nu < 1.0))
    lo = max(0, entry - 400)
    hi = min(t.size, entry + 800)
    t0 = t[entry]
    return {
        "altitude_km": h,
        "beta_deg": 0.0,
        "t_rel_s": np.round(t[lo:hi] - t0, 4).tolist(),
        "nu": np.round(nu[lo:hi], 6).tolist(),
        "penumbra_duration_s": float(
            np.sum((nu > 0.0) & (nu < 1.0)) * (t[1] - t[0]) / 2.0
        ),
    }


def main() -> int:
    print("E7  master curve")
    payload = {"epoch": EPOCH.isoformat(), "master_curve": master_curve()}
    print("E7  orbit profiles")
    payload["orbit_profiles"] = orbit_profiles()
    print("E7  penumbra zoom")
    payload["penumbra_zoom"] = penumbra_zoom()
    path = RESULTS / "e7_profiles.json"
    path.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"wrote {path.name} ({path.stat().st_size/1024:.0f} kB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
