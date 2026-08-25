---
name: reproduce
description: Regenerate every result and figure in this solarsim repository from scratch, and verify the regenerated output matches what is committed. Use this whenever someone wants to reproduce the study, re-run the simulations, rebuild the reports, check that results are still valid after a code change, or asks "does this still reproduce" / "re-run everything" / "rebuild the pages". Also use it before publishing, submitting, or sharing any number from this repository, since it is the only way to confirm the committed results and the code actually agree.
---

# Reproducing the study

Everything in `results/` and `web/*.html` is generated. Nothing is edited by hand.
This skill regenerates it and checks the regeneration agrees with what is committed.

## The pipeline

Run in this order — each stage consumes the previous stage's output.

```bash
pip install numpy scipy                # scipy is only needed for export_traces

python -m experiments.validate         # ~7 s   verification suite
python -m experiments.run_study        # ~20 min E1-E6, one simulated year each
python -m experiments.run_profiles     # ~2 min  E7, master curve and profiles
python -m experiments.export_traces    # ~10 s   scheduling traces and bounds
python -m experiments.build_page       # ~2 s    both HTML reports
```

`run_study` is the long one. Start it in the background and do something else;
it prints a timestamped line per configuration so progress is visible.

## What must be true afterwards

**The verification suite passes.** It exits non-zero on any failure, and the CI
workflow runs it before publishing, so a failure means no result in this
repository can be trusted until it is fixed. Read the failing check name — the
suite is organised so each one points at a specific piece of physics.

**The regenerated files match the committed ones.** The simulation is
deterministic: same epoch, same parameters, same numbers. A diff means either
the code changed or the committed results are stale, and it matters which:

```bash
git status --short results/ web/
git diff --stat results/
```

If `results/` changed but you did not intend to change the model, stop and find
out why before committing. That diff is the repository's own regression test.

**The pages render.** `build_page` fails loudly on a missing input, but a page
can still be built and be visually broken. Chromium and Playwright are
available; a quick check that every figure container has an SVG or table inside
it catches nearly all breakage:

```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    pg = b.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("file:///home/user/black-repo/web/index.html", wait_until="load")
    pg.wait_for_timeout(2500)
    print("errors:", errs or "none")
    print("charts:", pg.locator(".chart svg").count(), "tables:", pg.locator("table").count())
    b.close()
```

Chromium caches `file://` URLs aggressively. If a rebuild seems not to have
taken effect, append a `?v=<timestamp>` query string rather than concluding the
build failed.

## Making it faster while iterating

Only rerun what you actually invalidated:

- Changed the shadow, orbit or solar model → everything, starting with `validate`.
- Changed only the power or attitude model → `run_study` and `export_traces`;
  `run_profiles` does not use them.
- Changed only the scheduling code → `export_traces` and `build_page`.
- Changed only page copy, CSS or chart code → `build_page` alone.

For a quick smoke test of the long stage, `run_study` takes experiment names:
`python -m experiments.run_study E1 E6` runs two of the six.

## Known slow or fragile spots

- `run_study` E5 simulates 24 planes of a 72-plane shell; that alone is about
  two minutes and dominates the stage.
- `export_traces` needs SciPy for the reference LP. Without it the traces still
  export but `optimal_schedule` raises ImportError with a clear message.
- The published pages must be pure ASCII, because the artifact host supplies the
  `<head>` and the document cannot declare its own charset. `build_page` asserts
  this and exits rather than emitting a page that would render as mojibake.
