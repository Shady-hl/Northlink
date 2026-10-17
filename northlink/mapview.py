"""Interactive local map: pan, zoom, fit/reset, keyboard control and selectable markers.

Inline HTML/CSS/JS registered with Streamlit's built-in components v2 API. No
package, CDN, tile server, font or network request is involved. All SVG content is
built in northlink/visuals.py from bundled files and escaped text; delivery titles
and labels are inserted with textContent, never as HTML.
"""
from __future__ import annotations

import streamlit as st

CSS = """
:host, .nlm {font-family: system-ui, -apple-system, "Segoe UI", sans-serif; color: #e6edf4}
.nlm {border: 1px solid #537080; border-radius: 3px; background: #0f1d2c; overflow: hidden}
.bar {display: flex; flex-wrap: wrap; gap: 6px; align-items: center; padding: 10px 12px;
      border-bottom: 1px solid #22364a}
.bar .status {flex: 1 1 100%; font-size: 11px; color: #a9bccc; line-height: 1.4}
.bar button, .panel button, .layerbar button {font: inherit; font-size: 12px; color: #e6edf4; background: #16293b;
      border: 1px solid #36506a; border-radius: 8px; padding: 6px 10px; cursor: pointer}
.bar button:hover, .panel button:hover, .layerbar button:hover {background: #1d3549}
button:focus-visible, .stage:focus-visible, .marker:focus-visible {outline: 3px solid #ffd479; outline-offset: 2px}
.stage {position: relative; height: clamp(360px, calc(100vh - 390px), 760px); touch-action: none; cursor: grab; outline: none}
.map-tools {position:absolute;right:12px;bottom:14px;display:grid;gap:6px;z-index:3}
.map-tools button {width:39px;height:39px;border:1px solid #6b8799;border-radius:4px;background:#102738ee;color:white;font:600 14px system-ui;cursor:pointer}
.map-tools button:hover {background:#24516a}
.stage.drag {cursor: grabbing}
.stage.static {cursor: default}
svg {display: block; width: 100%; height: 100%; user-select: none}
.sea {fill: #0d2133} .grid {fill: none; stroke: #1b3549; vector-effect: non-scaling-stroke; stroke-width: 1}
.land {fill: #1d3342; stroke: none} .lake {fill: #0d2133}
.coast {fill: none; stroke: #4f6d7e; stroke-width: 1; vector-effect: non-scaling-stroke}
.border {fill: none; stroke: #8193a3; stroke-width: 1.2; stroke-dasharray: 5 4; vector-effect: non-scaling-stroke}
.warning {fill: url(#hatch); stroke: #f2c46e; stroke-width: 2.4; stroke-dasharray: 9 5; vector-effect: non-scaling-stroke}
.previous {fill: none; stroke: #e9eef2; stroke-width: 2; stroke-dasharray: 2 5; stroke-linecap: round; vector-effect: non-scaling-stroke}
.place circle {fill: #dfe8ee; stroke: #0b1723; vector-effect: non-scaling-stroke}
.place text, .grat {paint-order: stroke; stroke: #0b1723; stroke-linejoin: round; vector-effect: non-scaling-stroke}
.place text {fill: #dbe6ee} .grat {fill: #7f9bb0}
.marker {cursor: pointer; outline: none}
.marker .halo {fill: #70d6c4; fill-opacity: .16; stroke: none}
.marker .dot {fill: #70d6c4; stroke: #0b1723; vector-effect: non-scaling-stroke}
.marker .ring {fill: none; stroke: #ffffff; vector-effect: non-scaling-stroke}
.marker text {fill: #f4fbff; font-weight: 650; paint-order: stroke; stroke: #0b1723; stroke-linejoin: round;
      vector-effect: non-scaling-stroke}
.marker .flag {fill: #0b1723; font-weight: 800}
.panel {position: absolute; right: 10px; top: 10px; width: min(300px, 70%); background: #0d1a28ee;
      border: 1px solid #3a5873; border-radius: 10px; padding: 10px 12px; font-size: 12px; line-height: 1.4}
.panel h4 {margin: 0 0 2px; font-size: 13px} .panel p {margin: 0 0 8px; color: #a9bccc}
.panel ul {list-style: none; margin: 0; padding: 0; display: grid; gap: 6px}
.panel li button {width: 100%; text-align: left; display: block}
.panel li button[aria-current="true"] {border-color: #70d6c4; background: #183a3c}
.panel .close {position: absolute; right: 8px; top: 8px; padding: 2px 8px}
.layerbar {display: flex; flex-wrap: wrap; gap: 6px; align-items: center; padding: 8px 12px;
      border-top: 1px solid #22364a}
.layerbar .lbl {font-size: 10.5px; letter-spacing: .1em; text-transform: uppercase; color: #86a0b2;
      margin-right: 2px}
.layerbar button[aria-pressed="false"] {opacity: .5; border-style: dashed}
.foot {display: flex; flex-wrap: wrap; gap: 6px 16px; padding: 8px 12px 10px; border-top: 1px solid #22364a;
      font-size: 11px; color: #a9bccc; align-items: center}
.nlm.no-warning .warning, .nlm.no-previous .previous, .nlm.no-borders .border,
.nlm.no-grid .grid, .nlm.no-graticule .grid, .nlm.no-towns .place, .nlm.no-graticule .grat {display: none}
.key {display: inline-flex; align-items: center; gap: 6px}
.key svg {width: 26px; height: 14px}
.attr {flex-basis: 100%; color: #7f97aa; font-size: 10.5px}
.help {flex-basis: 100%; color: #7f97aa; font-size: 10.5px}
.legend {border-top:1px solid #22364a}.legend summary {cursor:pointer;padding:8px 12px;color:#a9bccc;font-size:11px}
.legend .foot {border-top:0;padding-top:0}
.nlm > .attr {padding:0 12px 9px;line-height:1.4;font-size:9px}
.map-options {position:relative;display:flex;align-items:center;gap:6px;padding:7px 12px;background:#102333;border-bottom:1px solid #345164}
.map-options button,.layer-menu summary {font:500 11px system-ui;color:#dce9f1;background:#162f42;border:1px solid #416478;border-radius:4px;padding:6px 10px;cursor:pointer}
.map-options button[aria-pressed="true"] {background:#d6e7ec;color:#183d50;border-color:#b3d1de}
.layer-menu {margin-left:auto}.layer-menu summary {list-style:none}
.layer-menu .layerbar {position:absolute;right:12px;top:42px;z-index:8;background:#102536;min-width:225px;border:1px solid #52778d;border-radius:4px;box-shadow:0 4px 15px #0005;display:grid;padding:10px}
.layer-menu .layerbar button {text-align:left;border-radius:4px;font-size:11px}
.map-note {font-size:9px;color:#9fb4c3;padding:4px 12px 6px;background:#102333}
.scale {position:absolute;left:12px;bottom:12px;pointer-events:none;color:#19364a;background:#f4f7f5e8;padding:5px 8px 4px;border-radius:3px;font-size:10px}
.scale-line {height:5px;border:1px solid #19364a;border-top:0;margin-bottom:3px}
.nlm.topographic .grid {stroke:#31546a;opacity:.18}
.nlm.topographic .sea,.nlm.topographic .lake {fill:#edf2f4}
.nlm.topographic .land {fill:#e4e8e5}
.nlm.topographic .coast {stroke:#82979d;opacity:.6}
.nlm.topographic .grat {fill:#153e57;stroke:#f7fafb;stroke-width:3px}
.nlm.topographic .place text,.nlm.topographic .marker text:not(.flag) {fill:#11364b;stroke:#fff}
.nlm.topographic .previous {stroke:#31566e;stroke-width:2.2}
.nlm.topographic .warning {stroke:#9a5b15;stroke-width:2}
.nlm.topographic #hatch rect {fill:#cd8b2e;fill-opacity:.08}
.nlm.topographic #hatch line {stroke:#9a5b15;stroke-opacity:.38}
.nlm:not(.topographic) .raster-base {display:none}
.nlm.geo .grid,.nlm.no-graticule .coordinate-grid {display:none}
.coordinate-grid line {stroke:#29495f;stroke-width:1;opacity:.38;vector-effect:non-scaling-stroke}
.nlm.topographic .coordinate-grid line {stroke:#31546a;opacity:.2}
"""

HTML = '<div class="nlm"></div>'

JS = r"""
const NS = 'http://www.w3.org/2000/svg';
const views = (window.__northlinkMapViews = window.__northlinkMapViews || {});
const settings = (window.__northlinkMapSettings = window.__northlinkMapSettings || {});

function el(tag, attrs, parent, text) {
  const n = tag.startsWith('svg:') ? document.createElementNS(NS, tag.slice(4)) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
  if (text !== undefined) n.textContent = text;
  if (parent) parent.appendChild(n);
  return n;
}

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement.querySelector('.nlm');
  root.replaceChildren();
  root.classList.toggle('geo', data.kind === 'geo');
  const cleanups = [];
  const on = (target, ev, fn, opts) => { target.addEventListener(ev, fn, opts); cleanups.push(() => target.removeEventListener(ev, fn, opts)); };

  // ------------------------------------------------------------ toolbar
  const bar = el('div', { class: 'bar' }, root);
  el('div', { class: 'status', role: 'status' }, bar, data.status);
  const buttons = {};
  const tools = data.pannable
    ? [['in', 'Zoom in', '+'], ['out', 'Zoom out', '−'], ['fit', 'Fit warning and points', 'Fit all'], ['locate', 'Locate selected site', 'Locate'],
       ...((data.rasters || []).length ? [['detail', 'Open offline detail at selected site', 'Detail']] : []), ['reset', 'Reset view', 'Reset']]
    : [];
  for (const [id, label, text] of tools) {
    buttons[id] = el('button', { type: 'button', 'aria-label': label, title: label }, bar, text);
  }

  // ------------------------------------------------------------ layer visibility
  const layersOn = (settings[data.view_key] = settings[data.view_key] || {});
  const options = el('div', {class: 'map-options'}, root);
  const hasRaster = (data.rasters || []).length > 0;
  if (!layersOn.__base) layersOn.__base = hasRaster ? 'topographic' : 'reference';
  if (!hasRaster) layersOn.__base = 'reference';
  root.classList.toggle('topographic', layersOn.__base === 'topographic');
  const baseButtons = [];
  if (hasRaster) {
    for (const [id, label] of [['topographic', 'Topographic'], ['reference', 'Outline']]) {
      const b = el('button', {type:'button','aria-label':`Basemap: ${label}`,'aria-pressed':String(layersOn.__base === id)}, options, label);
      baseButtons.push([id,b]);
      on(b,'click',()=>{
        layersOn.__base = id;
        root.classList.toggle('topographic', id === 'topographic');
        for (const [key,button] of baseButtons) button.setAttribute('aria-pressed',String(key === id));
        draw();
      });
    }
  }
  const menu = el('details', {class:'layer-menu'}, options);
  el('summary', {}, menu, 'Overlays ▾');
  const layerBar = el('div', { class: 'layerbar', role: 'group', 'aria-label': 'Map layers' }, menu);
  el('span', { class: 'lbl' }, layerBar, 'Layers');
  for (const [id, label] of (data.layers_list || [])) {
    if (!(id in layersOn)) layersOn[id] = !(hasRaster && id === 'borders');
    root.classList.toggle('no-' + id, !layersOn[id]);
    const b = el('button', { type: 'button', 'aria-pressed': String(layersOn[id]), 'aria-label': `Show or hide: ${label}` }, layerBar, label);
    on(b, 'click', () => {
      layersOn[id] = !layersOn[id];
      b.setAttribute('aria-pressed', String(layersOn[id]));
      root.classList.toggle('no-' + id, !layersOn[id]);
      draw();
    });
  }
  if (!(data.layers_list || []).length) options.remove();
  const mapNote = data.pannable ? el('div', {class:'map-note',role:'status'}, root) : null;

  // ------------------------------------------------------------ map stage
  const stage = el('div', { class: 'stage' + (data.pannable ? '' : ' static'), tabindex: '0', role: 'application',
    'aria-label': data.aria + (data.pannable ? '. Arrow keys pan, plus and minus zoom, F fits, 0 resets. Tab moves to exercise points.' : '. Tab moves to corridor markers.') }, root);
  const svg = el('svg:svg', { preserveAspectRatio: 'xMidYMid meet', 'aria-hidden': 'false' }, stage);
  if (data.pannable) {
    const controls = el('div', { class: 'map-tools', role: 'group', 'aria-label': 'Map navigation' }, stage);
    const icons = {in: '+', out: '−', fit: 'Fit', locate: '◎', detail: '▤', reset: '↺'};
    for (const [id, b] of Object.entries(buttons)) {
      if (id === 'detail') { b.textContent = 'Site detail'; options.insertBefore(b,menu); continue; }
      b.textContent = icons[id];
      controls.appendChild(b);
    }
  }
  const defs = el('svg:defs', {}, svg);
  const pat = el('svg:pattern', { id: 'hatch', width: '10', height: '10', patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' }, defs);
  el('svg:rect', { width: '10', height: '10', fill: '#f2c46e', 'fill-opacity': '0.10' }, pat);
  el('svg:line', { x1: '0', y1: '0', x2: '0', y2: '10', stroke: '#f2c46e', 'stroke-opacity': '0.45', 'stroke-width': '3' }, pat);
  const layers = el('svg:g', {}, svg);
  layers.innerHTML = data.layers;   // trusted: generated server-side from bundled files
  const rasterGroup = layers.querySelector('.raster-base');
  const rasters = (data.rasters || []).map(r => {
    const [x,y,width,height] = r.rect;
    return {...r, node: el('svg:image',{x,y,width,height,href:r.href,preserveAspectRatio:'none','aria-hidden':'true'},rasterGroup)};
  });
  const scale = data.projection ? el('div',{class:'scale','aria-label':'Approximate ground scale at map centre'},stage) : null;
  const scaleLine = scale ? el('div',{class:'scale-line'},scale) : null;
  const scaleLabel = scale ? el('span',{},scale) : null;
  const gridG = el('svg:g', {class:'coordinate-grid','aria-hidden':'true'},svg);
  const gratG = el('svg:g', { 'aria-hidden': 'true' }, svg);
  const placeG = el('svg:g', { 'aria-hidden': 'true' }, svg);
  const markerG = el('svg:g', {}, svg);

  const grat = (data.projection ? [] : data.graticule).map(g => ({ g, t: el('svg:text', { class: 'grat' }, gratG, g.text) }));
  const places = data.places.map(p => {
    const g = el('svg:g', { class: 'place' }, placeG);
    return { p, g, c: el('svg:circle', { cx: p.xy[0], cy: p.xy[1] }, g), t: el('svg:text', {}, g, p.name) };
  });

  // ------------------------------------------------------------ site panel
  let panel = null;
  function closePanel(focusMarker) {
    if (panel) { panel.remove(); panel = null; }
    if (focusMarker) focusMarker.focus();
  }
  function openPanel(m, node) {
    closePanel();
    panel = el('div', { class: 'panel', role: 'dialog', 'aria-label': m.label }, stage);
    const close = el('button', { type: 'button', class: 'close', 'aria-label': 'Close' }, panel, '×');
    on(close, 'click', () => closePanel(node));
    el('h4', {}, panel, m.label);
    el('p', {}, panel, m.note);
    const ul = el('ul', {}, panel);
    for (const d of m.deliveries) {
      const b = el('button', { type: 'button', 'aria-current': String(d.id === data.selected) }, el('li', {}, ul));
      el('strong', {}, b, d.id + ' · ' + d.status);
      el('br', {}, b);
      el('span', {}, b, d.title + ' · ' + d.window);
      on(b, 'click', () => setTriggerValue('select', d.id));
    }
    if (!m.deliveries.length) el('p', {}, panel, 'No deliveries at this point.');
    const first = panel.querySelector('li button');
    (first || close).focus();
    on(panel, 'keydown', e => { if (e.key === 'Escape') { e.stopPropagation(); closePanel(node); } });
  }

  const markers = data.markers.map(m => {
    const sel = m.id === data.selected_marker;
    const attention = m.deliveries.filter(d => d.attention).length;
    const g = el('svg:g', { class: 'marker', tabindex: '0', role: 'button',
      'aria-label': `${m.label}: ${m.deliveries.length} fictional deliveries, ${attention} need attention${sel ? ', contains selected delivery' : ''}. Press Enter to choose a delivery.` }, markerG);
    const parts = {
      halo: el('svg:circle', { class: 'halo' }, g),
      ring: sel ? el('svg:circle', { class: 'ring' }, g) : null,
      dot: el('svg:circle', { class: 'dot' }, g),
      flag: el('svg:text', { class: 'flag', 'text-anchor': 'middle', 'dominant-baseline': 'central' }, g, attention ? '!' : ''),
      label: el('svg:text', {}, g, (m.short_label || m.label) + (attention ? ` · ${attention} to review` : '')),
    };
    const activate = () => openPanel(m, g);
    on(g, 'click', e => { e.stopPropagation(); activate(); });
    on(g, 'keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); activate(); } });
    on(g, 'pointerdown', e => e.stopPropagation());
    return { m, g, ...parts };
  });

  // ------------------------------------------------------------ view state
  const key = data.view_key;
  const [minW, maxW] = data.limits;
  let vb = (views[key] && views[key].length === 4 ? views[key] : data.default_view).slice();

  function clamp(v) {
    const w = Math.min(maxW, Math.max(minW, v[2]));
    const h = v[3] * w / v[2];
    const cx = v[0] + v[2] / 2, cy = v[1] + v[3] / 2;
    return [cx - w / 2, cy - h / 2, w, h];
  }

  function draw() {
    vb = clamp(vb);
    views[key] = vb.slice();
    svg.setAttribute('viewBox', vb.join(' '));
    const r = stage.getBoundingClientRect();
    const px = Math.max(vb[2] / Math.max(r.width, 1), vb[3] / Math.max(r.height, 1)); // SVG units per screen px
    const ox = (r.width * px - vb[2]) / 2, oy = (r.height * px - vb[3]) / 2;
    const left = vb[0] - ox, top = vb[1] - oy;
    // Keep weather hatching at screen scale while zooming into roads/terrain.
    const hatchSize = 9*px;
    pat.setAttribute('width',hatchSize); pat.setAttribute('height',hatchSize);
    const hatchRect = pat.querySelector('rect'), hatchLine = pat.querySelector('line');
    hatchRect.setAttribute('width',hatchSize); hatchRect.setAttribute('height',hatchSize);
    hatchLine.setAttribute('y2',hatchSize); hatchLine.setAttribute('stroke-width',1.3*px);
    if (data.projection) {
      gridG.replaceChildren(); gratG.replaceChildren();
      const k = data.projection.k, origin = data.projection.origin;
      const latitude = y => Math.atan(Math.sinh(origin-y/k*Math.PI/180))*180/Math.PI;
      const latCentre = latitude(vb[1]+vb[3]/2)*Math.PI/180;
      const steps = [.001,.002,.005,.01,.02,.05,.1,.2,.5,1,2,5,10,20];
      const choose = target => steps.find(n=>target<=n*1.5) || 20;
      const sx = choose(90*px/k), sy = choose(90*px*Math.cos(latCentre)/k);
      const west = Math.max(-180,25+left/k), east = Math.min(180,25+(left+r.width*px)/k);
      const north = latitude(top), south = latitude(top+r.height*px);
      const label = (value,step,axis) => Math.abs(value).toFixed(step<1 ? Math.min(3,Math.ceil(-Math.log10(step))) : 0)+'°'+(axis==='x' ? (value<0?'W':'E') : (value<0?'S':'N'));
      for (let lon=Math.ceil(west/sx)*sx;lon<=east && lon<=180;lon+=sx) {
        const x=(lon-25)*k;
        el('svg:line',{x1:x,x2:x,y1:top,y2:top+r.height*px},gridG);
        el('svg:text',{class:'grat',x:x+4*px,y:top+15*px,'font-size':10.5*px,'stroke-width':3},gratG,label(lon,sx,'x'));
      }
      for (let lat=Math.ceil(south/sy)*sy;lat<=north && lat<85.052;lat+=sy) {
        const y=(origin-Math.asinh(Math.tan(lat*Math.PI/180)))*180/Math.PI*k;
        el('svg:line',{x1:left,x2:left+r.width*px,y1:y,y2:y},gridG);
        el('svg:text',{class:'grat',x:left+5*px,y:y-4*px,'font-size':10.5*px,'stroke-width':3},gratG,label(lat,sy,'y'));
      }
    }
    // Source pixels are placed in the same Web Mercator projection as the
    // warning geometry. Finer snapshots appear only near their native scale.
    const visibleRasters = [];
    for (const image of rasters) {
      const [x,y,w,h] = image.rect;
      const hits = x < left + r.width * px && x+w > left && y < top + r.height * px && y+h > top;
      const native = data.projection.k * 360 / (256 * 2**image.zoom);
      const show = hits && (image.zoom === 6 || px <= native * (image.zoom === 8 ? 6 : 2));
      image.node.style.display = show ? '' : 'none';
      if (show) visibleRasters.push(image.zoom);
    }
    if (mapNote) {
      const level = visibleRasters.length ? Math.max(...visibleRasters) : null;
      const text = layersOn.__base === 'topographic'
        ? (level ? `OFFLINE TOPO · z${level} snapshot · downloaded ${data.map_date}` : 'Outside offline topographic coverage · outline only')
        : 'OFFLINE OUTLINE · general geographic reference';
      mapNote.textContent = text + (data.selected_coordinate ? '  |  '+data.selected_coordinate : '');
    }
    if (scale) {
      const merc = data.projection.origin - (vb[1] + vb[3]/2) / data.projection.k * Math.PI / 180;
      const lat = Math.atan(Math.sinh(merc));
      const metresPerPixel = px * data.projection.metres_per_unit * Math.cos(lat);
      const target = metresPerPixel * 90;
      const choices = [100,200,500,1000,2000,5000,10000,20000,50000,100000,200000,500000];
      const distance = choices.filter(n=>n<=target).pop() || 100;
      scaleLine.style.width = (distance/metresPerPixel)+'px';
      scaleLabel.textContent = '≈ '+(distance>=1000 ? (distance/1000)+' km' : distance+' m');
    }
    const fs = 12.5 * px;
    for (const { g, t } of grat) {
      const x = g.axis === 'x' ? g.xy[0] : left + 6 * px;
      const y = g.axis === 'x' ? top + 16 * px : g.xy[1] - 4 * px;
      t.setAttribute('x', x); t.setAttribute('y', y);
      t.setAttribute('font-size', 10.5 * px); t.setAttribute('stroke-width', 3);
    }
    // Place labels: rank threshold by zoom, then greedy screen-space collision avoidance.
    const maxRank = vb[2] > 900 ? 4 : vb[2] > 500 ? 6 : 8;
    const taken = markers.map(({ m }) => [(m.x - left) / px - 20, (m.y - top) / px - 18, 220, 38]);
    for (const { p, g, c, t } of places) {
      const sx = (p.xy[0] - left) / px, sy = (p.xy[1] - top) / px;
      const box = [sx + 6, sy - 9, p.name.length * 7.2 + 4, 16];
      const inView = sx > -20 && sy > -20 && sx < r.width + 20 && sy < r.height + 20;
      const hit = taken.some(b => box[0] < b[0] + b[2] && b[0] < box[0] + box[2] && box[1] < b[1] + b[3] && b[1] < box[1] + box[3]);
      const show = inView && p.rank <= maxRank && !hit && layersOn.towns !== false;
      g.style.display = show ? '' : 'none';
      if (!show) continue;
      taken.push(box);
      c.setAttribute('r', 2.6 * px); c.setAttribute('stroke-width', 1);
      t.setAttribute('x', p.xy[0] + 6 * px); t.setAttribute('y', p.xy[1] + 4 * px);
      t.setAttribute('font-size', fs); t.setAttribute('stroke-width', 3);
    }
    for (const { m, g, halo, ring, dot, flag, label } of markers) {
      const sel = m.id === data.selected_marker;
      halo.setAttribute('cx', m.x); halo.setAttribute('cy', m.y); halo.setAttribute('r', (sel ? 22 : 15) * px);
      if (ring) { ring.setAttribute('cx', m.x); ring.setAttribute('cy', m.y); ring.setAttribute('r', 13 * px); ring.setAttribute('stroke-width', 2.5); }
      dot.setAttribute('cx', m.x); dot.setAttribute('cy', m.y); dot.setAttribute('r', 8.5 * px); dot.setAttribute('stroke-width', 2);
      flag.setAttribute('x', m.x); flag.setAttribute('y', m.y); flag.setAttribute('font-size', 12 * px);
      const sx = (m.x - left) / px, sy = (m.y - top) / px;
      const visible = sx >= -12 && sx <= r.width + 12 && sy >= -12 && sy <= r.height + 12;
      g.style.display = visible ? '' : 'none';
      label.setAttribute('font-size', 12 * px); label.setAttribute('stroke-width', 3.5);
      const labelW = label.getComputedTextLength() / px;
      const right = sx + 16 + labelW > r.width - 10 && sx - 16 - labelW >= 10;
      label.setAttribute('text-anchor', right ? 'end' : 'start');
      const labelX = right ? sx - 16 : Math.min(Math.max(sx + 16, 10), Math.max(10, r.width - labelW - 10));
      label.setAttribute('x', left + labelX * px);
      label.setAttribute('y', top + Math.min(Math.max(sy + 5, 18), r.height - 10) * px);
    }
  }

  function zoom(factor, cx, cy) {
    const w = Math.min(maxW, Math.max(minW, vb[2] * factor));
    const f = w / vb[2];
    cx = cx ?? vb[0] + vb[2] / 2; cy = cy ?? vb[1] + vb[3] / 2;
    vb = [cx - (cx - vb[0]) * f, cy - (cy - vb[1]) * f, vb[2] * f, vb[3] * f];
    draw();
  }
  function pan(dxFrac, dyFrac) { vb[0] += vb[2] * dxFrac; vb[1] += vb[3] * dyFrac; draw(); }
  function toSvg(e) {
    const r = stage.getBoundingClientRect();
    const px = Math.max(vb[2] / r.width, vb[3] / r.height);
    const ox = (r.width * px - vb[2]) / 2, oy = (r.height * px - vb[3]) / 2;
    return [vb[0] - ox + (e.clientX - r.left) * px, vb[1] - oy + (e.clientY - r.top) * px, px];
  }

  if (data.pannable) {
    on(buttons.in, 'click', () => zoom(1 / 1.4));
    on(buttons.out, 'click', () => zoom(1.4));
    on(buttons.fit, 'click', () => { vb = data.fit_view.slice(); draw(); });
    on(buttons.locate, 'click', () => {
      const m = data.markers.find(m => m.id === data.selected_marker);
      if (m) { vb = [m.x - vb[2] / 2, m.y - vb[3] / 2, vb[2], vb[3]]; draw(); }
    });
    if (buttons.detail) on(buttons.detail,'click',()=>{
      const m = data.markers.find(m=>m.id===data.selected_marker);
      if (m) {
        const width = 26, height = width * stage.clientHeight / Math.max(stage.clientWidth,1);
        vb = [m.x-width/2,m.y-height/2,width,height];
        draw();
      }
    });
    on(buttons.reset, 'click', () => { vb = data.default_view.slice(); draw(); });
    on(stage, 'wheel', e => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault(); const [x, y] = toSvg(e); zoom(Math.exp(e.deltaY * 0.0015), x, y);
    }, { passive: false });
    let drag = null;
    on(stage, 'pointerdown', e => {
      if (e.target.closest && e.target.closest('.panel, .map-tools')) return;
      drag = { x: e.clientX, y: e.clientY, vb: vb.slice(), px: toSvg(e)[2] };
      stage.setPointerCapture(e.pointerId); stage.classList.add('drag');
    });
    on(stage, 'pointermove', e => {
      if (!drag) return;
      vb = [drag.vb[0] - (e.clientX - drag.x) * drag.px, drag.vb[1] - (e.clientY - drag.y) * drag.px, drag.vb[2], drag.vb[3]];
      draw();
    });
    const end = () => { drag = null; stage.classList.remove('drag'); };
    on(stage, 'pointerup', end); on(stage, 'pointercancel', end);
    on(stage, 'keydown', e => {
      if (e.target !== stage) return;
      const k = e.key;
      if (k === 'ArrowLeft') pan(-0.12, 0); else if (k === 'ArrowRight') pan(0.12, 0);
      else if (k === 'ArrowUp') pan(0, -0.12); else if (k === 'ArrowDown') pan(0, 0.12);
      else if (k === '+' || k === '=') zoom(1 / 1.4); else if (k === '-' || k === '_') zoom(1.4);
      else if (k === 'f' || k === 'F') { vb = data.fit_view.slice(); draw(); }
      else if (k === '0') { vb = data.default_view.slice(); draw(); }
      else return;
      e.preventDefault();
    });
  }

  // ------------------------------------------------------------ legend + attribution
  const legend = el('details', { class: 'legend' }, root);
  el('summary', {}, legend, 'Map key & controls');
  const foot = el('div', { class: 'foot' }, legend);
  function key_(label, build) {
    const k = el('span', { class: 'key' }, foot);
    const s = el('svg:svg', { viewBox: '0 0 26 14', 'aria-hidden': 'true' }, k);
    build(s);
    el('span', {}, k, label);
  }
  if (data.kind === 'geo') {
    key_('Recorded MET warning area (hatched, dashed edge)', s => {
      const d = el('svg:defs', {}, s);
      const p = el('svg:pattern', { id: 'hk', width: '5', height: '5', patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' }, d);
      el('svg:line', { x1: '0', y1: '0', x2: '0', y2: '5', stroke: '#f2c46e', 'stroke-width': '2', 'stroke-opacity': '.6' }, p);
      el('svg:rect', { x: '1', y: '1', width: '24', height: '12', fill: 'url(#hk)', stroke: '#f2c46e', 'stroke-width': '1.6', 'stroke-dasharray': '4 2' }, s);
    });
    if (data.has_previous) key_('Previous loaded revision (dotted outline)', s =>
      el('svg:rect', { x: '1', y: '1', width: '24', height: '12', fill: 'none', stroke: '#c9d3dc', 'stroke-width': '1.4', 'stroke-dasharray': '1.5 2.5' }, s));
    key_('Fictional exercise point (select)', s => el('svg:circle', { cx: '13', cy: '7', r: '5', fill: '#70d6c4', stroke: '#0b1723' }, s));
    key_('“!” = deliveries to check', s => {
      el('svg:circle', { cx: '13', cy: '7', r: '6', fill: '#70d6c4' }, s);
      el('svg:text', { x: '13', y: '10.5', 'text-anchor': 'middle', 'font-size': '10', 'font-weight': '800', fill: '#0b1723' }, s, '!');
    });
    key_('White ring = selected delivery’s point', s => el('svg:circle', { cx: '13', cy: '7', r: '5.5', fill: 'none', stroke: '#fff', 'stroke-width': '1.6' }, s));
    key_('Town (Natural Earth)', s => el('svg:circle', { cx: '13', cy: '7', r: '2.6', fill: '#dfe8ee' }, s));
    key_('Country border', s => el('svg:line', { x1: '1', y1: '7', x2: '25', y2: '7', stroke: '#8193a3', 'stroke-width': '1.4', 'stroke-dasharray': '4 3' }, s));
    el('div', { class: 'help' }, foot, 'Drag or use arrow keys to pan · Ctrl/⌘ + scroll, + or − to zoom · Locate centres the selected site · Tab to a point, Enter to list its deliveries.');
    if (hasRaster) el('div',{class:'help'},foot,'Topographic imagery is a downloaded Kartverket snapshot, not a live road-status feed. Sharper z11 imagery is bundled only around the two exercise sites. The Detail button opens that area; Outline is the general reference fallback. Overlays affect added layers, not labels or roads baked into the image. Scale is approximate at the map centre. Coordinates are WGS84, not GPS measurements.');
  } else {
    key_('Corridor end marker (select)', s => el('svg:circle', { cx: '13', cy: '7', r: '5', fill: '#70d6c4', stroke: '#0b1723' }, s));
    key_('“!” = deliveries to check', s => {
      el('svg:circle', { cx: '13', cy: '7', r: '6', fill: '#70d6c4' }, s);
      el('svg:text', { x: '13', y: '10.5', 'text-anchor': 'middle', 'font-size': '10', 'font-weight': '800', fill: '#0b1723' }, s, '!');
    });
    key_('White ring = selected delivery’s corridor', s => el('svg:circle', { cx: '13', cy: '7', r: '5.5', fill: 'none', stroke: '#fff', 'stroke-width': '1.6' }, s));
    el('div', { class: 'help' }, foot, 'Tab to a corridor marker and press Enter, or click it, to list its deliveries.');
  }
  el('div', { class: 'attr' }, root, data.attribution);

  draw();
  const ro = new ResizeObserver(() => draw());
  ro.observe(stage);
  cleanups.push(() => ro.disconnect());
  return () => cleanups.forEach(fn => fn());
}
"""

_component = st.components.v2.component("northlink_map", html=HTML, css=CSS, js=JS)


def show(data: dict, key: str, on_select) -> str | None:
    """Render the map. `on_select` runs before the rerun when a delivery is picked on
    the map, so it can update the delivery selector; the picked ID is also returned."""
    result = _component(key=key, data=data, on_select_change=on_select, height="content")
    return result.select if isinstance(result.select, str) else None
