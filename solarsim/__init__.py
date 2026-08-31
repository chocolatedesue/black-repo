"""Solar illumination and energy-availability modelling for LEO/SSO satellites."""

from .constants import R_EARTH, SOLAR_CONSTANT
from .orbit import CircularOrbit, sso_inclination, raan_from_ltan, ltan_from_raan
from .geometry import beta_angle
from .shadow import (
    analytic_eclipse_fraction,
    beta_star,
    illumination,
    illumination_fraction,
)
from .simulate import OrbitSimulation, simulate_orbit
from .constellation import WalkerConstellation
from .topology import GridTopology
from .power import PowerSystem, energy_balance, energy_ledger
from .thermal import CellThermalResponse, ThermalPanel, earth_fluxes
from .load import GroundStation, LoadModel

__all__ = [
    "R_EARTH",
    "SOLAR_CONSTANT",
    "CircularOrbit",
    "sso_inclination",
    "raan_from_ltan",
    "ltan_from_raan",
    "beta_angle",
    "beta_star",
    "analytic_eclipse_fraction",
    "illumination",
    "illumination_fraction",
    "OrbitSimulation",
    "simulate_orbit",
    "WalkerConstellation",
    "GridTopology",
    "PowerSystem",
    "energy_balance",
    "energy_ledger",
    "ThermalPanel",
    "CellThermalResponse",
    "earth_fluxes",
    "LoadModel",
    "GroundStation",
]

__version__ = "1.0.0"
