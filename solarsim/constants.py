"""Physical and astrodynamical constants.

Values follow IERS Conventions (2010), IAU 2015 Resolution B3 nominal solar
values, and Vallado, *Fundamentals of Astrodynamics and Applications*, 4th ed.
Every constant used anywhere in the model is declared here so that a reviewer
can audit the numerical inputs of the study in one place.
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# Earth
# ---------------------------------------------------------------------------
R_EARTH = 6378.1363          # km,    equatorial radius (WGS-84 / EGM-96)
R_EARTH_POLAR = 6356.7516    # km,    polar radius (WGS-84)
FLATTENING = 1.0 / 298.257223563
MU_EARTH = 398600.4415       # km^3/s^2, geocentric gravitational constant
J2 = 1.08262668e-3           # -,      second zonal harmonic (EGM-96)
OMEGA_EARTH = 7.292115e-5    # rad/s,  Earth rotation rate

# ---------------------------------------------------------------------------
# Sun
# ---------------------------------------------------------------------------
R_SUN = 695700.0             # km,    nominal solar radius (IAU 2015 B3)
AU = 149597870.7             # km,    astronomical unit (IAU 2012 B2)
SOLAR_CONSTANT = 1361.0      # W/m^2, total solar irradiance at 1 AU
                             #        (Kopp & Lean 2011, doi:10.1029/2010GL045777)

# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------
JD_J2000 = 2451545.0         # Julian date of the J2000.0 epoch
SEC_PER_DAY = 86400.0
DAYS_PER_JULIAN_YEAR = 365.25
TROPICAL_YEAR_DAYS = 365.242190

# Mean rate at which the Sun's right ascension advances; a sun-synchronous
# orbit is defined by matching its nodal regression to this value.
SSO_NODAL_RATE = 2.0 * math.pi / (TROPICAL_YEAR_DAYS * SEC_PER_DAY)  # rad/s

# ---------------------------------------------------------------------------
# Shadow geometry
# ---------------------------------------------------------------------------
# Height of the effectively opaque atmosphere.  Below ~90 km the atmosphere is
# optically thick in the visible/near-IR bands that drive photovoltaic output,
# so the occulting body is modelled as a sphere of radius R_EARTH + H_ATM.
# See Vallado (2013) §5.3 and Montenbruck & Gill (2000) §3.4.  A sensitivity
# study over H_ATM in {0, 50, 90} km is reported by the validation suite.
H_ATM_DEFAULT = 90.0         # km

# ---------------------------------------------------------------------------
# Derived helpers
# ---------------------------------------------------------------------------
DEG = math.pi / 180.0
RAD = 180.0 / math.pi


def orbital_radius(altitude_km: float) -> float:
    """Geocentric radius of a circular orbit at `altitude_km` above R_EARTH."""
    return R_EARTH + altitude_km


def mean_motion(a_km: float) -> float:
    """Keplerian mean motion [rad/s] for semi-major axis `a_km`."""
    return math.sqrt(MU_EARTH / a_km**3)


def orbital_period(a_km: float) -> float:
    """Keplerian orbital period [s]."""
    return 2.0 * math.pi / mean_motion(a_km)
