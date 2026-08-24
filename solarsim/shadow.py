"""Earth-shadow models.

Three models of increasing fidelity are provided so that the sensitivity of the
reported statistics to the shadow assumption can itself be quantified -- a
question that is usually glossed over in the satellite-energy literature.

1. ``cylindrical`` -- the Earth casts an infinite cylinder of radius
   ``R_EARTH + h_atm``.  Binary illumination.  This is the model behind the
   familiar closed-form eclipse-fraction expression and is retained because it
   admits an analytic cross-check.
2. ``conical`` -- a dual-cone umbra/penumbra test (Vallado, Alg. 34).  Binary
   illumination; a satellite anywhere in the penumbra counts as eclipsed.
3. ``fractional`` (default) -- the illuminated fraction of the solar disc, from
   the area of the circular-circular lens formed by the apparent discs of the
   Sun and of the Earth as seen from the spacecraft.  This is the physically
   meaningful quantity for photovoltaic power, since generated power is
   proportional to unocculted solar disc area.  It reduces to the conical model
   at the umbra and full-sun boundaries.

References
----------
Vallado, D.A. (2013), *Fundamentals of Astrodynamics and Applications*, 4th ed.,
Sect. 5.3, Algorithm 34.
Montenbruck, O. and Gill, E. (2000), *Satellite Orbits*, Sect. 3.4
(conical shadow and the fractional-occultation formulation).
"""

from __future__ import annotations

import numpy as np

from .constants import H_ATM_DEFAULT, R_EARTH, R_SUN


# ---------------------------------------------------------------------------
# Model 1: cylindrical
# ---------------------------------------------------------------------------
def illumination_cylindrical(r_sat, r_sun, h_atm: float = H_ATM_DEFAULT):
    """Binary illumination under a cylindrical shadow. 1 = sunlit, 0 = eclipsed."""
    r_sat = np.asarray(r_sat, dtype=float)
    r_sun = np.asarray(r_sun, dtype=float)
    s_hat = r_sun / np.linalg.norm(r_sun, axis=-1, keepdims=True)

    along = np.sum(r_sat * s_hat, axis=-1)            # projection on Sun line
    perp = np.linalg.norm(r_sat - along[..., None] * s_hat, axis=-1)
    eclipsed = (along < 0.0) & (perp < (R_EARTH + h_atm))
    return np.where(eclipsed, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Model 2 and 3: conical geometry
# ---------------------------------------------------------------------------
def _apparent_geometry(r_sat, r_sun, h_atm: float):
    """Apparent angular radii of the Sun (a) and Earth (b) and their separation (c).

    All angles in radians, evaluated from the spacecraft.
    """
    r_sat = np.asarray(r_sat, dtype=float)
    r_sun = np.asarray(r_sun, dtype=float)

    d_sun = r_sun - r_sat                              # spacecraft -> Sun
    d_sun_norm = np.linalg.norm(d_sun, axis=-1)
    r_norm = np.linalg.norm(r_sat, axis=-1)

    r_occ = R_EARTH + h_atm
    a = np.arcsin(np.clip(R_SUN / d_sun_norm, -1.0, 1.0))     # Sun apparent radius
    b = np.arcsin(np.clip(r_occ / np.maximum(r_norm, r_occ), -1.0, 1.0))  # Earth

    # Angular separation between the Sun's centre and the Earth's centre as
    # seen from the spacecraft.  The Earth's centre lies along -r_sat.
    cos_c = np.sum(-r_sat * d_sun, axis=-1) / (r_norm * d_sun_norm)
    c = np.arccos(np.clip(cos_c, -1.0, 1.0))
    return a, b, c


def illumination_conical(r_sat, r_sun, h_atm: float = H_ATM_DEFAULT):
    """Binary illumination under the dual-cone model (penumbra counts as eclipse)."""
    a, b, c = _apparent_geometry(r_sat, r_sun, h_atm)
    return np.where(c >= a + b, 1.0, 0.0)


def umbra_flag(r_sat, r_sun, h_atm: float = H_ATM_DEFAULT):
    """1 where the spacecraft is in the geometric umbra (total eclipse)."""
    a, b, c = _apparent_geometry(r_sat, r_sun, h_atm)
    return np.where(c <= b - a, 1.0, 0.0)


def illumination_fraction(r_sat, r_sun, h_atm: float = H_ATM_DEFAULT):
    """Unocculted fraction of the solar disc, in [0, 1].

    Computed from the area of intersection of two circles of angular radii
    ``a`` (Sun) and ``b`` (Earth) whose centres are separated by ``c``:

        A_lens = a^2 acos((c^2+a^2-b^2)/(2ca))
               + b^2 acos((c^2+b^2-a^2)/(2cb))
               - 1/2 sqrt((-c+a+b)(c+a-b)(c-a+b)(c+a+b))

    and ``nu = 1 - A_lens / (pi a^2)``.  The small-angle treatment of the
    apparent discs as planar circles is exact to O(a^2) ~ 1e-5.
    """
    a, b, c = _apparent_geometry(r_sat, r_sun, h_atm)

    nu = np.ones(np.broadcast(a, b, c).shape, dtype=float)

    total = c <= (b - a)                     # Sun fully behind the Earth
    annular = c <= (a - b)                   # Earth fully inside the solar disc
    partial = (~total) & (~annular) & (c < (a + b))

    # Annular phase: a constant fraction b^2/a^2 of the disc is blocked.
    with np.errstate(divide="ignore", invalid="ignore"):
        nu = np.where(annular, 1.0 - (b**2) / (a**2), nu)

        cc = np.where(partial, c, 1.0)       # guard against division by zero
        aa = np.where(partial, a, 1.0)
        bb = np.where(partial, b, 1.0)

        t1 = aa**2 * np.arccos(
            np.clip((cc**2 + aa**2 - bb**2) / (2.0 * cc * aa), -1.0, 1.0)
        )
        t2 = bb**2 * np.arccos(
            np.clip((cc**2 + bb**2 - aa**2) / (2.0 * cc * bb), -1.0, 1.0)
        )
        t3 = 0.5 * np.sqrt(
            np.maximum(
                (-cc + aa + bb) * (cc + aa - bb) * (cc - aa + bb) * (cc + aa + bb),
                0.0,
            )
        )
        lens = t1 + t2 - t3
        nu = np.where(partial, 1.0 - lens / (np.pi * aa**2), nu)

    nu = np.where(total, 0.0, nu)
    return np.clip(nu, 0.0, 1.0)


MODELS = {
    "cylindrical": illumination_cylindrical,
    "conical": illumination_conical,
    "fractional": illumination_fraction,
}


def illumination(r_sat, r_sun, model: str = "fractional", h_atm: float = H_ATM_DEFAULT):
    """Dispatch to one of the shadow models by name."""
    try:
        fn = MODELS[model]
    except KeyError as exc:  # pragma: no cover - guarded by CLI validation
        raise ValueError(
            f"unknown shadow model {model!r}; choose from {sorted(MODELS)}"
        ) from exc
    return fn(r_sat, r_sun, h_atm)


# ---------------------------------------------------------------------------
# Closed-form reference solution
# ---------------------------------------------------------------------------
def analytic_eclipse_fraction(altitude_km: float, beta_rad, h_atm: float = 0.0):
    """Closed-form eclipse fraction of a circular orbit, cylindrical shadow.

        f_E = (1/pi) * arccos( sqrt(h^2 + 2 R h) / ((R + h) cos beta) )

    valid while |beta| < beta* = arcsin(R / (R + h)); zero otherwise.  Used only
    to validate the numerical propagation, never to produce reported results.
    """
    beta = np.asarray(beta_rad, dtype=float)
    R = R_EARTH + h_atm
    r = R_EARTH + altitude_km
    if r <= R:
        raise ValueError("orbit radius must exceed the occulting radius")
    ratio = np.sqrt(r**2 - R**2) / (r * np.cos(beta))
    out = np.where(np.abs(ratio) < 1.0, np.arccos(np.clip(ratio, -1.0, 1.0)) / np.pi, 0.0)
    return out


def beta_star(altitude_km: float, h_atm: float = 0.0) -> float:
    """Critical beta angle [rad] above which a circular orbit is eclipse-free."""
    R = R_EARTH + h_atm
    r = R_EARTH + altitude_km
    return float(np.arcsin(R / r))
