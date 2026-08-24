"""Julian-date utilities (UTC treated as UT1; the <1 s difference is
irrelevant at the fidelity of an eclipse-duration study)."""

from __future__ import annotations

import datetime as _dt

import numpy as np

from .constants import JD_J2000, SEC_PER_DAY


def datetime_to_jd(dt: _dt.datetime) -> float:
    """Convert a (naive, UTC) datetime to a Julian date.

    Uses the standard Fliegel & van Flandern (1968) algorithm.
    """
    y, m = dt.year, dt.month
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    day_frac = (
        dt.hour + dt.minute / 60.0 + (dt.second + dt.microsecond * 1e-6) / 3600.0
    ) / 24.0
    jd = (
        int(365.25 * (y + 4716))
        + int(30.6001 * (m + 1))
        + dt.day
        + b
        - 1524.5
        + day_frac
    )
    return jd


def jd_to_datetime(jd: float) -> _dt.datetime:
    """Inverse of :func:`datetime_to_jd` (rounded to the nearest second)."""
    jd_adj = jd + 0.5
    z = int(jd_adj)
    f = jd_adj - z
    if z < 2299161:
        a = z
    else:
        alpha = int((z - 1867216.25) / 36524.25)
        a = z + 1 + alpha - alpha // 4
    b = a + 1524
    c = int((b - 122.1) / 365.25)
    d = int(365.25 * c)
    e = int((b - d) / 30.6001)
    day = b - d - int(30.6001 * e) + f
    month = e - 1 if e < 14 else e - 13
    year = c - 4716 if month > 2 else c - 4715
    day_int = int(day)
    seconds = round((day - day_int) * SEC_PER_DAY)
    return _dt.datetime(year, month, day_int) + _dt.timedelta(seconds=int(seconds))


def days_since_j2000(jd) -> "float | np.ndarray":
    """Days elapsed since the J2000.0 epoch."""
    return np.asarray(jd, dtype=float) - JD_J2000
