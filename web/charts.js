/* =============================================================================
   Minimal SVG charting layer.

   No external libraries (the artifact CSP blocks them), no canvas: every mark
   is an SVG element so it stays crisp, themable through CSS custom properties,
   and inspectable.  Charts render into a fixed viewBox and scale to their
   container; pointer coordinates are mapped back through the SVG CTM so hover
   works at any width.
   ============================================================================= */

const NS = "http://www.w3.org/2000/svg";

export function svgEl(tag, attrs = {}, parent = null) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined) continue;
    n.setAttribute(k, String(v));
  }
  if (parent) parent.appendChild(n);
  return n;
}

export function htmlEl(tag, attrs = {}, parent = null) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined) continue;
    if (k === "text") n.textContent = v;
    else if (k === "html") n.innerHTML = v;
    else n.setAttribute(k, String(v));
  }
  if (parent) parent.appendChild(n);
  return n;
}

export const fmt = (v, d = 2) =>
  v === null || v === undefined || Number.isNaN(v) ? "--" : v.toFixed(d);

export const fmtInt = (v) => (Number.isFinite(v) ? Math.round(v).toString() : "--");

function _srgbToLin(c) {
  c /= 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

/** Relative luminance of a #rrggbb colour (WCAG 2.1). */
export function luminance(hex) {
  const h = hex.trim().replace("#", "");
  const n = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  const r = parseInt(n.slice(0, 2), 16);
  const g = parseInt(n.slice(2, 4), 16);
  const b = parseInt(n.slice(4, 6), 16);
  if ([r, g, b].some(Number.isNaN)) return 0.5;
  return 0.2126 * _srgbToLin(r) + 0.7152 * _srgbToLin(g) + 0.0722 * _srgbToLin(b);
}

/** Black or white ink, whichever has more contrast against `hex`. */
export function inkOn(hex) {
  const L = luminance(hex);
  const withWhite = 1.05 / (L + 0.05);
  const withBlack = (L + 0.05) / 0.05;
  return withWhite >= withBlack ? "#ffffff" : "#101216";
}

export function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/* -- scales ---------------------------------------------------------------- */

export function linScale(d0, d1, r0, r1) {
  const s = (x) => (d1 === d0 ? r0 : r0 + ((x - d0) / (d1 - d0)) * (r1 - r0));
  s.invert = (y) => (r1 === r0 ? d0 : d0 + ((y - r0) / (r1 - r0)) * (d1 - d0));
  s.domain = [d0, d1];
  s.range = [r0, r1];
  return s;
}

export function ticks(min, max, count = 6) {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) return [min];
  const span = max - min;
  const raw = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm >= 7.5 ? 10 : norm >= 3.5 ? 5 : norm >= 1.5 ? 2 : 1) * mag;
  const out = [];
  for (let t = Math.ceil(min / step) * step; t <= max + step * 1e-9; t += step) {
    out.push(Math.abs(t) < step * 1e-9 ? 0 : t);
  }
  return out;
}

/* -- tooltip --------------------------------------------------------------- */

function makeTooltip(container) {
  const tip = htmlEl("div", { class: "tooltip" }, container);
  return {
    node: tip,
    show(x, y, html) {
      tip.innerHTML = html;
      tip.classList.add("on");
      const cw = container.clientWidth;
      const tw = tip.offsetWidth;
      let left = x + 14;
      if (left + tw > cw - 4) left = x - tw - 14;
      if (left < 4) left = 4;
      tip.style.left = `${left}px`;
      tip.style.top = `${Math.max(4, y - tip.offsetHeight - 12)}px`;
    },
    hide() {
      tip.classList.remove("on");
    },
  };
}

function pointerToViewBox(svg, ev) {
  const ctm = svg.getScreenCTM();
  if (!ctm) return { x: 0, y: 0 };
  const pt = svg.createSVGPoint();
  pt.x = ev.clientX;
  pt.y = ev.clientY;
  const p = pt.matrixTransform(ctm.inverse());
  return { x: p.x, y: p.y };
}

/* =============================================================================
   Line chart -- multi-series, crosshair + shared tooltip
   ============================================================================= */

export function lineChart(container, opt) {
  const W = opt.width || 900;
  const H = opt.height || 340;
  const m = Object.assign({ t: 16, r: 20, b: 42, l: 56 }, opt.margin || {});
  container.innerHTML = "";
  container.classList.add("chart");

  const svg = svgEl(
    "svg",
    { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opt.ariaLabel || "" },
    container
  );
  const tip = makeTooltip(container);

  const series = opt.series.filter((s) => s.points && s.points.length);
  const allX = opt.xDomain || [
    Math.min(...series.flatMap((s) => s.points.map((p) => p[0]))),
    Math.max(...series.flatMap((s) => s.points.map((p) => p[0]))),
  ];
  const finiteY = series.flatMap((s) => s.points.map((p) => p[1])).filter(Number.isFinite);
  const allY = opt.yDomain || [Math.min(...finiteY), Math.max(...finiteY)];

  const x = linScale(allX[0], allX[1], m.l, W - m.r);
  const y = linScale(allY[0], allY[1], H - m.b, m.t);

  const xt = opt.xTicks || ticks(allX[0], allX[1], opt.xTickCount || 7);
  const yt = opt.yTicks || ticks(allY[0], allY[1], opt.yTickCount || 5);

  // grid
  const g = svgEl("g", {}, svg);
  for (const t of yt) {
    svgEl("line", { class: "grid-line", x1: m.l, x2: W - m.r, y1: y(t), y2: y(t) }, g);
  }
  svgEl("line", { class: "axis-line", x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b }, svg);

  for (const t of xt) {
    svgEl(
      "text",
      { class: "axis-text", x: x(t), y: H - m.b + 16, "text-anchor": "middle" },
      svg
    ).textContent = opt.fmtXTick ? opt.fmtXTick(t) : String(t);
  }
  for (const t of yt) {
    svgEl(
      "text",
      { class: "axis-text", x: m.l - 8, y: y(t) + 3.5, "text-anchor": "end" },
      svg
    ).textContent = opt.fmtYTick ? opt.fmtYTick(t) : String(t);
  }
  if (opt.xLabel) {
    svgEl(
      "text",
      { class: "axis-title", x: (m.l + W - m.r) / 2, y: H - 6, "text-anchor": "middle" },
      svg
    ).textContent = opt.xLabel;
  }
  if (opt.yLabel) {
    svgEl(
      "text",
      {
        class: "axis-title",
        x: 12,
        y: (m.t + H - m.b) / 2,
        "text-anchor": "middle",
        transform: `rotate(-90 12 ${(m.t + H - m.b) / 2})`,
      },
      svg
    ).textContent = opt.yLabel;
  }

  // reference rules
  for (const rule of opt.rules || []) {
    if (rule.y !== undefined) {
      svgEl(
        "line",
        {
          x1: m.l, x2: W - m.r, y1: y(rule.y), y2: y(rule.y),
          stroke: rule.color || cssVar("--line-strong"),
          "stroke-width": 1, "stroke-dasharray": rule.dash || "4 3",
        },
        svg
      );
      if (rule.label) {
        svgEl(
          "text",
          { class: "rule-text", x: W - m.r - 3, y: y(rule.y) - 5, "text-anchor": "end" },
          svg
        ).textContent = rule.label;
      }
    }
    if (rule.x !== undefined) {
      svgEl(
        "line",
        {
          x1: x(rule.x), x2: x(rule.x), y1: m.t, y2: H - m.b,
          stroke: rule.color || cssVar("--line-strong"),
          "stroke-width": 1, "stroke-dasharray": rule.dash || "4 3",
        },
        svg
      );
      if (rule.label) {
        const tx = svgEl(
          "text",
          {
            class: "rule-text", x: x(rule.x) + 5, y: m.t + 11,
            "text-anchor": rule.anchor || "start",
          },
          svg
        );
        tx.textContent = rule.label;
      }
    }
  }

  // filled bands between an upper and a lower series (min-max envelopes)
  for (const b of opt.envelopes || []) {
    const up = b.upper.filter((q) => Number.isFinite(q[1]));
    const lo = b.lower.filter((q) => Number.isFinite(q[1]));
    if (!up.length || !lo.length) continue;
    let d = "";
    up.forEach((q, i) => { d += `${i ? "L" : "M"}${x(q[0]).toFixed(2)} ${y(q[1]).toFixed(2)}`; });
    for (let i = lo.length - 1; i >= 0; i--) {
      d += `L${x(lo[i][0]).toFixed(2)} ${y(lo[i][1]).toFixed(2)}`;
    }
    svgEl("path", { d: d + "Z", fill: b.fill, opacity: b.opacity ?? 0.18 }, svg);
  }

  // bands (shaded x-ranges)
  for (const band of opt.bands || []) {
    svgEl(
      "rect",
      {
        x: x(band.x0), width: Math.max(0, x(band.x1) - x(band.x0)),
        y: m.t, height: H - m.b - m.t,
        fill: band.fill || cssVar("--eclipse-soft"),
      },
      svg
    );
    if (band.label) {
      svgEl(
        "text",
        {
          class: "rule-text", x: (x(band.x0) + x(band.x1)) / 2, y: m.t + 12,
          "text-anchor": "middle",
        },
        svg
      ).textContent = band.label;
    }
  }

  const path = (pts, close) => {
    let d = "";
    let pen = false;
    for (const [px, py] of pts) {
      if (!Number.isFinite(py)) { pen = false; continue; }
      d += `${pen ? "L" : "M"}${x(px).toFixed(2)} ${y(py).toFixed(2)}`;
      pen = true;
    }
    return d + (close || "");
  };

  for (const s of series) {
    if (s.area) {
      const base = y(Math.max(allY[0], 0));
      const pts = s.points.filter((p) => Number.isFinite(p[1]));
      if (pts.length) {
        const d =
          path(pts) +
          `L${x(pts[pts.length - 1][0]).toFixed(2)} ${base.toFixed(2)}` +
          `L${x(pts[0][0]).toFixed(2)} ${base.toFixed(2)}Z`;
        svgEl("path", { d, fill: s.areaFill || s.color, opacity: s.areaOpacity ?? 0.14 }, svg);
      }
    }
    svgEl(
      "path",
      {
        d: path(s.points),
        fill: "none",
        stroke: s.color,
        "stroke-width": s.width || 2,
        "stroke-dasharray": s.dash || null,
        "stroke-linejoin": "round",
        "stroke-linecap": "round",
      },
      svg
    );
    if (s.markers) {
      for (const [px, py] of s.points) {
        if (!Number.isFinite(py)) continue;
        svgEl(
          "circle",
          {
            cx: x(px), cy: y(py), r: 4.5, fill: s.color,
            stroke: cssVar("--surface"), "stroke-width": 2,
          },
          svg
        );
      }
    }
    if (s.endLabel) {
      const last = [...s.points].reverse().find((p) => Number.isFinite(p[1]));
      if (last) {
        svgEl(
          "text",
          {
            class: "series-label", x: x(last[0]) + 6, y: y(last[1]) + 4,
            fill: s.color, "text-anchor": "start",
          },
          svg
        ).textContent = s.endLabel;
      }
    }
  }

  // crosshair layer
  const hover = svgEl("g", { opacity: 0 }, svg);
  const vline = svgEl(
    "line",
    { y1: m.t, y2: H - m.b, stroke: cssVar("--ink-3"), "stroke-width": 1, "stroke-dasharray": "3 3" },
    hover
  );
  const dots = series.map((s) =>
    svgEl(
      "circle",
      { r: 4.5, fill: s.color, stroke: cssVar("--surface"), "stroke-width": 2 },
      hover
    )
  );

  const overlay = svgEl(
    "rect",
    {
      x: m.l, y: m.t, width: W - m.r - m.l, height: H - m.b - m.t,
      fill: "transparent", style: "cursor:crosshair",
    },
    svg
  );

  function nearest(sx) {
    const xv = x.invert(sx);
    let best = null;
    for (const s of series) {
      let lo = 0, hi = s.points.length - 1;
      while (hi - lo > 1) {
        const mid = (lo + hi) >> 1;
        if (s.points[mid][0] < xv) lo = mid; else hi = mid;
      }
      const cand = Math.abs(s.points[lo][0] - xv) < Math.abs(s.points[hi][0] - xv) ? lo : hi;
      if (best === null) best = s.points[cand][0];
    }
    return best;
  }

  function move(ev) {
    const p = pointerToViewBox(svg, ev);
    if (p.x < m.l || p.x > W - m.r) return;
    const xv = nearest(p.x);
    hover.setAttribute("opacity", 1);
    vline.setAttribute("x1", x(xv));
    vline.setAttribute("x2", x(xv));
    let rows = "";
    series.forEach((s, i) => {
      const pt = s.points.reduce((a, b) =>
        Math.abs(b[0] - xv) < Math.abs(a[0] - xv) ? b : a
      );
      if (Number.isFinite(pt[1])) {
        dots[i].setAttribute("cx", x(pt[0]));
        dots[i].setAttribute("cy", y(pt[1]));
        dots[i].setAttribute("opacity", 1);
        rows +=
          `<div class="row"><span><span class="dot" style="background:${s.color}"></span>` +
          `${s.name}</span><span>${opt.fmtValue ? opt.fmtValue(pt[1]) : fmt(pt[1])}</span></div>`;
      } else {
        dots[i].setAttribute("opacity", 0);
      }
    });
    const rect = container.getBoundingClientRect();
    tip.show(
      ev.clientX - rect.left,
      ev.clientY - rect.top,
      `<div class="tt-h">${opt.fmtTipTitle ? opt.fmtTipTitle(xv) : String(xv)}</div>${rows}`
    );
  }

  overlay.addEventListener("pointermove", move);
  overlay.addEventListener("pointerdown", move);
  overlay.addEventListener("pointerleave", () => {
    hover.setAttribute("opacity", 0);
    tip.hide();
  });

  return { svg, x, y };
}

/* =============================================================================
   Heatmap
   ============================================================================= */

export function heatmap(container, opt) {
  container.innerHTML = "";
  container.classList.add("chart");
  const cols = opt.cols, rows = opt.rows, vals = opt.values;
  const cw = opt.cellW || 78, ch = opt.cellH || 46;
  const m = { t: 34, r: 16, b: 40, l: 92 };
  const W = m.l + cols.length * cw + m.r;
  const H = m.t + rows.length * ch + m.b;

  const svg = svgEl(
    "svg",
    { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opt.ariaLabel || "",
      style: `min-width:${Math.min(W, 760)}px` },
    container
  );
  const tip = makeTooltip(container);

  const flat = vals.flat().filter(Number.isFinite);
  const vmin = opt.vmin ?? Math.min(...flat);
  const vmax = opt.vmax ?? Math.max(...flat);
  const ramp = (opt.ramp || ["--seq-0","--seq-1","--seq-2","--seq-3","--seq-4","--seq-5","--seq-6","--seq-7"]).map(cssVar);

  const color = (v) => {
    if (!Number.isFinite(v)) return cssVar("--surface-2");
    const t = Math.max(0, Math.min(1, (v - vmin) / (vmax - vmin || 1)));
    return ramp[Math.min(ramp.length - 1, Math.round(t * (ramp.length - 1)))];
  };


  rows.forEach((r, i) => {
    svgEl(
      "text",
      { class: "axis-text", x: m.l - 10, y: m.t + i * ch + ch / 2 + 3.5, "text-anchor": "end" },
      svg
    ).textContent = r.label;
  });
  cols.forEach((c, j) => {
    svgEl(
      "text",
      { class: "axis-text", x: m.l + j * cw + cw / 2, y: m.t - 12, "text-anchor": "middle" },
      svg
    ).textContent = c.label;
  });
  if (opt.colTitle) {
    svgEl("text", { class: "axis-title", x: m.l, y: 12 }, svg).textContent = opt.colTitle;
  }
  if (opt.rowTitle) {
    svgEl(
      "text",
      { class: "axis-title", x: 12, y: m.t + (rows.length * ch) / 2,
        "text-anchor": "middle",
        transform: `rotate(-90 12 ${m.t + (rows.length * ch) / 2})` },
      svg
    ).textContent = opt.rowTitle;
  }

  rows.forEach((r, i) => {
    cols.forEach((c, j) => {
      const v = vals[i][j];
      // 2px surface gap between cells (the mark spacer rule)
      const rect = svgEl(
        "rect",
        {
          x: m.l + j * cw + 1, y: m.t + i * ch + 1,
          width: cw - 2, height: ch - 2, rx: 2,
          fill: color(v), style: "cursor:pointer",
        },
        svg
      );
      svgEl(
        "text",
        {
          class: "axis-text",
          x: m.l + j * cw + cw / 2, y: m.t + i * ch + ch / 2 + 3.5,
          "text-anchor": "middle",
          fill: inkOn(color(v)),
          style: "pointer-events:none",
        },
        svg
      ).textContent = opt.fmtCell ? opt.fmtCell(v) : fmt(v, 1);

      const show = (ev) => {
        const rc = container.getBoundingClientRect();
        tip.show(ev.clientX - rc.left, ev.clientY - rc.top, opt.tipHtml(r, c, v, i, j));
      };
      rect.addEventListener("pointermove", show);
      rect.addEventListener("pointerenter", show);
      rect.addEventListener("pointerleave", () => tip.hide());
    });
  });

  // legend
  const lw = 150, lx = m.l, ly = H - 22;
  const gid = `gr${Math.random().toString(36).slice(2, 8)}`;
  const defs = svgEl("defs", {}, svg);
  const lg = svgEl("linearGradient", { id: gid, x1: 0, x2: 1, y1: 0, y2: 0 }, defs);
  ramp.forEach((c, i) =>
    svgEl("stop", { offset: i / (ramp.length - 1), "stop-color": c }, lg)
  );
  svgEl("rect", { x: lx, y: ly, width: lw, height: 9, rx: 2, fill: `url(#${gid})` }, svg);
  svgEl("text", { class: "axis-text", x: lx, y: ly + 22 }, svg).textContent =
    opt.fmtCell ? opt.fmtCell(vmin) : fmt(vmin, 1);
  svgEl("text", { class: "axis-text", x: lx + lw, y: ly + 22, "text-anchor": "end" }, svg)
    .textContent = opt.fmtCell ? opt.fmtCell(vmax) : fmt(vmax, 1);
  svgEl("text", { class: "axis-title", x: lx + lw + 12, y: ly + 9 }, svg).textContent =
    opt.legendTitle || "";

  return svg;
}

/* =============================================================================
   Strip plot -- one dot per member, with a mean rule
   ============================================================================= */

export function stripPlot(container, opt) {
  container.innerHTML = "";
  container.classList.add("chart");
  const W = opt.width || 900;
  const rowH = opt.rowH || 62;
  const m = { t: 14, r: 26, b: 44, l: opt.leftPad || 150 };
  const H = m.t + opt.groups.length * rowH + m.b;

  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": opt.ariaLabel || "" }, container);
  const tip = makeTooltip(container);

  const all = opt.groups.flatMap((g) => g.values);
  const dom = opt.xDomain || [Math.min(...all), Math.max(...all)];
  const pad = (dom[1] - dom[0]) * 0.08 || 1;
  const x = linScale(dom[0] - pad, dom[1] + pad, m.l, W - m.r);
  const xt = ticks(dom[0] - pad, dom[1] + pad, 6);

  for (const t of xt) {
    svgEl("line", { class: "grid-line", x1: x(t), x2: x(t), y1: m.t, y2: H - m.b }, svg);
    svgEl("text", { class: "axis-text", x: x(t), y: H - m.b + 17, "text-anchor": "middle" }, svg)
      .textContent = opt.fmtXTick ? opt.fmtXTick(t) : fmt(t, 2);
  }
  if (opt.xLabel) {
    svgEl("text", { class: "axis-title", x: (m.l + W - m.r) / 2, y: H - 8,
      "text-anchor": "middle" }, svg).textContent = opt.xLabel;
  }

  opt.groups.forEach((grp, i) => {
    const cy = m.t + i * rowH + rowH / 2;
    svgEl("line", { class: "axis-line", x1: m.l, x2: W - m.r, y1: cy + rowH / 2 - 2,
      y2: cy + rowH / 2 - 2, opacity: 0.5 }, svg);

    const lbl = svgEl("text", { class: "axis-text", x: m.l - 12, y: cy - 10,
      "text-anchor": "end", fill: cssVar("--ink") }, svg);
    lbl.textContent = grp.label;
    if (grp.sub) {
      svgEl("text", { class: "axis-text", x: m.l - 12, y: cy + 5, "text-anchor": "end" }, svg)
        .textContent = grp.sub;
    }

    const vmin = Math.min(...grp.values), vmax = Math.max(...grp.values);
    const mean = grp.values.reduce((a, b) => a + b, 0) / grp.values.length;

    // range bar
    svgEl("rect", {
      x: x(vmin), y: cy - 4, width: Math.max(2, x(vmax) - x(vmin)), height: 8, rx: 4,
      fill: grp.color, opacity: 0.16,
    }, svg);

    grp.values.forEach((v, k) => {
      const c = svgEl("circle", {
        cx: x(v), cy, r: 4, fill: grp.color, "fill-opacity": 0.85,
        stroke: cssVar("--surface"), "stroke-width": 1.5, style: "cursor:pointer",
      }, svg);
      const show = (ev) => {
        const rc = container.getBoundingClientRect();
        tip.show(ev.clientX - rc.left, ev.clientY - rc.top,
          opt.tipHtml(grp, v, k));
      };
      c.addEventListener("pointerenter", show);
      c.addEventListener("pointermove", show);
      c.addEventListener("pointerleave", () => tip.hide());
    });

    svgEl("line", { x1: x(mean), x2: x(mean), y1: cy - 13, y2: cy + 13,
      stroke: cssVar("--ink"), "stroke-width": 2 }, svg);

    if (opt.fmtSpread) {
      svgEl("text", {
        class: "axis-text", x: m.l - 12, y: cy + 20, "text-anchor": "end",
        fill: cssVar("--ink-2"),
      }, svg).textContent = opt.fmtSpread(vmin, vmax, mean);
    }
  });

  return svg;
}

/* =============================================================================
   Grouped bars
   ============================================================================= */

export function groupedBars(container, opt) {
  container.innerHTML = "";
  container.classList.add("chart");
  const W = opt.width || 900;
  const H = opt.height || 300;
  const m = Object.assign({ t: 18, r: 20, b: 56, l: 62 }, opt.margin || {});

  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": opt.ariaLabel || "" }, container);
  const tip = makeTooltip(container);

  const maxV = opt.yMax ?? Math.max(...opt.groups.flatMap((g) => g.values));
  const y = linScale(0, maxV, H - m.b, m.t);
  const yt = ticks(0, maxV, 5);
  for (const t of yt) {
    svgEl("line", { class: "grid-line", x1: m.l, x2: W - m.r, y1: y(t), y2: y(t) }, svg);
    svgEl("text", { class: "axis-text", x: m.l - 8, y: y(t) + 3.5, "text-anchor": "end" }, svg)
      .textContent = opt.fmtYTick ? opt.fmtYTick(t) : fmt(t, 0);
  }
  svgEl("line", { class: "axis-line", x1: m.l, x2: W - m.r, y1: y(0), y2: y(0) }, svg);
  if (opt.yLabel) {
    svgEl("text", { class: "axis-title", x: 12, y: (m.t + H - m.b) / 2,
      "text-anchor": "middle",
      transform: `rotate(-90 12 ${(m.t + H - m.b) / 2})` }, svg).textContent = opt.yLabel;
  }

  const gw = (W - m.l - m.r) / opt.groups.length;
  const nSeries = opt.seriesNames.length;
  const bw = Math.min(46, (gw - 22) / nSeries);

  opt.groups.forEach((g, i) => {
    const gx = m.l + i * gw;
    g.values.forEach((v, k) => {
      const bx = gx + (gw - nSeries * bw - (nSeries - 1) * 2) / 2 + k * (bw + 2);
      const bh = Math.max(1, y(0) - y(v));
      const r = svgEl("path", {
        d: roundedTopBar(bx, y(v), bw, bh, 4),
        fill: opt.colors[k], style: "cursor:pointer",
      }, svg);
      const show = (ev) => {
        const rc = container.getBoundingClientRect();
        tip.show(ev.clientX - rc.left, ev.clientY - rc.top,
          `<div class="tt-h">${g.label}</div><div class="row"><span>` +
          `<span class="dot" style="background:${opt.colors[k]}"></span>` +
          `${opt.seriesNames[k]}</span><span>${opt.fmtValue(v)}</span></div>`);
      };
      r.addEventListener("pointerenter", show);
      r.addEventListener("pointermove", show);
      r.addEventListener("pointerleave", () => tip.hide());

      if (opt.directLabels) {
        svgEl("text", {
          class: "axis-text", x: bx + bw / 2, y: y(v) - 6, "text-anchor": "middle",
          fill: cssVar("--ink"),
        }, svg).textContent = opt.fmtValue(v);
      }
    });
    const t = svgEl("text", {
      class: "axis-text", x: gx + gw / 2, y: H - m.b + 17, "text-anchor": "middle",
      fill: cssVar("--ink-2"),
    }, svg);
    (g.label.split("\n")).forEach((line, li) => {
      svgEl("tspan", { x: gx + gw / 2, dy: li === 0 ? 0 : 13 }, t).textContent = line;
    });
  });

  if (opt.rules) {
    for (const rl of opt.rules) {
      svgEl("line", {
        x1: m.l, x2: W - m.r, y1: y(rl.y), y2: y(rl.y),
        stroke: rl.color || cssVar("--critical"), "stroke-width": 1.5,
        "stroke-dasharray": "5 3",
      }, svg);
      svgEl("text", { class: "rule-text", x: W - m.r, y: y(rl.y) - 6,
        "text-anchor": "end", fill: rl.color || cssVar("--critical") }, svg)
        .textContent = rl.label;
    }
  }
  return svg;
}

function roundedTopBar(x, y, w, h, r) {
  const rr = Math.min(r, w / 2, h);
  return (
    `M${x} ${y + h}L${x} ${y + rr}Q${x} ${y} ${x + rr} ${y}` +
    `L${x + w - rr} ${y}Q${x + w} ${y} ${x + w} ${y + rr}L${x + w} ${y + h}Z`
  );
}

/* =============================================================================
   Data table (the accessible fallback for every chart)
   ============================================================================= */

export function renderTable(container, { caption, columns, rows }) {
  container.innerHTML = "";
  const wrap = htmlEl("div", { class: "scroll-x" }, container);
  const t = htmlEl("table", {}, wrap);
  if (caption) htmlEl("caption", { text: caption }, t);
  const thead = htmlEl("thead", {}, t);
  const tr = htmlEl("tr", {}, thead);
  columns.forEach((c) =>
    htmlEl("th", { text: c.label, class: c.numeric ? "n" : "" }, tr)
  );
  const tb = htmlEl("tbody", {}, t);
  rows.forEach((r) => {
    const row = htmlEl("tr", {}, tb);
    columns.forEach((c) =>
      htmlEl("td", { text: c.get(r), class: c.numeric ? "n" : "" }, row)
    );
  });
  return t;
}

export function attachTableToggle(button, wrap) {
  button.addEventListener("click", () => {
    const on = wrap.classList.toggle("on");
    button.textContent = on ? "Hide data table" : "Show data table";
    button.setAttribute("aria-expanded", String(on));
  });
}

/* =============================================================================
   Matrix plot -- a dense (rows x columns) field with no per-cell text.
   Used for plane x day fields where a labelled heatmap would be unreadable.
   ============================================================================= */

export function matrixPlot(container, opt) {
  container.innerHTML = "";
  container.classList.add("chart");
  const nR = opt.values.length, nC = opt.values[0].length;
  const m = { t: 14, r: 20, b: 76, l: opt.leftPad || 96 };
  const cw = opt.cellW || 2.4, chh = opt.cellH || 13;
  const W = m.l + nC * cw + m.r;
  const H = m.t + nR * chh + m.b;

  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": opt.ariaLabel || "", style: `min-width:${Math.min(W, 820)}px` }, container);
  const tip = makeTooltip(container);

  const flat = opt.values.flat().filter(Number.isFinite);
  const vmin = opt.vmin ?? Math.min(...flat);
  const vmax = opt.vmax ?? Math.max(...flat);
  const ramp = (opt.ramp || ["--seq-0","--seq-1","--seq-2","--seq-3","--seq-4","--seq-5","--seq-6","--seq-7"]).map(cssVar);
  const color = (v) => {
    if (!Number.isFinite(v)) return cssVar("--surface-2");
    const t = Math.max(0, Math.min(1, (v - vmin) / (vmax - vmin || 1)));
    return ramp[Math.min(ramp.length - 1, Math.round(t * (ramp.length - 1)))];
  };

  for (let i = 0; i < nR; i++) {
    for (let j = 0; j < nC; j++) {
      svgEl("rect", {
        x: m.l + j * cw, y: m.t + i * chh + 0.5,
        width: cw + 0.4, height: chh - 1,
        fill: color(opt.values[i][j]), "shape-rendering": "crispEdges",
      }, svg);
    }
    svgEl("text", { class: "axis-text", x: m.l - 8, y: m.t + i * chh + chh / 2 + 3.5,
      "text-anchor": "end" }, svg).textContent = opt.rowLabels[i];
  }

  for (const t of opt.colTicks || []) {
    svgEl("line", { x1: m.l + t.at * cw, x2: m.l + t.at * cw,
      y1: m.t + nR * chh, y2: m.t + nR * chh + 4, class: "axis-line" }, svg);
    svgEl("text", { class: "axis-text", x: m.l + t.at * cw,
      y: m.t + nR * chh + 17, "text-anchor": "middle" }, svg).textContent = t.label;
  }
  if (opt.xLabel) {
    svgEl("text", { class: "axis-title", x: (m.l + W - m.r) / 2,
      y: m.t + nR * chh + 36, "text-anchor": "middle" }, svg).textContent = opt.xLabel;
  }
  if (opt.rowTitle) {
    svgEl("text", { class: "axis-title", x: 12, y: m.t + (nR * chh) / 2,
      "text-anchor": "middle",
      transform: `rotate(-90 12 ${m.t + (nR * chh) / 2})` }, svg).textContent = opt.rowTitle;
  }

  const cursor = svgEl("rect", {
    x: 0, y: 0, width: cw + 1, height: chh, fill: "none",
    stroke: cssVar("--ink"), "stroke-width": 1.5, opacity: 0,
    "pointer-events": "none",
  }, svg);

  const overlay = svgEl("rect", {
    x: m.l, y: m.t, width: nC * cw, height: nR * chh,
    fill: "transparent", style: "cursor:crosshair",
  }, svg);

  const move = (ev) => {
    const p = pointerToViewBox(svg, ev);
    const j = Math.max(0, Math.min(nC - 1, Math.floor((p.x - m.l) / cw)));
    const i = Math.max(0, Math.min(nR - 1, Math.floor((p.y - m.t) / chh)));
    cursor.setAttribute("x", m.l + j * cw - 0.5);
    cursor.setAttribute("y", m.t + i * chh);
    cursor.setAttribute("opacity", 1);
    const rc = container.getBoundingClientRect();
    tip.show(ev.clientX - rc.left, ev.clientY - rc.top, opt.tipHtml(i, j, opt.values[i][j]));
  };
  overlay.addEventListener("pointermove", move);
  overlay.addEventListener("pointerdown", move);
  overlay.addEventListener("pointerleave", () => {
    cursor.setAttribute("opacity", 0);
    tip.hide();
  });

  // legend
  const lw = 150, lx = m.l, ly = H - 30;
  const gid = `mg${Math.random().toString(36).slice(2, 8)}`;
  const defs = svgEl("defs", {}, svg);
  const lg = svgEl("linearGradient", { id: gid, x1: 0, x2: 1, y1: 0, y2: 0 }, defs);
  ramp.forEach((c, i) => svgEl("stop", { offset: i / (ramp.length - 1), "stop-color": c }, lg));
  svgEl("rect", { x: lx, y: ly, width: lw, height: 9, rx: 2, fill: `url(#${gid})` }, svg);
  svgEl("text", { class: "axis-text", x: lx, y: ly + 21 }, svg).textContent = opt.fmtLegend(vmin);
  svgEl("text", { class: "axis-text", x: lx + lw, y: ly + 21, "text-anchor": "end" }, svg)
    .textContent = opt.fmtLegend(vmax);
  svgEl("text", { class: "axis-title", x: lx + lw + 12, y: ly + 9 }, svg).textContent =
    opt.legendTitle || "";

  return svg;
}
