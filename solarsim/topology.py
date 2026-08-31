"""Where the energy is, relative to the network: a Walker shell as a 2D torus.

The illumination model answers *how much energy a satellite has*.  This module
answers the question that follows it when a constellation is used as a
distributed compute resource: **where the energy is, relative to the network**.

The network is taken as given
-----------------------------
The crosslink graph is fixed here as the standard ``+Grid``: four terminals per
satellite, linking its two along-track neighbours in the same plane and the
phase-nearest satellite in each adjacent plane.  For a Walker Delta this is
exactly a **2D torus** of ``P`` planes by ``S`` slots, cyclic in both
directions, and it is *rigid*: all planes share a nodal regression rate, so
every partner is fixed for the life of the constellation and no link ever has
to be re-acquired.  Ranges are reported because they set the propagation delay,
not because the topology is in question.

Two facts make the torus exact rather than approximate:

* The intra-plane range is the closed-form chord ``2 a sin(pi/S)``, constant to
  machine precision, because the two satellites share a plane and a period.
* Walking once around the ring of ``P`` planes accumulates a phase offset of
  ``P F (360/T) = F (360/S)`` degrees, which is **exactly** ``F`` satellite
  slots.  The wrap-around link closes onto index ``s + F mod S`` with no
  residue, so a Walker Delta ``+Grid`` is a *twisted* torus with no phase seam.
  :attr:`GridTopology.seam_shift` returns that integer and the validation suite
  asserts it against the geometry.

What the module is for
----------------------
Every plane of a Walker Delta is the image of every other under a rotation of
the pattern about the Earth's axis, so the torus is plane-symmetric: plane ``p``
and plane ``p+1`` have identical link ranges, identical degree, and identical
ground-track coverage.  Combined with the near-identical annual duty cycles
reported by E5, a Delta shell offers **no persistent basis for assigning
different duties to different planes**.  What it does offer is a large
*instantaneous* energy spread, organised in the sun-fixed frame rather than by
plane index.  The quantities that decide whether that spread is usable -- how
many hops deep the shadow is, and how many links cross its boundary -- are
computed here on the fixed torus.

References
----------
Walker, J.G. (1984), *J. Br. Interplanet. Soc.* 37, 559.
Bhattacherjee, D. and Singla, A. (2019), "Network topology design at 27,000
km/hour", *CoNEXT '19* (the ``+Grid`` pattern and its motion-invariance).
"""

from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from .constants import DEG, H_ATM_DEFAULT, R_EARTH
from .constellation import WalkerConstellation
from .orbit import _perifocal_to_eci
from .shadow import illumination_fraction
from .solar import sun_vector_eci

#: Speed of light in vacuum [km/s].  Inter-satellite links are line-of-sight
#: through vacuum, so the propagation delay is the range divided by this --
#: unlike a terrestrial fibre, which runs at about two thirds of it.
C_KM_S = 299792.458

INTRA, INTER = 0, 1


@dataclass
class GridTopology:
    """The four-terminal ``+Grid`` crosslink graph of a Walker constellation."""

    constellation: WalkerConstellation

    def __post_init__(self) -> None:
        w = self.constellation
        self.n_planes = w.n_planes
        self.n_per_plane = w.n_per_plane
        self.n_total = w.n_total
        self._orbit = w.reference_orbit()
        raan0, u0, plane_index = w.satellite_elements_deg()
        self._raan0 = raan0 * DEG
        self._u0 = u0 * DEG
        self.plane_index = plane_index
        self.slot_index = np.tile(np.arange(self.n_per_plane), self.n_planes)
        self._build()

    # -- construction --------------------------------------------------------
    @property
    def seam_shift(self) -> int:
        """Slot relabelling of the wrap-around inter-plane link.

        Exactly ``F mod S``: see the module docstring.  For a Star pattern the
        ascending nodes span 180 deg, so the ring does not close on itself and
        the seam is a genuine discontinuity rather than a relabelling; the
        wrap-around link is then omitted.
        """
        return self.constellation.phasing_f % self.n_per_plane

    @property
    def ring_closes(self) -> bool:
        """True when plane ``P-1`` is a crosslink neighbour of plane ``0``.

        A Delta pattern spans the full 360 deg of right ascension, so its plane
        ring is cyclic.  A Star pattern spans 180 deg: its first and last planes
        are adjacent in space but counter-rotating, which is the seam that
        Iridium leaves unlinked.
        """
        return self.constellation.pattern == "delta"

    def _build(self) -> None:
        P, S = self.n_planes, self.n_per_plane
        adj = np.full((self.n_total, 4), -1, dtype=int)
        kind = np.full((self.n_total, 4), -1, dtype=int)
        shift = self.seam_shift
        for p in range(P):
            for s in range(S):
                i = p * S + s
                adj[i, 0] = p * S + (s + 1) % S
                adj[i, 1] = p * S + (s - 1) % S
                kind[i, 0] = kind[i, 1] = INTRA
                if p + 1 < P:
                    adj[i, 2] = (p + 1) * S + s
                    kind[i, 2] = INTER
                elif self.ring_closes:
                    adj[i, 2] = (s + shift) % S
                    kind[i, 2] = INTER
                if p - 1 >= 0:
                    adj[i, 3] = (p - 1) * S + s
                    kind[i, 3] = INTER
                elif self.ring_closes:
                    adj[i, 3] = (P - 1) * S + (s - shift) % S
                    kind[i, 3] = INTER
        self.neighbours = adj
        self.neighbour_kind = kind

        # Undirected edge list, each edge listed exactly once.  The wrap-around
        # link runs backwards in index, so ordering the endpoints is not enough
        # on its own; deduplicating the ordered pairs is.
        src = np.repeat(np.arange(self.n_total), 4)
        dst = adj.ravel()
        knd = kind.ravel()
        valid = dst >= 0
        pairs = np.stack(
            [np.minimum(src, dst), np.maximum(src, dst), knd], axis=1
        )[valid]
        uniq = np.unique(pairs, axis=0)
        self.edge_i, self.edge_j, self.edge_kind = uniq[:, 0], uniq[:, 1], uniq[:, 2]

    # -- kinematics ----------------------------------------------------------
    def positions_eci(self, t_s: float) -> np.ndarray:
        """Inertial position of every satellite at ``t_s`` [km], shape ``(T, 3)``."""
        o = self._orbit
        return _perifocal_to_eci(
            o.a_km,
            self._raan0 + o.raan_rate_rad_s * t_s,
            o.inc_rad,
            self._u0 + o.u_rate_rad_s * t_s,
        )

    def illumination(self, t_s: float) -> np.ndarray:
        """Unocculted solar-disc fraction of every satellite at ``t_s``."""
        o = self._orbit
        r = self.positions_eci(t_s)
        return illumination_fraction(r, sun_vector_eci(o.jd_at(t_s))[None, :])

    @property
    def intra_plane_range_km(self) -> float:
        """Closed-form along-track chord ``2 a sin(pi/S)``; exactly constant."""
        return 2.0 * self._orbit.a_km * np.sin(np.pi / self.n_per_plane)

    def link_ranges(self, r_eci: np.ndarray) -> np.ndarray:
        """Range [km] of every undirected edge for a position snapshot."""
        return np.linalg.norm(r_eci[self.edge_i] - r_eci[self.edge_j], axis=-1)

    def link_clearance_km(self, r_eci: np.ndarray) -> np.ndarray:
        """Altitude above the reference ellipsoid of each link's closest approach.

        Negative or small values mean the chord grazes the atmosphere and the
        link is not usable.  Compared against ``H_ATM_DEFAULT`` this is the same
        occulting sphere the shadow model uses, which keeps one assumption for
        both the optical path to the Sun and the optical path to a neighbour.
        """
        a = r_eci[self.edge_i]
        d = r_eci[self.edge_j] - a
        length = np.linalg.norm(d, axis=-1)
        unit = d / length[:, None]
        proj = np.clip(np.sum(-a * unit, axis=-1), 0.0, length)
        closest = np.linalg.norm(a + proj[:, None] * unit, axis=-1)
        return closest - R_EARTH

    def links_usable(self, r_eci: np.ndarray, h_atm: float = H_ATM_DEFAULT) -> np.ndarray:
        return self.link_clearance_km(r_eci) >= h_atm

    # -- energy / topology coupling -----------------------------------------
    def hops_to_sunlight(self, sunlit: np.ndarray) -> np.ndarray:
        """Breadth-first hop count from every satellite to the nearest sunlit one.

        Zero for a sunlit satellite.  This is the number of crosslinks a unit of
        work must traverse to reach a node that is generating power.
        """
        d = np.full(self.n_total, -1, dtype=int)
        q = deque(int(i) for i in np.flatnonzero(sunlit))
        for i in q:
            d[i] = 0
        adj = self.neighbours
        while q:
            i = q.popleft()
            for j in adj[i]:
                if j >= 0 and d[j] < 0:
                    d[j] = d[i] + 1
                    q.append(int(j))
        return d

    def latency_to_sunlight_ms(self, r_eci: np.ndarray, sunlit: np.ndarray) -> np.ndarray:
        """Shortest propagation delay [ms] from every satellite to a sunlit one.

        Dijkstra with the link range over ``c`` as the edge weight.  Switching,
        queueing and terminal latency are excluded: this is the floor set by
        geometry, and the honest thing to report because the rest is an
        implementation choice rather than a property of the orbit.
        """
        adj = self.neighbours
        d = np.full(self.n_total, np.inf)
        heap = []
        for i in np.flatnonzero(sunlit):
            d[i] = 0.0
            heap.append((0.0, int(i)))
        heapq.heapify(heap)
        while heap:
            du, i = heapq.heappop(heap)
            if du > d[i] + 1e-12:
                continue
            ri = r_eci[i]
            for j in adj[i]:
                if j < 0:
                    continue
                w = float(np.linalg.norm(ri - r_eci[j])) / C_KM_S * 1e3
                if du + w < d[j] - 1e-12:
                    d[j] = du + w
                    heapq.heappush(heap, (d[j], int(j)))
        return d

    def terminator_cut(self, r_eci: np.ndarray, sunlit: np.ndarray) -> dict:
        """The set of links crossing the sunlit/eclipsed boundary.

        Its cardinality is an upper bound on the maximum flow between the two
        halves of the constellation, so the aggregate crosslink capacity
        available for moving work into the sunlight is at most this many links
        times the per-link line rate -- however clever the routing.
        """
        crossing = sunlit[self.edge_i] != sunlit[self.edge_j]
        rng = self.link_ranges(r_eci)[crossing]
        n_ecl = int((~sunlit).sum())
        return {
            "n_links": int(crossing.sum()),
            "fraction_of_links": float(crossing.mean()),
            "mean_range_km": float(rng.mean()) if rng.size else float("nan"),
            "links_per_eclipsed_sat": float(crossing.sum() / n_ecl) if n_ecl else float("nan"),
        }

    def eclipsed_components(self, sunlit: np.ndarray) -> list:
        """Sizes of the connected components of the eclipsed set, largest first."""
        eclipsed = ~sunlit
        seen = np.zeros(self.n_total, dtype=bool)
        adj = self.neighbours
        sizes = []
        for start in np.flatnonzero(eclipsed):
            if seen[start]:
                continue
            stack = [int(start)]
            seen[start] = True
            n = 0
            while stack:
                i = stack.pop()
                n += 1
                for j in adj[i]:
                    if j >= 0 and eclipsed[j] and not seen[j]:
                        seen[j] = True
                        stack.append(int(j))
            sizes.append(n)
        return sorted(sizes, reverse=True)

    def is_connected(self) -> bool:
        seen = np.zeros(self.n_total, dtype=bool)
        stack = [0]
        seen[0] = True
        adj = self.neighbours
        while stack:
            i = stack.pop()
            for j in adj[i]:
                if j >= 0 and not seen[j]:
                    seen[j] = True
                    stack.append(int(j))
        return bool(seen.all())


def snapshot(topo: GridTopology, t_s: float, sunlit_threshold: float = 0.5) -> dict:
    """Every energy/topology statistic at one epoch.

    ``sunlit_threshold`` splits the fractional illumination into a binary
    partition.  The penumbra is only ~27 s of a ~95 min revolution, so the
    partition is insensitive to the threshold; 0.5 puts the boundary at half the
    solar disc.
    """
    r = topo.positions_eci(t_s)
    nu = topo.illumination(t_s)
    sunlit = nu > sunlit_threshold
    hops = topo.hops_to_sunlight(sunlit)
    ms = topo.latency_to_sunlight_ms(r, sunlit)
    eclipsed = ~sunlit
    rng = topo.link_ranges(r)
    intra = topo.edge_kind == INTRA
    return {
        "t_s": float(t_s),
        "sunlit_fraction": float(sunlit.mean()),
        "n_eclipsed": int(eclipsed.sum()),
        "hops_to_sun_mean": float(hops[eclipsed].mean()) if eclipsed.any() else 0.0,
        "hops_to_sun_max": int(hops.max()),
        "latency_to_sun_mean_ms": float(ms[eclipsed].mean()) if eclipsed.any() else 0.0,
        "latency_to_sun_max_ms": float(ms[np.isfinite(ms)].max()),
        "intra_range_km": float(rng[intra].mean()),
        "inter_range_min_km": float(rng[~intra].min()),
        "inter_range_max_km": float(rng[~intra].max()),
        "min_clearance_km": float(topo.link_clearance_km(r).min()),
        "eclipsed_component_sizes": topo.eclipsed_components(sunlit)[:3],
        **{f"cut_{k}": v for k, v in topo.terminator_cut(r, sunlit).items()},
    }
