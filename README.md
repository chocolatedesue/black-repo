# solarsim — orbital illumination and energy availability for LEO/SSO satellites

A verified, reproducible model of Earth-shadow geometry and photovoltaic energy
availability for circular low Earth orbits, sun-synchronous orbits, and Walker
constellations. Built to support energy-aware satellite research where the
numbers have to survive review.

Single dependency: NumPy.

```
python -m experiments.validate       # verification suite; exits non-zero on failure
python -m experiments.run_study      # E1-E6, one simulated year each   (~20 min)
python -m experiments.run_profiles   # E7, master curve and orbit profiles (~2 min)
python -m experiments.run_energy     # E8, energy intensity and consumption (~20 s)
python -m experiments.export_traces  # scheduling traces and bounds (needs SciPy)
python -m experiments.gpu_match      # E9, accelerator sizing; --dod, --bus-kg, --all
python -m experiments.build_page     # assemble both HTML reports from results/
```

Two reports are produced:

* **Orbital Sunlight Budget** (`web/index.html`) — the illumination study: eclipse
  geometry, the SSO design grid, Walker-constellation heterogeneity, EPS sizing.
* **Orbital Compute Energy Bounds** (`web/scheduling.html`) — the companion for
  energy-aware compute scheduling: the model to cite, the parameter table with
  provenance, the bounds a schedule must respect, and the headroom scheduling
  captures.

## What the model does

| Layer | Implementation |
|---|---|
| Orbit | Circular, mean elements, secular J2 rates for Ω, ω and M. Exact nodal period; sun-synchronous inclination solved in closed form; LTAN ↔ RAAN mapping against the *mean* Sun. |
| Sun | *Astronomical Almanac* low-precision series (< 0.01° in longitude), including the ±3.3 % annual irradiance modulation. |
| Shadow | Three models: cylindrical, dual-cone, and **fractional solar-disc occultation** (default) — the illuminated fraction ν computed from the circle–circle lens overlap of the apparent discs of Sun and Earth. Occulting radius R⊕ + 90 km. |
| Boundaries | Entry and exit epochs refined by bisection on the continuous shadow function, so reported durations are **independent of the sampling grid**. |
| Array | Two-axis, single-axis pitch, single-axis yaw, and body-mounted pointing models, each contributing a cosine factor κ(t) integrated alongside ν(t). |
| Power | `P_gen = ν·S·A·η_cell·f_pack·f_deg·η_ppt·κ`, per-revolution energy balance, battery SoC propagation, DoD, and EPS sizing. |
| Thermal | Lumped-node array temperature from a radiative balance — direct solar, albedo and Earth infrared in; emission from both faces and the extracted electrical power out — integrated with an unconditionally stable exponential step, so the eclipse transient is resolved. Cell efficiency is then `η(T) = η_ref(1 + α_P(T − T_ref))`. |
| Load | Housekeeping resolved by subsystem and by time: survival heaters keyed to the shadow function, downlink transmitter keyed to ground-station visibility (GMST-based access geometry), plus OBC, ADCS, receiver and EPS parasitics. |
| Accounting | A closed energy ledger from the array aperture to the load: every Wh of intercepted sunlight equals the sum of the optical, conversion, temperature, degradation, MPPT, charge and discharge losses, the curtailed surplus, and the delivered loads — verified to machine precision. |
| Constellations | Walker Delta and Star, per-plane statistics and instantaneous constellation-level sunlit fraction. |
| Scheduling | Per-slot power traces, the constant-draw and depth-of-discharge bounds, the burst envelope, and a reference LP for the optimal variable schedule. |
| Hardware | A catalogue of flown and candidate compute accelerators, the marginal array + battery + radiator mass of one *always-on* watt in a given orbit, and the depth-of-discharge / cycle-life trade that decides whether always-on is a five-year mission. |

## Verification

`experiments/validate.py` must pass before any result is generated. It checks:

- **Ephemeris** — solstice/equinox declinations and perihelion/aphelion distance
  against almanac values.
- **Sun-synchronous design** — inclinations at 400/600/800/1000 km against the
  standard design table, and LTAN held to < 2 min of drift over a year.
- **Shadow geometry** — under the closed-form solution's own assumptions
  (Keplerian plane, Sun frozen during a revolution) the numerical machinery
  reproduces `f_E = (1/π)·arccos(√(r²−R²)/(r·cos β))` to **~1e-16**. Running the
  same comparison with those assumptions restored *quantifies* what the closed
  form omits: up to 4.2e-4 in eclipse fraction, ≈ 2.4 s per revolution.
- **Convergence** — geometric durations are bit-identical from 128 to 8192
  samples per revolution (the bisection makes them grid-free); the illumination
  integral converges to < 1 ppm by 2048. Sensitivity to the opaque-atmosphere
  height and to the shadow model is reported rather than assumed away.
- **Energy chain** — sidereal time against Vallado's worked example to 1e-4 deg;
  Earth view factors and radiative equilibrium against their closed forms; the
  energy ledger closing to ~1e-15 relative in every configuration; the heaters
  landing in eclipse and not in sunlight; and a **no-regression check** that the
  original constant-load bounds are unchanged to 1e-9 W by everything above.

## Selected results (2024, one full year)

- SSO 550 km, LTAN 10:30 — eclipse 35.97 min/rev mean, duty cycle 0.626, β held
  inside −25.2°…−14.9° all year.
- SSO 550 km, LTAN 06:00 — duty cycle 0.938, 254 eclipse-free days.
- LEO 550 km, i = 53° — β sweeps ±76° on a 66-day beta cycle; 18.2 eclipse-free
  days, and a 36.8 min worst-case eclipse.
- Across the SSO grid (400–800 km × LTAN 06:00–12:00) annual duty cycle spans
  0.597 → 0.963: a **61 %** difference in harvested energy for the same array,
  from a choice that costs nothing in mass.
- **Walker Delta 53°:1584/72/17** — annual duty cycle varies by only **1.7 %**
  across planes (all planes traverse the same beta cycle, offset in phase), yet
  on any given day the planes span nearly the full range from full eclipse to
  none. Constellation-level sunlit fraction stays within 0.683–0.691.
- **Sun-synchronous Walker** — **44.1 %** annual spread across planes that never
  closes, because sun-synchrony pins each plane to its own local time.
  Placement, not timing.
- No single solar-array architecture wins: a pitch-axis drive delivers 338 W at
  LTAN 10:30 and collapses to 138 W (1.2 W worst revolution) at dawn–dusk; a
  yaw-axis drive is the mirror image at 533 W.

### Energy intensity and consumption

- The array does not run at its 28 °C rating: on the reference orbit it sits near
  **48 °C** in sunlight, peaks at **76 °C**, and falls to **−75 °C** in eclipse.
  At a triple-junction cell's ≈ −0.25 %/K that costs **3.9 % of annual harvested
  energy** (2.7–5.4 % across the year), and 5.1 % at the January epoch.
- **Albedo and Earth infrared cannot be dropped once temperature is modelled.**
  Excluding them — as earlier versions of this model did — puts the sunlit array
  at 26 °C, *below* its rating, and turns a 5.1 % loss into a 0.4 % bonus. The
  sign of the correction flips. They are a package or neither.
- Across the published spread of cell temperature coefficients (−0.15 to
  −0.35 %/K) the energy penalty runs **3.0 % to 7.3 %**. A more emissive rear
  face (ε 0.80 → 0.90) buys back a third of it, for no mass.
- The bus load is not flat. With heaters in eclipse and the transmitter over a
  ground station, the reference platform draws **37 W sunlit, 45 W in eclipse and
  87 W peak**, against a 45.8 W mean — and an SSO gets **197 contact minutes a
  day over 30 passes**, where the i = 53° case gets 38 minutes over 7.
- **Load shape helps scheduling rather than hurting it.** Against a flat load of
  the *same orbit-average*, giving the load its real shape drops the
  constant-draw baseline by 1.0 % (3.4 % at i = 53°) and leaves the LP optimum
  untouched, so the headroom rises from **+32.7 % to +34.0 %** (+13.4 % to
  +17.3 % at i = 53°). The heaters land where the battery has to pay for them.
- End to end, the two corrections take the achievable payload power from
  **310 W to 290 W (−6.2 %)** — a level shift that leaves every ratio below
  within a point of where it was, which is the strongest available argument for
  reporting scheduling results as ratios.
- Of the sunlight the array intercepts, **13.2 % reaches the payload**; the
  single largest recoverable line is the **18.7 % of generated energy shunted
  away** because a constant draw cannot absorb it when it arrives.

### Scheduling bounds

- A **constant** payload draw must survive the worst moment of every orbit, so it
  curtails generation for the rest of it: 233 W at LTAN 10:30 against an LP
  optimum of 310 W on identical hardware — **+33 % headroom for scheduling**. The
  gap tracks the eclipse fraction: only +9 % on a dawn–dusk orbit, +13 % at
  i = 53°.
- The familiar "orbit-average generation minus housekeeping" figure is not a bad
  estimate — it is the **upper bound reachable only by scheduling**, and the LP
  optimum lands within 0.5 % of it in all three orbits.
- With uniform task value the optimum is **bang-bang**: full power in sunlight,
  nothing in eclipse, because a round trip through the battery costs ~8 %.
  Eclipse-time computation is therefore always bought by a deadline, a coverage
  window or a latency target — never by energy.

### Running an accelerator through eclipse

- Always-on is never impossible, only priced. One watt of *continuous* payload
  power costs **51 g** of array + battery + radiator at LTAN 10:30, **41 g** on
  a dawn–dusk orbit, and **75 g** at i = 53° with a pitch-axis drive (50 g with
  a two-axis gimbal — the array is sized by the worst β of the year, so the
  drive choice moves the answer by half).
- A full H100 SXM at its 700 W board power is ~1120 W of system load. Running it
  continuously needs **7.5 m² of array, 2.4 kWh of battery, 4.7 m² of radiator,
  ~59 kg** of EPS and thermal hardware alone at LTAN 10:30 — so a 60 kg
  satellite carrying one cannot be running it continuously at full power. The
  same part on the study's reference 2 m² / 600 Wh bus runs at a **28 % duty
  cycle**.
- The radiator is not a footnote: in vacuum every delivered watt leaves as heat,
  so the radiator is 60–70 % of the array area for any part in the catalogue.
- **Depth of discharge, not mass, decides always-on.** Running through eclipse
  is one discharge cycle per orbit — 5 492 a year at LTAN 10:30. Halving battery
  mass by going from 30 % to 50 % DoD cuts life from 5.5 years to 1.8. On a
  dawn–dusk orbit the same load cycles the battery only **1 676 times a year**
  (254 eclipse-free days), so the identical 30 % design lasts **17.9 years** —
  3.3× the life for 20 % less mass. This is the strongest argument for dawn–dusk
  in the whole study, and it is invisible to an orbit-average energy budget.
- **A trap, now guarded.** The constant-draw bound is solved by requiring the
  battery to end the horizon as charged as it began, which is only meaningful
  over a *whole number of revolutions*. Handed `86400 / T` — 15.04 revolutions,
  an entirely natural thing to write — the window ends mid-sunlight on a
  just-topped-up battery, the bound comes back **5 % high**, and it reports the
  wrong binding constraint. `sustainable_power` now returns `periodicity_valid`
  with every result and the suite asserts both halves of this.

## Layout

```
solarsim/          constants, time, solar ephemeris, orbit, geometry, shadow,
                   attitude, simulate, constellation, power, thermal, load,
                   schedule, evaluate
experiments/       validate.py, run_study.py, run_profiles.py, run_energy.py,
                   export_traces.py, eval_policies.py, build_page.py
results/           *.json and trace_*.csv written by the experiments
web/               style.css, charts.js, app.js, app-scheduling.js, templates
                   -> index.html, scheduling.html (self-contained)
.claude/skills/    project skills: reproduce, experiment, evaluate
```

Every figure on both generated pages reads `results/` directly; no value is
transcribed by hand.

## Working on this repository

Three project skills capture the workflows, so a session in this repository can
pick them up without being told:

| Skill | Covers |
|---|---|
| `reproduce` | Regenerate every result and page, and verify the regeneration matches what is committed |
| `experiment` | Add an orbit, sweep, constellation, array model or figure — and what must not break |
| `evaluate` | Score a scheduling policy against the baseline and the LP optimum, with the traps that make naive comparisons wrong |

## Known limits

Circular orbits with mean elements: short-period J2 terms and drag decay are not
modelled (drag matters over a multi-year mission because it changes altitude and
therefore β*). Earth is a sphere, both for shadow geometry and for ground-station
access. Battery ageing and self-shadowing by the bus are out of scope.

The accelerator sizing in `solarsim/hardware.py` is a scoping calculation, not a
verified result: the orbital inputs come from the validated simulation, but the
platform coefficients (130 Wh/kg battery, 100 W/kg array, 250 W/m² radiator) are
engineering figures from the literature. `sensitivity()` reports the span across
their plausible ranges — for the H100 case, 40–110 kg against a 59 kg nominal.
Quote the ratios, not the absolute masses.

The thermal model is a single node per unit array area: it has no conduction to
the bus, no gradient across the panel, and no bus thermal state, so the survival
heaters are switched on the shadow function rather than by a thermostat. The
cell temperature coefficient is linear, and below about −50 °C it is being
extrapolated outside the range a datasheet characterises — which is why the
post-sunrise power spike is reported with that caveat rather than banked. Albedo
uses the standard `cos ζ` treatment, which is conservative near the terminator.
Ground-station contact assumes the transmitter is on for the whole window,
which is an upper bound on downlink energy.

## References

Vallado, *Fundamentals of Astrodynamics and Applications*, 4th ed. (§5.3 shadow,
§9.6 secular J2, §11.4 sun-synchronous design, eq. 3-47 sidereal time) ·
Montenbruck & Gill, *Satellite Orbits*, §3.3–3.4 · Walker, *J. Br. Interplanet.
Soc.* 37 (1984) 559 · Kopp & Lean, *Geophys. Res. Lett.* 38 (2011) L01706 ·
Wertz & Larson, *Space Mission Analysis and Design*, Ch. 11 (EPS sizing,
Table 11-8 power budgets) · Gilmore, *Spacecraft Thermal Control Handbook*,
Vol. I, Ch. 2–3 (environments, radiative balance) · ECSS-E-ST-10-04C (albedo and
outgoing longwave radiation) · Rauschenbach, *Solar Cell Array Design Handbook*,
Ch. 3 (cell temperature coefficients).

Parameter provenance: the orbital and solar constants are traceable to the
references above. The **platform** parameters — array optics, panel heat
capacity, cell temperature coefficient, and every line of the subsystem power
budget — are representative values for this class of spacecraft, not
measurements, and they are declared in one place each (`ThermalPanel`,
`CellThermalResponse`, `LoadModel`) so they can be replaced wholesale. The one
the results are most sensitive to, the cell temperature coefficient, is swept
rather than asserted.
