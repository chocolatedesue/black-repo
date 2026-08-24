"""Verification and validation suite.

Every claim the study makes rests on this file passing.  Four independent
checks are run:

V1  Sun ephemeris          -- solstice/equinox declinations and the perihelion
                              distance against published values.
V2  Sun-synchronous design -- computed SSO inclinations against the standard
                              design table.
V3  Shadow geometry        -- numerical eclipse fraction against the closed-form
                              cylindrical solution, and the critical beta angle
                              at which eclipses cease.
V4  Numerical convergence  -- eclipse duration as a function of the sampling
                              density, and sensitivity to the assumed opaque
                              atmosphere height and to the shadow model.

Run with ``python -m experiments.validate``; a non-zero exit status means a
check failed.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solarsim.constants import DEG, R_EARTH, AU
from solarsim.geometry import beta_angle
from solarsim.orbit import (
    CircularOrbit,
    nodal_period,
    raan_from_ltan,
    sso_inclination,
)
from solarsim.shadow import (
    analytic_eclipse_fraction,
    beta_star,
    illumination_conical,
    illumination_cylindrical,
    illumination_fraction,
)
from solarsim.simulate import simulate_orbit
from solarsim.solar import solar_declination, sun_unit_and_range
from solarsim.timeutil import datetime_to_jd

RESULTS = Path(__file__).resolve().parents[1] / "results"
RESULTS.mkdir(exist_ok=True)

_failures: list[str] = []
_records: list[dict] = []


def check(name: str, value: float, expected: float, tol: float, unit: str = "") -> None:
    ok = abs(value - expected) <= tol
    status = "PASS" if ok else "FAIL"
    print(
        f"  [{status}] {name:<52s} {value:12.5f} vs {expected:10.5f} "
        f"(tol {tol:g}) {unit}"
    )
    _records.append(
        {
            "check": name,
            "value": float(value),
            "expected": float(expected),
            "tolerance": float(tol),
            "unit": unit,
            "pass": bool(ok),
        }
    )
    if not ok:
        _failures.append(name)


# ---------------------------------------------------------------------------
def v1_sun_ephemeris() -> None:
    print("\nV1  Solar ephemeris")
    # Solstices and equinoxes of 2024 (UTC instants from the Astronomical Almanac)
    cases = [
        ("2024 March equinox     dec", dt.datetime(2024, 3, 20, 3, 6), 0.0, 0.02),
        ("2024 June solstice     dec", dt.datetime(2024, 6, 20, 20, 51), 23.44, 0.03),
        ("2024 September equinox dec", dt.datetime(2024, 9, 22, 12, 44), 0.0, 0.02),
        ("2024 December solstice dec", dt.datetime(2024, 12, 21, 9, 21), -23.44, 0.03),
    ]
    for label, when, expected, tol in cases:
        d = math.degrees(float(solar_declination(datetime_to_jd(when))))
        check(label, d, expected, tol, "deg")

    # Perihelion / aphelion distance, 2024
    _, r_peri = sun_unit_and_range(datetime_to_jd(dt.datetime(2024, 1, 3)))
    _, r_aph = sun_unit_and_range(datetime_to_jd(dt.datetime(2024, 7, 5)))
    check("Perihelion distance", float(r_peri) / AU, 0.98329, 0.0004, "AU")
    check("Aphelion distance", float(r_aph) / AU, 1.01671, 0.0004, "AU")


def v2_sun_synchronous() -> None:
    print("\nV2  Sun-synchronous inclination (design table)")
    # Reference values: Vallado (2013) Table 11-3 / Wertz SMAD sun-synchronous
    # design curve for circular orbits.
    table = [(400.0, 97.03), (600.0, 97.79), (800.0, 98.60), (1000.0, 99.48)]
    for h, expected in table:
        i = math.degrees(sso_inclination(R_EARTH + h))
        check(f"SSO inclination at h = {h:.0f} km", i, expected, 0.05, "deg")

    # A sun-synchronous orbit must hold its LTAN over a year.
    h = 600.0
    inc = sso_inclination(R_EARTH + h)
    jd0 = datetime_to_jd(dt.datetime(2024, 3, 20))
    orb = CircularOrbit(h, inc, raan_from_ltan(jd0, 10.5), 0.0, jd0)
    from solarsim.orbit import ltan_from_raan

    drift = []
    for day in (0.0, 91.0, 182.0, 273.0, 365.0):
        raan, _ = orb.elements_at(day * 86400.0)
        drift.append(ltan_from_raan(jd0 + day, float(raan)))
    check("LTAN drift over one year", (max(drift) - min(drift)) * 60.0, 0.0, 2.0, "min")


def v3_shadow_geometry() -> None:
    print("\nV3  Shadow geometry")
    # The critical beta angle above which a circular orbit never enters shadow.
    # Cross-checked two ways: against the textbook figure for the ISS altitude,
    # and for internal consistency against the closed-form eclipse fraction,
    # which must vanish exactly at beta* and be positive just inside it.
    check(
        "beta* at ISS altitude (~420 km), textbook value ~70 deg",
        math.degrees(beta_star(420.0, 0.0)),
        70.0,
        0.5,
        "deg",
    )
    for h in (420.0, 550.0, 800.0):
        bs = beta_star(h, 0.0)
        check(
            f"f_E(beta*) = 0 at h = {h:.0f} km",
            float(analytic_eclipse_fraction(h, bs + 1e-6, 0.0)),
            0.0,
            1e-12,
            "-",
        )
        check(
            f"f_E just inside beta* > 0 at h = {h:.0f} km",
            float(analytic_eclipse_fraction(h, bs - 1e-3, 0.0)) > 0.0,
            True,
            0.0,
            "-",
        )

    # Numerical propagation against the closed-form cylindrical eclipse fraction.
    #
    # The closed form assumes a Keplerian orbit plane and a Sun that does not
    # move during a revolution.  The check is therefore run as an ablation: with
    # those two assumptions reproduced exactly, the numerical machinery must
    # reproduce the closed form to machine-adjacent precision, which isolates
    # sampling, bisection and interval bookkeeping from physics.  The full model
    # is then compared against the same closed form to *quantify* what the two
    # neglected effects are worth -- a bias the satellite-energy literature
    # routinely inherits from using the closed form directly.
    print("  -- numerical vs closed form (cylindrical shadow, h_atm = 0) --")
    h = 550.0
    jd0 = datetime_to_jd(dt.datetime(2024, 3, 20))
    print(
        "     beta [deg]   bias: exact-assumptions      +J2 plane drift"
        "        +solar motion"
    )
    worst_exact = 0.0
    biases_full = []
    for target_beta_deg in (0.0, 20.0, 40.0, 55.0, 65.0):
        inc, raan = _plane_for_beta(target_beta_deg, jd0)
        row = []
        for j2, frozen in ((False, True), (True, True), (True, False)):
            orb = CircularOrbit(h, inc, raan, 0.0, jd0, j2_enabled=j2)
            sim = simulate_orbit(
                orb,
                duration_days=0.5,
                samples_per_rev=4096,
                h_atm=0.0,
                shadow_model="cylindrical",
                array_models=(),
                frozen_sun_jd=jd0 if frozen else None,
            )
            f_num = sim.eclipse_s / sim.nodal_period_s
            f_ana = analytic_eclipse_fraction(h, np.radians(sim.beta_deg), 0.0)
            row.append(float(np.mean(f_num - f_ana)))
        worst_exact = max(worst_exact, abs(row[0]))
        biases_full.append(abs(row[2]))
        print(
            f"     {target_beta_deg:8.1f}    {row[0]:+.3e}"
            f"              {row[1]:+.3e}          {row[2]:+.3e}"
        )
    check(
        "Numerical == closed form under the closed form's own assumptions",
        worst_exact,
        0.0,
        1e-9,
        "-",
    )
    max_bias = max(biases_full)
    print(
        f"     -> neglecting J2 plane drift and solar motion biases the eclipse "
        f"fraction by up to {max_bias:.2e}\n"
        f"        ({max_bias * 5730:.2f} s per revolution, "
        f"{max_bias * 5730 * 5500 / 3600:.1f} h per satellite-year)"
    )
    _records.append(
        {
            "check": "closed-form bias from neglected J2 and solar motion",
            "value": float(max_bias),
            "unit": "eclipse fraction",
            "pass": True,
        }
    )

    # Model ordering: cylindrical <= conical eclipse extent; the fractional model
    # must lie between the umbra and the full-sun boundary everywhere.
    rng = np.random.default_rng(20240320)
    jd = jd0 + rng.uniform(0.0, 365.0, 20000)
    r = R_EARTH + 550.0
    v = rng.normal(size=(20000, 3))
    r_sat = r * v / np.linalg.norm(v, axis=-1, keepdims=True)
    r_sun = sun_unit_and_range(jd)[0] * AU
    nu = illumination_fraction(r_sat, r_sun, 0.0)
    cyl = illumination_cylindrical(r_sat, r_sun, 0.0)
    con = illumination_conical(r_sat, r_sun, 0.0)
    check("nu in [0, 1]", float(np.max(np.abs(np.clip(nu, 0, 1) - nu))), 0.0, 1e-12)
    check(
        "conical fully-sunlit set implies nu == 1",
        float(np.max(np.abs(nu[con == 1.0] - 1.0))),
        0.0,
        1e-9,
    )
    check(
        "cylindrical-eclipsed set implies nu < 1",
        float(np.max(nu[cyl == 0.0])) if (cyl == 0.0).any() else 0.0,
        0.0,
        0.999,
    )


def v4_convergence() -> None:
    print("\nV4  Numerical convergence and model sensitivity")
    jd0 = datetime_to_jd(dt.datetime(2024, 3, 20))
    inc = sso_inclination(R_EARTH + 550.0)
    orb = CircularOrbit(550.0, inc, raan_from_ltan(jd0, 10.5), 0.0, jd0)

    grids = (128, 256, 512, 1024, 2048, 4096, 8192)
    runs = {
        n: simulate_orbit(
            orb,
            duration_days=3.0,
            samples_per_rev=n,
            h_atm=90.0,
            array_models=("single_axis_pitch",),
        )
        for n in grids
    }
    ref = runs[8192]
    print(
        "  samples/rev   dt [s]   mean eclipse [s]   d(eclipse) [s]   "
        "d(umbra) [s]   d(insolation integral) [ppm]"
    )
    for n in grids:
        s = runs[n]
        d_ecl = float(np.mean(s.eclipse_s) - np.mean(ref.eclipse_s))
        d_umb = float(np.mean(s.umbra_s) - np.mean(ref.umbra_s))
        rel = float(
            (np.mean(s.insolation_int_s) - np.mean(ref.insolation_int_s))
            / np.mean(ref.insolation_int_s)
            * 1e6
        )
        print(
            f"  {n:>10d}   {s.nodal_period_s/n:6.2f}   {np.mean(s.eclipse_s):16.4f}   "
            f"{d_ecl:+13.6f}   {d_umb:+11.6f}   {rel:+.2f}"
        )

    # Boundary epochs are found by bisection, so the geometric durations are
    # independent of the sampling grid; only the quadrature of the illumination
    # integral has a grid dependence, and it converges by ~512 samples/rev.
    check(
        "Eclipse duration grid-independent (128 vs 8192 samples/rev)",
        abs(float(np.mean(runs[128].eclipse_s) - np.mean(ref.eclipse_s))),
        0.0,
        1e-3,
        "s",
    )
    for n, tol in ((512, 1e-4), (2048, 1e-6)):
        check(
            f"Insolation integral converged at {n} samples/rev",
            abs(
                float(
                    (np.mean(runs[n].insolation_int_s) - np.mean(ref.insolation_int_s))
                    / np.mean(ref.insolation_int_s)
                )
            ),
            0.0,
            tol,
            "-",
        )

    print("  -- opaque-atmosphere height sensitivity (h = 550 km, LTAN 10:30) --")
    base = None
    for h_atm in (0.0, 50.0, 90.0, 120.0):
        sim = simulate_orbit(
            orb, duration_days=30.0, samples_per_rev=1024, h_atm=h_atm,
            array_models=(),
        )
        m = float(np.mean(sim.eclipse_s))
        base = base if base is not None else m
        print(
            f"     h_atm = {h_atm:5.0f} km   mean eclipse {m/60:7.4f} min "
            f"({(m - base):+6.2f} s vs h_atm = 0)"
        )
        _records.append(
            {
                "check": f"h_atm sensitivity {h_atm:.0f} km",
                "value": m / 60.0,
                "unit": "min",
                "pass": True,
            }
        )

    print("  -- penumbra duration (fraction of the eclipse spent partially lit) --")
    sim = simulate_orbit(
        orb, duration_days=30.0, samples_per_rev=2048, h_atm=90.0, array_models=()
    )
    ecl = sim.eclipse_s > 0
    pen = float(np.mean(sim.penumbra_s[ecl]))
    print(
        f"     mean penumbra {pen:.2f} s = "
        f"{100*pen/np.mean(sim.eclipse_s[ecl]):.2f} % of the eclipse"
    )
    check("Penumbra duration is a small correction", pen, 16.0, 8.0, "s")


def _plane_for_beta(target_beta_deg: float, jd: float):
    """Find (inclination, RAAN) giving a requested beta angle at epoch `jd`.

    Places the orbit normal at the requested angle from the Sun by choosing an
    inclination and solving for the RAAN, which keeps the test independent of
    the sun-synchronous machinery exercised elsewhere.
    """
    dec = float(solar_declination(jd))
    target = math.radians(target_beta_deg)
    # sin(beta) = cos(dec) sin(i) sin(Omega - ra) + sin(dec) cos(i)
    # Choose i = 60 deg and solve for (Omega - ra).
    inc = math.radians(60.0)
    from solarsim.solar import solar_right_ascension

    ra = float(solar_right_ascension(jd))
    s = (math.sin(target) - math.sin(dec) * math.cos(inc)) / (
        math.cos(dec) * math.sin(inc)
    )
    s = max(-1.0, min(1.0, s))
    return inc, ra + math.asin(s)


def main() -> int:
    print("=" * 78)
    print("solarsim verification and validation suite")
    print("=" * 78)
    v1_sun_ephemeris()
    v2_sun_synchronous()
    v3_shadow_geometry()
    v4_convergence()

    print("\n" + "=" * 78)
    if _failures:
        print(f"FAILED {len(_failures)} check(s): " + ", ".join(_failures))
    else:
        print("All checks passed.")
    (RESULTS / "validation.json").write_text(json.dumps(_records, indent=2))
    print(f"Record written to {RESULTS / 'validation.json'}")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
