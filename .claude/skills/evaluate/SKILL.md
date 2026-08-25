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

## Scoring against a realistic load, not a flat one

`power_trace` takes two optional refinements, both off by default:

```python
trace = power_trace(orbit, system, n_orbits=15, dt_s=10.0,
                    load=LoadModel(),   # heaters in eclipse, transmitter over stations
                    thermal=True)       # array temperature and the cell derate
```

They matter for a policy comparison in opposite directions, and it is worth
knowing which is which before quoting a number:

- **The shaped load raises the value of scheduling.** Survival heaters switch on
  in eclipse, so the load peaks exactly where generation is zero and the battery
  has to pay round-trip efficiency plus depth-of-discharge for it. That lowers
  the constant-draw baseline and leaves the LP optimum alone: on the reference
  orbit the headroom goes from +32.7 % to +34.0 %, and at i = 53° from +13.4 %
  to +17.3 %. A policy scored against a flat load is being scored against an
  unrealistically *strong* baseline.
- **The thermal derate lowers everything by about the same factor.** It costs
  ~5 % of generation and ~6 % of the optimum, so ratios barely move. It changes
  what you may claim in watts, not what you may claim in percent.

The downlink windows are also now real: `trace.in_contact` marks them, and they
are the natural place for a deadline- or coverage-driven policy to earn
something the uniform-value problem cannot. That was listed above as the axis a
contribution has to come from; the model now supplies it.

**Two horizon traps, both of which produce plausible wrong numbers:**

- Use a **whole number of revolutions**. `sustainable_power` tests energy
  neutrality by whether the battery ends as charged as it began, which is
  phase-dependent otherwise. `86400 / T` is 15.04 revolutions and returns a
  bound 5 % high with the wrong binding constraint. Check `periodicity_valid`.
- Any trace using `load=` wants **~15 revolutions, not 3**. A three-orbit window
  contains an unrepresentative number of ground passes — none at all for
  i = 53° — which deletes the transmitter from the comparison. That happens to
  agree with the ten-orbit minimum this harness already requires for a different
  reason.

## Changing the platform or orbit

The bounds depend entirely on the platform. `PowerSystem` carries array area,
cell efficiency, battery capacity, depth-of-discharge limit and housekeeping
load; `LoadModel` breaks that last one into subsystems if you want it shaped;
`ThermalPanel` and `CellThermalResponse` carry the array's optics and its
temperature coefficient; `power_trace` takes the orbit and the slot length. Every number in a
result is specific to those, so report them alongside any scheduling claim. The
companion report at `web/scheduling.html` has the parameter table with
provenance for each value, including which ones are placeholders that must be
replaced with measurements before publication.

The energy cost per unit of work — `JOULES_PER_INFERENCE` in
`experiments/export_traces.py` — is a placeholder and cannot come from this
model. It has to be measured on the target accelerator.

The same caution applies to the cell temperature coefficient in
`CellThermalResponse`: it is representative rather than measured, the derate is
close to proportional to it, and `python -m experiments.run_energy B` sweeps it
across the published range (3.0 % to 7.3 % energy penalty). Quote the sweep, not
the point value.
