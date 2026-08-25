---
name: evaluate
description: Score an energy-aware compute scheduling policy in this solarsim repository against the constant-power baseline and the offline LP optimum, with a feasibility check the policy cannot fudge. Use this whenever someone wants to test, benchmark, compare or measure a scheduling policy, algorithm or heuristic; asks how much energy or throughput a schedule achieves; wants baselines for a paper's evaluation section; or asks "is my policy any good" / "how close to optimal is this". Also use it when they describe a scheduling idea and want to know whether it is worth implementing — the bounds answer that before any code is written.
---

# Evaluating a scheduling policy

`solarsim.evaluate` exists so that a policy comparison is honest by
construction. Three things it enforces, each of which is easy to get wrong by
hand:

1. **The feasibility check is not the policy's own.** Every policy is replayed
   through the same battery simulation. A depth-of-discharge breach is reported,
   never clipped away, so a policy cannot look good by quietly overdrawing.
2. **Baselines are computed, not guessed.** The constant-power baseline is the
   largest fixed draw that survives the orbit, solved by bisection on the state
   of charge.
3. **The headline number is the optimality gap.** Beating a weak baseline proves
   little. The reference LP is the true ceiling for a given objective, so report
   how close a policy gets to it.

## Running it

```bash
python -m experiments.eval_policies                  # 10 orbits, SSO 10:30
python -m experiments.eval_policies --orbits 30      # longer horizon
python -m experiments.eval_policies --case leo_53 --json
```

To score a new policy, add it to `build_policies()` in
`experiments/eval_policies.py` and rerun. A policy is any callable
`policy(k, ctx) -> payload watts`, where `ctx` carries what an online scheduler
could legitimately know at slot `k`: the trace, the current state of charge, and
the platform parameters. Reading `ctx.trace.p_gen_w[k+1:]` makes it clairvoyant
— sometimes that is the point, but say so, because it is no longer comparable
to a causal policy.

## Reading the output

| Column | Means |
|---|---|
| `mean P` | Raw mean payload power over the horizon |
| `steady (W)` | The same, after debiting any net battery drawdown. This is the comparable figure |
| `vs base` | Against the constant-power baseline |
| `gap to LP` | Against the offline optimum. Only shown for periodic-feasible policies |
| `feasible` | No DoD breach, no unmet demand, and ends at least as charged as it started |

## The traps this harness was built to catch

**A short horizon flatters policies that drain the battery.** The obvious myopic
policy — spend all surplus in sunlight, idle through eclipse — never banks
anything, so it loses one eclipse's worth of housekeeping every orbit. Over
three orbits it appears to beat the LP optimum; by ten it breaches the
depth-of-discharge floor. **Evaluate over at least ten orbits.** Three is not
enough for the failure to surface.

**Periodicity is part of feasibility.** A policy that ends the horizon with less
charge than it started has borrowed energy it cannot repay, and its mean is not
something it could sustain. That is why `steady (W)` exists and why the
optimality gap is suppressed for non-periodic policies rather than printed as a
misleading negative.

**Both bounds bind, in different orbits.** The sustainable draw is limited by
energy neutrality *and* by the depth-of-discharge floor. In this repository's
reference configuration the DoD limit binds at i = 53° while energy balance
binds at LTAN 10:30 — the result reports which. A bound derived from the energy
balance alone overstates available power whenever the battery is sized for cycle
life rather than capacity, which in LEO it almost always is.

## What the bounds already tell you, before writing any policy

A one-line causal policy — bank until the battery is full, then spend all
surplus — lands within about 0.1 % of the offline LP optimum when every task is
worth the same. **With uniform task value the scheduling problem is essentially
trivial**, and the optimum is bang-bang: full power in sunlight, nothing in
eclipse, because a round trip through the battery costs about 8 %.

The consequence for a paper is worth stating plainly. A contribution has to come
from somewhere the uniform-value problem does not reach: heterogeneous task
value, deadlines, coverage or downlink windows, thermal derating, or
coordination across planes of a constellation. If a proposed policy only beats a
constant-power baseline under uniform value, the honest comparison is against
`bank_then_spend_policy`, not against the constant draw — and that is a much
harder bar.

Deadlines are the natural next axis: `deadline_policy` holds a payload floor
through eclipse and is reported infeasible at 120 W on the reference platform,
which is exactly the tension a scheduler has to manage. Sweeping that floor
shows what a latency target costs in feasible throughput.

## Changing the platform or orbit

The bounds depend entirely on the platform. `PowerSystem` carries array area,
cell efficiency, battery capacity, depth-of-discharge limit and housekeeping
load; `power_trace` takes the orbit and the slot length. Every number in a
result is specific to those, so report them alongside any scheduling claim. The
companion report at `web/scheduling.html` has the parameter table with
provenance for each value, including which ones are placeholders that must be
replaced with measurements before publication.

The energy cost per unit of work — `JOULES_PER_INFERENCE` in
`experiments/export_traces.py` — is a placeholder and cannot come from this
model. It has to be measured on the target accelerator.
