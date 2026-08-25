"""Where the energy goes: a subsystem-resolved, time-varying spacecraft load.

The rest of this model is careful about the supply side and casual about the
demand side, which until now was a single number -- ``housekeeping_w = 45`` --
held constant through the orbit.  That constant hides the one feature of the
load that actually interacts with the orbit:

    **The load is largest exactly when generation is zero.**

Survival heaters are sized for the cold case and switch on in eclipse; the
array, the battery and the propellant lines are all coldest there.  A model
with a flat housekeeping draw puts the heater energy in sunlight, where the
array pays for it directly, instead of in eclipse, where it has to come out of
the battery and is therefore charged the round-trip efficiency *and* counted
against the depth-of-discharge limit.  Both bounds in :mod:`solarsim.schedule`
move as a result, and they move the pessimistic way.

Two further loads are genuinely bursty rather than constant:

* the **downlink transmitter**, which runs only inside ground-station contact
  windows -- a few minutes of a 96-minute orbit, at a power comparable to the
  entire rest of the bus;
* **attitude slews**, which draw wheel torque power in short bursts.

Modelling these as their orbit-average value is fine for an annual energy
budget and wrong for a scheduler, because a scheduler's binding constraint is
an instantaneous power balance and a depth-of-discharge floor, neither of which
is linear in the load.

Every number here is a *platform* parameter, not a physical constant.  They are
declared in one dataclass with the reasoning attached so a reader can replace
them wholesale with their own spacecraft's budget; the defaults describe the
same representative ~200 kg smallsat the rest of the study assumes, and they sum
to the 45 W the earlier constant-load model used, so the two are comparable.

Reference for the structure of a power budget, and for the practice of
splitting it by mode: Wertz & Larson, *Space Mission Analysis and Design*,
Ch. 11.4 and Table 11-8.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional, Sequence

import numpy as np

from .constants import DEG, OMEGA_EARTH, R_EARTH
from .timeutil import gmst_rad


# ---------------------------------------------------------------------------
# Ground-station access
# ---------------------------------------------------------------------------
@dataclass
class GroundStation:
    """A ground station, for working out when the transmitter is on.

    ``min_elevation_deg`` is the mask below which the link is not usable.  Ten
    degrees is the usual figure for an S- or X-band LEO station: below it the
    slant range, the atmospheric path and the local horizon all work against the
    link budget.
    """

    name: str
    lat_deg: float
    lon_deg: float
    alt_km: float = 0.0
    min_elevation_deg: float = 10.0

    def position_ecef(self) -> np.ndarray:
        """Station position in an Earth-fixed frame, spherical Earth [km].

        A spherical Earth misplaces a station by up to ~21 km in the radial
        direction relative to WGS-84.  Against a 550 km orbit that shifts the
        computed elevation angle by a fraction of a degree and an access-window
        boundary by a few seconds -- immaterial for a power budget, where what
        matters is the total contact minutes per day.
        """
        lat = self.lat_deg * DEG
        lon = self.lon_deg * DEG
        r = R_EARTH + self.alt_km
        return np.array([
            r * np.cos(lat) * np.cos(lon),
            r * np.cos(lat) * np.sin(lon),
            r * np.sin(lat),
        ])


def _eci_to_ecef(r_eci, jd):
    """Rotate ECI to Earth-fixed by the Greenwich mean sidereal angle.

    Polar motion, nutation and precession are omitted; over a study of this
    fidelity they move the ground track by well under a kilometre.
    """
    theta = np.asarray(gmst_rad(jd), dtype=float)
    c, s = np.cos(theta), np.sin(theta)
    x, y, z = r_eci[..., 0], r_eci[..., 1], r_eci[..., 2]
    return np.stack([c * x + s * y, -s * x + c * y, z], axis=-1)


def elevation_deg(r_eci, jd, station: GroundStation) -> np.ndarray:
    """Elevation of the spacecraft above the station's local horizon [deg].

    Computed from the topocentric vector in the Earth-fixed frame: the angle
    between the station-to-satellite line and the local horizontal plane, whose
    normal is the station's own radius vector on a spherical Earth.
    """
    r_ecef = _eci_to_ecef(np.asarray(r_eci, dtype=float), jd)
    r_site = station.position_ecef()
    rho = r_ecef - r_site
    rho_mag = np.linalg.norm(rho, axis=-1)
    up = r_site / np.linalg.norm(r_site)
    sin_el = np.sum(rho * up, axis=-1) / np.maximum(rho_mag, 1e-12)
    return np.rad2deg(np.arcsin(np.clip(sin_el, -1.0, 1.0)))


def contact_mask(r_eci, jd, stations: Sequence[GroundStation]) -> np.ndarray:
    """Boolean: is *any* station in view at each sample?

    The union is the right thing for a power model -- the transmitter is on if
    there is somebody to talk to -- even though a real operations plan would
    also have to arbitrate between overlapping passes.
    """
    r_eci = np.asarray(r_eci, dtype=float)
    mask = np.zeros(r_eci.shape[:-1], dtype=bool)
    for st in stations:
        mask |= elevation_deg(r_eci, jd, st) >= st.min_elevation_deg
    return mask


# A small, deliberately unexotic network: two high-latitude stations that see
# almost every revolution of a polar or sun-synchronous orbit, and two
# mid-latitude ones that do not.  A sun-synchronous satellite gets most of its
# contact time from the polar pair, which is why commercial LEO operators build
# there; the mid-latitude stations are included so the same model gives sensible
# answers for the i = 53 deg case, which the polar stations serve poorly.
DEFAULT_NETWORK = (
    GroundStation("Svalbard", 78.23, 15.39),
    GroundStation("Troll", -72.01, 2.53),
    GroundStation("Fairbanks", 64.86, -147.85),
    GroundStation("Santiago", -33.15, -70.67),
)


# ---------------------------------------------------------------------------
# The load itself
# ---------------------------------------------------------------------------
@dataclass
class LoadModel:
    """Housekeeping demand broken out by subsystem, in watts.

    The defaults sum to 37 W of always-on draw, 45 W in eclipse, and 87 W in
    the worst case of an eclipse pass over a ground station.  The orbit-average
    lands near the flat 45 W this model replaces, but it does not land there
    exactly, and it lands somewhere different in every orbit -- so comparing the
    shaped load against the old constant would confound two effects: a different
    *level* of demand and a different *shape*.

    :mod:`experiments.run_energy` therefore separates them, scoring the shaped
    load against a flat load set to the shaped load's own orbit-average.  Any
    difference that survives that control is attributable to shape alone, which
    is the claim worth making.

    Values follow the proportions of a typical smallsat budget (SMAD Table
    11-8): the bus computer and attitude control dominate the quiescent state,
    the transmitter dominates the peak, and thermal control is the term that
    varies with the orbit rather than with the operations plan.
    """

    # --- always on -------------------------------------------------------
    obc_w: float = 11.0              # flight computer, bus avionics, harness
    adcs_base_w: float = 13.0        # reaction wheels at steady momentum,
                                     # star tracker, IMU, magnetometer
    comms_rx_w: float = 4.0          # receiver, permanently listening
    eps_parasitic_w: float = 3.0     # PCDU quiescent, telemetry, shunt drivers
    thermal_base_w: float = 6.0      # baseline thermostatic control

    # --- eclipse-driven --------------------------------------------------
    heater_eclipse_w: float = 8.0
    """Survival heaters, on in eclipse only.

    This is the term the constant-load model misplaces.  Battery cells must be
    held above roughly 0 C to charge safely and the optical bench must be held
    within its stability band; both demands peak in the dark.  Modelled as a
    switched load keyed to the shadow function rather than to a thermostat, since
    the model has no bus thermal state -- an approximation that puts the energy in
    the right place in time, which is what the scheduling bounds are sensitive
    to, without pretending to a fidelity the rest of the model does not have.
    """

    # --- contact-driven --------------------------------------------------
    comms_tx_w: float = 42.0
    """Downlink transmitter, on only inside a ground-station contact window.

    Representative of a ~10 W RF X-band downlink at the ~25 % DC-to-RF
    efficiency of a solid-state amplifier at this class.  It is the largest
    single non-payload load on the spacecraft and it is on for a few percent of
    the orbit, which is precisely the pattern that a constant-load model cannot
    represent and a scheduler must plan around.
    """

    # --- manoeuvre-driven ------------------------------------------------
    adcs_slew_w: float = 18.0        # wheel torque power during a slew
    slew_duty: float = 0.0
    """Fraction of the orbit spent slewing, as a crude duty cycle.

    Zero by default: a nadir-pointing platform on a circular orbit slews only to
    acquire targets, and modelling that properly needs a tasking plan this model
    does not have.  Exposed so that an agile-imaging case can switch it on and
    see what it costs.
    """

    def constant_w(self) -> float:
        """The part of the load that never varies."""
        return (
            self.obc_w
            + self.adcs_base_w
            + self.comms_rx_w
            + self.eps_parasitic_w
            + self.thermal_base_w
        )

    def sunlit_quiescent_w(self) -> float:
        """Draw in sunlight with no contact and no slew -- the floor of the load."""
        return self.constant_w() + self.adcs_slew_w * self.slew_duty

    def eclipse_quiescent_w(self) -> float:
        """Draw in eclipse with no contact -- the floor plus the heaters."""
        return self.sunlit_quiescent_w() + self.heater_eclipse_w

    def peak_w(self) -> float:
        """Worst-case simultaneous housekeeping draw: eclipse, in contact."""
        return self.eclipse_quiescent_w() + self.comms_tx_w

    def profile_w(self, eclipsed, in_contact=None) -> np.ndarray:
        """Housekeeping draw at each sample of a trace.

        ``eclipsed`` and ``in_contact`` are boolean arrays over the same grid.
        ``in_contact`` may be omitted, in which case the transmitter is off
        throughout and the result isolates the effect of the heaters alone.
        """
        eclipsed = np.asarray(eclipsed, dtype=bool)
        p = np.full(eclipsed.shape, self.sunlit_quiescent_w(), dtype=float)
        p += np.where(eclipsed, self.heater_eclipse_w, 0.0)
        if in_contact is not None:
            p += np.where(np.asarray(in_contact, dtype=bool), self.comms_tx_w, 0.0)
        return p

    def breakdown_w(self, eclipsed, in_contact=None) -> dict:
        """Mean draw of each subsystem over a trace, in watts.

        The keys are the ledger's consumption categories, so this is what closes
        the books against generation in :func:`solarsim.power.energy_ledger`.
        """
        eclipsed = np.asarray(eclipsed, dtype=bool)
        f_ecl = float(np.mean(eclipsed))
        f_con = (0.0 if in_contact is None
                 else float(np.mean(np.asarray(in_contact, dtype=bool))))
        return {
            "obc_w": self.obc_w,
            "adcs_w": self.adcs_base_w + self.adcs_slew_w * self.slew_duty,
            "comms_rx_w": self.comms_rx_w,
            "comms_tx_w": self.comms_tx_w * f_con,
            "eps_parasitic_w": self.eps_parasitic_w,
            "thermal_base_w": self.thermal_base_w,
            "heater_w": self.heater_eclipse_w * f_ecl,
            "eclipse_fraction": f_ecl,
            "contact_fraction": f_con,
        }

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update({
            "constant_w": self.constant_w(),
            "sunlit_quiescent_w": self.sunlit_quiescent_w(),
            "eclipse_quiescent_w": self.eclipse_quiescent_w(),
            "peak_w": self.peak_w(),
        })
        return d
