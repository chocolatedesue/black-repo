"""Solar-array pointing models.

Each model returns the *effective cosine factor* ``kappa(t)``: the ratio of the
array's projected area normal to the Sun line to its total physical cell area.
Generated power is then

    P(t) = nu(t) * S(t) * A_cell * eta * kappa(t)

with ``nu`` the fractional illumination from :mod:`solarsim.shadow` and ``S``
the instantaneous irradiance.  Separating ``kappa`` from ``nu`` keeps the
geometric (shadow) and the platform (attitude) contributions independent and
auditable.

All models assume a nadir-pointing LVLH reference attitude, which is the usual
baseline for Earth-observation and for LEO edge-computing payloads that must
keep a nadir antenna or an optical instrument on target.  Sun-pointing is then
achieved, if at all, by gimballed wings rather than by slewing the bus.
"""

from __future__ import annotations

import numpy as np


def _lvlh_axes(r_sat, h_hat):
    """Nadir-pointing LVLH triad (x along-track-ish, y = -h, z = nadir)."""
    r_hat = r_sat / np.linalg.norm(r_sat, axis=-1, keepdims=True)
    z_hat = -r_hat                     # nadir
    y_hat = -h_hat                     # negative orbit normal (pitch axis)
    x_hat = np.cross(y_hat, z_hat)
    x_hat = x_hat / np.linalg.norm(x_hat, axis=-1, keepdims=True)
    return x_hat, y_hat, z_hat, r_hat


def two_axis(r_sat, s_hat, h_hat):
    """Two-axis gimballed wings: the array normal always tracks the Sun."""
    return np.ones(np.shape(r_sat)[:-1], dtype=float)


def single_axis_pitch(r_sat, s_hat, h_hat):
    """Wings on a pitch-axis drive aligned with the orbit normal.

    The array can null the in-plane Sun angle but not the out-of-plane
    component, so the cosine factor collapses to ``cos(beta)``.  This is the
    dominant loss mechanism for high-|beta| orbits and is the reason a
    dawn-dusk sun-synchronous orbit does not deliver the power its near-total
    illumination would suggest.
    """
    sin_beta = np.sum(s_hat * h_hat, axis=-1)
    return np.sqrt(np.clip(1.0 - sin_beta**2, 0.0, 1.0))


def body_zenith(r_sat, s_hat, h_hat):
    """A single body-mounted panel on the anti-nadir (zenith) face."""
    _, _, _, r_hat = _lvlh_axes(r_sat, h_hat)
    return np.maximum(np.sum(r_hat * s_hat, axis=-1), 0.0)


def body_box6(r_sat, s_hat, h_hat):
    """Six body-mounted panels of equal area, one per face of a cuboid bus.

    Returns the projected area normalised by the area of a *single* face, so
    the value lies in [1, sqrt(3)] whenever the spacecraft is sunlit: exactly
    one face of each opposing pair contributes.  Dividing by six recovers the
    fraction of installed cell area that is productive, which is the figure of
    merit for mass- and area-constrained CubeSats.
    """
    x_hat, y_hat, z_hat, _ = _lvlh_axes(r_sat, h_hat)
    return (
        np.abs(np.sum(x_hat * s_hat, axis=-1))
        + np.abs(np.sum(y_hat * s_hat, axis=-1))
        + np.abs(np.sum(z_hat * s_hat, axis=-1))
    )


def body_box6_normalised(r_sat, s_hat, h_hat):
    """:func:`body_box6` divided by the six installed faces."""
    return body_box6(r_sat, s_hat, h_hat) / 6.0


ARRAY_MODELS = {
    "two_axis": two_axis,
    "single_axis_pitch": single_axis_pitch,
    "body_zenith": body_zenith,
    "body_box6_norm": body_box6_normalised,
}

ARRAY_LABELS = {
    "two_axis": "Two-axis gimballed wings",
    "single_axis_pitch": "Single-axis (pitch) drive",
    "body_zenith": "Body-mounted, zenith face",
    "body_box6_norm": "Body-mounted, 6-face cuboid",
}
