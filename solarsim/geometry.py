"""Sun-orbit geometry: beta angle and related derived quantities."""

from __future__ import annotations

import numpy as np

from .orbit import orbit_normal
from .solar import sun_unit_and_range


def beta_angle(raan, inc, jd) -> np.ndarray:
    """Solar beta angle [rad]: the angle between the Sun and the orbit plane.

        sin(beta) = cos(dec) sin(i) sin(Omega - ra) + sin(dec) cos(i)

    Equivalently the dot product of the unit Sun vector with the orbit's unit
    angular-momentum vector.  Positive when the Sun lies on the +h side of the
    plane.  |beta| is the single geometric parameter that controls the eclipse
    fraction of a circular orbit.
    """
    h_hat = orbit_normal(np.asarray(raan, dtype=float), inc)
    s_hat, _ = sun_unit_and_range(jd)
    return np.arcsin(np.clip(np.sum(h_hat * s_hat, axis=-1), -1.0, 1.0))


def sun_in_plane_angle(raan, inc, jd) -> np.ndarray:
    """Argument of latitude [rad] of the Sun's projection onto the orbit plane.

    The eclipse is centred on the anti-solar point, i.e. at an argument of
    latitude of ``sun_in_plane_angle + pi``.  Useful for locating the eclipse
    within a revolution and for phasing analysis inside a Walker plane.
    """
    raan = np.asarray(raan, dtype=float)
    s_hat, _ = sun_unit_and_range(jd)

    cos_r, sin_r = np.cos(raan), np.sin(raan)
    cos_i, sin_i = np.cos(inc), np.sin(inc)

    # In-plane basis: p_hat points to the ascending node, q_hat 90 deg ahead.
    p_hat = np.stack(np.broadcast_arrays(cos_r, sin_r, np.zeros_like(cos_r)), axis=-1)
    q_hat = np.stack(
        np.broadcast_arrays(
            -sin_r * cos_i,
            cos_r * cos_i,
            np.broadcast_to(sin_i, np.shape(cos_r)),
        ),
        axis=-1,
    )
    return np.mod(
        np.arctan2(np.sum(s_hat * q_hat, axis=-1), np.sum(s_hat * p_hat, axis=-1)),
        2.0 * np.pi,
    )
