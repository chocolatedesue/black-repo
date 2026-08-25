"""E9 -- matching compute accelerators to the orbital energy budget.

Answers, for every part in :data:`solarsim.hardware.ACCELERATORS` and every
reference orbit: what does it cost to run this continuously, eclipse included,
and what happens instead if it is allowed to duty-cycle?

    python -m experiments.gpu_match                    # table + results/e9_accelerators.json
    python -m experiments.gpu_match --orbit sso_dawn_dusk
    python -m experiments.gpu_match --bus-kg 60        # what fits in a given mass budget

Reads ``results/e1_reference.json`` and ``results/scheduling.json``; runs no
simulation of its own, so it is fast and cannot disagree with the study.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solarsim.hardware import (
    ACCELERATORS,
    ACCELERATOR_BY_KEY,
    battery_dod_tradeoff,
    Platform,
    duty_cycled_alternative,
    marginal_cost,
    sensitivity,
    size_always_on,
)

RESULTS = Path(__file__).resolve().parents[1] / "results"

#: Orbit -> the array drive that orbit would actually fly.  A pitch-axis drive
#: collapses at dawn-dusk (2.9 W/m^2 in the worst revolution), so pairing every
#: orbit with the same drive would produce a meaningless comparison.
ARRAY_FOR_ORBIT = {
    "sso_1030": "single_axis_pitch",
    "sso_dawn_dusk": "single_axis_yaw",
    "leo_53": "single_axis_pitch",
    "leo_iss": "single_axis_pitch",
}


def build(platform: Platform) -> dict:
    e1 = json.loads((RESULTS / "e1_reference.json").read_text())
    sched = json.loads((RESULTS / "scheduling.json").read_text())

    out = {
        "platform": {
            "battery_wh_per_kg": platform.battery_wh_per_kg,
            "array_w_per_kg": platform.array_w_per_kg,
            "array_w_per_m2_peak": platform.array_w_per_m2_peak,
            "array_kg_per_m2": platform.array_kg_per_m2,
            "radiator_w_per_m2": platform.radiator_w_per_m2,
            "radiator_kg_per_m2": platform.radiator_kg_per_m2,
            "housekeeping_w": platform.eps.housekeeping_w,
            "dod_limit": platform.eps.dod_limit,
        },
        "accelerators": [
            {
                "key": a.key, "name": a.name, "vendor": a.vendor, "class": a.class_,
                "board_w": a.board_w, "system_factor": a.system_factor,
                "system_w": a.system_w, "throughput": a.throughput,
                "throughput_unit": a.throughput_unit, "note": a.note, "flown": a.flown,
            }
            for a in ACCELERATORS
        ],
        "orbits": {},
    }

    for key, array_model in ARRAY_FOR_ORBIT.items():
        summary = e1["cases"][key]["summary"]
        cost = marginal_cost(summary, array_model, platform)
        entry = {
            "label": summary["label"],
            "array_model": array_model,
            "cost_per_always_on_watt": cost.to_dict(),
            # The array drive is sized by the *worst* revolution of the year, so
            # the choice moves the array term by more than a factor of two on an
            # inclined orbit.  Recorded for every drive rather than asserted.
            "cost_by_array_model": {
                m: marginal_cost(summary, m, platform).to_dict()
                for m in summary["array_yield"]
            },
            "parts": {},
        }
        sc = sched["cases"].get(key)
        if sc is not None:
            entry["reference_bus"] = {
                "array_m2": platform.eps.array_area_m2,
                "battery_wh": sc["battery_wh"],
                "sustainable_payload_w": sc["sustainable"]["sustainable_payload_w"],
                "optimal_payload_w": sc["optimal"]["mean_payload_w"],
            }
        for a in ACCELERATORS:
            rec = size_always_on(a, cost, platform)
            if sc is not None:
                rec["duty_cycled"] = duty_cycled_alternative(
                    a, cost,
                    sc["sustainable"]["sustainable_payload_w"],
                    sc["optimal"]["mean_payload_w"],
                )
            entry["parts"][a.key] = rec
        # The DoD trade is reported for one representative always-on load; it
        # is linear in load, so the years-to-EOL column is load-independent.
        entry["dod_tradeoff_h100_sxm"] = battery_dod_tradeoff(
            ACCELERATOR_BY_KEY["h100_sxm"].system_w + platform.eps.housekeeping_w,
            summary, platform,
        )
        out["orbits"][key] = entry

    # Sensitivity is reported for one part in one orbit; the coefficients are
    # linear in load, so the relative span is identical for every other row.
    out["sensitivity_h100_sxm_sso_1030"] = sensitivity(
        ACCELERATOR_BY_KEY["h100_sxm"], e1["cases"]["sso_1030"]["summary"],
        "single_axis_pitch", platform,
    )
    return out



def print_table(data: dict, orbit: str) -> None:
    o = data["orbits"][orbit]
    c = o["cost_per_always_on_watt"]
    ref = o.get("reference_bus", {})

    print(f"{o['label']}   array: {o['array_model']}")
    print(f"  worst eclipse {c['eclipse_max_min']:.1f} min of a "
          f"{c['nodal_period_min']:.1f} min orbit "
          f"(mean {c['eclipse_mean_min']:.1f} min)")
    print(f"  one always-on watt costs "
          f"{c['battery_wh_per_w']:.2f} Wh battery + "
          f"{c['array_m2_per_w']*1e3:.2f} dm2 array + "
          f"{c['radiator_m2_per_w']*1e3:.2f} dm2 radiator "
          f"= {c['total_kg_per_w']*1e3:.0f} g/W  ({c['w_per_kg']:.1f} W/kg)")
    by_model = o["cost_by_array_model"]
    cheapest = min(by_model, key=lambda m: by_model[m]["total_kg_per_w"])
    if cheapest != o["array_model"]:
        print(f"  ({cheapest} would cost "
              f"{by_model[cheapest]['total_kg_per_w']*1e3:.0f} g/W instead)")
    if ref:
        print(f"  reference 2 m2 / 600 Wh bus sustains "
              f"{ref['sustainable_payload_w']:.0f} W constant, "
              f"{ref['optimal_payload_w']:.0f} W scheduled\n")

    print("  sized for always-on            |  on the reference bus instead")
    head = (f"{'part':26s} {'sysW':>5s} {'battWh':>7s} {'array':>6s} {'rad':>6s} "
            f"{'EPSkg':>6s} | {'always-on':>9s} {'duty':>5s}")
    print(head)
    print("-" * len(head))
    for a in data["accelerators"]:
        rec = o["parts"][a["key"]]
        d = rec.get("duty_cycled", {})
        on = ("n/a" if not d
              else "yes" if d["always_on_possible_on_reference_bus"] else "no")
        duty = f"{100*d['duty_optimal']:.0f}%" if d else "--"
        print(f"{a['name']:26.26s} {rec['system_w']:5.0f} {rec['battery_wh']:7.0f} "
              f"{rec['array_m2']:4.1f}m2 {rec['radiator_m2']:4.1f}m2 "
              f"{rec['eps_thermal_kg']:5.1f}kg | {on:>9s} {duty:>5s}")


def print_dod(data: dict, orbit: str) -> None:
    o = data["orbits"][orbit]
    rows = o["dod_tradeoff_h100_sxm"]
    print(f"\n  battery trade for a {rows[0]['battery_wh']*rows[0]['dod']*0.97/(o['cost_per_always_on_watt']['eclipse_max_min']/60):.0f} W "
          f"always-on load  ({rows[0]['cycles_per_year']:.0f} discharge cycles/year):")
    print(f"    {'DoD':>5s} {'Wh':>6s} {'kg':>6s} {'cycle life':>10s} {'years':>6s}")
    for r in rows:
        print(f"    {r['dod']:5.0%} {r['battery_wh']:6.0f} {r['battery_kg']:6.1f} "
              f"{r['cycle_life']:10,d} {r['years_to_eol']:6.1f}")


def print_budget(data: dict, orbit: str, bus_kg: float) -> None:
    """Largest always-on part that fits a given array+battery+radiator budget."""
    o = data["orbits"][orbit]
    c = o["cost_per_always_on_watt"]
    hk = data["platform"]["housekeeping_w"]
    load_w = bus_kg / c["total_kg_per_w"]
    payload_w = load_w - hk
    print(f"\n{bus_kg:.0f} kg of array + battery + radiator in {o['label']} "
          f"supports {load_w:.0f} W of load, i.e. {payload_w:.0f} W of payload.")
    fits = [a for a in data["accelerators"] if a["system_w"] <= payload_w]
    if not fits:
        print("  -> not enough for any part in the catalogue, continuously.")
        return
    best = max(fits, key=lambda a: a["system_w"])
    print(f"  -> largest always-on part: {best['name']} "
          f"({best['board_w']:.0f} W board, {best['system_w']:.0f} W system)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--orbit", default="sso_1030", choices=sorted(ARRAY_FOR_ORBIT))
    ap.add_argument("--all", action="store_true", help="print every orbit")
    ap.add_argument("--bus-kg", type=float, default=None)
    ap.add_argument("--dod", action="store_true",
                    help="battery mass vs cycle life for an always-on load")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    data = build(Platform())
    orbits = sorted(ARRAY_FOR_ORBIT) if args.all else [args.orbit]
    for i, k in enumerate(orbits):
        if i:
            print()
        print_table(data, k)
        if args.dod:
            print_dod(data, k)
        if args.bus_kg is not None:
            print_budget(data, k, args.bus_kg)

    s = data["sensitivity_h100_sxm_sso_1030"]
    print(f"\nsensitivity (H100 SXM, SSO 10:30): nominal {s['nominal_kg']:.0f} kg, "
          f"range {s['best_case_kg']:.0f}-{s['worst_case_kg']:.0f} kg "
          f"across the full coefficient span.")

    if not args.no_write:
        path = RESULTS / "e9_accelerators.json"
        path.write_text(json.dumps(data, indent=1, default=float))
        print(f"wrote {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
