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
    ["Cell efficiency η", "0.30 (BOL, AM0, 28 °C)",
     "Typical triple-junction GaAs. PULL THE CURRENT DATASHEET (AzurSpace / Spectrolab / Rocket Lab) — this is a placeholder"],
    ["Packing factor", "0.90", "Cell area / substrate area; typical"],
    ["End-of-life factor", "0.85",
     "Lumped radiation + UV degradation. For a fluence-driven curve use ESA SPENVIS"],
    ["MPPT / PCDU efficiency", "0.93", "Typical; vendor datasheet"],
    ["Battery capacity", "600 Wh", "Reference platform"],
    ["Depth-of-discharge limit", "30 %",
     "LEO cycles ~5 500/year, which is what forces a low DoD; cell cycle-life curve"],
    ["Charge / discharge efficiency", "0.95 / 0.97", "Typical Li-ion round trip"],
    ["Housekeeping load", "45 W", "Bus, ADCS, TT&C, thermal"],
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
      ["p_house_w", "W", "Constant housekeeping draw"],
      ["p_surplus_w", "W", "p_gen_w - p_house_w; negative in shadow"],
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
      ["Earth albedo on the array", "up to +25 % on a nadir-facing panel at 550 km; near zero on a sun-tracking wing",
       "Skip unless the platform is body-mounted. It scales P_gen by a near-constant factor, so scheduling ratios barely move"],
      ["Array temperature", "−8 to −17 % depending on architecture",
       "Skip. Fold it into the end-of-life factor and say so"],
      ["Earth infrared on the array", "~200 W/m² incident, 0 W electrical",
       "Skip for power outright — GaAs cuts off at ~870 nm, Earth IR peaks near 10 µm. It only matters through temperature"],
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
