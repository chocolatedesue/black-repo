"""Circular-orbit kinematics with secular J2 perturbations.

Eclipse statistics depend on the orbit only through (a, i, RAAN, u).  Short
period and long period perturbations displace the satellite by a few kilometres
and shift the shadow boundary crossing by well under a second, whereas the
*secular* nodal regression accumulates tens of degrees per month and completely
changes the illumination geometry.  The propagator therefore retains the
secular J2 rates in closed form and neglects the periodic terms -- the standard
"mean element" model used for constellation-level mission analysis.

References
----------
Vallado, D.A. (2013), *Fundamentals of Astrodynamics and Applications*, 4th ed.,
Sects. 9.6 (secular J2 rates) and 11.4 (sun-synchronous and repeat-ground-track
design).
Wertz, J.R. (2011), *Space Mission Engineering: The New SMAD*, Sect. 9.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .constants import (
    DEG,
    J2,
    MU_EARTH,
    R_EARTH,
    SSO_NODAL_RATE,
    mean_motion,
)
from .solar import days_since_j2000


def j2_kappa(a_km: float, inc_rad: float) -> float:
    """Common factor (3/2) n J2 (Re/a)^2 of the secular rates, e = 0."""
    n = mean_motion(a_km)
    return 1.5 * J2 * (R_EARTH / a_km) ** 2 * n


def raan_rate(a_km: float, inc_rad: float) -> float:
    """Secular nodal regression dOmega/dt [rad/s] for a circular orbit."""
    return -j2_kappa(a_km, inc_rad) * math.cos(inc_rad)


def arglat_rate(a_km: float, inc_rad: float) -> float:
    """Secular rate of the argument of latitude u = omega + M [rad/s].

    Obtained by summing the secular rates of the argument of perigee and the
    mean anomaly, d(u)/dt = n + kappa (4 cos^2 i - 1).  Its reciprocal gives the
    nodal (draconitic) period, which is the period that governs the eclipse
    cycle.
    """
    n = mean_motion(a_km)
    kappa = j2_kappa(a_km, inc_rad)
    return n + kappa * (4.0 * math.cos(inc_rad) ** 2 - 1.0)


def nodal_period(a_km: float, inc_rad: float) -> float:
    """Nodal (draconitic) period [s]."""
    return 2.0 * math.pi / arglat_rate(a_km, inc_rad)


def sso_inclination(a_km: float) -> float:
    """Inclination [rad] making a circular orbit of radius `a_km` sun-synchronous.

    Solves -kappa cos(i) = 2*pi / tropical_year for i, i.e. the nodal regression
    exactly tracks the mean motion of the Sun in right ascension.  Returns NaN
    when no solution exists (the required |cos i| exceeds unity, which happens
    above roughly 6000 km altitude).
    """
    # kappa itself depends on i only through nothing (e = 0), so the solve is
    # direct rather than iterative.
    kappa = j2_kappa(a_km, 0.0)
    cos_i = -SSO_NODAL_RATE / kappa
    if abs(cos_i) > 1.0:
        return float("nan")
    return math.acos(cos_i)


def mean_sun_right_ascension(jd) -> np.ndarray:
    """Right ascension [rad] of the fictitious mean Sun.

    Local *mean* solar time, and therefore LTAN, is defined against the mean
    Sun, which moves uniformly along the equator with right ascension equal to
    the Sun's mean longitude.  Using the apparent Sun instead would introduce
    the equation of time (up to +/-16 min) into the RAAN mapping.
    """
    n = days_since_j2000(jd)
    return np.mod((280.460 + 0.9856474 * n) * DEG, 2.0 * math.pi)


def raan_from_ltan(jd_epoch: float, ltan_hours: float) -> float:
    """RAAN [rad] corresponding to a local time of the ascending node.

    Omega = alpha_meanSun + (LTAN - 12 h) * 15 deg/h.
    """
    alpha = float(mean_sun_right_ascension(jd_epoch))
    return float(np.mod(alpha + (ltan_hours - 12.0) * 15.0 * DEG, 2.0 * math.pi))


def ltan_from_raan(jd: float, raan_rad: float) -> float:
    """Local time of the ascending node [decimal hours] for a given RAAN."""
    alpha = float(mean_sun_right_ascension(jd))
    return float(np.mod((raan_rad - alpha) / (15.0 * DEG) + 12.0, 24.0))


@dataclass
class CircularOrbit:
    """A circular orbit propagated with secular J2 rates.

    Attributes
    ----------
    altitude_km : float
        Altitude above the equatorial radius; the semi-major axis is
        ``R_EARTH + altitude_km``.
    inc_rad : float
        Inclination.
    raan0_rad : float
        Right ascension of the ascending node at ``jd_epoch``.
    u0_rad : float
        Argument of latitude at ``jd_epoch``.
    jd_epoch : float
        Reference epoch (Julian date).
    """

    altitude_km: float
    inc_rad: float
    raan0_rad: float = 0.0
    u0_rad: float = 0.0
    jd_epoch: float = 2451545.0
    j2_enabled: bool = True
    """Set False for a purely Keplerian plane (no nodal regression).  Used by
    the validation suite to reproduce the assumptions of the closed-form
    eclipse solution; never used for reported results."""

    a_km: float = field(init=False)
    period_s: float = field(init=False)
    nodal_period_s: float = field(init=False)
    raan_rate_rad_s: float = field(init=False)
    u_rate_rad_s: float = field(init=False)

    def __post_init__(self) -> None:
        self.a_km = R_EARTH + self.altitude_km
        self.period_s = 2.0 * math.pi * math.sqrt(self.a_km**3 / MU_EARTH)
        if self.j2_enabled:
            self.raan_rate_rad_s = raan_rate(self.a_km, self.inc_rad)
            self.u_rate_rad_s = arglat_rate(self.a_km, self.inc_rad)
        else:
            self.raan_rate_rad_s = 0.0
            self.u_rate_rad_s = mean_motion(self.a_km)
        self.nodal_period_s = 2.0 * math.pi / self.u_rate_rad_s

    # -- element propagation -------------------------------------------------
    def elements_at(self, t_s):
        """Mean RAAN and argument of latitude [rad] at `t_s` seconds past epoch."""
        t = np.asarray(t_s, dtype=float)
        raan = self.raan0_rad + self.raan_rate_rad_s * t
        u = self.u0_rad + self.u_rate_rad_s * t
        return raan, u

    def position_eci(self, t_s) -> np.ndarray:
        """Inertial position [km], shape (..., 3)."""
        raan, u = self.elements_at(t_s)
        return _perifocal_to_eci(self.a_km, raan, self.inc_rad, u)

    def jd_at(self, t_s):
        """Julian date(s) at `t_s` seconds past epoch."""
        return self.jd_epoch + np.asarray(t_s, dtype=float) / 86400.0


def _perifocal_to_eci(r_km, raan, inc, u) -> np.ndarray:
    """Position of a circular orbit given (r, RAAN, i, argument of latitude)."""
    cos_r, sin_r = np.cos(raan), np.sin(raan)
    cos_u, sin_u = np.cos(u), np.sin(u)
    cos_i, sin_i = np.cos(inc), np.sin(inc)
    x = r_km * (cos_r * cos_u - sin_r * sin_u * cos_i)
    y = r_km * (sin_r * cos_u + cos_r * sin_u * cos_i)
    z = r_km * (sin_u * sin_i)
    return np.stack(np.broadcast_arrays(x, y, z), axis=-1)


def orbit_normal(raan, inc) -> np.ndarray:
    """Unit angular-momentum vector of the orbit plane."""
    cos_r, sin_r = np.cos(raan), np.sin(raan)
    cos_i, sin_i = np.cos(inc), np.sin(inc)
    return np.stack(
        np.broadcast_arrays(sin_r * sin_i, -cos_r * sin_i, np.broadcast_to(cos_i, np.shape(raan))),
        axis=-1,
    )
