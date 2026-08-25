# solarsim — orbital illumination and energy availability for LEO/SSO satellites

A verified, reproducible model of Earth-shadow geometry and photovoltaic energy
availability for circular low Earth orbits, sun-synchronous orbits, and Walker
constellations. Built to support energy-aware satellite research where the
numbers have to survive review.

Single dependency: NumPy.

```
python -m experiments.validate      # verification suite; exits non-zero on failure
python -m experiments.run_study     # E1-E6, one simulated year each   (~20 min)
python -m experiments.run_profiles  # E7, master curve and orbit profiles (~2 min)
python -m experiments.build_page    # assemble web/index.html from results/*.json
```

## What the model does

| Layer | Implementation |
|---|---|
| Orbit | Circular, mean elements, secular J2 rates for Ω, ω and M. Exact nodal period; sun-synchronous inclination solved in closed form; LTAN ↔ RAAN mapping against the *mean* Sun. |
| Sun | *Astronomical Almanac* low-precision series (< 0.01° in longitude), including the ±3.3 % annual irradiance modulation. |
| Shadow | Three models: cylindrical, dual-cone, and **fractional solar-disc occultation** (default) — the illuminated fraction ν computed from the circle–circle lens overlap of the apparent discs of Sun and Earth. Occulting radius R⊕ + 90 km. |
| Boundaries | Entry and exit epochs refined by bisection on the continuous shadow function, so reported durations are **independent of the sampling grid**. |
| Array | Two-axis, single-axis pitch, single-axis yaw, and body-mounted pointing models, each contributing a cosine factor κ(t) integrated alongside ν(t). |
| Power | `P_gen = ν·S·A·η_cell·f_pack·f_deg·η_ppt·κ`, per-revolution energy balance, battery SoC propagation, DoD, and EPS sizing. |
| Constellations | Walker Delta and Star, per-plane statistics and instantaneous constellation-level sunlit fraction. |

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

## Layout

```
solarsim/          constants, time, solar ephemeris, orbit, geometry,
                   shadow, attitude, simulate, constellation, power
experiments/       validate.py, run_study.py, run_profiles.py, build_page.py
results/           *.json written by the experiments
web/               style.css, charts.js, app.js, index.template.html
                   -> index.html (single self-contained file)
```

Every figure on the generated page reads `results/*.json` directly; no value is
transcribed by hand.

## Known limits

Circular orbits with mean elements: short-period J2 terms and drag decay are not
modelled (drag matters over a multi-year mission because it changes altitude and
therefore β*). Earth is a sphere for shadow purposes. Albedo and Earth infrared
input to the array are excluded — conservative for power, not for thermal.
Battery ageing, temperature-dependent cell efficiency and self-shadowing by the
bus are out of scope.

## References

Vallado, *Fundamentals of Astrodynamics and Applications*, 4th ed. (§5.3 shadow,
§9.6 secular J2, §11.4 sun-synchronous design) · Montenbruck & Gill, *Satellite
Orbits*, §3.3–3.4 · Walker, *J. Br. Interplanet. Soc.* 37 (1984) 559 · Kopp &
Lean, *Geophys. Res. Lett.* 38 (2011) L01706 · Wertz & Larson, *Space Mission
Analysis and Design*, Ch. 11.
