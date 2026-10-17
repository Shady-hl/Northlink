"""Local SVG reference views. No remote tiles, fonts, JavaScript or image calls."""
from __future__ import annotations

import html
import json
from functools import lru_cache
from pathlib import Path
from .mapgeo import project as proj, K, MERCATOR_ORIGIN, METRES_PER_UNIT
from . import topomap

COLORS = {"conflict": "#bd9cff", "restriction": "#ff8683", "advisory": "#f4c16b",
          "needs_confirmation": "#f4c16b", "no_match": "#8da9be"}

STYLE = """
<style>
@import none;
.stApp {background:#0a1421;color:#e6edf4}
[data-testid="stSidebar"] {background:#101e2d;border-right:1px solid #223348}
.block-container {padding-top:1.1rem;padding-bottom:2rem;max-width:1580px}
h1,h2,h3 {letter-spacing:-.025em} h1 {font-size:2.1rem!important}
[data-testid="stMetric"] {padding:8px 14px;background:#112131;border:1px solid #263b50;border-radius:12px}
[data-testid="stMetricLabel"] {font-size:.78rem;color:#9fb2c3}
[data-testid="stMetricValue"] {font-size:1.55rem}
.nl-eyebrow {font-size:11px;letter-spacing:.17em;font-weight:700;color:#67d6c0;margin-bottom:8px}
.nl-brand {font-weight:750;font-size:22px;letter-spacing:.13em;margin:0 0 4px}
.nl-sub {color:#a4b7c8;font-size:13px;line-height:1.5;margin:0}
.nl-status {border:1px solid #335465;border-radius:99px;padding:6px 12px;color:#89ddce;font-size:11px;display:inline-block}
.nl-card {padding:13px 16px;border:1px solid #2b4055;border-left:3px solid var(--tone);border-radius:10px;background:#112131;margin:0 0 9px}
.nl-card-top {display:flex;justify-content:space-between;gap:10px;color:var(--tone);font-size:10px;font-weight:750;letter-spacing:.07em}
.nl-card h4 {margin:7px 0 3px;font-size:14px;line-height:1.4;color:#e8eff5;font-weight:650}
.nl-card p {margin:5px 0 0;color:#a9bccc;font-size:11px;line-height:1.5}
.nl-map {border:1px solid #2b4055;background:#101f30;border-radius:14px;overflow:hidden;margin:0 0 12px}
.nl-map-head {padding:15px 18px 0;color:#e0ebf2;font-size:13px;font-weight:650}
.nl-map-sub {padding:5px 18px 5px;color:#8ea9bd;font-size:11px}
.nl-map svg {display:block;width:100%;height:auto}
[data-testid="stTabs"] {margin-top:14px}
[data-testid="stExpander"] {border-color:#2b4055}
</style>
""".replace("@import none;", "")


STYLE += """
<style>
.stApp {background:#0c121b;color:#dde5ee}
[data-testid="stHeader"] {height:0!important;background:transparent!important;pointer-events:none}
[data-testid="stToolbar"] {display:flex!important;position:fixed;left:10px;top:12px;right:auto;width:32px;pointer-events:auto}
[data-testid="stToolbarActions"],[data-testid="stAppDeployButton"],[data-testid="stMainMenu"] {display:none!important}
[data-testid="stSidebarHeader"] {position:sticky;top:0;z-index:20;background:#101e2d}
[data-testid="stSidebarCollapseButton"], [data-testid="stSidebarCollapseButton"] button {visibility:visible!important;opacity:1!important}
.block-container {padding:1rem 1.75rem 2rem;max-width:1740px}
h1,h2,h3,h4 {letter-spacing:-.02em}
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {gap:.55rem}
.desk-brand {font-size:18px;font-weight:750;letter-spacing:.11em;white-space:nowrap;padding-left:32px}
.desk-brand span {display:block;font-size:10px;font-weight:500;letter-spacing:.16em;color:#8e9cab;margin:3px 0 0 22px}
.desk-local {text-align:right;font-size:10px;letter-spacing:.11em;color:#9ab4c6}
.desk-local span {display:block;letter-spacing:0;font-size:11px;color:#758698;margin-top:4px}
.desk-mode {display:flex;justify-content:space-between;gap:12px;border-block:1px solid #283340;padding:8px 0;
 font-size:10px;letter-spacing:.06em;color:#b3c1cf}
.desk-mode span:first-child {color:#dfc58e}
.desk-counts {display:flex;gap:24px;padding:2px 0 4px;font-size:11px;color:#91a2b4}
.desk-counts strong {color:#e3edf6;font-size:16px;font-weight:650;margin-right:4px}
.st-key-exercise-notice [data-testid="stAlert"] {padding:3px 10px;background:#29251b;border:1px solid #4e4431}
.st-key-exercise-notice [data-testid="stAlert"] p {font-size:11px;line-height:1.4}
.st-key-exercise-notice [data-testid="stAlert"] > div {padding:4px 8px;background:transparent}
[data-testid="stTabs"] {margin-top:0}
[data-baseweb="tab-list"] {gap:20px;border-bottom:1px solid #283340}
[data-baseweb="tab"] {font-size:12px;padding:9px 0}
[data-testid="stButton"] button {border-radius:6px;min-height:34px;font-size:12px;box-shadow:none}
[data-testid="stTextInput"] input,[data-baseweb="select"] {font-size:12px}
[data-testid="stTextArea"] textarea {font-size:12px;line-height:1.4}
[data-testid="stWidgetLabel"] p {font-size:11px;color:#a0b0c0}
.st-key-delivery-queue {background:#101923;border:1px solid #293543;border-radius:8px;padding:12px!important;
 gap:.3rem!important;max-height:calc(100vh - 230px);overflow-y:auto;scrollbar-width:thin}
.st-key-delivery-queue [data-testid="stVerticalBlock"] {gap:.35rem}
.st-key-delivery-queue [data-testid="stButton"] button {justify-content:flex-start;text-align:left;padding:8px 10px;height:auto;min-height:42px}
.st-key-delivery-queue [data-testid="stButton"] button p {font-size:12px;line-height:1.3}
.st-key-delivery-queue [data-testid="stCaptionContainer"] p {font-size:10px;line-height:1.4;padding-left:2px}
.st-key-desk-inspector {border-left:1px solid #293543;padding-left:16px!important;gap:.45rem!important}
.desk-section {font-size:10px;font-weight:650;letter-spacing:.12em;color:#8fa2b5;margin:2px 0 8px;text-transform:uppercase}
.desk-selection {font-size:20px;font-weight:700;color:#eef4fa;margin:5px 0 3px}
.desk-subtitle {font-size:12px;color:#a6b5c4;line-height:1.5;margin-bottom:10px}
.desk-status {border:1px solid #364557;border-left:3px solid var(--tone);padding:9px 10px;border-radius:5px;
 font-size:12px;line-height:1.5;color:#dfe8f0;background:#121c28;margin:8px 0}
.desk-status strong {color:var(--tone)}
.desk-reason {font-size:12px;line-height:1.55;color:#b4c2d0;margin:10px 0}
.desk-next {font-size:12px;line-height:1.5;color:#dfebf5;padding:9px 10px;background:#182737;border-radius:5px;margin-bottom:12px}
.desk-fact {display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid #25303c;padding:7px 0;font-size:11px}
.desk-fact span {color:#8ea0b2}.desk-fact strong {font-weight:500;text-align:right;color:#d7e2ed;overflow-wrap:anywhere}
[data-testid="stForm"] {border-color:#304052;border-radius:7px;padding:12px}
[data-testid="stAlert"] {border-radius:6px;font-size:12px}
[data-testid="stExpander"] {border-color:#293543;border-radius:6px}
[data-testid="stExpander"] summary p {font-size:12px}
@media (max-width:1100px) {.block-container {padding-inline:1rem}.desk-brand{font-size:15px}.desk-counts{gap:15px}.st-key-desk-inspector{padding-left:10px!important}}
</style>
"""

# Map-led workspace: public product screenshots inform the arrangement, not the
# symbols, branding or an implication of military certification.
STYLE += """
<style>
.stApp {background:#f3f5f6;color:#203342}
.block-container {padding:.65rem 1rem 1.5rem;max-width:1920px}
.st-key-desk-header {background:#10445c;border-bottom:3px solid #0b7698;padding:9px 14px!important;border-radius:3px;gap:0!important}
.desk-brand {color:#fff;font-size:19px;letter-spacing:.08em;line-height:1.2}
.desk-brand span {display:inline;font-size:10px;color:#b2d1df;margin-left:10px;letter-spacing:.1em}
.desk-local {color:#c1dce8}.desk-local span {color:#99bfce}
.st-key-desk-header [data-baseweb="select"] > div {background:#0d374d;color:white;border-color:#38687b}
.st-key-desk-header input {color:#173b51!important}
[data-testid="stToolbar"] {top:24px;left:24px}
[data-testid="stExpandSidebarButton"] {position:fixed!important;top:30px!important;left:27px!important;z-index:10000;pointer-events:auto}
[data-testid="stExpandSidebarButton"] span {color:#d8ebf4!important}
[data-testid="stSidebar"] {background:#e9eef1;border-color:#bdcbd3}
[data-testid="stSidebarHeader"] {background:#e9eef1}
.desk-mode {border-color:#cfdae0;font-size:10px;color:#556d7b;padding:5px 0}
.desk-mode span:first-child {color:#66522a}
.desk-counts {gap:24px;color:#586d7b;padding:0}.desk-counts strong {color:#173b51;font-size:15px}
[role="tablist"] {border-color:#c5d2da;gap:22px}
[data-testid="stTab"] {font-size:12px;color:#455f70;padding:7px 0}
[data-testid="stTab"][aria-selected="true"] {color:#00678b;font-weight:650}
.st-key-desk-toolbox {background:#e6ebee;border:1px solid #bfccd4;border-radius:3px;padding:0!important;overflow:hidden}
.toolbox-heading {padding:13px 14px;border-bottom:1px solid #becbd3;font-size:16px;font-weight:650;background:#d9e1e6;color:#203b4c}
.toolbox-heading span {float:right;font-size:9px;letter-spacing:.1em;color:#5d7585;padding-top:5px}
.st-key-desk-toolbox [role="tablist"] {padding-inline:13px;gap:22px}
.st-key-desk-toolbox [data-testid="stTab"] {font-size:12px}
.st-key-desk-toolbox [data-testid="stTabPanel"] {padding:10px 12px;height:calc(100vh - 330px);min-height:360px;overflow-y:auto;scrollbar-width:thin}
.st-key-delivery-queue {background:transparent;border:0;border-radius:0;padding:0!important;max-height:none;overflow:visible}
.st-key-delivery-queue [data-testid="stButton"] button {border-radius:3px;border-color:#bdccd5;background:#f6f8f9;color:#213f52;min-height:43px}
.st-key-delivery-queue [data-testid="stButton"] button[kind="primary"] {background:#d0e8f1;border-color:#147b9c;color:#075d7d;border-left:4px solid #087b9c}
.st-key-delivery-queue [data-testid="stButton"] button > div {width:100%;text-align:left}
.st-key-delivery-queue [data-testid="stCaptionContainer"] p {color:#586e7d}
.st-key-desk-inspector {border:0;padding:0!important}
.desk-section {color:#557181;margin-bottom:6px}
.desk-selection {color:#173e55;font-size:20px;margin-top:2px}.desk-subtitle {color:#536e7e}
.desk-status {background:#fff;border-color:#c4d2dc;color:#243f51;border-left-color:var(--tone)}
.desk-status strong {color:#263e50}
.desk-reason {color:#435d6e;line-height:1.5}.desk-next {color:#183f55;background:#d5e5ed;margin-bottom:8px}
.desk-fact {border-color:#c9d5dd}.desk-fact span {color:#597181}.desk-fact strong {color:#213f51}
[data-testid="stWidgetLabel"] p {color:#4d687a}
[data-testid="stForm"] {border-color:#c1d0da;background:#f4f7f9;padding:10px;border-radius:3px}
[data-testid="stExpander"] {border-color:#c6d2da;border-radius:3px}
.st-key-desk-toolbox [data-testid="stMarkdownContainer"] table {font-size:10px;overflow-wrap:anywhere}
.st-key-desk-toolbox [data-testid="stMarkdownContainer"] th,.st-key-desk-toolbox [data-testid="stMarkdownContainer"] td {padding:5px 4px}
.nl-card {background:#e8eff3;border-color:#b5c8d4}.nl-card h4 {color:#1b3d52}.nl-card p {color:#4b697c}
.st-key-exercise-notice [data-testid="stAlert"] {background:#fff4dc;border-color:#e3d1a2;color:#655022}
@media (max-width:1100px) {.desk-brand span{display:none}.desk-local span{display:none}.block-container{padding-inline:.65rem}}
@media (max-width:640px) {.st-key-desk-toolbox [data-testid="stTabPanel"]{height:auto;max-height:520px;min-height:0}.desk-local{display:none}.desk-mode{flex-wrap:wrap}.desk-counts{flex-wrap:wrap;gap:5px 14px}}
</style>
"""

STYLE += """
<style>
.st-key-evidence-workspace,.st-key-raw-workspace,.st-key-brief-workspace,.st-key-sources-workspace,.st-key-intake-workspace {
 max-width:1440px;gap:.75rem!important;padding-top:6px}
.panel-heading {border-bottom:1px solid #cbd6dd;padding:6px 0 12px;margin-bottom:2px}
.panel-eyebrow {font-size:10px;color:#5c7687;letter-spacing:.12em;font-weight:650;text-transform:uppercase}
.panel-heading h2 {font-size:21px!important;line-height:1.3!important;color:#193e54;margin:5px 0!important;padding:0!important;font-weight:650}
.panel-heading p {font-size:12px;color:#577080;line-height:1.5;margin:0}
.panel-facts {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border:1px solid #cad6de;background:#e8eef2;border-radius:4px;margin:0 0 10px}
.panel-facts>div {padding:10px 12px;border-right:1px solid #ccd7de;min-width:0}
.panel-facts>div:last-child {border-right:0}.panel-facts span {display:block;font-size:10px;color:#5b7485;margin-bottom:4px}
.panel-facts strong {display:block;font-size:12px;color:#213e50;font-weight:600;overflow-wrap:anywhere}
.st-key-evidence-workspace [data-testid="stMarkdownContainer"] p,
.st-key-evidence-workspace [data-testid="stMarkdownContainer"] li,
.st-key-brief-workspace [data-testid="stMarkdownContainer"] p,
.st-key-sources-workspace [data-testid="stMarkdownContainer"] p,
.st-key-intake-workspace [data-testid="stMarkdownContainer"] p {font-size:13px;line-height:1.5}
.st-key-evidence-workspace [data-testid="stCaptionContainer"] p,
.st-key-sources-workspace [data-testid="stCaptionContainer"] p,
.st-key-intake-workspace [data-testid="stCaptionContainer"] p {font-size:11px;line-height:1.45}
.st-key-evidence-workspace h3,.st-key-sources-workspace h3,.st-key-intake-workspace h3 {font-size:16px!important;line-height:1.4!important;padding:3px 0 8px!important}
.st-key-evidence-workspace [data-testid="stAlert"],.st-key-intake-workspace [data-testid="stAlert"] {padding:8px 10px}
.st-key-evidence-workspace [data-testid="stAlert"] p {font-size:12px;line-height:1.5}
.st-key-decision-summary {background:#e6edf2;border:1px solid #c2d0da;border-radius:4px;padding:13px!important;gap:.55rem!important}
.st-key-decision-summary [data-testid="stButton"] button {min-height:40px}
.st-key-evidence-workspace [data-testid="stExpander"] summary p {font-size:12px;font-weight:600}
.st-key-evidence-workspace [data-testid="stExpander"] pre {white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px}
.st-key-raw-workspace pre {font-size:12px}
.st-key-brief-workspace h1 {font-size:21px!important}.st-key-brief-workspace h2 {font-size:17px!important}
.st-key-sources-workspace [data-testid="stVerticalBlock"] {gap:.6rem}
@media(max-width:900px){.panel-facts{grid-template-columns:repeat(2,minmax(0,1fr))}.panel-facts>div:nth-child(2){border-right:0}.panel-facts>div:nth-child(-n+2){border-bottom:1px solid #ccd7de}}
@media(max-width:640px){.panel-heading h2{font-size:19px!important}}
</style>
"""


def card(ident: str, title: str, category: str, state: str, detail: str) -> str:
    e = html.escape
    names = {"conflict": "CONFLICTING REPORTS", "restriction": "REPORTED RESTRICTION",
             "advisory": "POTENTIAL WEATHER IMPACT", "needs_confirmation": "NEEDS CONFIRMATION",
             "no_match": "NO MATCHING IMPACT"}
    return (f'<div class="nl-card" style="--tone:{COLORS[category]}"><div class="nl-card-top">'
            f'<span>{e(ident)} · {names[category]}</span><span>{e(state.upper())}</span></div>'
            f'<h4>{e(title)}</h4><p>{e(detail)}</p></div>')


def schematic(statuses: dict | None = None) -> str:
    paths = ["M78 220 C220 220 220 90 415 90 L625 90",
             "M78 220 C250 220 340 190 625 190",
             "M78 220 C230 220 350 300 625 300"]
    colors = ["#f4c16b", "#ff8683", "#bd9cff"]
    labels = [("C1 · weather advisory", 65), ("C2 · reported restriction", 165), ("C3 · conflicting reports", 275)]
    if statuses:
        names = {"no_match": "no matching impact", "advisory": "potential advisory impact", "restriction": "reported restriction", "conflict": "conflicting reports", "needs_confirmation": "needs confirmation"}
        colors = [COLORS[statuses[c]] for c in ("C1", "C2", "C3")]
        labels = [(f"{c} · {names[statuses[c]]}", y) for c, y in zip(("C1", "C2", "C3"), (65, 165, 275))]
    s = ['<svg viewBox="0 0 720 370" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Fictional corridor reference diagram">',
         '<defs><pattern id="grid" width="35" height="35" patternUnits="userSpaceOnUse"><path d="M35 0H0V35" fill="none" stroke="#24384b" stroke-width=".5"/></pattern></defs>',
         '<rect width="720" height="370" fill="url(#grid)"/>']
    for p, c, (label, y) in zip(paths, colors, labels):
        s.extend([f'<path d="{p}" fill="none" stroke="{c}" stroke-width="3" opacity=".85"/>',
                  f'<text x="355" y="{y}" fill="{c}" font-size="13" font-family="system-ui">{label}</text>',
                  f'<circle cx="625" cy="{y+25}" r="7" fill="{c}"/>'])
    s.extend(['<circle cx="78" cy="220" r="13" fill="#101f30" stroke="#70d6c4" stroke-width="3"/>',
              '<text x="35" y="253" fill="#c4d8e5" font-size="12" font-family="system-ui">Supply hub</text>',
              '<text x="26" y="28" fill="#8da9be" font-size="10" font-family="system-ui" letter-spacing="2">FICTIONAL EXERCISE · NOT A NAVIGATION MAP</text>',
              '</svg>'])
    return ''.join(s)


def geography(geometry: dict, selected_site: str | None = None) -> str:
    from .replay import SITES
    def xy(lon, lat):
        return 36 + (lon - 17) / 17 * 648, 315 - (lat - 68.8) / 3.7 * 280
    def path(ring):
        return "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in (xy(*p[:2]) for p in ring)) + "Z"
    s = ['<svg viewBox="0 0 720 370" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Recorded MET warning polygon and fictional delivery-site points in Northern Norway">',
         '<defs><clipPath id="bounds"><rect x="20" y="20" width="680" height="310" rx="8"/></clipPath></defs>',
         '<rect width="720" height="370" fill="#101f30"/>']
    for lon in range(18, 35, 2):
        x, _ = xy(lon, 70)
        s.append(f'<path d="M{x:.1f} 20V330" stroke="#20384b"/><text x="{x:.1f}" y="347" fill="#7694aa" font-size="10" font-family="system-ui">{lon}°E</text>')
    for lat in (69, 70, 71, 72):
        _, y = xy(20, lat)
        s.append(f'<path d="M20 {y:.1f}H700" stroke="#20384b"/><text x="4" y="{y-4:.1f}" fill="#7694aa" font-size="10" font-family="system-ui">{lat}°</text>')
    s.append('<g clip-path="url(#bounds)">')
    base = json.loads((Path(__file__).resolve().parent.parent / "assets" / "north-region.geojson").read_text())
    for f in base["features"]:
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for p in polys:
            s.append(f'<path d="{path(p[0])}" fill="#1e3441" stroke="#496473" stroke-width="1"/>')
    polys = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    for p in polys:
        s.append(f'<path d="{" ".join(path(ring) for ring in p)}" fill="#eebc61" fill-opacity=".18" fill-rule="evenodd" stroke="#efc477" stroke-width="2" stroke-dasharray="6 4"/>')
    s.extend(['<text x="180" y="240" fill="#658392" font-size="12" font-family="system-ui" letter-spacing="3">NORTHERN NORWAY</text>',
              '<text x="440" y="85" fill="#f2ce91" font-size="11" font-family="system-ui">Recorded warning area</text>'])
    for ident, site in SITES.items():
        x, y = xy(site["lon"], site["lat"])
        if selected_site == ident:
            s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="18" fill="#70d6c4" fill-opacity=".15"/>')
        anchor = "end" if x > 480 else "start"
        tx = x - 14 if anchor == "end" else x + 14
        s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="#70d6c4" stroke="#0b1723" stroke-width="2"/>')
        s.append(f'<text x="{tx:.1f}" y="{y+22:.1f}" text-anchor="{anchor}" fill="#d6e7ef" font-size="12" font-family="system-ui">{html.escape(site["label"])}</text>')
    s.extend(['</g>', '<text x="24" y="365" fill="#86a0b2" font-size="9" font-family="system-ui">MET Norway · recorded warning / Natural Earth · public-domain outline / Exercise points are not operational locations</text>', '</svg>'])
    return ''.join(s)


def panel(svg: str, title: str, subtitle: str) -> str:
    return (f'<div class="nl-map"><div class="nl-map-head">{html.escape(title)}</div>'
            f'<div class="nl-map-sub">{html.escape(subtitle)}</div>{svg}</div>')


# ---------------------------------------------------------------- interactive map
# Pre-projected SVG passed to a local inline component (northlink/mapview.py).
# Scaled Web Mercator display aligns local raster tiles and vector overlays.
# Geographic evidence matching remains unchanged in replay.py.
BASEMAP = Path(__file__).resolve().parent.parent / "assets" / "basemap-high-north.json"
DEFAULT_VIEW = (17.2, 68.55, 34.2, 71.65)   # lon0, lat0, lon1, lat1 shown on first open / Reset


def view_box(lon0: float, lat0: float, lon1: float, lat1: float, pad: float = 0.0) -> list[float]:
    x0, y1 = proj(lon0, lat0)
    x1, y0 = proj(lon1, lat1)
    w, h = x1 - x0, y1 - y0
    return [round(x0 - w * pad, 4), round(y0 - h * pad, 4), round(w * (1 + 2 * pad), 4), round(h * (1 + 2 * pad), 4)]


def _d(points, close: bool) -> str:
    return "M" + "L".join("%.3f,%.3f" % proj(p[0], p[1]) for p in points) + ("Z" if close else "")


def _rings(geometry: dict) -> list:
    polys = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    return [ring for p in polys for ring in p]


def bounds(geometry: dict, extra: list[tuple[float, float]] = ()) -> tuple[float, float, float, float]:
    pts = [p[:2] for ring in _rings(geometry) for p in ring] + list(extra)
    return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))


@lru_cache(maxsize=1)
def basemap() -> dict:
    """Bundled Natural Earth layers as projected SVG fragments plus place list."""
    b = json.loads(BASEMAP.read_text(encoding="utf-8"))
    lon0, lat0, lon1, lat1 = b["meta"]["bbox_lon_lat"]
    x0, y0, w, h = view_box(lon0, lat0, lon1, lat1)
    grid = []
    for lon in range(int(lon0) + 1, int(lon1)):
        if lon % 2 == 0:
            grid.append(_d([(lon, lat0), (lon, lat1)], False))
    for lat in range(int(lat0) + 1, int(lat1) + 1):
        grid.append(_d([(lon0, lat), (lon1, lat)], False))
    svg = "".join([
        '<g class="reference-base">',
        f'<rect class="sea" x="{x0}" y="{y0}" width="{w}" height="{h}"/>',
        f'<path class="land" d="{"".join(_d(r, True) for r in b["land"])}"/>',
        f'<path class="lake" d="{"".join(_d(r, True) for r in b["lakes"])}"/>',
        f'<path class="coast" d="{"".join(_d(c, False) for c in b["coast"])}"/>',
        '</g><g class="raster-base"></g>',
        f'<path class="grid" d="{"".join(grid)}"/>',
        f'<path class="border" d="{"".join(_d(c, False) for c in b["borders"])}"/>',
    ])
    places = [{"name": p["name"], "rank": p["rank"], "xy": proj(p["lon"], p["lat"])} for p in b["places"]]
    graticule = ([{"text": f"{lon}°E", "xy": proj(lon, 71.9), "axis": "x"} for lon in range(18, 36, 2)] +
                 [{"text": f"{lat}°N", "xy": proj(17.4, lat), "axis": "y"} for lat in range(66, 75)])
    return {"svg": svg, "places": places, "graticule": graticule, "license": b["meta"]["license"]}


def recorded_map(shown_geometry: dict, previous_geometry: dict | None, sites: dict, groups: dict,
                 selected: str | None, selected_site: str | None, status: str, view_key: str) -> dict:
    """Data for the interactive recorded-weather map. `groups` maps site id to its
    deliveries [{id, title, status, window}]; only fictional exercise points are selectable."""
    base = basemap()
    warning = (f'<path class="warning" fill-rule="evenodd" d="{"".join(_d(r, True) for r in _rings(shown_geometry))}">'
               '<title>Recorded MET warning area (shown revision)</title></path>')
    previous = ""
    if previous_geometry is not None:
        previous = (f'<path class="previous" d="{"".join(_d(r, True) for r in _rings(previous_geometry))}">'
                    '<title>Previous loaded revision outline</title></path>')
    markers = []
    for ident, site in sites.items():
        x, y = proj(site["lon"], site["lat"])
        markers.append({"id": ident, "label": site["label"], "short_label": site["label"].replace(" exercise point", "").replace(" comparison point", ""), "x": x, "y": y,
                        "note": site["note"], "deliveries": groups.get(ident, [])})
    # Fit must include the full warning even where the regional basemap ends.
    # Include the previous outline too, so comparing revisions doesn't crop it.
    lon0, lat0, lon1, lat1 = bounds(shown_geometry, [(s["lon"], s["lat"]) for s in sites.values()])
    if previous_geometry:
        p0, q0, p1, q1 = bounds(previous_geometry)
        lon0, lat0, lon1, lat1 = min(lon0, p0), min(lat0, q0), max(lon1, p1), max(lat1, q1)
    fit = (lon0, lat0, lon1, lat1)
    pack = topomap.prepared()
    rasters = [{"id": r["id"], "zoom": r["zoom"], "site": r["site"],
                "rect": view_box(*r["bbox"]), "href": r["href"]} for r in pack["images"]]
    coordinate = sites.get(selected_site)
    return {
        "kind": "geo", "view_key": view_key + "-mercator-v1", "layers": base["svg"] + warning + previous,
        "rasters": rasters, "map_date": pack["date"],
        "projection": {"k": K, "origin": MERCATOR_ORIGIN, "metres_per_unit": METRES_PER_UNIT},
        "selected_coordinate": f"{coordinate['lat']:.4f}°N {coordinate['lon']:.4f}°E · fictional point" if coordinate else "",
        "places": base["places"], "graticule": base["graticule"], "markers": markers,
        "layers_list": ([["warning", "Warning area"]] +
                        ([["previous", "Previous revision"]] if previous_geometry is not None else []) +
                        [["towns", "Reference town labels"], ["borders", "Border overlay"], ["graticule", "Coordinate grid"]]),
        "selected": selected, "selected_marker": selected_site, "status": status,
        "default_view": view_box(*DEFAULT_VIEW), "fit_view": view_box(*fit, pad=0.06),
        "limits": [20, 1500], "pannable": True, "has_previous": previous_geometry is not None,
        "attribution": ("Topographic snapshot: © Kartverket, CC BY 4.0 · " if rasters else "") +
                       "Outline: Natural Earth, public domain · Warning polygon: MET Norway, CC BY 4.0 · "
                       "Exercise points and deliveries are fictional · Not for navigation",
        "aria": "Map of Northern Norway with the recorded MET warning area and fictional exercise points",
    }


def schematic_map(statuses: dict, groups: dict, selected: str | None, selected_corridor: str | None, view_key: str) -> dict:
    """The fictional corridor diagram, with corridor endpoints as selectable markers."""
    inner = schematic(statuses)
    inner = inner[inner.index(">") + 1:inner.rindex("</svg>")]
    markers = [{"id": c, "label": c, "x": 625, "y": y + 25,
                "note": "Fictional exercise corridor, not a navigation route", "deliveries": groups.get(c, [])}
               for c, y in zip(("C1", "C2", "C3"), (65, 165, 275))]
    return {
        "kind": "schematic", "view_key": view_key, "layers": inner, "places": [], "graticule": [],
        "layers_list": [],
        "markers": markers, "selected": selected, "selected_marker": selected_corridor,
        "status": "Synthetic exercise · fictional corridors C1–C3",
        "default_view": [0, 0, 720, 370], "fit_view": [0, 0, 720, 370], "limits": [720, 720],
        "pannable": False, "has_previous": False,
        "attribution": "Local reference diagram · all corridors, deliveries and reports are fictional",
        "aria": "Fictional corridor reference diagram",
    }
