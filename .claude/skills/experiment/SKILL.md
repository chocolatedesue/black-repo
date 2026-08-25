---
name: experiment
description: Add or modify a simulation experiment in this solarsim repository — a new orbit, altitude or inclination sweep, a new Walker constellation, a new solar-array pointing model, or a new figure in one of the HTML reports. Use this whenever someone wants to simulate a different orbit or constellation, sweep a parameter, add a case to the study, change the reference platform, or add a chart or table to the reports. Also use it when they ask "what if we used orbit X" or "can you add altitude Y" — those are experiments, and this skill covers where the code goes and what must not break.
---

# Adding an experiment

The repository has one hard invariant: **`results/*.json` is the only source of
truth for the reports.** Every figure and every number on both HTML pages is
read from those files at build time. Nothing is transcribed. Keep that true and
the rest is mechanical.

## Where things live

| Layer | File | Add here when |
|---|---|---|
| Physics | `solarsim/shadow.py`, `orbit.py`, `solar.py`, `geometry.py` | The model itself is wrong or incomplete |
| Attitude | `solarsim/attitude.py` | A new solar-array pointing architecture |
| Power | `solarsim/power.py` | EPS parameters or sizing logic |
| Constellations | `solarsim/constellation.py` | A new Walker pattern or phasing rule |
| Scheduling | `solarsim/schedule.py`, `evaluate.py` | Bounds, traces, or policy scoring |
| Experiments | `experiments/run_study.py` (E1–E6), `run_profiles.py` (E7), `export_traces.py` | A new case, sweep, or output file |
| Report | `web/*.template.html` + `web/app*.js` | A new figure or table |
| Assembly | `experiments/build_page.py` | A new page, or a new field the page needs |

## Adding a case to an existing sweep

Most requests are this. The sweeps are plain lists at the top of each experiment
function; extend the list and rerun that experiment. For example a new altitude
in E4 is one entry in `alts`, and a new constellation in E5 is one tuple in
`designs`.

Then rerun only what you touched and rebuild:

```bash
python -m experiments.run_study E4     # just that experiment
python -m experiments.build_page
```

The page picks the new case up automatically if the figure iterates over the
list — most do. Check the figure rather than assuming: a chart that hard-codes which
cases to plot needs its own list updated too. In the illumination report,
Figure 5 pins three reference orbits and Figures 7 and 8 pin five local times
and five inclinations respectively -- deliberately, to keep the series count
readable and inside the validated categorical palette.

## Adding a whole experiment

Follow the shape of the existing ones. Each is a function that runs simulations,
prints a progress line per configuration, and calls `_write("<name>", payload)`.
Register it in the `EXPERIMENTS` dict so it can be run by name.

Two conventions worth keeping because the report depends on them:

- **Store summaries, not raw arrays.** `OrbitSimulation.summary()` gives a flat
  dict of everything the pages need. Per-revolution series get decimated or
  aggregated to daily values before serialisation, which is why the payload
  stays under a few hundred kB.
- **Record the parameters alongside the values.** Every result file carries its
  epoch, duration and model settings. A number without its configuration is not
  reproducible, and the pages print these in their captions.

## Adding a solar-array pointing model

Add a function to `solarsim/attitude.py` returning the effective cosine factor
κ(t) ∈ [0, 1], register it in `ARRAY_MODELS` and `ARRAY_LABELS`, then add its
name to `ARRAYS` in `run_study.py`. The simulator integrates
∫ν(t)·(S/S₀)·κ(t) dt per revolution for every registered model in one pass, so
adding one costs almost nothing.

Explain in the docstring *when the architecture wins*. The existing models are
only interesting because pitch-axis and yaw-axis drives are mirror images —
strong at low and high |β| respectively — and that comparison is the point.

## What must not break

**Run the verification suite after any change to the physics.** It is the
difference between a model and a guess:

```bash
python -m experiments.validate
```

It reproduces the closed-form cylindrical eclipse solution to ~1e-16 under that
solution's own assumptions, checks the solar ephemeris against almanac values,
and checks the sun-synchronous inclinations against the standard design table.
If a change breaks it, the change is wrong — the suite is not the thing to
adjust.

**Do not weaken a check to make it pass.** If a new tolerance is genuinely
needed, the reason belongs in the code as a comment explaining the physics, not
as a looser number. When the numerical result disagreed with the closed form
during development, the resolution was to discover that J2 plane drift and
solar motion explain the gap — and to report that as a finding — not to widen
the tolerance.

**Keep the pages pure ASCII.** `build_page` escapes non-ASCII automatically for
HTML and JavaScript, but `style.css` cannot be escaped that way and the build
fails if it contains any. Use CSS escapes there if you ever need a symbol.

**Rebuild and diff.** `git diff --stat results/` after a rerun should show only
the files you meant to change. An unexpected diff is the repository telling you
a shared parameter moved.
