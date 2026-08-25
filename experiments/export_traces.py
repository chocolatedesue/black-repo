"""Export energy-availability traces and scheduling bounds.

Produces, for each reference orbit, the three things an energy-aware compute
scheduler needs:

  results/trace_<case>.csv   per-slot generated power and payload surplus
  results/scheduling.json    sustainable-power and burst bounds, plus the
                             workload translation

    python -m experiments.export_traces
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solarsim.constants import DEG, R_EARTH
from solarsim.orbit import CircularOrbit, raan_from_ltan, sso_inclination
from solarsim.power import PowerSystem
from solarsim.schedule import (
    burst_envelope,
    compute_yield,
    optimal_schedule,
    power_trace,
    sustainable_power,
)
from solarsim.timeutil import datetime_to_jd

RESULTS = Path(__file__).resolve().parents[1] / "results"
RESULTS.mkdir(exist_ok=True)

EPOCH = dt.datetime(2024, 1, 1)
JD0 = datetime_to_jd(EPOCH)

# Energy cost of one unit of work.  PLACEHOLDER -- replace with a measurement
# on the target accelerator; the model cannot supply this number.
JOULES_PER_INFERENCE = 2.5

CASES = [
    ("sso_1030", "SSO 550 km, LTAN 10:30",
     CircularOrbit(550.0, sso_inclination(R_EARTH + 550.0),
                   raan_from_ltan(JD0, 10.5), 0.0, JD0)),
    ("sso_dawn_dusk", "SSO 550 km, LTAN 06:00",
     CircularOrbit(550.0, sso_inclination(R_EARTH + 550.0),
                   raan_from_ltan(JD0, 6.0), 0.0, JD0)),
    ("leo_53", "LEO 550 km, i = 53 deg",
     CircularOrbit(550.0, 53.0 * DEG, 0.0, 0.0, JD0)),
]

# The pitch-axis drive is the common LEO baseline; the dawn-dusk orbit is also
# reported with a yaw-axis drive, which is what such a platform would fly.
ARRAY_BY_CASE = {
    "sso_1030": "single_axis_pitch",
    "sso_dawn_dusk": "single_axis_yaw",
    "leo_53": "single_axis_pitch",
}


def main() -> int:
    out = {
        "epoch": EPOCH.isoformat(),
        "joules_per_inference_placeholder": JOULES_PER_INFERENCE,
        "cases": {},
    }
    for key, title, orbit in CASES:
        system = PowerSystem(array_model=ARRAY_BY_CASE[key])
        trace = power_trace(orbit, system, n_orbits=3.0, dt_s=10.0, label=title)

        csv_path = RESULTS / f"trace_{key}.csv"
        trace.to_csv(csv_path)

        sus = sustainable_power(trace)
        multiples = [1.1, 1.2, 1.35, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0]
        levels = [sus["sustainable_payload_w"] * m for m in multiples]
        burst = burst_envelope(trace, levels)
        opt = optimal_schedule(trace)
        yield_const = compute_yield(
            sus["sustainable_payload_w"], JOULES_PER_INFERENCE, trace.nodal_period_s)
        yield_opt = compute_yield(
            opt["mean_payload_w"], JOULES_PER_INFERENCE, trace.nodal_period_s)

        out["cases"][key] = {
            "title": title,
            "array_model": system.array_model,
            "trace_csv": csv_path.name,
            "trace_summary": trace.summary(),
            "sustainable": sus,
            "burst": burst,
            "optimal": {k: v for k, v in opt.items() if k != "payload_w"},
            "optimal_payload_w": [round(float(x), 3) for x in opt["payload_w"]],
            "compute_yield_constant": yield_const,
            "compute_yield_optimal": yield_opt,
            "battery_wh": system.battery_capacity_wh,
            "dod_limit": system.dod_limit,
            "housekeeping_w": system.housekeeping_w,
            "nodal_period_min": trace.nodal_period_s / 60.0,
        }

        print(
            f"{title:28s} [{system.array_model:17s}]  "
            f"P_gen_mean {sus.get('p_gen_mean_w', 0):6.1f} W  "
            f"constant {sus['sustainable_payload_w']:6.1f} W  "
            f"-> LP optimum {opt['mean_payload_w']:6.1f} W  "
            f"({opt['headroom_pct']:+.1f} %)  [naive {sus.get('naive_estimate_w', 0):6.1f} W]"
        )
        for b in burst[::3]:
            d = b["max_duration_s"]
            print(f"      burst {b['payload_w']:6.1f} W -> "
                  f"{'unlimited' if d == float('inf') else f'{d/60:6.1f} min'}")

    path = RESULTS / "scheduling.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"\nwrote {path.name} and {len(CASES)} trace CSVs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
