/* =============================================================================
   Page wiring.  Every figure reads DATA, which the build step inlines straight
   from the JSON the simulation writes -- no value on this page is transcribed
   by hand.
   ============================================================================= */

import {
  svgEl, htmlEl, fmt, fmtInt, cssVar, linScale, ticks,
  lineChart, heatmap, matrixPlot, stripPlot, groupedBars, renderTable, attachTableToggle,
} from "./charts.js";

const D = window.DATA;
const R_EARTH = 6378.1363;
const H_ATM = 90.0;
const ORD = ["--ord-1", "--ord-2", "--ord-3", "--ord-4", "--ord-5"];
const CAT = ["--s1", "--s2", "--s3"];
// Four-slot set for the array-pointing comparison; validated against the
// adjacent-pair CVD gates in both modes, with direct labels on every bar.
const CAT4 = ["--s1", "--s2", "--s3", "--s4"];

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const MONTH_START = [0,31,60,91,121,152,182,213,244,274,305,335];
const monthTick = (d) => {
  const i = MONTH_START.indexOf(Math.round(d));
  return i >= 0 ? MONTHS[i] : "";
};
const dayLabel = (d) => {
  let m = 0;
  while (m < 11 && MONTH_START[m + 1] <= d) m++;
  return `${MONTHS[m]} ${Math.round(d) - MONTH_START[m] + 1}`;
};

const redraws = [];
function register(fn) { redraws.push(fn); fn(); }
function redrawAll() { redraws.forEach((f) => f()); }

/* -- theme ----------------------------------------------------------------- */

const toggle = document.getElementById("themeToggle");
toggle.addEventListener("click", () => {
  const root = document.documentElement;
  const cur = root.getAttribute("data-theme");
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const effective = cur || (systemDark ? "dark" : "light");
  root.setAttribute("data-theme", effective === "dark" ? "light" : "dark");
  requestAnimationFrame(redrawAll);
});

/* -- section nav highlight ------------------------------------------------- */

const navLinks = [...document.querySelectorAll("#topnav a")];
const sections = navLinks
  .map((a) => document.querySelector(a.getAttribute("href")))
  .filter(Boolean);
if ("IntersectionObserver" in window) {
  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((e) => {
        if (!e.isIntersecting) return;
        navLinks.forEach((a) =>
          a.classList.toggle("active", a.getAttribute("href") === `#${e.target.id}`)
        );
      });
    },
    { rootMargin: "-45% 0px -50% 0px" }
  );
  sections.forEach((s) => io.observe(s));
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

function slider(host, { label, min, max, step, value, fmtVal, onInput }) {
  htmlEl("span", { class: "ctl-label", text: label }, host);
  const input = htmlEl("input", {
    type: "range", min, max, step, value, "aria-label": label,
  }, host);
  const out = htmlEl("span", { class: "readout", text: fmtVal(value) }, host);
  input.addEventListener("input", () => {
    const v = parseFloat(input.value);
    out.textContent = fmtVal(v);
    onInput(v);
  });
  return { get value() { return parseFloat(input.value); },
           set value(v) { input.value = v; out.textContent = fmtVal(v); } };
}

function legend(host, items, shape = "line") {
  host.innerHTML = "";
  items.forEach((it) => {
    const w = htmlEl("span", { class: "item" }, host);
    htmlEl("span", {
      class: `swatch${shape === "block" ? " block" : ""}`,
      style: `background:${it.color}`,
    }, w);
    htmlEl("span", { text: it.label }, w);
  });
}

/* -- header ---------------------------------------------------------------- */

document.getElementById("bl-epoch").textContent = D.epoch.slice(0, 10);
document.getElementById("ft-epoch").textContent = D.epoch.slice(0, 10);
document.getElementById("bl-revs").textContent =
  D.e1.cases.sso_1030.summary.n_revs.toLocaleString();

(function tiles() {
  const host = document.getElementById("tiles");
  const sso = D.e1.cases.sso_1030.summary;
  const dd = D.e1.cases.sso_dawn_dusk.summary;
  const l53 = D.e1.cases.leo_53.summary;
  const items = [
    {
      k: "Eclipse per revolution",
      v: fmt(sso.eclipse_mean_min, 1), u: "min",
      s: `SSO 550 km, LTAN 10:30 · ${fmt(100 * sso.eclipse_fraction_mean, 1)} % of the ${fmt(sso.nodal_period_min, 1)} min period`,
    },
    {
      k: "Illumination duty cycle",
      v: fmt(sso.duty_cycle_mean, 3), u: "",
      s: `Same orbit. Energy scales with this, not with the sunlit flag`,
    },
    {
      k: "Dawn–dusk duty cycle",
      v: fmt(dd.duty_cycle_mean, 3), u: "",
      s: `LTAN 06:00 · ${fmt(dd.eclipse_free_days, 0)} eclipse-free days per year`,
    },
    {
      k: "Beta swing, i = 53°",
      v: `±${fmt(Math.max(Math.abs(l53.beta_min_deg), l53.beta_max_deg), 0)}`, u: "°",
      s: `Non-SSO shells sweep the full range; eclipse-free above β* = ${fmt(l53.beta_star_deg ?? D.e1.cases.leo_53.summary.beta_star_deg, 1)}°`,
    },
    {
      k: "Worst-case eclipse",
      v: fmt(Math.max(sso.eclipse_max_min, l53.eclipse_max_min), 1), u: "min",
      s: "Sizes the battery. Reached at β = 0 in any 550 km orbit",
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

/* =============================================================================
   Figure 1 -- orbit-plane cross-section
   ============================================================================= */

(function orbitRing() {
  const mc = D.e7.master_curve;
  const controls = document.getElementById("ringControls");
  const chart = document.getElementById("ringChart");
  const readout = document.getElementById("ringReadout");

  let altIdx = mc.altitudes_km.indexOf(550) >= 0 ? mc.altitudes_km.indexOf(550) : 1;
  let beta = 0;

  segmented(
    controls,
    mc.altitudes_km.map((h, i) => ({ label: `${h} km`, value: i })),
    altIdx,
    (v) => { altIdx = v; draw(); },
    "Altitude"
  );
  const betaSlider = slider(controls, {
    label: "Beta", min: 0, max: 90, step: 0.5, value: 0,
    fmtVal: (v) => `${v.toFixed(1)}°`,
    onInput: (v) => { beta = v; draw(); },
  });

  const interp = (arr) => {
    const b = mc.beta_deg;
    let i = Math.min(b.length - 2, Math.max(0, Math.floor(beta / (b[1] - b[0]))));
    const t = (beta - b[i]) / (b[i + 1] - b[i]);
    const a = arr[altIdx][i], c = arr[altIdx][i + 1];
    if (!Number.isFinite(a) || !Number.isFinite(c)) return Number.isFinite(a) ? a : c;
    return a + t * (c - a);
  };

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let raf = null, phase = 0, lastT = 0;

  function draw() {
    const h = mc.altitudes_km[altIdx];
    const r = R_EARTH + h;
    const Rocc = R_EARTH + H_ATM;
    const period = mc.period_min[altIdx];
    const eclMin = Math.max(0, interp(mc.eclipse_min));
    const eclFrac = Math.max(0, interp(mc.eclipse_fraction));
    const bstar = mc.beta_star_deg[altIdx];
    const arcHalf = (eclFrac * 360) / 2;                       // degrees

    const W = 480, H = 300, CX = 206, CY = 150;
    const px = 84 / R_EARTH;                                   // km -> px
    const rp = r * px, Rp = R_EARTH * px, Rop = Rocc * px;

    chart.innerHTML = "";
    chart.classList.add("chart");
    const svg = svgEl("svg", {
      viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": `Orbit plane cross-section at ${h} km, beta ${beta} degrees. ` +
        `Eclipse ${eclMin.toFixed(1)} minutes of a ${period.toFixed(1)} minute period.`,
    }, chart);

    // -- shadow region: the anti-sunward half of x^2 sin^2(b) + y^2 = Rocc^2
    const sb = Math.sin((beta * Math.PI) / 180);
    const shadow = svgEl("g", {}, svg);
    if (sb < 1e-4) {
      svgEl("rect", {
        x: 0, y: CY - Rop, width: CX, height: 2 * Rop,
        fill: cssVar("--eclipse"), opacity: 0.13,
      }, shadow);
      svgEl("line", { x1: 0, x2: CX, y1: CY - Rop, y2: CY - Rop,
        stroke: cssVar("--eclipse"), "stroke-width": 1.2, "stroke-dasharray": "5 4" }, shadow);
      svgEl("line", { x1: 0, x2: CX, y1: CY + Rop, y2: CY + Rop,
        stroke: cssVar("--eclipse"), "stroke-width": 1.2, "stroke-dasharray": "5 4" }, shadow);
    } else {
      const a = Rop / sb;                                       // semi-major, px
      const clipped = Math.min(a, CX + 10);
      let d = `M${CX} ${CY - Rop}`;
      const N = 200;
      for (let i = 1; i <= N; i++) {
        const th = (Math.PI / 2) + (i / N) * Math.PI;           // top -> bottom via -x
        let xk = a * Math.cos(th), yk = Rop * Math.sin(th);
        if (-xk > clipped) { xk = -clipped; yk = Rop * Math.sqrt(Math.max(0, 1 - (xk / a) ** 2)) * Math.sign(yk || 1); }
        d += `L${(CX + xk).toFixed(2)} ${(CY - yk).toFixed(2)}`;
      }
      d += "Z";
      svgEl("path", { d, fill: cssVar("--eclipse"), opacity: 0.13 }, shadow);
      svgEl("path", { d, fill: "none", stroke: cssVar("--eclipse"),
        "stroke-width": 1.2, "stroke-dasharray": "5 4", opacity: 0.85 }, shadow);
    }

    // -- Sun direction, drawn at the right edge clear of the orbit
    const rays = svgEl("g", {}, svg);
    for (let k = -3; k <= 3; k++) {
      const y = CY + k * 13;
      const len = 26 - Math.abs(k) * 3;
      svgEl("line", { x1: W - 8 - len, x2: W - 8, y1: y, y2: y,
        stroke: cssVar("--sunlit"), "stroke-width": 2.5, "stroke-linecap": "round",
        opacity: 0.6 }, rays);
    }
    svgEl("text", { class: "axis-title", x: W - 8, y: CY + 62, "text-anchor": "end",
      fill: cssVar("--sunlit") }, svg).textContent = "TO SUN";

    // -- Earth
    svgEl("circle", { cx: CX, cy: CY, r: Rop, fill: "none",
      stroke: cssVar("--earth-line"), "stroke-width": 1, "stroke-dasharray": "2 3",
      opacity: 0.8 }, svg);
    svgEl("circle", { cx: CX, cy: CY, r: Rp, fill: cssVar("--earth"),
      stroke: cssVar("--earth-line"), "stroke-width": 1 }, svg);
    svgEl("text", { class: "axis-text", x: CX, y: CY + 4, "text-anchor": "middle",
      fill: cssVar("--surface") }, svg).textContent = "EARTH";

    // -- orbit arcs.  Sun is at +x; the eclipse is centred on 180 deg.
    const pol = (deg, rad) => [
      CX + rad * Math.cos((deg * Math.PI) / 180),
      CY - rad * Math.sin((deg * Math.PI) / 180),
    ];
    const arcPath = (a0, a1, rad) => {
      const [x0, y0] = pol(a0, rad), [x1, y1] = pol(a1, rad);
      const large = Math.abs(a1 - a0) > 180 ? 1 : 0;
      return `M${x0.toFixed(2)} ${y0.toFixed(2)}A${rad} ${rad} 0 ${large} 0 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
    };

    svgEl("circle", { cx: CX, cy: CY, r: rp, fill: "none",
      stroke: cssVar("--line"), "stroke-width": 1 }, svg);

    const gap = arcHalf > 0.6 ? 0.6 : 0;                        // 2px surface gap
    if (arcHalf > 0) {
      svgEl("path", {
        d: arcPath(180 - arcHalf + gap, 180 + arcHalf - gap, rp),
        fill: "none", stroke: cssVar("--eclipse"), "stroke-width": 6,
        "stroke-linecap": "butt",
      }, svg);
    }
    svgEl("path", {
      d: arcPath(180 + arcHalf + gap, 180 - arcHalf - gap + 360, rp),
      fill: "none", stroke: cssVar("--sunlit"), "stroke-width": 6,
      "stroke-linecap": "butt",
    }, svg);

    // terminator crossings
    if (arcHalf > 0) {
      [180 - arcHalf, 180 + arcHalf].forEach((ang) => {
        const [px1, py1] = pol(ang, rp);
        svgEl("circle", { cx: px1, cy: py1, r: 4, fill: cssVar("--surface"),
          stroke: cssVar("--ink-2"), "stroke-width": 1.5 }, svg);
      });
    }

    // direct labels, placed outside the orbit so nothing overlaps the Earth
    if (arcHalf > 3) {
      const [lx, ly] = pol(180, rp + 16);
      const t = svgEl("text", { class: "series-label", x: lx, y: ly - 4,
        "text-anchor": "end", fill: cssVar("--eclipse") }, svg);
      svgEl("tspan", { x: lx }, t).textContent = "ECLIPSE";
      svgEl("tspan", { x: lx, dy: 15 }, t).textContent = `${eclMin.toFixed(1)} min`;
      // leader from the arc midpoint to the label
      const [ax, ay] = pol(180, rp);
      svgEl("line", { x1: ax, y1: ay, x2: lx + 4, y2: ly - 8,
        stroke: cssVar("--eclipse"), "stroke-width": 1, opacity: 0.45 }, svg);
    }
    const sunMid = arcHalf > 3 ? 42 : 42;
    const [sx, sy] = pol(sunMid, rp + 16);
    const ts = svgEl("text", { class: "series-label", x: sx + 4, y: sy - 4,
      "text-anchor": "start", fill: cssVar("--sunlit") }, svg);
    svgEl("tspan", { x: sx + 4 }, ts).textContent = "SUNLIT";
    svgEl("tspan", { x: sx + 4, dy: 15 }, ts).textContent =
      `${(period - eclMin).toFixed(1)} min`;
    const [bx, by] = pol(sunMid, rp);
    svgEl("line", { x1: bx, y1: by, x2: sx, y2: sy - 8,
      stroke: cssVar("--sunlit"), "stroke-width": 1, opacity: 0.45 }, svg);

    // satellite marker
    const sat = svgEl("circle", { r: 5.5, fill: cssVar("--ink"),
      stroke: cssVar("--surface"), "stroke-width": 2 }, svg);
    const place = (deg) => {
      const [x1, y1] = pol(deg, rp);
      sat.setAttribute("cx", x1);
      sat.setAttribute("cy", y1);
      const inEcl = Math.abs(((deg - 180 + 540) % 360) - 180) < arcHalf;
      sat.setAttribute("fill", inEcl ? cssVar("--eclipse") : cssVar("--sunlit"));
    };
    if (raf) cancelAnimationFrame(raf);
    if (reduced) {
      place(35);
    } else {
      lastT = 0;
      const step = (ts2) => {
        if (lastT) phase = (phase + ((ts2 - lastT) / 1000) * 22) % 360;
        lastT = ts2;
        place(phase);
        raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    }

    // -- readout panel
    readout.innerHTML = "";
    const free = eclMin <= 0;
    const rows = [
      ["Orbital period", `${period.toFixed(2)} min`],
      ["Sunlit per revolution", `${(period - eclMin).toFixed(2)} min`],
      ["Eclipse per revolution", free ? "none" : `${eclMin.toFixed(2)} min`],
      ["Eclipse fraction", free ? "0.0 %" : `${(100 * eclFrac).toFixed(2)} %`],
      ["Critical beta β*", `${bstar.toFixed(2)}°`],
      ["Shadow ellipse semi-major", sb < 1e-4 ? "∞ (strip)" : `${(Rocc / sb).toFixed(0)} km`],
      ["Orbit radius r", `${r.toFixed(0)} km`],
      ["Eclipses per day", free ? "0" : (1440 / period).toFixed(1)],
    ];
    const tbl = htmlEl("table", {}, readout);
    const tb = htmlEl("tbody", {}, tbl);
    rows.forEach(([k, v]) => {
      const tr = htmlEl("tr", {}, tb);
      htmlEl("td", { text: k, style: "white-space:normal;color:var(--ink-2)" }, tr);
      htmlEl("td", { text: v, class: "n" }, tr);
    });
    const note = htmlEl("div", { style: "margin-top:14px" }, readout);
    if (free) {
      htmlEl("span", { class: "pill pass",
        html: `<span class="ico">✓</span> β &gt; β* — continuous sunlight` }, note);
    } else if (beta > bstar - 6) {
      htmlEl("span", { class: "pill warn",
        html: `<span class="ico">!</span> within 6° of β* — steep sensitivity` }, note);
    } else {
      htmlEl("span", { class: "pill",
        html: `<span class="ico">•</span> eclipsed every revolution` }, note);
    }
  }

  register(draw);
})();

/* =============================================================================
   Figure 2 -- illumination profile
   ============================================================================= */

(function profile() {
  const op = D.e7.orbit_profiles;
  const shown = [0, 55, 65, 68, 75];
  const cases = op.cases.filter((c) => shown.includes(c.beta_deg));
  const host = document.getElementById("profileChart");

  register(() => {
    const series = cases.map((c, i) => ({
      name: `β = ${c.beta_deg}°`,
      color: cssVar(ORD[i]),
      points: op.u_deg.map((u, k) => [u, c.nu[k]]),
      endLabel: null,
    }));
    legend(
      document.getElementById("profileLegend"),
      cases.map((c, i) => ({
        label: `β = ${c.beta_deg}°  ·  ${c.eclipse_min.toFixed(1)} min eclipse`,
        color: cssVar(ORD[i]),
      }))
    );
    lineChart(host, {
      height: 300,
      series,
      xDomain: [0, 360],
      yDomain: [0, 1.06],
      xTicks: [0, 45, 90, 135, 180, 225, 270, 315, 360],
      yTicks: [0, 0.25, 0.5, 0.75, 1],
      xLabel: "Argument of latitude from the ascending node  (deg)",
      yLabel: "Illuminated fraction of the solar disc",
      fmtXTick: (t) => `${t}°`,
      fmtYTick: (t) => t.toFixed(2),
      fmtValue: (v) => v.toFixed(4),
      fmtTipTitle: (u) => `u = ${u.toFixed(1)}°`,
      ariaLabel: "Illumination profile around one revolution for five beta angles",
    });
  });

  const wrap = document.getElementById("tblWrap2");
  renderTable(wrap, {
    caption: `Single-revolution illumination at ${op.altitude_km} km (nodal period ${op.cases[0].period_min.toFixed(2)} min)`,
    columns: [
      { label: "β (deg)", get: (r) => fmt(r.beta_deg, 1), numeric: true },
      { label: "Eclipse (min)", get: (r) => fmt(r.eclipse_min, 3), numeric: true },
      { label: "Sunlit (min)", get: (r) => fmt(r.sunlit_min, 3), numeric: true },
      { label: "Eclipse arc (deg)", get: (r) => fmt(r.eclipse_arc_deg, 2), numeric: true },
      { label: "Mean ν", get: (r) => fmt(r.mean_nu, 4), numeric: true },
    ],
    rows: op.cases,
  });
  attachTableToggle(document.getElementById("tblBtn2"), wrap);
})();

/* =============================================================================
   Figure 3 -- penumbra zoom
   ============================================================================= */

(function penumbra() {
  const pz = D.e7.penumbra_zoom;
  const host = document.getElementById("penumbraChart");
  const first = pz.t_rel_s.findIndex((t, i) => pz.nu[i] < 1);
  const last = pz.nu.length - 1 - [...pz.nu].reverse().findIndex((v) => v > 0);
  const dur = pz.t_rel_s[last] - pz.t_rel_s[first];

  document.getElementById("pen-dur").textContent = `${dur.toFixed(1)} s`;
  const eclMin = D.e7.orbit_profiles.cases.find((c) => c.beta_deg === 0).eclipse_min;
  document.getElementById("pen-pct").textContent =
    `${(100 * dur / (eclMin * 60)).toFixed(2)} %`;

  register(() => {
    lineChart(host, {
      height: 250,
      margin: { t: 16, r: 24, b: 46, l: 56 },
      series: [{
        name: "ν",
        color: cssVar("--s1"),
        points: pz.t_rel_s.map((t, i) => [t, pz.nu[i]]),
        area: true,
        areaFill: cssVar("--s1"),
      }],
      bands: [{ x0: pz.t_rel_s[first], x1: pz.t_rel_s[last],
        fill: cssVar("--eclipse-soft"), label: `penumbra  ${dur.toFixed(1)} s` }],
      yDomain: [0, 1.05],
      yTicks: [0, 0.25, 0.5, 0.75, 1],
      xLabel: "Time from first contact  (s)",
      yLabel: "Illuminated fraction",
      fmtXTick: (t) => `${t.toFixed(0)}`,
      fmtYTick: (t) => t.toFixed(2),
      fmtValue: (v) => v.toFixed(5),
      fmtTipTitle: (t) => `t = ${t.toFixed(2)} s`,
      ariaLabel: "Fractional illumination through a shadow entry, resolved in seconds",
    });
  });
})();

/* =============================================================================
   Figure 4 -- master curve
   ============================================================================= */

(function master() {
  const mc = D.e7.master_curve;
  const host = document.getElementById("masterChart");
  let mode = "min";
  segmented(
    document.getElementById("masterControls"),
    [{ label: "Minutes", value: "min" }, { label: "Fraction of period", value: "frac" }],
    "min",
    (v) => { mode = v; draw(); },
    "Show"
  );

  function draw() {
    const arr = mode === "min" ? mc.eclipse_min : mc.eclipse_fraction;
    const series = mc.altitudes_km.map((h, i) => ({
      name: `${h} km`,
      color: cssVar(ORD[i]),
      points: mc.beta_deg.map((b, k) => [b, arr[i][k]]),
    }));
    legend(
      document.getElementById("masterLegend"),
      mc.altitudes_km.map((h, i) => ({
        label: `${h} km  ·  β* = ${mc.beta_star_deg[i].toFixed(1)}°`,
        color: cssVar(ORD[i]),
      }))
    );
    lineChart(host, {
      height: 340,
      series,
      xDomain: [0, 90],
      yDomain: [0, mode === "min" ? 40 : 0.4],
      xTicks: [0, 10, 20, 30, 40, 50, 60, 70, 80, 90],
      rules: mc.beta_star_deg.map((b, i) => ({
        x: b, color: cssVar(ORD[i]), dash: "3 4",
        label: i === 0 || i === mc.beta_star_deg.length - 1 ? `β*` : null,
      })),
      xLabel: "Solar beta angle  (deg)",
      yLabel: mode === "min" ? "Eclipse per revolution  (min)" : "Eclipse fraction  f_E",
      fmtXTick: (t) => `${t}°`,
      fmtYTick: (t) => (mode === "min" ? t.toFixed(0) : t.toFixed(2)),
      fmtValue: (v) => (mode === "min" ? `${v.toFixed(2)} min` : v.toFixed(4)),
      fmtTipTitle: (b) => `β = ${b.toFixed(1)}°`,
      ariaLabel: "Eclipse duration against beta angle for five altitudes",
    });
  }
  register(draw);
})();

/* -- Table 1: altitude family --------------------------------------------- */

(function altTable() {
  renderTable(document.getElementById("altTable"), {
    caption: "Circular orbits at i = 53°, one simulated year, fractional shadow model",
    columns: [
      { label: "h (km)", get: (r) => fmtInt(r.altitude_km), numeric: true },
      { label: "T_nodal (min)", get: (r) => fmt(r.nodal_period_min, 2), numeric: true },
      { label: "β* (deg)", get: (r) => fmt(r.beta_star_deg, 2), numeric: true },
      { label: "Mean eclipse (min)", get: (r) => fmt(r.eclipse_mean_min, 2), numeric: true },
      { label: "Max eclipse (min)", get: (r) => fmt(r.eclipse_max_min, 2), numeric: true },
      { label: "Mean f_E", get: (r) => fmt(r.eclipse_fraction_mean, 4), numeric: true },
      { label: "Max f_E", get: (r) => fmt(r.eclipse_fraction_max, 4), numeric: true },
      { label: "Duty cycle", get: (r) => fmt(r.duty_cycle_mean, 4), numeric: true },
      { label: "Eclipse-free (d/yr)", get: (r) => fmt(r.eclipse_free_days, 1), numeric: true },
    ],
    rows: D.e4.cases,
  });
})();

/* =============================================================================
   Figure 5 -- one year of beta and eclipse
   ============================================================================= */

(function annual() {
  const keys = ["sso_1030", "sso_dawn_dusk", "leo_53"];
  const cases = keys.map((k, i) => ({
    key: k, ...D.e1.cases[k], color: CAT[i],
  }));
  let lower = "eclipse";
  segmented(
    document.getElementById("annualControls"),
    [{ label: "Eclipse duration", value: "eclipse" },
     { label: "Illumination duty cycle", value: "duty" }],
    "eclipse",
    (v) => { lower = v; draw(); },
    "Lower panel"
  );

  const xTicks = MONTH_START;

  function draw() {
    legend(
      document.getElementById("annualLegend"),
      cases.map((c) => ({ label: c.title, color: cssVar(c.color) }))
    );
    lineChart(document.getElementById("annualBeta"), {
      height: 250,
      margin: { t: 14, r: 20, b: 34, l: 56 },
      series: cases.map((c) => ({
        name: c.title, color: cssVar(c.color),
        points: c.daily.beta_deg.map((v, d) => [d, v]),
      })),
      xDomain: [0, 365],
      yDomain: [-92, 92],
      xTicks, yTicks: [-90, -60, -30, 0, 30, 60, 90],
      yLabel: "Solar beta angle  (deg)",
      fmtXTick: monthTick,
      fmtYTick: (t) => `${t}°`,
      fmtValue: (v) => `${v.toFixed(2)}°`,
      fmtTipTitle: dayLabel,
      rules: [
        { y: D.e1.cases.leo_53.summary.beta_star_deg, label: "β* (550 km)",
          color: cssVar("--ink-3") },
        { y: -D.e1.cases.leo_53.summary.beta_star_deg, color: cssVar("--ink-3") },
      ],
      ariaLabel: "Beta angle over one year for three reference orbits",
    });

    const isEcl = lower === "eclipse";
    lineChart(document.getElementById("annualEclipse"), {
      height: 250,
      margin: { t: 14, r: 20, b: 46, l: 56 },
      series: cases.map((c) => ({
        name: c.title, color: cssVar(c.color),
        points: (isEcl ? c.daily.eclipse_min : c.daily.duty_cycle).map((v, d) => [d, v]),
      })),
      xDomain: [0, 365],
      yDomain: isEcl ? [0, 40] : [0.5, 1.02],
      xTicks,
      xLabel: "Day of year 2024",
      yLabel: isEcl ? "Eclipse per revolution  (min)" : "Illumination duty cycle",
      fmtXTick: monthTick,
      fmtYTick: (t) => (isEcl ? t.toFixed(0) : t.toFixed(2)),
      fmtValue: (v) => (isEcl ? `${v.toFixed(2)} min` : v.toFixed(4)),
      fmtTipTitle: dayLabel,
      ariaLabel: isEcl
        ? "Daily mean eclipse duration over one year"
        : "Daily mean illumination duty cycle over one year",
    });

    const l53 = D.e1.cases.leo_53.summary;
    const dd = D.e1.cases.sso_dawn_dusk.summary;
    document.getElementById("annualNote").innerHTML =
      `The sun-synchronous orbit at LTAN 10:30 holds β inside ` +
      `<b>${fmt(D.e1.cases.sso_1030.summary.beta_min_deg, 1)}° to ` +
      `${fmt(D.e1.cases.sso_1030.summary.beta_max_deg, 1)}°</b> all year — the residual ` +
      `swing is the solar declination plus the equation of time, not a design error. ` +
      `The i = 53° shell sweeps <b>${fmt(l53.beta_min_deg, 0)}° to ${fmt(l53.beta_max_deg, 0)}°</b> ` +
      `and spends <b>${fmt(l53.eclipse_free_days, 1)} days</b> of the year with no eclipse at all, ` +
      `while the dawn–dusk orbit spends <b>${fmt(dd.eclipse_free_days, 0)} days</b> there. ` +
      `An annual mean hides both regimes; report the distribution instead.`;
  }
  register(draw);
})();

/* -- Table 2: reference orbits --------------------------------------------- */

(function refTable() {
  const rows = Object.entries(D.e1.cases).map(([k, v]) => ({ key: k, ...v.summary, title: v.title }));
  renderTable(document.getElementById("refTable"), {
    caption: "One simulated year (366 days) from 2024-01-01, 2048 samples per revolution",
    columns: [
      { label: "Orbit", get: (r) => r.title },
      { label: "i (deg)", get: (r) => fmt(r.inc_deg, 2), numeric: true },
      { label: "T (min)", get: (r) => fmt(r.nodal_period_min, 2), numeric: true },
      { label: "β range (deg)", get: (r) => `${fmt(r.beta_min_deg, 1)} … ${fmt(r.beta_max_deg, 1)}`, numeric: true },
      { label: "Mean ecl (min)", get: (r) => fmt(r.eclipse_mean_min, 2), numeric: true },
      { label: "Max ecl (min)", get: (r) => fmt(r.eclipse_max_min, 2), numeric: true },
      { label: "Duty cycle", get: (r) => fmt(r.duty_cycle_mean, 4), numeric: true },
      { label: "Min duty", get: (r) => fmt(r.duty_cycle_min, 4), numeric: true },
      { label: "Ecl-free (d)", get: (r) => fmt(r.eclipse_free_days, 1), numeric: true },
      { label: "Penumbra (s)", get: (r) => fmt(r.penumbra_mean_s, 1), numeric: true },
    ],
    rows,
  });
})();

/* =============================================================================
   Figure 6 -- SSO design grid
   ============================================================================= */

(function ssoGrid() {
  const g = D.e2;
  const metrics = {
    ecl: { label: "Mean eclipse (min)", get: (c) => c.eclipse_mean_min, fmt: (v) => fmt(v, 1) },
    duty: { label: "Duty cycle", get: (c) => c.duty_cycle_mean, fmt: (v) => fmt(v, 3) },
    free: { label: "Eclipse-free days", get: (c) => c.eclipse_free_days, fmt: (v) => fmt(v, 0) },
    beta: { label: "Max |β| (deg)", get: (c) => c.beta_abs_max_deg, fmt: (v) => fmt(v, 0) },
  };
  let metric = "duty";
  segmented(
    document.getElementById("gridControls"),
    Object.entries(metrics).map(([k, v]) => ({ label: v.label, value: k })),
    "duty",
    (v) => { metric = v; draw(); },
    "Metric"
  );

  function draw() {
    const M = metrics[metric];
    const values = g.grid.map((row) => row.map(M.get));
    heatmap(document.getElementById("ssoHeat"), {
      rows: g.altitudes_km.map((h) => ({ label: `${h} km` })),
      cols: g.ltan_hours.map((t) => ({
        label: `${String(Math.floor(t)).padStart(2, "0")}:${t % 1 ? "30" : "00"}`,
      })),
      values,
      cellW: 76, cellH: 46,
      colTitle: "LOCAL TIME OF ASCENDING NODE",
      rowTitle: "ALTITUDE",
      legendTitle: M.label.toUpperCase(),
      fmtCell: M.fmt,
      tipHtml: (r, c, v, i, j) => {
        const cell = g.grid[i][j];
        return `<div class="tt-h">${r.label} · LTAN ${c.label}</div>` +
          `<div class="row"><span>Inclination</span><span>${fmt(cell.inc_deg, 2)}°</span></div>` +
          `<div class="row"><span>Max |β|</span><span>${fmt(cell.beta_abs_max_deg, 1)}°</span></div>` +
          `<div class="row"><span>β*</span><span>${fmt(cell.beta_star_deg, 1)}°</span></div>` +
          `<div class="row"><span>Mean eclipse</span><span>${fmt(cell.eclipse_mean_min, 2)} min</span></div>` +
          `<div class="row"><span>Max eclipse</span><span>${fmt(cell.eclipse_max_min, 2)} min</span></div>` +
          `<div class="row"><span>Duty cycle</span><span>${fmt(cell.duty_cycle_mean, 4)}</span></div>` +
          `<div class="row"><span>Eclipse-free</span><span>${fmt(cell.eclipse_free_days, 1)} d</span></div>`;
      },
      ariaLabel: `${M.label} across local time of ascending node and altitude`,
    });
  }
  register(draw);

  const flat = g.grid.flat();
  const best = flat.reduce((a, b) => (b.duty_cycle_mean > a.duty_cycle_mean ? b : a));
  const worst = flat.reduce((a, b) => (b.duty_cycle_mean < a.duty_cycle_mean ? b : a));
  document.getElementById("gridNote").innerHTML =
    `Across the grid the annual duty cycle runs from <b>${fmt(worst.duty_cycle_mean, 3)}</b> ` +
    `(${worst.altitude_km} km, LTAN ${fmt(worst.ltan_hours, 1)}h) to ` +
    `<b>${fmt(best.duty_cycle_mean, 3)}</b> (${best.altitude_km} km, LTAN ` +
    `${fmt(best.ltan_hours, 1)}h) — a <b>${fmt(100 * (best.duty_cycle_mean / worst.duty_cycle_mean - 1), 0)} %</b> ` +
    `difference in harvested energy for the same array, from a choice that costs nothing. ` +
    `Local time dominates: moving from LTAN 12:00 to 06:00 buys far more than any ` +
    `altitude change inside this range. Hover any cell for its full record.`;
})();

/* -- Figure 7: annual eclipse profile by LTAN ------------------------------ */

(function ltanProfiles() {
  const g = D.e2;
  const rowIdx = g.altitudes_km.indexOf(600);
  const row = g.grid[rowIdx];
  const picks = [6.0, 7.0, 8.0, 10.5, 12.0];
  const sel = picks.map((t) => row[g.ltan_hours.indexOf(t)]).filter(Boolean);

  register(() => {
    legend(
      document.getElementById("ltanLegend"),
      sel.map((c, i) => ({
        label: `LTAN ${String(Math.floor(c.ltan_hours)).padStart(2, "0")}:${c.ltan_hours % 1 ? "30" : "00"}`,
        color: cssVar(ORD[i]),
      }))
    );
    lineChart(document.getElementById("ltanChart"), {
      height: 300,
      series: sel.map((c, i) => ({
        name: `LTAN ${fmt(c.ltan_hours, 1)}h`,
        color: cssVar(ORD[i]),
        points: c.eclipse_daily_min.map((v, d) => [d, v]),
      })),
      xDomain: [0, 365],
      yDomain: [0, 38],
      xTicks: MONTH_START,
      xLabel: "Day of year 2024",
      yLabel: "Eclipse per revolution  (min)",
      fmtXTick: monthTick,
      fmtYTick: (t) => t.toFixed(0),
      fmtValue: (v) => (v > 0 ? `${v.toFixed(2)} min` : "none"),
      fmtTipTitle: dayLabel,
      ariaLabel: "Annual eclipse duration profile at 600 km for five local times",
    });
  });
})();

/* =============================================================================
   Figure 8 -- inclination
   ============================================================================= */

(function inclination() {
  const cases = D.e3.cases;
  const picks = [28.5, 45, 53, 70, 87.9];
  const sel = picks.map((i) => cases.find((c) => Math.abs(c.inc_deg - i) < 0.05)).filter(Boolean);
  let mode = "beta";
  segmented(
    document.getElementById("incControls"),
    [{ label: "Beta angle", value: "beta" }, { label: "Eclipse duration", value: "ecl" }],
    "beta",
    (v) => { mode = v; draw(); },
    "Show"
  );

  function draw() {
    legend(
      document.getElementById("incLegend"),
      sel.map((c, i) => ({
        label: `i = ${fmt(c.inc_deg, 1)}°  ·  β cycle ${fmt(c.beta_cycle_days, 0)} d`,
        color: cssVar(ORD[i]),
      }))
    );
    const isB = mode === "beta";
    lineChart(document.getElementById("incChart"), {
      height: 330,
      series: sel.map((c, i) => ({
        name: `i = ${fmt(c.inc_deg, 1)}°`,
        color: cssVar(ORD[i]),
        points: (isB ? c.beta_daily : c.eclipse_daily_min).map((v, d) => [d, v]),
      })),
      xDomain: [0, 365],
      yDomain: isB ? [-92, 92] : [0, 38],
      xTicks: MONTH_START,
      yTicks: isB ? [-90, -60, -30, 0, 30, 60, 90] : undefined,
      xLabel: "Day of year 2024",
      yLabel: isB ? "Solar beta angle  (deg)" : "Eclipse per revolution  (min)",
      rules: isB
        ? [{ y: 69.0, label: "β* (550 km)", color: cssVar("--ink-3") },
           { y: -69.0, color: cssVar("--ink-3") }]
        : [],
      fmtXTick: monthTick,
      fmtYTick: (t) => (isB ? `${t}°` : t.toFixed(0)),
      fmtValue: (v) => (isB ? `${v.toFixed(2)}°` : v > 0 ? `${v.toFixed(2)} min` : "none"),
      fmtTipTitle: dayLabel,
      ariaLabel: isB
        ? "Beta angle over one year for five inclinations at 550 km"
        : "Eclipse duration over one year for five inclinations at 550 km",
    });
  }
  register(draw);

  const c53 = cases.find((c) => Math.abs(c.inc_deg - 53) < 0.05);
  document.getElementById("incNote").innerHTML =
    `At i = 53° the node regresses about 5° per day against the Sun's 1°, so the ` +
    `geometry repeats every <b>${fmt(c53.beta_cycle_days, 1)} days</b> — roughly ` +
    `<b>${fmt(365 / c53.beta_cycle_days, 1)} full beta cycles per year</b>, each with its own ` +
    `eclipse-free window and its own worst case. Raising the inclination lengthens the ` +
    `cycle until, near 97–98°, the two rates match and the cycle becomes the year itself: ` +
    `that limit is the sun-synchronous condition.`;
})();

/* -- Table 3: inclination sweep -------------------------------------------- */

(function incTable() {
  renderTable(document.getElementById("incTable"), {
    caption: "Circular orbits at 550 km, one simulated year",
    columns: [
      { label: "i (deg)", get: (r) => fmt(r.inc_deg, 1), numeric: true },
      { label: "β cycle (d)", get: (r) => (r.beta_cycle_days > 3000 ? "∞" : fmt(r.beta_cycle_days, 1)), numeric: true },
      { label: "β min (deg)", get: (r) => fmt(r.beta_min_deg, 1), numeric: true },
      { label: "β max (deg)", get: (r) => fmt(r.beta_max_deg, 1), numeric: true },
      { label: "Mean ecl (min)", get: (r) => fmt(r.eclipse_mean_min, 2), numeric: true },
      { label: "Max ecl (min)", get: (r) => fmt(r.eclipse_max_min, 2), numeric: true },
      { label: "Duty cycle", get: (r) => fmt(r.duty_cycle_mean, 4), numeric: true },
      { label: "Min duty", get: (r) => fmt(r.duty_cycle_min, 4), numeric: true },
      { label: "Ecl-free (d/yr)", get: (r) => fmt(r.eclipse_free_days, 1), numeric: true },
    ],
    rows: D.e3.cases,
  });
})();

/* =============================================================================
   Figures 9-11 -- Walker constellations
   ============================================================================= */

(function constellations() {
  const cs = D.e5.constellations;
  const keys = Object.keys(cs);
  const shortName = (k) => cs[k].title.split(":")[0].replace("Walker ", "");
  // Spread of the annual duty cycle across the planes that were simulated.
  // Divide by the number of simulated planes, not the shell's plane count --
  // large shells are sub-sampled.
  const dutySpread = (c) => {
    const v = c.plane_spread.duty_cycle_mean;
    const mean = v.reduce((a, b) => a + b, 0) / v.length;
    return (100 * (Math.max(...v) - Math.min(...v))) / mean;
  };

  /* -- Figure 9: plane x day field of eclipse duration --------------------- */
  let mSel = keys[0];
  segmented(
    document.getElementById("matrixControls"),
    keys.map((k) => ({ label: shortName(k), value: k })),
    keys[0],
    (v) => { mSel = v; drawMatrix(); },
    "Shell"
  );

  function drawMatrix() {
    const c = cs[mSel];
    const values = c.planes.map((p) => p.eclipse_daily_min);
    matrixPlot(document.getElementById("planeMatrix"), {
      values,
      rowLabels: c.planes.map((p) =>
        c.pattern === "star" && c.inc_deg > 95
          ? `LTAN ${p.ltan_hours.toFixed(1)}h`
          : `Ω ${p.raan_deg.toFixed(0)}°`
      ),
      cellW: 1.9,
      cellH: Math.max(9, Math.min(20, 320 / c.planes.length)),
      leftPad: 92,
      colTicks: MONTH_START.map((d, i) => ({ at: d, label: MONTHS[i] })),
      xLabel: "Day of year 2024",
      rowTitle: "ORBITAL PLANE",
      legendTitle: "ECLIPSE PER REVOLUTION (MIN)",
      vmin: 0,
      fmtLegend: (v) => v.toFixed(0),
      tipHtml: (i, j, v) => {
        const p = c.planes[i];
        return `<div class="tt-h">Plane ${p.plane_index} · ${dayLabel(j)}</div>` +
          `<div class="row"><span>RAAN</span><span>${fmt(p.raan_deg, 1)}°</span></div>` +
          `<div class="row"><span>LTAN</span><span>${fmt(p.ltan_hours, 2)} h</span></div>` +
          `<div class="row"><span>Beta</span><span>${fmt(p.beta_daily[j], 1)}°</span></div>` +
          `<div class="row"><span>Eclipse</span><span>${v > 0 ? fmt(v, 2) + " min" : "none"}</span></div>`;
      },
      ariaLabel: `Eclipse duration per revolution for each plane of ${c.title} across one year`,
    });

    const sso = c.inc_deg > 95;
    const spread = dutySpread(c);
    document.getElementById("matrixNote").innerHTML =
      `<b>${c.title}.</b> Each row is one orbital plane, each column one day; ` +
      `colour is that plane's mean eclipse duration on that day. ` +
      (sso
        ? `Because the shell is sun-synchronous, every plane's node is locked to its own ` +
          `local time, so the bands are <b>horizontal and permanent</b>: a plane near ` +
          `06:00 stays eclipse-free for most of the year while a plane near noon never is. ` +
          `The annual duty cycle therefore differs by <b>${fmt(spread, 1)} %</b> across the shell, ` +
          `for the entire mission.`
        : `All planes share one nodal regression rate, so they traverse the <em>same</em> beta ` +
          `cycle offset only in phase: the bands run <b>diagonally</b>. Every plane eventually ` +
          `sees every condition, and the annual duty cycle varies by just ` +
          `<b>${fmt(spread, 1)} %</b> across the shell &mdash; but on any given day the planes ` +
          `are in completely different states.`) +
      ` ${c.planes.length} of ${c.n_planes} planes shown` +
      (c.planes.length < c.n_planes ? ", sampled uniformly in RAAN." : ".");
  }
  register(drawMatrix);

  /* -- Figure 10: annual uniformity vs instantaneous spread ---------------- */
  register(() => {
    stripPlot(document.getElementById("planeStrip"), {
      leftPad: 210,
      rowH: 62,
      groups: keys.map((k) => {
        const c = cs[k];
        return {
          label: shortName(k),
          sub: `${c.n_total} sats · ${c.n_planes} planes · ${c.altitude_km} km`,
          values: c.plane_spread.duty_cycle_mean,
          color: cssVar("--s1"),
          key: k,
        };
      }),
      xLabel: "Annual mean illumination duty cycle per plane",
      fmtXTick: (t) => t.toFixed(2),
      fmtSpread: (lo, hi, mean) => `spread ${(100 * (hi - lo) / mean).toFixed(1)} %`,
      tipHtml: (grp, v, k) => {
        const c = cs[grp.key];
        const p = c.planes[k];
        return `<div class="tt-h">${grp.label} · plane ${p.plane_index}</div>` +
          `<div class="row"><span>RAAN</span><span>${fmt(p.raan_deg, 1)}°</span></div>` +
          `<div class="row"><span>LTAN</span><span>${fmt(p.ltan_hours, 2)} h</span></div>` +
          `<div class="row"><span>Duty cycle</span><span>${fmt(v, 4)}</span></div>` +
          `<div class="row"><span>Mean eclipse</span><span>${fmt(p.eclipse_mean_min, 2)} min</span></div>` +
          `<div class="row"><span>Max |β|</span><span>${fmt(p.beta_abs_max_deg, 1)}°</span></div>` +
          `<div class="row"><span>Eclipse-free</span><span>${fmt(p.eclipse_free_days, 1)} d</span></div>`;
      },
      ariaLabel: "Per-plane annual duty cycle for four Walker constellations",
    });

    // Day-by-day spread across the planes of the Delta shell.  One shell only:
    // two overlapping translucent bands hide each other, and the annual
    // contrast is already carried by the strip plot above.
    const envKey = keys[0];
    const envC = cs[envKey];
    const nDays = envC.planes[0].eclipse_daily_min.length;
    const lo = [], hi = [], mean = [];
    for (let d = 0; d < nDays; d++) {
      const col = envC.planes.map((p) => p.eclipse_daily_min[d]);
      lo.push([d, Math.min(...col)]);
      hi.push([d, Math.max(...col)]);
      mean.push([d, col.reduce((a, b) => a + b, 0) / col.length]);
    }
    const envColor = cssVar("--s1");
    legend(document.getElementById("envLegend"), [
      { label: `${shortName(envKey)} - across-plane mean on each day`, color: envColor },
      { label: "band = full spread across the shell's planes that day",
        color: cssVar("--s1-soft") },
    ]);
    lineChart(document.getElementById("planeEnvelope"), {
      height: 280,
      series: [{ name: "Across-plane mean", color: envColor, points: mean }],
      envelopes: [{ upper: hi, lower: lo, fill: envColor, opacity: 0.18 }],
      xDomain: [0, 365],
      yDomain: [0, 40],
      xTicks: MONTH_START,
      xLabel: "Day of year 2024",
      yLabel: "Eclipse per revolution  (min)",
      fmtXTick: monthTick,
      fmtYTick: (t) => t.toFixed(0),
      fmtValue: (v) => (v > 0 ? `${v.toFixed(2)} min` : "none"),
      fmtTipTitle: dayLabel,
      ariaLabel: `Daily spread of eclipse duration across the planes of ${envC.title}`,
    });

  });

  const delta = cs[keys[0]];
  const ssoKey = keys.find((k) => cs[k].inc_deg > 95);
  const ssoC = ssoKey ? cs[ssoKey] : null;
  document.getElementById("stripNote").innerHTML =
    `Top: one dot per simulated plane, the bar spanning their range, the rule at the ` +
    `constellation mean. Bottom: the ${shortName(keys[0])} shell resolved in time &mdash; ` +
    `the line is the across-plane mean for that day, the band the full spread across its ` +
    `planes on that day. The two views disagree on purpose. Annually the Delta shell is ` +
    `almost uniform (<b>${fmt(dutySpread(delta), 1)} %</b> spread) because all its planes ` +
    `regress at one rate and merely sit at different phases of the same beta cycle; yet on ` +
    `most days its planes span nearly the whole range from full eclipse to none. ` +
    (ssoC
      ? `The sun-synchronous shell is the opposite case: <b>${fmt(dutySpread(ssoC), 1)} %</b> ` +
        `annual spread that never closes, because sun-synchrony pins each plane to its own ` +
        `local time for the whole mission. Placing a workload across the first shell is a ` +
        `timing problem; across the second it is a placement problem, and the placement is ` +
        `fixed at launch.`
      : "");

  /* -- Figure 11: instantaneous aggregate --------------------------------- */
  let sel = keys[0];
  segmented(
    document.getElementById("constControls"),
    keys.map((k) => ({ label: shortName(k), value: k })),
    keys[0],
    (v) => { sel = v; drawAgg(); },
    "Shell"
  );

  function drawAgg() {
    const c = cs[sel];
    const a = c.aggregate;
    lineChart(document.getElementById("constChart"), {
      height: 280,
      series: [{
        name: "Sunlit fraction",
        color: cssVar("--sunlit"),
        points: a.t_hours.map((t, i) => [t, a.sunlit_fraction[i]]),
        area: true, areaFill: cssVar("--sunlit"), areaOpacity: 0.16,
      }],
      xDomain: [0, 72],
      yDomain: [0, 1.02],
      xTicks: [0, 12, 24, 36, 48, 60, 72],
      yTicks: [0, 0.25, 0.5, 0.75, 1],
      xLabel: "Hours from epoch",
      yLabel: "Fraction of the constellation in sunlight",
      rules: [{ y: a.mean, label: `mean ${a.mean.toFixed(3)}`, color: cssVar("--ink-3") }],
      fmtXTick: (t) => `${t}h`,
      fmtYTick: (t) => t.toFixed(2),
      fmtValue: (v) => v.toFixed(4),
      fmtTipTitle: (t) => `t + ${t.toFixed(2)} h`,
      ariaLabel: `Instantaneous sunlit fraction of ${c.title} over three days`,
    });
    document.getElementById("constNote").innerHTML =
      `<b>${c.title}.</b> Over three days the sunlit share of the ${c.n_total}-satellite ` +
      `shell stays between <b>${fmt(a.min, 3)}</b> and <b>${fmt(a.max, 3)}</b> about a mean ` +
      `of <b>${fmt(a.mean, 3)}</b> — a peak-to-peak swing of only ` +
      `<b>${fmt(100 * a.peak_to_peak, 1)} percentage points</b>. Aggregating over enough ` +
      `planes and phases smooths the constellation's total generating capacity almost flat, ` +
      `even though each satellite is switching between full sun and full shadow every ` +
      `${fmt(D.e1.cases.leo_53.summary.nodal_period_min, 0)} minutes. The constellation is a ` +
      `steady power source made of violently unsteady ones — which is precisely why ` +
      `energy-aware placement across planes pays, and why a per-satellite average does not ` +
      `describe either level.`;
  }
  register(drawAgg);

  /* -- plane data table ---------------------------------------------------- */
  const wrap = document.getElementById("tblWrap9");
  const rows = keys.flatMap((k) => cs[k].planes.map((p) => ({ c: cs[k], p })));
  renderTable(wrap, {
    caption: "Simulated planes (large shells are sub-sampled uniformly in RAAN)",
    columns: [
      { label: "Constellation", get: (r) => r.c.title.split(":")[0] },
      { label: "Plane", get: (r) => fmtInt(r.p.plane_index), numeric: true },
      { label: "RAAN (deg)", get: (r) => fmt(r.p.raan_deg, 1), numeric: true },
      { label: "LTAN (h)", get: (r) => fmt(r.p.ltan_hours, 2), numeric: true },
      { label: "Max |β| (deg)", get: (r) => fmt(r.p.beta_abs_max_deg, 1), numeric: true },
      { label: "Mean ecl (min)", get: (r) => fmt(r.p.eclipse_mean_min, 2), numeric: true },
      { label: "Duty cycle", get: (r) => fmt(r.p.duty_cycle_mean, 4), numeric: true },
      { label: "Ecl-free (d/yr)", get: (r) => fmt(r.p.eclipse_free_days, 1), numeric: true },
    ],
    rows,
  });
  attachTableToggle(document.getElementById("tblBtn9"), wrap);
})();

/* =============================================================================
   Figure 12 & Table 4 -- power
   ============================================================================= */

(function power() {
  const e6 = D.e6;
  const models = ["two_axis", "single_axis_pitch", "single_axis_yaw", "body_box6_norm"];
  const labels = e6.power_system.array_labels;
  const keys = Object.keys(e6.cases);

  register(() => {
    legend(
      document.getElementById("powerLegend"),
      models.map((m, i) => ({ label: labels[m], color: cssVar(CAT4[i]) })),
      "block"
    );
    groupedBars(document.getElementById("powerBars"), {
      height: 320,
      groups: keys.map((k) => ({
        label: e6.cases[k].title.replace(", ", "\n"),
        values: models.map((m) => e6.cases[k].arrays[m].p_gen_mean_w),
      })),
      seriesNames: models.map((m) => labels[m]),
      colors: CAT4.map(cssVar),
      yLabel: "Orbit-average generated power  (W)",
      fmtValue: (v) => `${v.toFixed(1)} W`,
      fmtYTick: (t) => t.toFixed(0),
      directLabels: true,
      rules: [{ y: e6.power_system.load_w, label: `load ${e6.power_system.load_w} W` }],
      ariaLabel: "Orbit-average generated power by orbit and array pointing model",
    });
  });

  const dd = e6.cases.sso_dawn_dusk.arrays;
  const ss = e6.cases.sso_1030.arrays;
  const l53 = e6.cases.leo_53.arrays;
  document.getElementById("powerNote").innerHTML =
    `Array area, cell efficiency and degradation are identical across every bar; only ` +
    `the orbit and the pointing architecture change. The result is that <b>no single ` +
    `array architecture wins</b>. A pitch-axis drive nulls the in-plane Sun angle, so it ` +
    `is strong at 10:30 (<b>${fmt(ss.single_axis_pitch.p_gen_mean_w, 0)} W</b>) and ` +
    `collapses at dawn-dusk (<b>${fmt(dd.single_axis_pitch.p_gen_mean_w, 0)} W</b> mean, ` +
    `<b>${fmt(dd.single_axis_pitch.p_gen_min_w, 1)} W</b> in the worst revolution) because ` +
    `|&#x3b2;| near 90&deg; is exactly the component it cannot reach. A yaw-axis drive is the ` +
    `mirror image: <b>${fmt(dd.single_axis_yaw.p_gen_mean_w, 0)} W</b> at dawn-dusk against ` +
    `<b>${fmt(ss.single_axis_yaw.p_gen_mean_w, 0)} W</b> at 10:30. The dawn-dusk orbit's ` +
    `illumination advantage is real &mdash; <b>${fmt(100 * (dd.two_axis.p_gen_mean_w / ss.two_axis.p_gen_mean_w - 1), 0)} %</b> ` +
    `more energy with two-axis wings &mdash; but it is only collectable by an architecture ` +
    `matched to its beta angle. Reporting illumination without an array model does not ` +
    `overstate or understate the answer consistently; it makes the comparison meaningless.`;
})();

(function epsTable() {
  const e6 = D.e6;
  const models = ["two_axis", "single_axis_pitch", "single_axis_yaw", "body_box6_norm"];
  const labels = e6.power_system.array_labels;
  let orbit = Object.keys(e6.cases)[0];

  segmented(
    document.getElementById("epsControls"),
    Object.keys(e6.cases).map((k) => ({ label: e6.cases[k].title, value: k })),
    orbit,
    (v) => { orbit = v; draw(); },
    "Orbit"
  );

  function draw() {
    const c = e6.cases[orbit];
    renderTable(document.getElementById("epsTable"), {
      caption:
        `${c.title} · array ${e6.power_system.array_area_m2} m², ` +
        `${fmt(100 * e6.power_system.cell_efficiency, 0)} % cells, ` +
        `${e6.power_system.battery_capacity_wh} Wh battery, ` +
        `${e6.power_system.load_w} W load (${e6.power_system.housekeeping_w} W bus + ` +
        `${e6.power_system.payload_w} W payload), DoD limit ` +
        `${fmt(100 * e6.power_system.dod_limit, 0)} %`,
      columns: [
        { label: "Array pointing", get: (r) => labels[r.m] },
        { label: "Mean P_gen (W)", get: (r) => fmt(r.d.p_gen_mean_w, 1), numeric: true },
        { label: "Worst P_gen (W)", get: (r) => fmt(r.d.p_gen_min_w, 1), numeric: true },
        { label: "Mean margin", get: (r) => `${fmt(100 * r.d.margin_mean, 1)} %`, numeric: true },
        { label: "Worst margin", get: (r) => `${fmt(100 * r.d.margin_worst, 1)} %`, numeric: true },
        { label: "Min SoC", get: (r) => fmt(r.d.soc_min, 3), numeric: true },
        { label: "Max DoD", get: (r) => `${fmt(100 * r.d.dod_max, 1)} %`, numeric: true },
        { label: "Battery needed (Wh)", get: (r) => fmt(r.d.battery_wh_required, 0), numeric: true },
        { label: "Array needed (m²)", get: (r) => (Number.isFinite(r.d.array_m2_required) ? fmt(r.d.array_m2_required, 2) : "∞"), numeric: true },
        { label: "Cycles / yr", get: (r) => fmtInt(r.d.eclipse_cycles_per_year), numeric: true },
      ],
      rows: models.map((m) => ({ m, d: c.arrays[m] })),
    });

    const sap = c.arrays.single_axis_pitch;
    document.getElementById("epsNote").innerHTML =
      `&ldquo;Battery needed&rdquo; sizes the worst simulated revolution to the ` +
      `${fmt(100 * e6.power_system.dod_limit, 0)} % depth-of-discharge limit; ` +
      `&ldquo;array needed&rdquo; is the area for a non-negative balance in the worst ` +
      `revolution with a 10 % margin. With a single-axis drive this orbit needs ` +
      `<b>${fmt(sap.battery_wh_required, 0)} Wh</b> and ` +
      `<b>${fmt(sap.array_m2_required, 2)} m²</b>, and cycles the battery ` +
      `<b>${fmtInt(sap.eclipse_cycles_per_year)}</b> times a year — the cycle count that ` +
      `drives LEO battery life, and the reason the DoD limit is set as low as it is.`;
  }
  register(draw);
})();

/* =============================================================================
   Tables 5 & 6 -- validation and sensitivity
   ============================================================================= */

(function valTable() {
  const rows = D.validation.filter((r) => r.expected !== undefined);
  renderTable(document.getElementById("valTable"), {
    caption: "experiments/validate.py — every check must pass before results are generated",
    columns: [
      { label: "Check", get: (r) => r.check },
      { label: "Computed", get: (r) => fmt(r.value, 5), numeric: true },
      { label: "Reference", get: (r) => fmt(r.expected, 5), numeric: true },
      { label: "Tolerance", get: (r) => r.tolerance.toExponential(0), numeric: true },
      { label: "Unit", get: (r) => r.unit || "—" },
      { label: "Result", get: (r) => (r.pass ? "PASS" : "FAIL") },
    ],
    rows,
  });
})();

(function sensTable() {
  const sm = D.e6.shadow_model;
  const ha = D.e6.h_atm_sensitivity;
  const rows = [];
  const ref = sm.fractional;
  for (const [k, v] of Object.entries(sm)) {
    rows.push({
      choice: "Shadow model",
      value: k,
      ecl: v.eclipse_mean_min,
      duty: v.duty_cycle_mean,
      delta: 100 * (v.duty_cycle_mean / ref.duty_cycle_mean - 1),
      note: k === "cylindrical" ? "point-source Sun, no penumbra"
        : k === "conical" ? "dual cone, penumbra counted as full eclipse"
        : "fractional solar-disc occultation (used throughout)",
    });
  }
  const refH = ha["90"];
  for (const [k, v] of Object.entries(ha)) {
    rows.push({
      choice: "Opaque atmosphere",
      value: `${k} km`,
      ecl: v.eclipse_mean_min,
      duty: v.duty_cycle_mean,
      delta: 100 * (v.duty_cycle_mean / refH.duty_cycle_mean - 1),
      note: k === "0" ? "solid Earth only"
        : k === "90" ? "used throughout — atmosphere opaque below ~90 km"
        : "sensitivity bound",
    });
  }
  renderTable(document.getElementById("sensTable"), {
    caption: "SSO 550 km, LTAN 10:30, one simulated year. Δ is against the adopted choice in each block.",
    columns: [
      { label: "Choice", get: (r) => r.choice },
      { label: "Setting", get: (r) => r.value },
      { label: "Mean eclipse (min)", get: (r) => fmt(r.ecl, 3), numeric: true },
      { label: "Duty cycle", get: (r) => fmt(r.duty, 5), numeric: true },
      { label: "Δ energy", get: (r) => `${r.delta >= 0 ? "+" : ""}${fmt(r.delta, 3)} %`, numeric: true },
      { label: "Meaning", get: (r) => r.note },
    ],
    rows,
  });
})();
