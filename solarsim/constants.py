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
# Radiative environment
# ---------------------------------------------------------------------------
# Stefan-Boltzmann constant (CODATA 2018, exact under the 2019 SI redefinition).
STEFAN_BOLTZMANN = 5.670374419e-8   # W/(m^2 K^4)

# Earth's radiation budget as seen by a spacecraft in LEO.  Both quantities are
# strong functions of the sub-satellite point and of cloud cover; the values
# here are the global annual means, which is the right choice for an energy
# *budget* over many revolutions.  Worst-case thermal design uses the hot-case
# values instead, and both are reported by the sensitivity study.
#
#   ALBEDO_MEAN   global annual mean Bond albedo of Earth
#   EARTH_IR_MEAN global annual mean outgoing longwave radiation (OLR)
#
# The two are tied together by the planetary energy balance: an Earth in
# equilibrium re-emits the fraction of the solar constant it does not reflect,
# (1 - a) * S / 4 = 0.70 * 1361 / 4 = 238 W/m^2, which is where EARTH_IR_MEAN
# comes from and why the pair must not be varied independently by much.
# See ECSS-E-ST-10-04C (space environment) and Gilmore, *Spacecraft Thermal
# Control Handbook*, Vol. I, Ch. 2.
ALBEDO_MEAN = 0.30           # -
ALBEDO_HOT = 0.35            # -,      hot-case design value
EARTH_IR_MEAN = 237.0        # W/m^2,  global annual mean OLR
EARTH_IR_HOT = 260.0         # W/m^2,  hot-case design value

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
