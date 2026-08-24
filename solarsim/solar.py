"""Apparent geocentric position of the Sun.

The low-precision series of the *Astronomical Almanac* (Sect. C24) is used.
It is accurate to better than 0.01 deg in ecliptic longitude and 2e-5 AU in
range over 1950-2050, which corresponds to a shadow-boundary timing error of
well under one second for a low Earth orbit -- two orders of magnitude below
the eclipse durations of interest here.

Reference
---------
U.S. Naval Observatory / H.M. Nautical Almanac Office, *The Astronomical
Almanac*, "Low precision formulae for the Sun".  Reproduced in Vallado (2013),
Algorithm 29 ("Sun"), and Montenbruck & Gill (2000), Sect. 3.3.2.
"""

from __future__ import annotations

import numpy as np

from .constants import AU, DEG, SOLAR_CONSTANT
from .timeutil import days_since_j2000


def sun_vector_eci(jd) -> np.ndarray:
    """Geocentric Sun position in the mean equator/equinox of date.

    Parameters
    ----------
    jd : float or array_like
        Julian date(s), UTC.

    Returns
    -------
    ndarray, shape (..., 3)
        Sun position in kilometres, ECI (mean-of-date ~ J2000 to within the
        precession over the simulated span, which is immaterial for shadow
        geometry because the orbit is propagated in the same frame).
    """
    n = days_since_j2000(jd)

    # Mean longitude and mean anomaly of the Sun [deg]
    L = 280.460 + 0.9856474 * n
    g = (357.528 + 0.9856003 * n) * DEG

    # Ecliptic longitude, equation of centre truncated after the second term
    lam = (L + 1.915 * np.sin(g) + 0.020 * np.sin(2.0 * g)) * DEG

    # Obliquity of the ecliptic [rad]
    eps = (23.439 - 4.0e-7 * n) * DEG

    # Sun-Earth distance [AU]
    r_au = 1.00014 - 0.01671 * np.cos(g) - 0.00014 * np.cos(2.0 * g)
    r_km = r_au * AU

    cos_lam, sin_lam = np.cos(lam), np.sin(lam)
    vec = np.stack(
        [cos_lam, np.cos(eps) * sin_lam, np.sin(eps) * sin_lam], axis=-1
    )
    return vec * np.asarray(r_km)[..., None]


def sun_unit_and_range(jd):
    """Return (unit vector towards the Sun, Sun-Earth range in km)."""
    v = sun_vector_eci(jd)
    r = np.linalg.norm(v, axis=-1)
    return v / r[..., None], r


def solar_declination(jd) -> np.ndarray:
    """Apparent solar declination [rad]."""
    u, _ = sun_unit_and_range(jd)
    return np.arcsin(u[..., 2])


def solar_right_ascension(jd) -> np.ndarray:
    """Apparent solar right ascension [rad], in [0, 2*pi)."""
    u, _ = sun_unit_and_range(jd)
    return np.mod(np.arctan2(u[..., 1], u[..., 0]), 2.0 * np.pi)


def irradiance(jd) -> np.ndarray:
    """Total solar irradiance [W/m^2] at the Earth's instantaneous distance.

    Scales the 1 AU total solar irradiance by the inverse-square law, which
    introduces the well-known +/-3.3 % annual modulation between perihelion
    (early January) and aphelion (early July).
    """
    _, r = sun_unit_and_range(jd)
    return SOLAR_CONSTANT * (AU / r) ** 2
