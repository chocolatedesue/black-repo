"""Matching real compute accelerators to the orbital energy budget.

The rest of this package answers "how much energy is available".  This module
answers the question that follows immediately: *given a specific piece of
compute hardware, what does it cost to keep it running, and can it run through
eclipse?*

Two things make that question sharper than it looks.

**Always-on is never impossible, it is priced.**  Any load can be carried
through eclipse by a large enough battery, so the interesting output is not a
yes/no but a *marginal mass cost per always-on watt* -- battery, array and
radiator mass per watt of continuous payload draw.  That number is a property
of the orbit alone (:func:`marginal_cost`), which is why it can be tabulated
once and applied to any accelerator.

**Board power is not system power, and every watt becomes heat.**  A GPU's TDP
excludes its host CPU, memory and storage; and in vacuum the only way out for
the resulting heat is radiation, so the radiator is sized by the same number
that sizes the array.  For datacenter-class parts the radiator is comparable in
area to the solar array, which is the single most common omission in
back-of-envelope "GPU in space" estimates.

Scope and honesty
-----------------
The orbital quantities used here (eclipse durations, per-revolution array
yield) come from the verified simulation and carry its error bars.  The
*platform* coefficients -- battery specific energy, array specific power,
radiator heat rejection -- are engineering figures from the smallsat
literature, not outputs of this model.  They are collected in :class:`Platform`
with their ranges so a reader can substitute their own, and
:func:`sensitivity` reports how much the conclusion moves across the plausible
range.  Nothing in this module is claimed to the precision of the illumination
results; it is a scoping calculation with an auditable set of assumptions.

References for the accelerator figures are recorded per entry in
:data:`ACCELERATORS`.  Where a part has flown, the mission is named.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

from .constants import SOLAR_CONSTANT
from .power import PowerSystem

# ---------------------------------------------------------------------------
# Accelerator catalogue
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Accelerator:
    """A compute part, with the numbers needed to size a spacecraft around it.

    ``board_w`` is the part's own sustained power at its nominal operating
    point -- module power for an SoC, board/TDP for a discrete GPU.  It is
    deliberately *not* the peak: peak power sizes the PCDU and the transient
    battery response, not the orbit-average energy budget this module is about.

    ``system_factor`` converts board power to the power the spacecraft bus must
    actually deliver: host CPU, DRAM, NVMe, PCIe switching and voltage
    conversion.  Self-contained SoC modules already include their host, so they
    sit near 1.25 (carrier board, storage, converters).  A discrete datacenter
    GPU needs a whole server behind it; the 8-GPU reference nodes published by
    the vendors run about 1.8x the summed GPU power, and a single-GPU payload
    amortises the host worse rather than better, so 1.6 is optimistic.
    """

    key: str
    name: str
    vendor: str
    class_: str                  # space | edge | embedded | workstation | datacenter
    board_w: float
    system_factor: float
    throughput: float            # in the units of `throughput_unit`
    throughput_unit: str
    note: str
    flown: str = ""              # mission, if the part or its family has flown

    @property
    def system_w(self) -> float:
        """Power the bus must deliver to run this part continuously."""
        return self.board_w * self.system_factor

    @property
    def efficiency(self) -> float:
        """Throughput per system watt, in `throughput_unit` per W."""
        return self.throughput / self.system_w


#: Sustained power and throughput for parts that are either flying, space
#: qualified, or credibly proposed for orbital compute.  Throughput is quoted
#: in the vendor's headline units and is *not* comparable across rows with
#: different units -- INT8 TOPS and BF16 TFLOPS measure different things.  It is
#: carried so that energy cost per unit of work can be formed within a row.
ACCELERATORS = (
    Accelerator(
        "myriad2", "Movidius Myriad 2", "Intel", "space",
        board_w=1.0, system_factor=1.6, throughput=0.1, throughput_unit="TOPS INT8",
        note="Vision processing unit; the whole payload computer draws a few watts.",
        flown="ESA PhiSat-1 (2020), first neural inference in orbit",
    ),
    Accelerator(
        "myriadx", "Movidius Myriad X", "Intel", "space",
        board_w=2.0, system_factor=1.6, throughput=4.0, throughput_unit="TOPS INT8",
        note="Flown inside the Ubotica CogniSAT / Unibap iX10 payload computers.",
        flown="ESA PhiSat-2 (2023), Ubotica CogniSAT-6 (2024)",
    ),
    Accelerator(
        "versal_ai", "Versal AI Core XQR VC1902", "AMD/Xilinx", "space",
        board_w=30.0, system_factor=1.3, throughput=100.0, throughput_unit="TOPS INT8",
        note="Radiation-tolerant adaptive SoC; AI engines plus programmable logic.",
        flown="space-grade qualified part",
    ),
    Accelerator(
        "orin_nx", "Jetson Orin NX 16 GB", "NVIDIA", "edge",
        board_w=25.0, system_factor=1.25, throughput=100.0, throughput_unit="TOPS INT8",
        note="COTS module; the usual choice for on-board inference on a 6U-12U bus.",
        flown="COTS derivatives on commercial smallsats",
    ),
    Accelerator(
        "agx_orin", "Jetson AGX Orin 64 GB", "NVIDIA", "edge",
        board_w=60.0, system_factor=1.25, throughput=275.0, throughput_unit="TOPS INT8",
        note="Configurable 15-60 W; quoted at its maximum sustained mode.",
        flown="COTS; space-qualified carriers offered by several vendors",
    ),
    Accelerator(
        "agx_thor", "Jetson AGX Thor", "NVIDIA", "edge",
        board_w=130.0, system_factor=1.25, throughput=2070.0, throughput_unit="TFLOPS FP4",
        note="Blackwell-generation edge module; the top of the low-power class.",
    ),
    Accelerator(
        "cloud_ai100", "Cloud AI 100 Standard", "Qualcomm", "embedded",
        board_w=75.0, system_factor=1.5, throughput=350.0, throughput_unit="TOPS INT8",
        note="Passively cooled inference card; needs a host, unlike the SoCs above.",
    ),
    Accelerator(
        "l4", "L4", "NVIDIA", "datacenter",
        board_w=72.0, system_factor=1.6, throughput=242.0, throughput_unit="TFLOPS FP16",
        note="Single-slot inference GPU; the lowest-power part in the server line.",
    ),
    Accelerator(
        "a100_pcie", "A100 PCIe 80 GB", "NVIDIA", "datacenter",
        board_w=250.0, system_factor=1.6, throughput=312.0, throughput_unit="TFLOPS BF16",
        note="Ampere training GPU, PCIe form factor.",
    ),
    Accelerator(
        "l40s", "L40S", "NVIDIA", "datacenter",
        board_w=350.0, system_factor=1.6, throughput=362.0, throughput_unit="TFLOPS BF16",
        note="Ada inference/graphics GPU.",
    ),
    Accelerator(
        "h100_pcie", "H100 PCIe 80 GB", "NVIDIA", "datacenter",
        board_w=350.0, system_factor=1.6, throughput=756.0, throughput_unit="TFLOPS BF16",
        note="The power-capped H100; the variant an orbital payload would choose.",
    ),
    Accelerator(
        "h100_sxm", "H100 SXM5 80 GB", "NVIDIA", "datacenter",
        board_w=700.0, system_factor=1.6, throughput=989.0, throughput_unit="TFLOPS BF16",
        note="Full-power H100. Doubling board power buys 31 % more throughput.",
        flown="Starcloud-1 (Nov 2025), first datacenter GPU in orbit",
    ),
    Accelerator(
        "b200", "B200 SXM", "NVIDIA", "datacenter",
        board_w=1000.0, system_factor=1.6, throughput=2250.0, throughput_unit="TFLOPS BF16",
        note="Blackwell; the current upper end of single-package datacenter power.",
    ),
)

ACCELERATOR_BY_KEY = {a.key: a for a in ACCELERATORS}


# ---------------------------------------------------------------------------
# Platform coefficients
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Platform:
    """Mass and heat-rejection coefficients for the supporting spacecraft.

    Every field carries a plausible range in its comment.  These are the
    numbers a reviewer will push on, so :func:`sensitivity` sweeps them rather
    than leaving the reader to trust the midpoint.
    """

    battery_wh_per_kg: float = 130.0    # 90-160, pack level, space Li-ion
    array_w_per_kg: float = 100.0       # 60-150 W/kg BOL, rigid to flexible
    radiator_w_per_m2: float = 250.0    # 150-350, single-sided, ~40 C, LEO sink
    radiator_kg_per_m2: float = 4.0     # 3-6, panel plus heat-pipe transport
    #: Electrical chain from the EPS model, so the two stay consistent.
    eps: PowerSystem = field(default_factory=PowerSystem)

    @property
    def array_w_per_m2_peak(self) -> float:
        """Array electrical output per m^2 in full sun at normal incidence."""
        return self.eps.array_gain_w / self.eps.array_area_m2

    @property
    def array_kg_per_m2(self) -> float:
        return self.array_w_per_m2_peak / self.array_w_per_kg

    @property
    def insolation_to_electrical(self) -> float:
        """Conversion from orbit-average incident W/m^2 to electrical W/m^2."""
        return self.array_w_per_m2_peak / SOLAR_CONSTANT


# ---------------------------------------------------------------------------
# The orbit-only quantity: what one always-on watt costs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OrbitCost:
    """Marginal cost of one watt of *continuous* payload power in a given orbit."""

    label: str
    array_model: str
    nodal_period_min: float
    eclipse_max_min: float
    eclipse_mean_min: float
    battery_wh_per_w: float
    battery_kg_per_w: float
    array_m2_per_w: float
    array_kg_per_w: float
    radiator_m2_per_w: float
    radiator_kg_per_w: float

    @property
    def total_kg_per_w(self) -> float:
        return self.battery_kg_per_w + self.array_kg_per_w + self.radiator_kg_per_w

    @property
    def w_per_kg(self) -> float:
        """Continuous payload watts per kg of array + battery + radiator."""
        return 1.0 / self.total_kg_per_w

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total_kg_per_w"] = self.total_kg_per_w
        d["w_per_kg"] = self.w_per_kg
        return d


def marginal_cost(
    summary: dict,
    array_model: str,
    platform: Optional[Platform] = None,
) -> OrbitCost:
    """Cost of one always-on watt, from an ``e1``-style orbit summary.

    Three independent sizing conditions, each linear in payload power:

    **Battery** must carry the load through the *worst* eclipse of the year
    without exceeding the depth-of-discharge limit -- the same condition as
    :func:`solarsim.power.size_battery`, expressed per watt.

    **Array** must, in the worst revolution, generate the sunlit load directly
    *and* refill what the eclipse took out.  The eclipse share is charged the
    full round trip, so it costs ``1/(eta_c . eta_d)`` -- about 8 % more than
    the sunlit share.  This is why an always-on watt is strictly more expensive
    than an average watt, before any mass is counted.

    **Radiator** must reject the entire delivered power, because in vacuum
    there is nowhere else for it to go.  Sizing is by orbit-average power,
    which is the right choice for a continuous load and would not be for a
    bursty one.
    """
    platform = platform or Platform()
    eps = platform.eps

    period_min = float(summary["nodal_period_min"])
    ecl_max_min = float(summary["eclipse_max_min"])
    sun_min = period_min - ecl_max_min

    # Battery: worst-case eclipse within the DoD limit.
    battery_wh_per_w = (
        ecl_max_min / 60.0 / (eps.discharge_efficiency * eps.dod_limit)
    )

    # Array: worst-revolution orbit-average electrical yield per m^2.
    yield_min_w_m2 = (
        float(summary["array_yield"][array_model]["min_w_m2"])
        * platform.insolation_to_electrical
    )
    round_trip = eps.charge_efficiency * eps.discharge_efficiency
    demand_w_min = sun_min + ecl_max_min / round_trip      # W.min of generation per W of load
    supply_w_min_per_m2 = yield_min_w_m2 * period_min
    array_m2_per_w = (
        float("inf") if supply_w_min_per_m2 <= 0.0
        else demand_w_min / supply_w_min_per_m2
    )

    radiator_m2_per_w = 1.0 / platform.radiator_w_per_m2

    return OrbitCost(
        label=str(summary.get("label", "")),
        array_model=array_model,
        nodal_period_min=period_min,
        eclipse_max_min=ecl_max_min,
        eclipse_mean_min=float(summary["eclipse_mean_min"]),
        battery_wh_per_w=battery_wh_per_w,
        battery_kg_per_w=battery_wh_per_w / platform.battery_wh_per_kg,
        array_m2_per_w=array_m2_per_w,
        array_kg_per_w=array_m2_per_w * platform.array_kg_per_m2,
        radiator_m2_per_w=radiator_m2_per_w,
        radiator_kg_per_w=radiator_m2_per_w * platform.radiator_kg_per_m2,
    )


# ---------------------------------------------------------------------------
# Sizing a spacecraft around one accelerator
# ---------------------------------------------------------------------------


def size_always_on(
    accel: Accelerator,
    cost: OrbitCost,
    platform: Optional[Platform] = None,
    housekeeping_w: Optional[float] = None,
) -> dict:
    """Size the EPS and radiator to run `accel` continuously, eclipse included.

    Housekeeping is carried at the same continuous cost, because the bus does
    not switch off in eclipse either -- so the answer scales with total load,
    not payload load.
    """
    platform = platform or Platform()
    hk = platform.eps.housekeeping_w if housekeeping_w is None else housekeeping_w
    payload_w = accel.system_w
    load_w = payload_w + hk

    battery_wh = load_w * cost.battery_wh_per_w
    array_m2 = load_w * cost.array_m2_per_w
    radiator_m2 = load_w * cost.radiator_m2_per_w
    mass = {
        "battery_kg": load_w * cost.battery_kg_per_w,
        "array_kg": load_w * cost.array_kg_per_w,
        "radiator_kg": load_w * cost.radiator_kg_per_w,
    }
    subsystem_kg = sum(mass.values())

    return {
        "accelerator": accel.key,
        "name": accel.name,
        "class": accel.class_,
        "board_w": accel.board_w,
        "system_w": payload_w,
        "housekeeping_w": hk,
        "load_w": load_w,
        "battery_wh": battery_wh,
        "battery_cells_equiv": battery_wh / 600.0,      # in units of the reference pack
        "array_m2": array_m2,
        "array_peak_w": array_m2 * platform.array_w_per_m2_peak,
        "radiator_m2": radiator_m2,
        **mass,
        "eps_thermal_kg": subsystem_kg,
        "eps_thermal_w_per_kg": load_w / subsystem_kg if subsystem_kg else float("inf"),
        "throughput": accel.throughput,
        "throughput_unit": accel.throughput_unit,
        "throughput_per_system_w": accel.efficiency,
        "throughput_per_eps_kg": accel.throughput / subsystem_kg if subsystem_kg else float("inf"),
        "flown": accel.flown,
    }


def duty_cycled_alternative(
    accel: Accelerator,
    cost: OrbitCost,
    sustainable_payload_w: float,
    optimal_payload_w: float,
) -> dict:
    """What the same part delivers if it is *not* required to run through eclipse.

    The comparison the always-on question actually turns on.  A part that draws
    more than the orbit can sustain continuously is not thereby excluded -- it
    runs at a duty cycle.  The two policies below are the bounds already
    established in :mod:`solarsim.schedule`: a constant draw that must survive
    the worst moment of every orbit, and the offline optimum that spends
    generation as it arrives.

    Duty cycle here is the fraction of wall-clock time the part can run *at its
    nominal operating point*, which is the honest figure for a load that is
    much cheaper to gate than to throttle continuously.
    """
    p = accel.system_w
    return {
        "accelerator": accel.key,
        "system_w": p,
        "always_on_possible_on_reference_bus": bool(p <= sustainable_payload_w),
        "duty_constant_bound": min(1.0, sustainable_payload_w / p),
        "duty_optimal": min(1.0, optimal_payload_w / p),
        "throughput_fraction_constant": min(1.0, sustainable_payload_w / p),
        "throughput_fraction_optimal": min(1.0, optimal_payload_w / p),
        "scheduling_gain_pct": 100.0 * (optimal_payload_w / sustainable_payload_w - 1.0),
    }


def sensitivity(
    accel: Accelerator,
    summary: dict,
    array_model: str,
    base: Optional[Platform] = None,
) -> dict:
    """How far the mass answer moves across the plausible coefficient ranges.

    Reported as the span of ``eps_thermal_kg``, so a reader can see immediately
    whether a conclusion survives the assumptions or depends on them.
    """
    base = base or Platform()
    # The radiator *class* (body-mounted vs deployable liquid) is a design
    # choice, not an uncertainty, and the two differ by more than 5x -- so it is
    # reported separately rather than swept.  Within a class the spread is about
    # +-40 %, which is what the relative bounds below express.
    sweeps = {
        "battery_wh_per_kg": (90.0, 160.0),
        "array_w_per_kg": (60.0, 150.0),
        "radiator_w_per_m2": (0.6 * base.radiator_w_per_m2,
                              1.4 * base.radiator_w_per_m2),
        "radiator_kg_per_m2": (0.75 * base.radiator_kg_per_m2,
                               1.5 * base.radiator_kg_per_m2),
    }
    nominal = size_always_on(accel, marginal_cost(summary, array_model, base), base)
    out = {"nominal_kg": nominal["eps_thermal_kg"], "spans": {}}
    for name, (lo, hi) in sweeps.items():
        vals = []
        for v in (lo, hi):
            p = Platform(**{**{k: getattr(base, k) for k in sweeps}, name: v, "eps": base.eps})
            vals.append(size_always_on(accel, marginal_cost(summary, array_model, p), p)["eps_thermal_kg"])
        out["spans"][name] = {"low": min(vals), "high": max(vals), "range": (lo, hi)}
    # Worst and best corner of all four together.
    corners = []
    for bw in sweeps["battery_wh_per_kg"]:
        for aw in sweeps["array_w_per_kg"]:
            for rw in sweeps["radiator_w_per_m2"]:
                for rk in sweeps["radiator_kg_per_m2"]:
                    p = Platform(bw, aw, rw, rk, base.eps)
                    corners.append(
                        size_always_on(accel, marginal_cost(summary, array_model, p), p)["eps_thermal_kg"]
                    )
    out["best_case_kg"] = min(corners)
    out["worst_case_kg"] = max(corners)
    return out


# ---------------------------------------------------------------------------
# The lever that actually decides always-on: depth of discharge
# ---------------------------------------------------------------------------

#: Representative cycle life of space-qualified LEO Li-ion against depth of
#: discharge, to 80 % of beginning-of-life capacity.  Cycle life falls far
#: faster than linearly in DoD, which is why LEO missions design to 20-30 %
#: while GEO missions -- two eclipse seasons a year instead of 5500 cycles --
#: routinely design to 70-80 %.  Figures are order-of-magnitude design values
#: from the smallsat battery literature, not a qualification dataset.
CYCLE_LIFE_VS_DOD = {
    0.10: 100_000,
    0.20: 60_000,
    0.30: 30_000,
    0.40: 18_000,
    0.50: 10_000,
    0.60: 6_000,
    0.80: 2_000,
}


def battery_dod_tradeoff(
    load_w: float,
    summary: dict,
    platform: Optional[Platform] = None,
    dods=tuple(sorted(CYCLE_LIFE_VS_DOD)),
) -> list:
    """Battery mass against mission life for an always-on load.

    Always-on means one discharge cycle *per orbit* -- roughly 5500 a year in
    LEO -- so the battery is the one subsystem for which "run through eclipse"
    is not merely a mass penalty but a wear-out mechanism.  Battery mass scales
    as ``1/DoD`` while cycle life collapses much faster, so there is a genuine
    optimum rather than a monotone trade, and it is what decides whether a
    continuously-running payload is a five-year mission or a one-year one.
    """
    platform = platform or Platform()
    period_min = float(summary["nodal_period_min"])
    ecl_max_min = float(summary["eclipse_max_min"])
    ecl_mean_min = float(summary["eclipse_mean_min"])
    eta_d = platform.eps.discharge_efficiency

    # Only revolutions with an eclipse cycle the battery.  The mean eclipse
    # over all revolutions divided by the mean over eclipsed ones recovers that
    # fraction without needing the full time series.
    eclipsed = float(summary.get("eclipse_mean_over_eclipsed_min") or ecl_mean_min)
    duty = ecl_mean_min / eclipsed if eclipsed > 0 else 0.0
    cycles_per_year = 365.25 * 24 * 60 / period_min * duty

    rows = []
    for dod in dods:
        wh = load_w * (ecl_max_min / 60.0) / (eta_d * dod)
        life = CYCLE_LIFE_VS_DOD[dod]
        rows.append({
            "dod": dod,
            "battery_wh": wh,
            "battery_kg": wh / platform.battery_wh_per_kg,
            "cycles_per_year": cycles_per_year,
            "cycle_life": life,
            "years_to_eol": life / cycles_per_year if cycles_per_year else float("inf"),
        })
    return rows


# ---------------------------------------------------------------------------
# External calibration: what industry actually builds
# ---------------------------------------------------------------------------

#: Published or company-stated figures for real orbital-compute hardware, used
#: to calibrate the platform coefficients above rather than to validate the
#: simulation.  These are *claims from product announcements and regulatory
#: filings*, not measured flight telemetry, and are labelled as such.  They are
#: the only external anchor available: neither SpaceX nor Google publishes
#: array power for an operational satellite.
EXTERNAL_REFERENCES = {
    "spacex_ai1": {
        "label": "SpaceX AI1 orbital compute satellite (announced 2026)",
        "kind": "company claim, product unveiling",
        "array_power_kw": 150.0,
        "array_w_per_m2": 250.0,          # stated areal density
        "array_area_m2": 600.0,           # implied, 150 kW / 250 W/m^2
        "radiator_area_m2": 110.0,
        "radiator_w_per_m2": 1400.0,      # stated; double-sided, knife-edge to sun
        "compute_mean_kw": 120.0,
        "compute_peak_kw": 150.0,
        "specific_power_w_per_kg": 70.0,  # stated as 70 kW per tonne, whole spacecraft
        "wingspan_m": 70.0,
        "note": (
            "The radiator's stated capacity, 110 m^2 x 1400 W/m^2 = 154 kW, is "
            "sized to the full 150 kW array -- an independent confirmation that "
            "in vacuum the radiator is sized by the same number as the array."
        ),
    },
    "starlink_v2_mini": {
        "label": "Starlink V2 Mini (operational)",
        "kind": "array area published; power NOT published",
        "array_area_m2": 104.96,          # two wings of 52.48 m^2
        "array_power_kw": None,
        "note": (
            "At SpaceX's own stated 250 W/m^2 the array would produce about "
            "26 kW peak.  That is an inference from two SpaceX numbers, not a "
            "published figure, and is quoted as such."
        ),
    },
}


#: Radiator options.  The default elsewhere in this module is the conservative
#: body-mounted panel; a purpose-built orbital-compute satellite does far
#: better, and the difference is large enough to change conclusions.
RADIATORS = {
    "body_mounted": {
        "w_per_m2": 250.0, "kg_per_m2": 4.0,
        "note": "Single-sided panel on the bus, ~40 C, LEO sink. Conservative.",
    },
    "deployable_liquid": {
        "w_per_m2": 1400.0, "kg_per_m2": 6.0,
        "note": (
            "Pumped-loop deployable, radiating from both faces, held knife-edge "
            "to the Sun. Calibrated to the AI1 figure; 1400 W/m^2 is 700 per "
            "face, which is a 69 C surface at eps = 0.9 -- entirely physical."
        ),
    },
}


#: Array technology.  ``research_grade`` is this study's default: a 30 %
#: triple-junction GaAs array of the kind flown on science and Earth-observation
#: missions.  ``commercial_megaconstellation`` is back-solved from SpaceX's
#: stated 250 W/m^2, which implies a ~22 % cell -- optimised for cost per watt
#: and production rate rather than watts per square metre.  Which one a paper
#: should assume depends entirely on who is imagined to be building the
#: satellite, and the two differ by 16 % in absolute power.
PANEL_TECH = {
    "research_grade": {
        "cell_efficiency": 0.30, "packing_factor": 0.90,
        "note": "Triple-junction GaAs, e.g. Spectrolab XTJ / Azur 3G30.",
    },
    "commercial_megaconstellation": {
        "cell_efficiency": 0.22, "packing_factor": 0.90,
        "note": "Back-solved from SpaceX's stated 250 W/m^2 BOL areal density.",
    },
}


def make_platform(
    panel: str = "research_grade",
    radiator: str = "body_mounted",
    battery_wh_per_kg: float = 130.0,
    array_w_per_kg: float = 100.0,
    **eps_overrides,
) -> Platform:
    """Build a :class:`Platform` from named technology choices."""
    p = PANEL_TECH[panel]
    r = RADIATORS[radiator]
    eps = PowerSystem(
        cell_efficiency=p["cell_efficiency"],
        packing_factor=p["packing_factor"],
        **eps_overrides,
    )
    return Platform(
        battery_wh_per_kg=battery_wh_per_kg,
        array_w_per_kg=array_w_per_kg,
        radiator_w_per_m2=r["w_per_m2"],
        radiator_kg_per_m2=r["kg_per_m2"],
        eps=eps,
    )


def check_against_reference(platform: Optional[Platform] = None) -> dict:
    """Compare this model's generation chain with the AI1 published figures.

    This is a *calibration* check, not a validation of the simulation: it tests
    the engineering coefficients, which are assumptions, against what a company
    says it is building.  A large disagreement means the assumptions describe a
    different class of spacecraft, not that the orbital mechanics are wrong.
    """
    platform = platform or Platform()
    ref = EXTERNAL_REFERENCES["spacex_ai1"]
    eps = platform.eps

    model_bol = (
        SOLAR_CONSTANT * eps.cell_efficiency * eps.packing_factor * eps.ppt_efficiency
    )
    model_eol = model_bol * eps.degradation_bol_eol
    return {
        "reference": ref["label"],
        "kind": ref["kind"],
        "array": {
            "reference_w_per_m2": ref["array_w_per_m2"],
            "model_bol_w_per_m2": model_bol,
            "model_eol_w_per_m2": model_eol,
            "ratio_bol": model_bol / ref["array_w_per_m2"],
            "implied_cell_efficiency": ref["array_w_per_m2"]
            / (SOLAR_CONSTANT * eps.packing_factor * eps.ppt_efficiency),
        },
        "radiator": {
            "reference_w_per_m2": ref["radiator_w_per_m2"],
            "model_w_per_m2": platform.radiator_w_per_m2,
            "ratio": platform.radiator_w_per_m2 / ref["radiator_w_per_m2"],
            "reference_capacity_kw": ref["radiator_area_m2"]
            * ref["radiator_w_per_m2"] / 1e3,
            "reference_array_kw": ref["array_power_kw"],
            "capacity_over_array": (
                ref["radiator_area_m2"] * ref["radiator_w_per_m2"] / 1e3
                / ref["array_power_kw"]
            ),
        },
        "specific_power": {
            "reference_w_per_kg": ref["specific_power_w_per_kg"],
            "note": (
                "The remaining gap after array and radiator technology are "
                "matched sits in specific mass: this model uses 100 W/kg for "
                "the array and 130 Wh/kg for the battery, which are the "
                "literature figures for conventional deployable hardware. A "
                "claim of 70 W/kg for a whole spacecraft requires an array "
                "several times lighter per watt than that. The gap is left "
                "open rather than tuned away -- it is the difference between "
                "what is documented and what is announced."
            ),
        },
        "note": ref["note"],
    }


# ---------------------------------------------------------------------------
# Where the uncertainty actually lives
# ---------------------------------------------------------------------------

#: Term-by-term uncertainty in ``P_gen = nu . S . A . eta_cell . f_pack .
#: f_deg . eta_ppt . kappa``.  Each entry is (nominal, low, high, status,
#: source).  ``status`` is the honest label: *measured* for a physical constant,
#: *validated* for something this package reproduces against a closed form or an
#: almanac, *modelled* for something computed from a stated physical model, and
#: *assumed* for an engineering coefficient taken from the literature.
GENERATION_BUDGET = {
    "solar_constant": (
        1.0, 0.9996, 1.0004, "measured",
        "1361 +- 0.5 W/m^2 total solar irradiance, Kopp & Lean (2011), TIM/SORCE.",
    ),
    "sun_distance": (
        1.0, 0.9668, 1.0344, "modelled",
        "+-3.3 % annual 1/r^2 modulation; ephemeris validated against almanac "
        "perihelion and aphelion distances. Not an error -- a real seasonal signal.",
    ),
    "occultation_nu": (
        1.0, 1.0, 1.0, "validated",
        "Reproduces the closed-form cylindrical eclipse fraction to ~1e-16 under "
        "its own assumptions; durations are grid-free by bisection.",
    ),
    "pointing_kappa": (
        1.0, 0.99, 1.0, "modelled",
        "Exact given the attitude model. The band allows for real pointing error "
        "and drive backlash, which the kinematics do not represent.",
    ),
    "cell_efficiency": (
        0.30, 0.22, 0.32, "assumed",
        "Technology choice, not measurement error: 30-32 % for triple-junction "
        "GaAs, ~22 % implied by SpaceX's stated 250 W/m^2 areal density.",
    ),
    "packing_factor": (
        0.90, 0.85, 0.93, "assumed",
        "Cell area over substrate area; depends on cell geometry and layout.",
    ),
    "degradation": (
        0.85, 0.75, 0.92, "assumed",
        "End-of-life radiation and UV. 0.85 is conservative for a 5-year mission "
        "at 550 km, where the radiation environment is benign compared with the "
        "belts; it would be right for a longer mission or a higher altitude.",
    ),
    "ppt_efficiency": (
        0.93, 0.90, 0.96, "assumed",
        "MPPT and PCDU conversion.",
    ),
    "temperature": (
        1.0, 0.927, 0.970, "modelled",
        "Array temperature from the lumped radiative balance in solarsim.thermal, "
        "with the cell's linear coefficient. Costs 3.0-7.3 % of annual harvested "
        "energy across the swept optics range; off by default.",
    ),
}


def generation_uncertainty() -> dict:
    """Decompose the generation uncertainty, and show what it does *not* touch.

    The point of this function is the last field it returns.  Every uncertain
    term in the chain is a *constant multiplicative factor* on power: none of
    them depends on time, orbit, beta angle, plane or schedule.  So they cancel
    exactly out of every ratio the study reports -- duty cycles, the LTAN
    comparison, plane-to-plane spread, scheduling headroom, the relative cost of
    an always-on watt between orbits.  They move only absolute watts, and they
    move them by exactly the factor you got wrong.

    That is why the study's conclusions are quoted as ratios.  A reader who
    disagrees with the 30 % cell can scale every absolute number in one
    multiplication and change no conclusion.
    """
    lo = hi = 1.0
    rows = []
    for name, (nom, low, high, status, src) in GENERATION_BUDGET.items():
        rel_lo, rel_hi = low / nom, high / nom
        if status == "assumed":
            lo *= rel_lo
            hi *= rel_hi
        rows.append({
            "term": name, "nominal": nom, "low": low, "high": high,
            "relative_low": rel_lo, "relative_high": rel_hi,
            "status": status, "source": src,
        })
    return {
        "terms": rows,
        "assumed_multiplier_low": lo,
        "assumed_multiplier_high": hi,
        "assumed_span_pct": 100.0 * (hi - lo),
        "geometry_status": (
            "validated to ~1e-16 against the closed form; grid-independent"
        ),
        "invariant_under_this_uncertainty": [
            "eclipse and sunlit durations",
            "duty cycle and eclipse fraction",
            "LTAN and altitude comparisons (ratios of harvested energy)",
            "plane-to-plane spread in a constellation",
            "scheduling headroom (LP optimum over constant-draw bound)",
            "relative cost of an always-on watt between orbits",
            "battery cycles per year and the depth-of-discharge trade",
        ],
        "scales_linearly_with_this_uncertainty": [
            "absolute generated power in W",
            "absolute harvested energy in Wh",
            "required array area for a given load",
            "sustainable payload power in W",
        ],
    }
