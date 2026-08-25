/* =============================================================================
   Scheduling-bounds page.  Reads the same DATA payload the build step inlines
   from results/scheduling.json and the exported trace CSVs.
   ============================================================================= */

import {
  svgEl, htmlEl, fmt, fmtInt, cssVar,
  lineChart, renderTable,
} from "./charts.js";

const D = window.DATA;
const S = D.sched;
const CAT = ["--s1", "--s2", "--s3"];

const redraws = [];
function register(fn) { redraws.push(fn); fn(); }
function redrawAll() { redraws.forEach((f) => f()); }

/* -- theme ----------------------------------------------------------------- */

document.getElementById("themeToggle").addEventListener("click", () => {
  const root = document.documentElement;
  const cur = root.getAttribute("data-theme");
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const effective = cur || (systemDark ? "dark" : "light");
  root.setAttribute("data-theme", effective === "dark" ? "light" : "dark");
  requestAnimationFrame(redrawAll);
});

/* -- section nav highlight ------------------------------------------------- */

const navLinks = [...document.querySelectorAll("#topnav a")];
if ("IntersectionObserver" in window) {
  const io = new IntersectionObserver(
    (entries) => entries.forEach((e) => {
      if (!e.isIntersecting) return;
      navLinks.forEach((a) =>
        a.classList.toggle("active", a.getAttribute("href") === `#${e.target.id}`));
    }),
    { rootMargin: "-45% 0px -50% 0px" }
  );
  navLinks.map((a) => document.querySelector(a.getAttribute("href")))
    .filter(Boolean).forEach((s) => io.observe(s));
}

/* -- controls -------------------------------------------------------------- */

function segmented(host, items, initial, onChange, label) {
  if (label) htmlEl("span", { class: "ctl-label", text: label }, host);
  const seg = htmlEl("div", { class: "seg", role: "group" }, host);
  let value = initial;
  const btns = items.map((it) => {
    const b = htmlEl("button", {
      type: "button", text: it.label,
      "aria-pressed": String(it.value === initial),
    }, seg);
    b.addEventListener("click", () => {
      value = it.value;
      btns.forEach((x, i) => x.setAttribute("aria-pressed", String(items[i].value === value)));
      onChange(value);
    });
    return b;
  });
  return { get value() { return value; } };
}

function legend(host, items) {
  host.innerHTML = "";
  items.forEach((it) => {
    const w = htmlEl("span", { class: "item" }, host);
    htmlEl("span", { class: "swatch", style: `background:${it.color}` }, w);
    htmlEl("span", { text: it.label }, w);
  });
}

const KEYS = Object.keys(S.cases);
const short = (k) => S.cases[k].title;

/* -- header ---------------------------------------------------------------- */

document.getElementById("bl-epoch").textContent = S.epoch.slice(0, 10);

(function tiles() {
  const host = document.getElementById("tiles");
  const ref = S.cases.sso_1030 || S.cases[KEYS[0]];
  const headroom = KEYS.map((k) => S.cases[k].optimal.headroom_pct);

  const items = [
    {
      k: "Constant-power baseline",
      v: fmt(ref.sustainable.sustainable_payload_w, 0), u: "W",
      s: `${ref.title} · a fixed payload draw must curtail generation whenever the battery is full`,
    },
    {
      k: "Optimally scheduled",
      v: fmt(ref.optimal.mean_payload_w, 0), u: "W",
      s: "Same hardware, same orbit — the LP of §4 spending surplus as it arrives",
    },
    {
      k: "Scheduling headroom",
      v: `+${fmt(ref.optimal.headroom_pct, 0)}`, u: "%",
      s: `Across these orbits: +${fmt(Math.min(...headroom), 0)} % to +${fmt(Math.max(...headroom), 0)} %, largest where the eclipse is longest`,
    },
    {
      k: "Burst at 2× the baseline",
      v: fmt(burstAt(ref, 2.0) / 60, 0), u: "min",
      s: `On a full ${ref.battery_wh} Wh battery at ${fmt(100 * ref.dod_limit, 0)} % DoD`,
    },
  ];
  items.forEach((it) => {
    const t = htmlEl("div", { class: "tile" }, host);
    htmlEl("div", { class: "k", text: it.k }, t);
    const v = htmlEl("div", { class: "v" }, t);
    v.textContent = it.v;
    if (it.u) htmlEl("span", { class: "u", text: it.u }, v);
    htmlEl("div", { class: "s", text: it.s }, t);
  });
})();

function burstAt(caseObj, multiple) {
  const target = caseObj.sustainable.sustainable_payload_w * multiple;
  const b = caseObj.burst.reduce((a, x) =>
    Math.abs(x.payload_w - target) < Math.abs(a.payload_w - target) ? x : a);
  return b.max_duration_s;
}

/* =============================================================================
   Table 1 -- parameters and provenance
   ============================================================================= */

(function paramTable() {
  const rows = [
    ["Total solar irradiance", "1361 W/m² at 1 AU",
     "Kopp & Lean 2011 (GRL 38, L01706); scaled by (AU/r☉)² each step"],
    ["Solar ephemeris", "< 0.01° in longitude",
     "Astronomical Almanac low-precision series; Montenbruck & Gill §3.3"],
    ["Occulting radius", "R⊕ + 90 km",
     "Atmosphere optically thick below ~90 km; Vallado §5.3. Sensitivity reported in the illumination study"],
    ["Array area", "2.0 m²", "Reference platform — replace with your bus"],
        ["Cell efficiency \u03b7", "0.30 (BOL, AM0, 28 \u00b0C)",
     "Typical triple-junction GaAs. PULL THE CURRENT DATASHEET (AzurSpace / Spectrolab / Rocket Lab) - this is a placeholder, and \u00a7 7 shows the temperature coefficient that comes with it matters as much as the rating"],
    ["Packing factor", "0.90", "Cell area / substrate area; typical"],
    ["End-of-life factor", "0.85",
     "Lumped radiation + UV degradation. For a fluence-driven curve use ESA SPENVIS"],
    ["MPPT / PCDU efficiency", "0.93", "Typical; vendor datasheet"],
    ["Battery capacity", "600 Wh", "Reference platform"],
    ["Depth-of-discharge limit", "30 %",
     "LEO cycles ~5 500/year, which is what forces a low DoD; cell cycle-life curve"],
    ["Charge / discharge efficiency", "0.95 / 0.97", "Typical Li-ion round trip"],
    ["Housekeeping load", "45 W flat",
     "Bus, ADCS, TT&C, thermal, lumped. \u00a7 7 breaks this into subsystems and gives it a shape: 37 W sunlit, 45 W in eclipse (survival heaters), 87 W peak over a ground station"],
    ["Array pointing", "single-axis pitch or yaw",
     "κ = cos β for a pitch-axis drive; √(1-(ŝ·r̂)²) for a yaw-axis drive"],
  ];
  renderTable(document.getElementById("paramTable"), {
    columns: [
      { label: "Quantity", get: (r) => r[0] },
      { label: "Value", get: (r) => r[1] },
      { label: "Source / note", get: (r) => r[2] },
    ],
    rows,
  });
  // The provenance column is prose; let it wrap rather than force a wide scroll.
  document.querySelectorAll("#paramTable td:last-child, #paramTable th:last-child")
    .forEach((el) => { el.style.whiteSpace = "normal"; el.style.minWidth = "34ch"; });
})();

/* =============================================================================
   Figure 1 -- power trace against the ceiling
   ============================================================================= */

(function traceFig() {
  let sel = KEYS[0];
  segmented(
    document.getElementById("traceControls"),
    KEYS.map((k) => ({ label: short(k), value: k })),
    KEYS[0],
    (v) => { sel = v; draw(); },
    "Orbit"
  );

  function draw() {
    const c = S.cases[sel];
    const tr = D.traces[sel];
    const sus = c.sustainable.sustainable_payload_w;
    const house = c.housekeeping_w;

    // Eclipse spans, for the shaded bands.
    const bands = [];
    let start = null;
    tr.eclipsed.forEach((e, i) => {
      if (e && start === null) start = tr.t_s[i];
      if (!e && start !== null) {
        bands.push({ x0: start / 60, x1: tr.t_s[i] / 60,
                     fill: cssVar("--eclipse-soft") });
        start = null;
      }
    });
    if (start !== null) {
      bands.push({ x0: start / 60, x1: tr.t_s[tr.t_s.length - 1] / 60,
                   fill: cssVar("--eclipse-soft") });
    }

    legend(document.getElementById("traceLegend"), [
      { label: "Generated power", color: cssVar("--s1") },
      { label: "Constant-power baseline (total demand)", color: cssVar("--s2") },
      { label: "Optimally scheduled payload", color: cssVar("--s3") },
      { label: "Eclipse", color: cssVar("--eclipse") },
    ]);

    lineChart(document.getElementById("traceChart"), {
      height: 330,
      series: [
        {
          name: "Generated",
          color: cssVar("--s1"),
          points: tr.t_s.map((t, i) => [t / 60, tr.p_gen_w[i]]),
          area: true, areaFill: cssVar("--s1"), areaOpacity: 0.12,
        },
        {
          name: "Constant baseline demand",
          color: cssVar("--s2"),
          points: [[0, house + sus], [tr.t_s[tr.t_s.length - 1] / 60, house + sus]],
          dash: "6 4",
        },
        {
          name: "Scheduled payload",
          color: cssVar("--s3"),
          points: tr.t_s.map((t, i) => [t / 60, c.optimal_payload_w[i]]),
          width: 2,
        },
      ],
      bands,
      xDomain: [0, tr.t_s[tr.t_s.length - 1] / 60],
      yDomain: [0, Math.max(...tr.p_gen_w) * 1.08],
      xLabel: "Minutes from epoch",
      yLabel: "Power  (W)",
      fmtXTick: (t) => t.toFixed(0),
      fmtYTick: (t) => t.toFixed(0),
      fmtValue: (v) => `${v.toFixed(1)} W`,
      fmtTipTitle: (t) => `t + ${t.toFixed(1)} min`,
      ariaLabel: `Generated power over three orbits for ${c.title}, against the sustainable demand level`,
    });

    const ts = c.trace_summary;
    document.getElementById("traceNote").innerHTML =
      `<b>${c.title}</b>, ${c.array_model.replace(/_/g, " ")}. Generation peaks at ` +
      `<b>${fmt(ts.p_gen_max_w, 0)} W</b> and averages <b>${fmt(ts.p_gen_mean_w, 0)} W</b>; ` +
      `<b>${fmt(100 * ts.eclipse_slot_fraction, 0)} %</b> of slots are eclipsed. ` +
      `The dashed line is total demand for a payload held constant at the highest level ` +
      `that survives every orbit &mdash; <b>${fmt(sus, 0)} W</b>. The green trace is the ` +
      `same platform under the LP of &sect;4, free to vary, averaging ` +
      `<b>${fmt(c.optimal.mean_payload_w, 0)} W</b> &mdash; <b>+${fmt(c.optimal.headroom_pct, 1)} %</b> ` +
      `on identical hardware. ` +
      `<b>The optimum is bang-bang</b>: full power through sunlight, nothing at all in ` +
      `shadow. That is not a solver artefact. Round-tripping a joule through the battery ` +
      `costs about 8 %, so when every task is worth the same, computing in eclipse is ` +
      `strictly worse than computing in sunlight, and the battery is left to carry only ` +
      `the bus. Any eclipse-time computation in a real system is therefore bought by a ` +
      `deadline, a coverage window or a latency target &mdash; which is exactly where the ` +
      `scheduling problem stops being trivial. This is a three-orbit window at epoch and ` +
      `sits slightly above the annual mean; the illumination study carries the full year.`;
  }
  register(draw);
})();

/* -- Table 2: bounds ------------------------------------------------------- */

(function boundsTable() {
  renderTable(document.getElementById("boundsTable"), {
    caption: "Three orbits at epoch, 10 s slots, identical hardware in every row. The naive ceiling is orbit-average generation minus housekeeping.",
    columns: [
      { label: "Orbit", get: (r) => r.c.title },
      { label: "Array", get: (r) => r.c.array_model.replace(/_/g, " ") },
      { label: "T (min)", get: (r) => fmt(r.c.nodal_period_min, 1), numeric: true },
      { label: "Mean P_gen (W)", get: (r) => fmt(r.c.trace_summary.p_gen_mean_w, 1), numeric: true },
      { label: "Peak P_gen (W)", get: (r) => fmt(r.c.trace_summary.p_gen_max_w, 1), numeric: true },
      { label: "Constant baseline (W)", get: (r) => fmt(r.c.sustainable.sustainable_payload_w, 1), numeric: true },
      { label: "Binding constraint", get: (r) => r.c.sustainable.binding_constraint.replace(/_/g, " ") },
      { label: "LP optimum (W)", get: (r) => fmt(r.c.optimal.mean_payload_w, 1), numeric: true },
      { label: "Headroom", get: (r) => `+${fmt(r.c.optimal.headroom_pct, 1)} %`, numeric: true },
      { label: "Naive ceiling (W)", get: (r) => fmt(r.c.sustainable.naive_estimate_w, 1), numeric: true },
    ],
    rows: KEYS.map((k) => ({ c: S.cases[k] })),
  });
})();

/* =============================================================================
   Figure 2 -- burst envelope
   ============================================================================= */

(function burstFig() {
  let sel = KEYS[0];
  segmented(
    document.getElementById("burstControls"),
    KEYS.map((k) => ({ label: short(k), value: k })),
    KEYS[0],
    (v) => { sel = v; draw(); },
    "Orbit"
  );

  function draw() {
    const c = S.cases[sel];
    const sus = c.sustainable.sustainable_payload_w;
    const pts = c.burst
      .filter((b) => Number.isFinite(b.max_duration_s))
      .map((b) => [b.payload_w / sus, b.max_duration_s / 60]);

    lineChart(document.getElementById("burstChart"), {
      height: 290,
      series: [{
        name: "Maximum hold time",
        color: cssVar("--s1"),
        points: pts,
        markers: true,
      }],
      xDomain: [1, Math.max(...pts.map((p) => p[0])) * 1.05],
      yDomain: [0, Math.max(...pts.map((p) => p[1])) * 1.12],
      xLabel: "Payload power, as a multiple of the sustainable ceiling",
      yLabel: "Maximum hold time  (min)",
      rules: [{ y: c.nodal_period_min, label: `one orbit (${fmt(c.nodal_period_min, 0)} min)`,
                color: cssVar("--ink-3") }],
      fmtXTick: (t) => `${t.toFixed(1)}×`,
      fmtYTick: (t) => t.toFixed(0),
      fmtValue: (v) => `${v.toFixed(1)} min`,
      fmtTipTitle: (x) => `${x.toFixed(2)}× ceiling = ${fmt(x * sus, 0)} W`,
      ariaLabel: `Maximum burst duration against payload power for ${c.title}`,
    });

    const two = c.burst.reduce((a, x) =>
      Math.abs(x.payload_w - 2 * sus) < Math.abs(a.payload_w - 2 * sus) ? x : a);
    document.getElementById("burstNote").innerHTML =
      `Starting from a full usable battery (<b>${fmt(c.battery_wh * c.dod_limit, 0)} Wh</b> ` +
      `of ${c.battery_wh} Wh at a ${fmt(100 * c.dod_limit, 0)} % depth-of-discharge limit), ` +
      `and placing the window where the deficit is smallest. At twice the ceiling ` +
      `(<b>${fmt(two.payload_w, 0)} W</b>) the platform holds for ` +
      `<b>${fmt(two.max_duration_s / 60, 0)} min</b> &mdash; comparable to a single orbit, ` +
      `so a burst of that size is an every-few-orbits event, not a mode. The curve falls ` +
      `roughly as 1/(excess power), which is why deadline-driven batches are far cheaper ` +
      `to schedule as several modest windows than as one large one.`;
  }
  register(draw);
})();

/* -- Table 3: trace schema ------------------------------------------------- */

(function schemaTable() {
  renderTable(document.getElementById("schemaTable"), {
    caption: `results/trace_<case>.csv — ${fmtInt(S.cases[KEYS[0]].trace_summary.n_slots)} rows at ${S.cases[KEYS[0]].trace_summary.dt_s} s slots`,
    columns: [
      { label: "Column", get: (r) => r[0] },
      { label: "Unit", get: (r) => r[1] },
      { label: "Meaning", get: (r) => r[2] },
    ],
    rows: [
      ["t_s", "s", "Seconds from epoch; the slot's start"],
      ["nu", "—", "Fractional illumination in [0, 1]; 1 is full sun, 0 is umbra"],
      ["eclipsed", "0/1", "1 whenever nu < 1, i.e. penumbra counts as eclipsed"],
      ["p_gen_w", "W", "Array output. This is G[k] in the LP of §4"],
      ["p_house_w", "W", "Housekeeping draw in this slot. Constant in these traces; varies slot to slot when a load model is supplied (see \u00a7 7)"],
      ["p_surplus_w", "W", "p_gen_w - p_house_w; negative in shadow"],
      ["in_contact", "0/1", "Present only on traces built with a ground-station network: 1 inside a downlink window, when the transmitter load applies"],
    ],
  });
  document.querySelectorAll("#schemaTable td:last-child")
    .forEach((el) => { el.style.whiteSpace = "normal"; });
})();

/* -- Table 4: what to skip ------------------------------------------------- */

(function skipTable() {
  renderTable(document.getElementById("skipTable"), {
    columns: [
      { label: "Refinement", get: (r) => r[0] },
      { label: "Magnitude", get: (r) => r[1] },
      { label: "Verdict for a scheduling paper", get: (r) => r[2] },
    ],
    rows: [
            ["Array temperature", "measured: -3.9 % of annual energy on the reference orbit, -3.9 to -4.1 % across the three; -5.1 % at the January epoch",
       "NO LONGER SKIPPED - modelled in \u00a7 7. It is a systematic, one-signed bias, but it scales P_gen almost uniformly, so ratios move under a point"],
      ["Earth albedo and infrared on the array", "no photocurrent, but a third of the panel's thermal input",
       "NO LONGER SKIPPED - and they cannot be skipped once temperature is modelled: excluding them puts the sunlit array at 26 C, below its rating, turning a 5 % loss into a 0.4 % bonus"],
      ["Shape of the housekeeping load", "heaters +8 W in eclipse, transmitter +42 W over a station; bus peak 87 W against a 46 W mean",
       "NO LONGER SKIPPED - modelled in \u00a7 7. It lowers the constant-draw baseline without touching the optimum, so it raises the headroom scheduling captures"],
      ["Radiation degradation vs time", "the 0.85 factor, resolved year by year",
       "Skip for a single-epoch study; add if the contribution is about multi-year operation"],
      ["Solar cycle in TSI", "±0.05 %", "Skip. It is 60× smaller than the annual orbital variation already modelled"],
      ["Higher-precision solar ephemeris", "~1e-5 in eclipse fraction",
       "Skip, but the number is worth quoting once to close off the question"],
    ],
  });
  document.querySelectorAll("#skipTable td")
    .forEach((el) => { el.style.whiteSpace = "normal"; });
})();

/* =============================================================================
   Section 7 -- energy intensity and consumption (E8)
   ============================================================================= */

const E8 = D.e8;
const E8KEYS = E8 && E8.bounds ? Object.keys(E8.bounds.cases) : [];

/* -- Figure 5: generation, panel temperature, shaped load ------------------ */

(function loadFig() {
  if (!E8KEYS.length) return;
  let sel = E8KEYS[0];
  segmented(
    document.getElementById("loadControls"),
    E8KEYS.map((k) => ({ label: E8.bounds.cases[k].title, value: k })),
    E8KEYS[0],
    (v) => { sel = v; draw(); },
    "Orbit"
  );

  function draw() {
    const c = E8.bounds.cases[sel];
    const lt = c.load_trace;
    const xs = lt.t_s.map((t) => t / 60);
    const xMax = xs[xs.length - 1];

    // Shade eclipse; mark contact windows with a second, denser band so the
    // transmitter spikes are attributable at a glance.
    const spans = (flags, fill) => {
      const out = [];
      let start = null;
      flags.forEach((f, i) => {
        if (f && start === null) start = xs[i];
        if (!f && start !== null) { out.push({ x0: start, x1: xs[i], fill }); start = null; }
      });
      if (start !== null) out.push({ x0: start, x1: xMax, fill });
      return out;
    };
    const bands = spans(lt.eclipsed, cssVar("--eclipse-soft"))
      .concat(spans(lt.in_contact, cssVar("--s3") + "22"));

    legend(document.getElementById("loadLegend"), [
      { label: "Generated, at the 28 °C rating", color: cssVar("--s1") },
      { label: "Generated, at the temperature the array actually reaches", color: cssVar("--s2") },
      { label: "Housekeeping demand", color: cssVar("--s3") },
      { label: "Eclipse", color: cssVar("--eclipse") },
    ]);

    lineChart(document.getElementById("loadChart"), {
      height: 330,
      series: [
        { name: "Generated (rated)", color: cssVar("--s1"),
          points: xs.map((t, i) => [t, lt.p_gen_w[i]]), dash: "5 3" },
        { name: "Generated (thermal)", color: cssVar("--s2"),
          points: xs.map((t, i) => [t, lt.p_gen_thermal_w[i]]),
          area: true, areaFill: cssVar("--s2"), areaOpacity: 0.12 },
        { name: "Housekeeping", color: cssVar("--s3"),
          points: xs.map((t, i) => [t, lt.p_house_w[i]]), width: 2 },
      ],
      bands,
      xDomain: [0, xMax],
      yDomain: [0, Math.max(...lt.p_gen_w) * 1.08],
      xLabel: "Minutes from epoch",
      yLabel: "Power  (W)",
      fmtXTick: (t) => t.toFixed(0),
      fmtYTick: (t) => t.toFixed(0),
      fmtValue: (v) => `${v.toFixed(1)} W`,
      fmtTipTitle: (t) => `t + ${t.toFixed(1)} min`,
      ariaLabel: `Generation at rated and actual cell temperature, with the shaped housekeeping load, for ${c.title}`,
    });

    const th = E8.thermal ? E8.thermal[sel] : null;
    const tmin = Math.min(...lt.panel_t_c), tmax = Math.max(...lt.panel_t_c);
    document.getElementById("loadNote").innerHTML =
      `<b>${c.title}</b>, ${c.array_model.replace(/_/g, " ")}, two revolutions at 30 s. ` +
      `The panel swings from <b>${fmt(tmin, 0)} °C</b> to <b>${fmt(tmax, 0)} °C</b>; ` +
      `the gap between the two generation curves is what that costs, ` +
      (th ? `<b>${fmt(th.energy_penalty_pct, 1)} %</b> of annual harvested energy ` +
            `averaged over the year (${fmt(100 * (1 - th.derate_max), 1)}&ndash;` +
            `${fmt(100 * (1 - th.derate_min), 1)} % across it). ` : "") +
      `Note where the curves <em>cross</em>: for a few minutes after each sunrise the ` +
      `array is still cold and outperforms its own rating &mdash; a real effect, though ` +
      `the size of that spike should be read with care, since it extrapolates a linear ` +
      `temperature coefficient far below the range it is fitted over, and a real ` +
      `regulator's tracking range may not follow the array up. It is a small ` +
      `contribution to the integral either way. ` +
      `The housekeeping trace steps up by the survival-heater load in shadow and spikes ` +
      `by the transmitter load over a ground station (shaded green) &mdash; a peak of ` +
      `<b>${fmt(c.configs.shaped.housekeeping_max_w, 0)} W</b> against a mean of ` +
      `<b>${fmt(c.configs.shaped.housekeeping_mean_w, 1)} W</b>.`;
  }
  register(draw);
})();

/* -- Table 5: the energy ledger -------------------------------------------- */

(function ledgerTable() {
  if (!E8KEYS.length) return;
  const c = E8.bounds.cases[E8KEYS[0]];
  const L = c.configs.shaped_plus_thermal.ledger;
  const inc = L.incident_wh;
  const pct = (v) => `${(100 * Math.abs(v) / inc).toFixed(2)} %`;

  // renderTable writes textContent, so every cell here is plain text.
  const rows = [
    ["Sunlight intercepted by the array", L.incident_wh, ""],
    ["  less  substrate not covered by cells", -L.loss_packing_wh, "packing factor 0.90"],
    ["  less  photons the cell cannot convert", -L.loss_conversion_wh, "at the 28 \u00b0C rating"],
    ["  less  running above the rating", -L.loss_temperature_wh, "the correction this section adds"],
    ["  less  radiation and UV degradation", -L.loss_degradation_wh, "end-of-life factor 0.85"],
    ["  less  MPPT and PCDU conversion", -L.loss_ppt_wh, "efficiency 0.93"],
    ["= Delivered to the bus", L.bus_generated_wh, ""],
    ["  less  battery charge loss", -L.loss_charge_wh, "round trip, charging leg"],
    ["  less  battery discharge loss", -L.loss_discharge_wh, "round trip, discharging leg"],
    ["  less  shunted with the battery full", -L.curtailed_wh,
     "not a hardware loss - energy the schedule failed to use"],
    ["  less  consumed by housekeeping", -L.delivered_housekeeping_wh, "bus, ADCS, comms, heaters"],
    ["  less  consumed by the payload", -L.delivered_payload_wh, "at the constant-draw bound"],
    ["= Net change in stored energy", -L.stored_delta_wh, "zero over a whole number of revolutions"],
  ];

  renderTable(document.getElementById("ledgerTable"), {
    caption: `${c.title} \u2014 ${fmt(c.horizon_hours, 1)} h (${fmtInt(c.n_orbits)} revolutions), shaped load and thermal derate`,
    columns: [
      { label: "Line", get: (r) => r[0] },
      { label: "Wh", get: (r) => fmt(r[1], 1), numeric: true },
      { label: "of incident", get: (r) => pct(r[1]), numeric: true },
      { label: "Note", get: (r) => r[2] },
    ],
    rows,
  });
  document.querySelectorAll("#ledgerTable td:last-child")
    .forEach((el) => { el.style.whiteSpace = "normal"; });
  // The two subtotal rows carry the structure of the table; make them readable
  // as such rather than as just two more lines.
  document.querySelectorAll("#ledgerTable tbody tr").forEach((tr) => {
    if (tr.firstChild.textContent.startsWith("=")) tr.style.fontWeight = "600";
  });

  document.getElementById("ledgerNote").innerHTML =
    `Every line is computed, none transcribed; the residual between the intercepted ` +
    `sunlight and the sum of the rest is <b>${(L.residual_relative).toExponential(1)}</b> ` +
    `relative &mdash; machine precision, which is the point of keeping the ledger at all. ` +
    `End to end, <b>${fmt(100 * L.end_to_end_efficiency, 1)} %</b> of the sunlight the array ` +
    `intercepts reaches the payload. The line to read twice is the shunted energy: ` +
    `<b>${fmt(100 * L.curtailed_fraction_of_generated, 1)} %</b> of everything the array ` +
    `generates is thrown away because a constant draw cannot absorb it when it arrives. ` +
    `That is the case for scheduling, stated as an accounting identity.`;
})();

/* -- Table 6: corrected bounds --------------------------------------------- */

(function corrTable() {
  if (!E8KEYS.length) return;
  let sel = E8KEYS[0];
  segmented(
    document.getElementById("corrControls"),
    E8KEYS.map((k) => ({ label: E8.bounds.cases[k].title, value: k })),
    E8KEYS[0],
    (v) => { sel = v; draw(); },
    "Orbit"
  );

  const LABEL = {
    legacy_constant_45w: "Flat 45 W bus (the earlier model)",
    flat_at_shaped_mean: "Flat, at the shaped load's own mean",
    shaped: "Shaped: heaters in eclipse, transmitter over stations",
    shaped_plus_thermal: "Shaped, plus the thermal derate",
  };

  function draw() {
    const c = E8.bounds.cases[sel];
    const rows = Object.keys(LABEL).map((k) => [LABEL[k], c.configs[k]]);
    renderTable(document.getElementById("corrTable"), {
      caption: `${c.title} \u2014 ${fmt(c.horizon_hours, 1)} h, ${c.array_model.replace(/_/g, " ")}`,
      columns: [
        { label: "Load / generation model", get: (r) => r[0] },
        { label: "Bus mean", get: (r) => `${fmt(r[1].housekeeping_mean_w, 1)} W`, numeric: true },
        { label: "Bus peak", get: (r) => `${fmt(r[1].housekeeping_max_w, 0)} W`, numeric: true },
        { label: "P_gen", get: (r) => `${fmt(r[1].p_gen_mean_w, 0)} W`, numeric: true },
        { label: "Constant bound", get: (r) => `${fmt(r[1].constant_bound_w, 1)} W`, numeric: true },
        { label: "LP optimum", get: (r) => `${fmt(r[1].lp_optimum_w, 1)} W`, numeric: true },
        { label: "Headroom", get: (r) => `${fmt(r[1].headroom_pct, 1)} %`, numeric: true },
        { label: "Shunted", get: (r) => `${fmt(100 * r[1].curtailed_fraction_of_generated, 1)} %`, numeric: true },
      ],
      rows,
    });

    const so = c.shape_only_effect, te = c.thermal_effect, ee = c.end_to_end;
    document.getElementById("corrNote").innerHTML =
      `<b>Shape, isolated from level.</b> Rows 2 and 3 draw the same mean bus power ` +
      `(<b>${fmt(c.flat_equivalent_w, 1)} W</b>) and differ only in <em>when</em>. Giving the ` +
      `load its real shape moves the constant-draw bound by ` +
      `<b>${fmt(so.constant_bound_delta_pct, 1)} %</b> and the LP optimum by ` +
      `<b>${fmt(so.lp_optimum_delta_pct, 1)} %</b>, so the headroom for scheduling goes from ` +
      `<b>${fmt(so.headroom_pct_flat, 1)} %</b> to <b>${fmt(so.headroom_pct_shaped, 1)} %</b>. ` +
      `The heaters land in eclipse, where the battery has to pay for them at the round-trip ` +
      `efficiency and against the depth-of-discharge limit; a constant draw has to absorb that ` +
      `and an optimised one does not. Modelling the load honestly makes scheduling look ` +
      `<em>better</em>, not worse. ` +
      `<b>Temperature.</b> The derate costs <b>${fmt(te.p_gen_delta_pct, 1)} %</b> of generation ` +
      `and <b>${fmt(te.lp_optimum_delta_pct, 1)} %</b> of the optimum. ` +
      `<b>End to end</b>, the achievable payload power falls from ` +
      `<b>${fmt(ee.legacy_lp_optimum_w, 0)} W</b> to <b>${fmt(ee.corrected_lp_optimum_w, 0)} W</b> ` +
      `(<b>${fmt(ee.delta_pct, 1)} %</b>) &mdash; a level shift that leaves every ratio in ` +
      `&sect;&nbsp;3 essentially where it was.`;
  }
  register(draw);
})();

/* -- Table 7: what the derate rests on ------------------------------------- */

(function sensTable() {
  if (!E8 || !E8.sensitivity) return;
  const sw = E8.sensitivity.sweeps;
  const rows = [];
  sw.temperature_coefficient.forEach((r) => rows.push([
    "Cell temperature coefficient",
    `${fmt(100 * r.temp_coeff_per_k, 2)} %/K`,
    "\u2014",
    `${fmt(r.energy_penalty_pct, 2)} %`,
  ]));
  sw.optical_properties.forEach((r) => rows.push([
    "Panel optics",
    `\u03b1 = ${r.alpha_solar}, \u03b5 = ${r.eps_front} / ${r.eps_back}  (${r.note})`,
    `${fmt(r.t_sunlit_mean_c, 1)} \u00b0C`, `${fmt(r.energy_penalty_pct, 2)} %`,
  ]));
  sw.earth_flux.forEach((r) => rows.push([
    "Albedo and Earth infrared", r.note,
    `${fmt(r.t_sunlit_mean_c, 1)} \u00b0C`, `${fmt(r.energy_penalty_pct, 2)} %`,
  ]));
  sw.heat_capacity.forEach((r) => rows.push([
    "Panel heat capacity",
    `${fmtInt(r.heat_capacity_j_m2k)} J/m\u00b2K  (\u03c4 = ${fmt(r.time_constant_s, 0)} s)`,
    `${fmt(r.t_sunlit_mean_c, 1)} \u00b0C`, `${fmt(100 * (1 - r.derate), 2)} %`,
  ]));

  renderTable(document.getElementById("sensTable"), {
    caption: `${E8.sensitivity.case} \u2014 one parameter varied at a time about the baseline`,
    columns: [
      { label: "Parameter", get: (r) => r[0] },
      { label: "Value", get: (r) => r[1] },
      { label: "Sunlit mean", get: (r) => r[2], numeric: true },
      { label: "Energy penalty", get: (r) => r[3], numeric: true },
    ],
    rows,
  });
  document.querySelectorAll("#sensTable td:nth-child(2)")
    .forEach((el) => { el.style.whiteSpace = "normal"; });
})();
