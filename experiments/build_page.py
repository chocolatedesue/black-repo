"""Assemble the single-file HTML report from the simulation results.

The artifact runtime forbids external resources other than Google Fonts, so the
stylesheet, both JavaScript modules and the entire result payload are inlined
into one document.  Series that the page never reads are dropped and the rest
are rounded, which keeps the page small without touching any reported value.

    python -m experiments.build_page
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
WEB = ROOT / "web"
OUT = WEB / "index.html"


def _ascii_html(text: str) -> str:
    """Escape non-ASCII as numeric character references.

    The published page supplies only the body; the surrounding <head> is added
    by the host, so the document cannot declare its own charset.  Emitting pure
    ASCII makes the page render identically whatever encoding the host assumes.
    """
    return "".join(c if ord(c) < 128 else f"&#x{ord(c):x};" for c in text)


def _ascii_js(text: str) -> str:
    """Escape non-ASCII as JavaScript unicode escapes.

    HTML character references are not decoded inside <script>, so script
    content needs the JavaScript escape form instead.
    """
    out = []
    for c in text:
        if ord(c) < 128:
            out.append(c)
        elif ord(c) > 0xFFFF:
            n = ord(c) - 0x10000
            out.append(f"\\u{0xD800 + (n >> 10):04x}\\u{0xDC00 + (n & 0x3FF):04x}")
        else:
            out.append(f"\\u{ord(c):04x}")
    return "".join(out)


def _round(obj, nd: int = 5):
    """Recursively round floats so the inlined JSON stays compact."""
    if isinstance(obj, float):
        return round(obj, nd)
    if isinstance(obj, list):
        return [_round(v, nd) for v in obj]
    if isinstance(obj, dict):
        return {k: _round(v, nd) for k, v in obj.items()}
    return obj


def _load(name: str) -> dict:
    path = RESULTS / f"{name}.json"
    if not path.exists():
        sys.exit(
            f"missing {path.name}. Run `python -m experiments.run_study` and "
            f"`python -m experiments.run_profiles` first."
        )
    return json.loads(path.read_text())


def _strip_summary(s: dict) -> dict:
    """Drop the per-array yield block the page does not read."""
    return {k: v for k, v in s.items() if k != "array_yield"}


def build_payload() -> dict:
    e1 = _load("e1_reference")
    e2 = _load("e2_sso_grid")
    e3 = _load("e3_inclination")
    e4 = _load("e4_altitude")
    e5 = _load("e5_constellations")
    e6 = _load("e6_energy")
    e7 = _load("e7_profiles")
    val = _load("validation")

    payload = {
        "epoch": e1["epoch"],
        "e1": {
            "cases": {
                k: {
                    "title": v["title"],
                    "summary": _strip_summary(v["summary"]),
                    "daily": {
                        kk: vv
                        for kk, vv in v["daily"].items()
                        if kk in ("beta_deg", "eclipse_min", "duty_cycle")
                    },
                }
                for k, v in e1["cases"].items()
            }
        },
        "e2": {
            "altitudes_km": e2["altitudes_km"],
            "ltan_hours": e2["ltan_hours"],
            "grid": [[_strip_summary(c) for c in row] for row in e2["grid"]],
        },
        "e3": {"cases": [_strip_summary(c) for c in e3["cases"]]},
        "e4": {"cases": [_strip_summary(c) for c in e4["cases"]]},
        "e5": {
            "constellations": {
                k: {
                    **{
                        kk: v[kk]
                        for kk in (
                            "title", "pattern", "altitude_km", "inc_deg",
                            "n_total", "n_planes", "phasing_f", "aggregate",
                            "plane_spread",
                        )
                    },
                    "planes": [
                        {
                            kk: p[kk]
                            for kk in (
                                "plane_index", "raan_deg", "ltan_hours",
                                "beta_abs_max_deg", "eclipse_mean_min",
                                "duty_cycle_mean", "eclipse_free_days",
                                "beta_daily", "eclipse_daily_min",
                            )
                        }
                        for p in v["planes"]
                    ],
                }
                for k, v in e5["constellations"].items()
            }
        },
        "e6": {
            "power_system": e6["power_system"],
            "shadow_model": e6["shadow_model"],
            "h_atm_sensitivity": e6["h_atm_sensitivity"],
            "cases": {
                k: {
                    "title": v["title"],
                    "arrays": {
                        m: {
                            kk: vv
                            for kk, vv in a.items()
                            if kk not in ("soc_daily", "p_gen_daily_w", "dod_daily")
                        }
                        for m, a in v["arrays"].items()
                    },
                }
                for k, v in e6["cases"].items()
            },
        },
        "e7": e7,
        "validation": val,
    }
    return _round(payload)


def _assemble(template_name: str, app_name: str, payload: dict, out_name: str) -> int:
    """Inline the stylesheet, both modules and the payload into one document."""
    template = (WEB / template_name).read_text()
    css = (WEB / "style.css").read_text()
    charts = (WEB / "charts.js").read_text()
    app = (WEB / app_name).read_text()

    # Concatenate the two modules: `charts.js` first with its exports turned into
    # plain declarations, then the page module with its import statement removed.
    # The published page is a single inline module, so cross-file imports cannot
    # be resolved at runtime.
    charts_inline = charts.replace("export function ", "function ").replace(
        "export const ", "const "
    )
    app_inline = app[app.index("} from \"./charts.js\";") + len('} from "./charts.js";'):]

    # json.dumps escapes non-ASCII by default, which is what the inline script needs.
    data_js = "window.DATA = " + json.dumps(payload, separators=(",", ":")) + ";\n"
    js = _ascii_js(data_js + charts_inline + "\n" + app_inline)

    non_ascii_css = [c for c in css if ord(c) > 127]
    if non_ascii_css:
        sys.exit(f"style.css contains non-ASCII characters: {set(non_ascii_css)}")

    html = _ascii_html(template).replace("/*__CSS__*/", css).replace("/*__JS__*/", js)
    if any(ord(c) > 127 for c in html):
        sys.exit(f"{out_name} is not pure ASCII")
    out = WEB / out_name
    out.write_text(html, encoding="ascii")
    size = out.stat().st_size / 1024
    print(f"wrote {out.relative_to(ROOT)}  ({size:.0f} kB)")
    return 1 if size > 16 * 1024 else 0


def build_scheduling_payload() -> dict:
    """Payload for the scheduling-bounds page: bounds plus the raw power traces."""
    sched = _load("scheduling")
    traces = {}
    for key, case in sched["cases"].items():
        path = RESULTS / case["trace_csv"]
        if not path.exists():
            sys.exit(f"missing {path.name}. Run `python -m experiments.export_traces`.")
        rows = [ln.split(",") for ln in path.read_text().strip().splitlines()[1:]]
        traces[key] = {
            "t_s": [float(r[0]) for r in rows],
            "p_gen_w": [float(r[3]) for r in rows],
            "eclipsed": [int(r[2]) for r in rows],
        }
    return _round({"sched": sched, "traces": traces})


def main() -> int:
    rc = _assemble("index.template.html", "app.js", build_payload(), "index.html")
    if (WEB / "scheduling.template.html").exists():
        rc |= _assemble(
            "scheduling.template.html", "app-scheduling.js",
            build_scheduling_payload(), "scheduling.html",
        )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
