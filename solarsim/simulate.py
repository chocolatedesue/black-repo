"""Per-revolution illumination and eclipse statistics for a circular orbit.

The engine samples one nodal revolution with ``samples_per_rev`` points,
evaluates the shadow function at every sample, and then *refines* every shadow
boundary crossing by bisection so that entry and exit epochs are resolved to
better than a millisecond regardless of the sampling step.  Reported durations
are therefore free of the quantisation error that dominates naive fixed-step
eclipse counters.

Two integrals are produced per revolution:

* geometric durations -- penumbral entry to exit, and umbral entry to exit,
  obtained exactly from the refined crossing epochs;
* the *illumination integral* ``\\int nu(t) dt`` and the *insolation integral*
  ``\\int nu(t) S(t)/S_0 dt``, obtained by trapezoidal quadrature of the
  fractional-illumination function on the sample grid.  These drive the power
  model and account correctly for partial illumination in the penumbra and for
  the annual +/-3.3 % modulation of solar irradiance.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Dict, Optional, Sequence

import numpy as np

from .attitude import ARRAY_MODELS
from .constants import SOLAR_CONSTANT
from .geometry import beta_angle
from .constants import R_EARTH
from .orbit import CircularOrbit, orbit_normal
from .shadow import _apparent_geometry, illumination_fraction
from .solar import irradiance, sun_unit_and_range, sun_vector_eci

_MAX_CHUNK_SAMPLES = 400_000


@dataclass
class OrbitSimulation:
    """Per-revolution results of an illumination simulation."""

    label: str
    altitude_km: float
    inc_deg: float
    raan0_deg: float
    ltan_hours: Optional[float]
    period_s: float
    nodal_period_s: float
    n_revs: int
    duration_days: float
    shadow_model: str
    h_atm_km: float
    samples_per_rev: int

    rev_start_s: np.ndarray        # (n_revs,) epoch of each revolution
    beta_deg: np.ndarray           # (n_revs,) beta angle at mid-revolution
    eclipse_s: np.ndarray          # (n_revs,) penumbral entry -> exit duration
    umbra_s: np.ndarray            # (n_revs,) total-eclipse duration
    penumbra_s: np.ndarray         # (n_revs,) time in partial occultation
    sunlit_s: np.ndarray           # (n_revs,) nodal period - eclipse_s
    illum_integral_s: np.ndarray   # (n_revs,) \int nu dt  [s]
    insolation_int_s: np.ndarray   # (n_revs,) \int nu S/S0 dt  [s]

    # \int nu (S/S0) kappa dt [s] for each solar-array pointing model
    array_integral_s: Dict[str, np.ndarray] = field(default_factory=dict)

    # -- convenience aggregates ---------------------------------------------
    @property
    def eclipse_fraction(self) -> np.ndarray:
        return self.eclipse_s / self.nodal_period_s

    @property
    def duty_cycle(self) -> np.ndarray:
        """Effective illumination duty cycle \\int nu dt / T -- the quantity that
        actually scales photovoltaic energy production, unlike the binary
        sunlit fraction."""
        return self.illum_integral_s / self.nodal_period_s

    def summary(self) -> dict:
        ecl = self.eclipse_s
        eclipsed_revs = ecl > 0.0
        return {
            "label": self.label,
            "altitude_km": self.altitude_km,
            "inc_deg": self.inc_deg,
            "ltan_hours": self.ltan_hours,
            "period_min": self.period_s / 60.0,
            "nodal_period_min": self.nodal_period_s / 60.0,
            "n_revs": int(self.n_revs),
            "duration_days": self.duration_days,
            "beta_min_deg": float(np.min(self.beta_deg)),
            "beta_max_deg": float(np.max(self.beta_deg)),
            "beta_abs_max_deg": float(np.max(np.abs(self.beta_deg))),
            "eclipse_mean_min": float(np.mean(ecl) / 60.0),
            "eclipse_max_min": float(np.max(ecl) / 60.0),
            "eclipse_p95_min": float(np.percentile(ecl, 95) / 60.0),
            "eclipse_mean_over_eclipsed_min": (
                float(np.mean(ecl[eclipsed_revs]) / 60.0) if eclipsed_revs.any() else 0.0
            ),
            "umbra_max_min": float(np.max(self.umbra_s) / 60.0),
            "penumbra_mean_s": float(np.mean(self.penumbra_s[eclipsed_revs]))
            if eclipsed_revs.any()
            else 0.0,
            "eclipse_fraction_mean": float(np.mean(self.eclipse_fraction)),
            "eclipse_fraction_max": float(np.max(self.eclipse_fraction)),
            "duty_cycle_mean": float(np.mean(self.duty_cycle)),
            "duty_cycle_min": float(np.min(self.duty_cycle)),
            "eclipse_free_rev_fraction": float(np.mean(~eclipsed_revs)),
            "eclipse_free_days": float(
                np.sum(~eclipsed_revs) * self.nodal_period_s / 86400.0
            ),
            "insolation_mean_equiv_s": float(np.mean(self.insolation_int_s)),
            "orbit_avg_insolation_w_m2": float(
                np.mean(self.insolation_int_s) / self.nodal_period_s * SOLAR_CONSTANT
            ),
            "array_yield": {
                name: {
                    "mean_w_m2": float(
                        np.mean(v) / self.nodal_period_s * SOLAR_CONSTANT
                    ),
                    "min_w_m2": float(np.min(v) / self.nodal_period_s * SOLAR_CONSTANT),
                    "cosine_efficiency": float(
                        np.mean(v) / np.mean(self.insolation_int_s)
                    ),
                }
                for name, v in self.array_integral_s.items()
            },
        }

    def to_json_dict(self, decimate: int = 1) -> dict:
        """Serialisable form; `decimate` thins the per-revolution series."""
        d = {
            k: v
            for k, v in asdict(self).items()
            if not isinstance(v, np.ndarray) and k != "array_integral_s"
        }
        series = {
            "rev_start_s": self.rev_start_s,
            "beta_deg": self.beta_deg,
            "eclipse_s": self.eclipse_s,
            "umbra_s": self.umbra_s,
            "penumbra_s": self.penumbra_s,
            "illum_integral_s": self.illum_integral_s,
            "insolation_int_s": self.insolation_int_s,
        }
        for name, v in self.array_integral_s.items():
            series[f"array_{name}_s"] = v
        d["series"] = {
            k: np.round(v[::decimate], 4).tolist() for k, v in series.items()
        }
        d["array_models"] = sorted(self.array_integral_s)
        d["summary"] = self.summary()
        return d


# ---------------------------------------------------------------------------
# Shadow functions and their refinement
# ---------------------------------------------------------------------------
def _cylindrical_functions(r_sat, r_sun, h_atm: float):
    """Signed distance to a cylindrical shadow boundary.

    Positive means sunlit.  The branch on the anti-solar side is
    ``perp - R_occ``; on the sunward side the function is the (always positive)
    ``|r| - R_occ``.  The two branches agree where ``along = 0``, so the result
    is continuous and safe to bisect.
    """
    s_hat = r_sun / np.linalg.norm(r_sun, axis=-1, keepdims=True)
    along = np.sum(r_sat * s_hat, axis=-1)
    perp = np.linalg.norm(r_sat - along[..., None] * s_hat, axis=-1)
    r_norm = np.linalg.norm(r_sat, axis=-1)
    r_occ = R_EARTH + h_atm
    return np.where(along < 0.0, perp - r_occ, r_norm - r_occ)


def _sun_at(orbit: CircularOrbit, t_s, frozen_jd: Optional[float]):
    """Sun position, optionally held fixed at `frozen_jd`.

    Freezing the Sun removes its within-revolution motion, which the closed-form
    eclipse solution implicitly assumes.  Used only by the validation suite.
    """
    if frozen_jd is None:
        return sun_vector_eci(orbit.jd_at(t_s))
    v = sun_vector_eci(frozen_jd)
    return np.broadcast_to(v, np.shape(t_s) + (3,))


def _shadow_functions(
    orbit: CircularOrbit,
    t_s: np.ndarray,
    h_atm: float,
    model: str = "fractional",
    frozen_jd: Optional[float] = None,
):
    """Penumbra and umbra signed distances at times `t_s`.

    ``f_pen > 0`` means fully sunlit; ``f_umb < 0`` means total eclipse.  Both
    are continuous in t, which is what makes bisection well behaved.  Under the
    cylindrical model the two boundaries coincide, since a point-source Sun at
    infinity casts no penumbra.
    """
    r_sat = orbit.position_eci(t_s)
    r_sun = _sun_at(orbit, t_s, frozen_jd)
    if model == "cylindrical":
        f = _cylindrical_functions(r_sat, r_sun, h_atm)
        return f, f
    a, b, c = _apparent_geometry(r_sat, r_sun, h_atm)
    return c - (a + b), c - (b - a)


def _illumination_for_model(r_sat, r_sun, h_atm: float, model: str):
    """Fractional illumination consistent with the selected shadow model."""
    if model == "fractional":
        return illumination_fraction(r_sat, r_sun, h_atm)
    if model == "cylindrical":
        return np.where(_cylindrical_functions(r_sat, r_sun, h_atm) > 0.0, 1.0, 0.0)
    if model == "conical":
        a, b, c = _apparent_geometry(r_sat, r_sun, h_atm)
        return np.where(c >= a + b, 1.0, 0.0)
    raise ValueError(f"unknown shadow model {model!r}")


def _refine_crossings(orbit, t_lo, t_hi, h_atm, which: str, model: str,
                      frozen_jd: Optional[float] = None, iterations: int = 40):
    """Vectorised bisection of the shadow function between bracketing samples."""
    t_lo = np.array(t_lo, dtype=float)
    t_hi = np.array(t_hi, dtype=float)
    idx = 0 if which == "pen" else 1

    f_lo = _shadow_functions(orbit, t_lo, h_atm, model, frozen_jd)[idx]
    for _ in range(iterations):
        t_mid = 0.5 * (t_lo + t_hi)
        f_mid = _shadow_functions(orbit, t_mid, h_atm, model, frozen_jd)[idx]
        same = np.sign(f_mid) == np.sign(f_lo)
        t_lo = np.where(same, t_mid, t_lo)
        t_hi = np.where(same, t_hi, t_mid)
        f_lo = np.where(same, f_mid, f_lo)
    return 0.5 * (t_lo + t_hi)


def _crossing_intervals(orbit, t, f, h_atm, which, model, frozen_jd=None):
    """Return (starts, ends) of the intervals where `f < 0`, refined to <1 ms.

    Intervals that are open at the beginning or end of the simulated span are
    clipped to the span, which is harmless because the span always covers an
    integer number of revolutions plus a guard revolution.
    """
    inside = f < 0.0
    if not inside.any():
        return np.empty(0), np.empty(0)

    d = np.diff(inside.astype(np.int8))
    enter_idx = np.flatnonzero(d == 1)       # sunlit -> shadow between i, i+1
    exit_idx = np.flatnonzero(d == -1)       # shadow -> sunlit between i, i+1

    starts = (
        _refine_crossings(
            orbit, t[enter_idx], t[enter_idx + 1], h_atm, which, model, frozen_jd
        )
        if enter_idx.size
        else np.empty(0)
    )
    ends = (
        _refine_crossings(
            orbit, t[exit_idx], t[exit_idx + 1], h_atm, which, model, frozen_jd
        )
        if exit_idx.size
        else np.empty(0)
    )

    if inside[0]:
        starts = np.concatenate([[t[0]], starts])
    if inside[-1]:
        ends = np.concatenate([ends, [t[-1]]])
    return starts, ends


def _cumulative_from_intervals(starts, ends, query_t):
    """Total interval measure in [0, query_t] evaluated at each `query_t`.

    Builds the piecewise-linear cumulative measure at the interval breakpoints
    and interpolates, which is exact for the query points used here.
    """
    if starts.size == 0:
        return np.zeros_like(query_t)
    order = np.argsort(starts)
    s, e = starts[order], ends[order]
    knots = np.empty(2 * s.size + 1)
    vals = np.empty(2 * s.size + 1)
    knots[0], vals[0] = -np.inf, 0.0
    knots[1::2], knots[2::2] = s, e
    durations = np.cumsum(e - s)
    vals[1::2] = np.concatenate([[0.0], durations[:-1]])
    vals[2::2] = durations
    return np.interp(query_t, knots[1:], vals[1:], left=0.0, right=vals[-1])


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def simulate_orbit(
    orbit: CircularOrbit,
    duration_days: float = 365.25,
    samples_per_rev: int = 1024,
    h_atm: float = 90.0,
    shadow_model: str = "fractional",
    label: str = "",
    ltan_hours: Optional[float] = None,
    array_models: Sequence[str] = ("two_axis", "single_axis_pitch", "body_box6_norm"),
    frozen_sun_jd: Optional[float] = None,
) -> OrbitSimulation:
    """Simulate `duration_days` of illumination for `orbit`.

    Parameters
    ----------
    array_models
        Names from :data:`solarsim.attitude.ARRAY_MODELS`.  For each, the
        integral ``\\int nu (S/S_0) kappa dt`` is accumulated per revolution.
    """
    T = orbit.nodal_period_s
    n_revs = int(np.floor(duration_days * 86400.0 / T))
    dt = T / samples_per_rev
    # One guard sample beyond the last revolution so that the final interval is
    # closed and the cumulative measure is defined on the whole span.
    n_samples = n_revs * samples_per_rev + 1

    rev_edges = np.arange(n_revs + 1) * T

    ecl_starts, ecl_ends = [], []
    umb_starts, umb_ends = [], []
    illum_partial = np.zeros(n_revs)
    insol_partial = np.zeros(n_revs)
    array_partial = {name: np.zeros(n_revs) for name in array_models}

    # Process in chunks aligned to whole revolutions to bound peak memory.
    revs_per_chunk = max(1, _MAX_CHUNK_SAMPLES // samples_per_rev)
    for k0 in range(0, n_revs, revs_per_chunk):
        k1 = min(k0 + revs_per_chunk, n_revs)
        t = np.arange(k0 * samples_per_rev, k1 * samples_per_rev + 1) * dt
        f_pen, f_umb = _shadow_functions(orbit, t, h_atm, shadow_model, frozen_sun_jd)

        s, e = _crossing_intervals(
            orbit, t, f_pen, h_atm, "pen", shadow_model, frozen_sun_jd
        )
        ecl_starts.append(s)
        ecl_ends.append(e)
        s, e = _crossing_intervals(
            orbit, t, f_umb, h_atm, "umb", shadow_model, frozen_sun_jd
        )
        umb_starts.append(s)
        umb_ends.append(e)

        # Illumination and insolation integrals by trapezoid, per revolution.
        r_sat = orbit.position_eci(t)
        jd = orbit.jd_at(t)
        nu = _illumination_for_model(
            r_sat, _sun_at(orbit, t, frozen_sun_jd), h_atm, shadow_model
        )
        scale = irradiance(jd) / SOLAR_CONSTANT

        nu_rev = nu[:-1].reshape(k1 - k0, samples_per_rev)
        nu_rev_next = nu[1:].reshape(k1 - k0, samples_per_rev)
        sc_rev = scale[:-1].reshape(k1 - k0, samples_per_rev)
        sc_rev_next = scale[1:].reshape(k1 - k0, samples_per_rev)

        illum_partial[k0:k1] = 0.5 * dt * np.sum(nu_rev + nu_rev_next, axis=1)
        insol_partial[k0:k1] = (
            0.5 * dt * np.sum(nu_rev * sc_rev + nu_rev_next * sc_rev_next, axis=1)
        )

        if array_models:
            raan_t, _ = orbit.elements_at(t)
            h_hat = orbit_normal(raan_t, orbit.inc_rad)
            r_sun_arr = _sun_at(orbit, t, frozen_sun_jd)
            s_hat = r_sun_arr / np.linalg.norm(r_sun_arr, axis=-1, keepdims=True)
            w = nu * scale                       # illumination x irradiance ratio
            for name in array_models:
                kappa = ARRAY_MODELS[name](r_sat, s_hat, h_hat)
                g = w * kappa
                array_partial[name][k0:k1] = (
                    0.5
                    * dt
                    * np.sum(
                        g[:-1].reshape(k1 - k0, samples_per_rev)
                        + g[1:].reshape(k1 - k0, samples_per_rev),
                        axis=1,
                    )
                )

    ecl_starts = np.concatenate(ecl_starts) if ecl_starts else np.empty(0)
    ecl_ends = np.concatenate(ecl_ends) if ecl_ends else np.empty(0)
    umb_starts = np.concatenate(umb_starts) if umb_starts else np.empty(0)
    umb_ends = np.concatenate(umb_ends) if umb_ends else np.empty(0)

    cum_ecl = _cumulative_from_intervals(ecl_starts, ecl_ends, rev_edges)
    cum_umb = _cumulative_from_intervals(umb_starts, umb_ends, rev_edges)
    eclipse_s = np.diff(cum_ecl)
    umbra_s = np.diff(cum_umb)

    rev_start = rev_edges[:-1]
    raan_mid, _ = orbit.elements_at(rev_start + 0.5 * T)
    jd_mid = (
        orbit.jd_at(rev_start + 0.5 * T)
        if frozen_sun_jd is None
        else np.full(rev_start.shape, frozen_sun_jd)
    )
    beta = beta_angle(raan_mid, orbit.inc_rad, jd_mid)

    return OrbitSimulation(
        label=label or f"h={orbit.altitude_km:.0f}km i={np.degrees(orbit.inc_rad):.1f}deg",
        altitude_km=orbit.altitude_km,
        inc_deg=float(np.degrees(orbit.inc_rad)),
        raan0_deg=float(np.degrees(orbit.raan0_rad) % 360.0),
        ltan_hours=ltan_hours,
        period_s=orbit.period_s,
        nodal_period_s=T,
        n_revs=n_revs,
        duration_days=duration_days,
        shadow_model=shadow_model,
        h_atm_km=h_atm,
        samples_per_rev=samples_per_rev,
        rev_start_s=rev_start,
        beta_deg=np.degrees(beta),
        eclipse_s=eclipse_s,
        umbra_s=umbra_s,
        penumbra_s=eclipse_s - umbra_s,
        sunlit_s=T - eclipse_s,
        illum_integral_s=illum_partial,
        insolation_int_s=insol_partial,
        array_integral_s=array_partial,
    )
