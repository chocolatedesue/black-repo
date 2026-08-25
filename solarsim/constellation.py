"""Walker constellation geometry.

Walker notation ``i: T/P/F`` (Walker, J.G., 1984, "Satellite constellations",
*J. Br. Interplanet. Soc.* 37, 559-571):

* ``T`` -- total number of satellites,
* ``P`` -- number of equally spaced orbital planes,
* ``F`` -- relative phasing factor, ``0 <= F <= P-1``.

with ``S = T/P`` satellites per plane.  For a **Delta** pattern the ascending
nodes span the full 360 deg; for a **Star** pattern (typical of polar
constellations such as Iridium) they span 180 deg, because a plane at
``Omega + 180 deg`` with the same inclination retraces the same ground track in
the opposite direction.

Illumination consequence
------------------------
Every satellite in a plane shares the plane's RAAN, hence the same beta angle
and the same per-revolution eclipse duration; the phasing factor only shifts
*when* in the revolution the eclipse occurs.  Energy availability is therefore
a **per-plane** property, while instantaneous constellation-level sunlit
capacity is a per-satellite property.  Both are provided here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from .constants import DEG
from .geometry import beta_angle
from .orbit import CircularOrbit, raan_from_ltan
from .shadow import illumination_fraction
from .solar import sun_vector_eci


@dataclass
class WalkerConstellation:
    """A Walker Delta or Star constellation of circular orbits."""

    altitude_km: float
    inc_deg: float
    n_total: int
    n_planes: int
    phasing_f: int = 0
    pattern: str = "delta"          # "delta" or "star"
    raan0_deg: float = 0.0
    u0_deg: float = 0.0
    jd_epoch: float = 2451545.0
    name: str = ""
    raan_span_override_deg: Optional[float] = None

    def __post_init__(self) -> None:
        if self.n_total % self.n_planes:
            raise ValueError("n_total must be divisible by n_planes")
        if not 0 <= self.phasing_f <= self.n_planes - 1:
            raise ValueError("phasing factor F must satisfy 0 <= F <= P-1")
        if self.pattern not in ("delta", "star"):
            raise ValueError("pattern must be 'delta' or 'star'")
        self.n_per_plane = self.n_total // self.n_planes
        if not self.name:
            self.name = (
                f"Walker {self.pattern.capitalize()} "
                f"{self.inc_deg:g}:{self.n_total}/{self.n_planes}/{self.phasing_f}"
            )

    # -- geometry ------------------------------------------------------------
    @property
    def raan_span_deg(self) -> float:
        if self.raan_span_override_deg is not None:
            return self.raan_span_override_deg
        return 360.0 if self.pattern == "delta" else 180.0

    def plane_raans_deg(self) -> np.ndarray:
        step = self.raan_span_deg / self.n_planes
        return np.mod(self.raan0_deg + step * np.arange(self.n_planes), 360.0)

    def satellite_elements_deg(self):
        """Initial (RAAN, argument of latitude) of every satellite, in degrees."""
        raans = self.plane_raans_deg()
        p_idx = np.repeat(np.arange(self.n_planes), self.n_per_plane)
        s_idx = np.tile(np.arange(self.n_per_plane), self.n_planes)
        u = np.mod(
            self.u0_deg
            + s_idx * (360.0 / self.n_per_plane)
            + p_idx * self.phasing_f * (360.0 / self.n_total),
            360.0,
        )
        return raans[p_idx], u, p_idx

    def plane_orbits(self) -> List[CircularOrbit]:
        """One representative satellite per plane (sufficient for energy stats)."""
        return [
            CircularOrbit(
                altitude_km=self.altitude_km,
                inc_rad=self.inc_deg * DEG,
                raan0_rad=raan * DEG,
                u0_rad=self.u0_deg * DEG,
                jd_epoch=self.jd_epoch,
            )
            for raan in self.plane_raans_deg()
        ]

    def reference_orbit(self) -> CircularOrbit:
        return self.plane_orbits()[0]

    # -- instantaneous constellation state -----------------------------------
    def illumination_grid(self, t_s) -> np.ndarray:
        """Fractional illumination of every satellite at every epoch.

        Returns an array of shape ``(len(t_s), n_total)``.  All planes share the
        same nodal regression rate, so the RAAN spacing is rigid in time and the
        pattern is preserved.
        """
        from .orbit import _perifocal_to_eci

        ref = self.reference_orbit()
        t = np.atleast_1d(np.asarray(t_s, dtype=float))
        raan0, u0, _ = self.satellite_elements_deg()

        # Chunk over epochs: the (epoch x satellite) grid is large for a
        # thousand-satellite shell and the shadow test allocates several
        # intermediates of the same shape.
        rows_per_chunk = max(1, 2_000_000 // max(self.n_total, 1))
        out = np.empty((t.size, self.n_total), dtype=float)
        for k0 in range(0, t.size, rows_per_chunk):
            k1 = min(k0 + rows_per_chunk, t.size)
            tc = t[k0:k1]
            raan = raan0[None, :] * DEG + ref.raan_rate_rad_s * tc[:, None]
            u = u0[None, :] * DEG + ref.u_rate_rad_s * tc[:, None]
            r_sat = _perifocal_to_eci(ref.a_km, raan, ref.inc_rad, u)
            r_sun = sun_vector_eci(ref.jd_at(tc))[:, None, :]
            out[k0:k1] = illumination_fraction(r_sat, r_sun)
        return out

    def plane_beta_deg(self, t_s) -> np.ndarray:
        """Beta angle of every plane at every epoch, shape ``(len(t_s), P)``."""
        ref = self.reference_orbit()
        t = np.atleast_1d(np.asarray(t_s, dtype=float))
        raan = (
            self.plane_raans_deg()[None, :] * DEG + ref.raan_rate_rad_s * t[:, None]
        )
        jd = ref.jd_at(t)[:, None]
        return np.degrees(beta_angle(raan, ref.inc_rad, jd))


def sso_walker(
    altitude_km: float,
    n_total: int,
    n_planes: int,
    ltan_hours: float,
    phasing_f: int = 0,
    jd_epoch: float = 2451545.0,
    ltan_span_hours: Optional[float] = None,
    name: str = "",
) -> WalkerConstellation:
    """A sun-synchronous Walker constellation anchored on an LTAN.

    ``ltan_span_hours`` controls how the planes are distributed in local time:
    the default (``None``) spreads them over 12 h, which is the full range of
    distinct sun-synchronous planes (an LTAN of ``t`` and of ``t + 12 h``
    describe the same plane traversed in opposite directions).
    """
    from .orbit import sso_inclination
    from .constants import R_EARTH

    inc = sso_inclination(R_EARTH + altitude_km)
    if math.isnan(inc):
        raise ValueError("no sun-synchronous solution at this altitude")
    raan0 = raan_from_ltan(jd_epoch, ltan_hours)
    span = None if ltan_span_hours is None else ltan_span_hours * 15.0
    return WalkerConstellation(
        altitude_km=altitude_km,
        inc_deg=math.degrees(inc),
        n_total=n_total,
        n_planes=n_planes,
        phasing_f=phasing_f,
        pattern="star",
        raan0_deg=math.degrees(raan0),
        jd_epoch=jd_epoch,
        name=name or f"SSO Walker {n_total}/{n_planes}/{phasing_f} @ LTAN {ltan_hours:g}h",
        raan_span_override_deg=span,
    )
