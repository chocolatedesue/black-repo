"""Score a set of scheduling policies against the bounds.

A worked example of :mod:`solarsim.evaluate`, and the starting point for
evaluating a new policy: add it to ``POLICIES`` and rerun.

    python -m experiments.eval_policies                 # default: 10 orbits
    python -m experiments.eval_policies --orbits 30     # longer horizon
    python -m experiments.eval_policies --case leo_53

The default horizon is ten orbits rather than three on purpose.  A policy that
quietly runs its battery down needs several orbits before the depth-of-discharge
floor catches it, so a short horizon flatters exactly the policies that would
fail in flight -- see the ``sunlight only`` row, which looks best at three
orbits and breaches the floor by ten.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solarsim.constants import DEG, R_EARTH
from solarsim.evaluate import (
    bank_then_spend_policy,
    constant_policy,
    deadline_policy,
    evaluate,
    format_table,
    sunlight_only_policy,
)
from solarsim.orbit import CircularOrbit, raan_from_ltan, sso_inclination
from solarsim.power import PowerSystem
from solarsim.schedule import power_trace, sustainable_power
from solarsim.timeutil import datetime_to_jd

RESULTS = Path(__file__).resolve().parents[1] / "results"
EPOCH = dt.datetime(2024, 1, 1)
JD0 = datetime_to_jd(EPOCH)

CASES = {
    "sso_1030": (
        "SSO 550 km, LTAN 10:30", "single_axis_pitch",
        lambda: CircularOrbit(550.0, sso_inclination(R_EARTH + 550.0),
                              raan_from_ltan(JD0, 10.5), 0.0, JD0),
    ),
    "sso_dawn_dusk": (
        "SSO 550 km, LTAN 06:00", "single_axis_yaw",
        lambda: CircularOrbit(550.0, sso_inclination(R_EARTH + 550.0),
                              raan_from_ltan(JD0, 6.0), 0.0, JD0),
    ),
    "leo_53": (
        "LEO 550 km, i = 53 deg", "single_axis_pitch",
        lambda: CircularOrbit(550.0, 53.0 * DEG, 0.0, 0.0, JD0),
    ),
}


def build_policies(baseline_w: float) -> dict:
    """The reference set every new policy should be compared against.

    ``bank then spend`` is the one to beat: it is causal, has no parameters, and
    lands within a fraction of a percent of the offline LP optimum when every
    task is worth the same.  Beating the constant baseline is not evidence of
    anything; closing the gap on ``bank then spend`` under a workload with real
    deadlines is.
    """
    return {
        "constant (baseline)": constant_policy(baseline_w),
        "constant (30 % over)": constant_policy(baseline_w * 1.3),
        "sunlight only": sunlight_only_policy(),
        "bank then spend": bank_then_spend_policy(),
        "deadline floor 120 W": deadline_policy(120.0),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", default="sso_1030", choices=sorted(CASES))
    ap.add_argument("--orbits", type=float, default=10.0)
    ap.add_argument("--slot", type=float, default=10.0, help="slot length in seconds")
    ap.add_argument("--json", action="store_true", help="also write results/policy_eval.json")
    args = ap.parse_args(argv)

    title, array_model, make_orbit = CASES[args.case]
    trace = power_trace(
        make_orbit(),
        PowerSystem(array_model=array_model),
        n_orbits=args.orbits,
        dt_s=args.slot,
        label=title,
    )
    baseline = sustainable_power(trace)["sustainable_payload_w"]
    report = evaluate(trace, build_policies(baseline))

    print(f"{title}  [{array_model}]  "
          f"{args.orbits:g} orbits, {args.slot:g} s slots, {trace.t_s.size} of them\n")
    print(format_table(report))

    if args.json:
        path = RESULTS / "policy_eval.json"
        path.write_text(json.dumps(report, indent=2, default=float))
        print(f"\nwrote {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
