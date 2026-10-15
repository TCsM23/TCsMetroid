// Visual map designer: drag rooms, draw doors, edit in the side panel, live checking.
// The draft map lives in the browser as plain data. The server never sees it until
// the preview call (every change) or Save (when you press the button).
"use strict";

const root = document.getElementById("designer-root");
const MODE = root.dataset.mode;                 // "designer" or "sandbox"
const DEFAULT_POWERUPS = JSON.parse(document.getElementById("designer-items").textContent);
const svg = document.getElementById("designer-canvas");
const scroller = document.getElementById("designer-scroll");
const SVG_NS = "http://www.w3.org/2000/svg";

const CELL_X = 150, CELL_Y = 104, ROOM_W = 108, ROOM_H = 58, PAD = 14;

let draft = JSON.parse(document.getElementById("designer-data").textContent);
if (!Array.isArray(draft.powerups) || !draft.powerups.length) draft.powerups = structuredClone(DEFAULT_POWERUPS);
let tool = "move";
let selected = null;          // {kind: "room", key}, {kind: "gate", index} or {kind: "powerup", key}
let report = null;            // last answer from /api/preview
let dirty = false;
let drag = null;              // room being dragged
let connect = null;           // door being drawn
let pan = null;               // empty space being dragged to scroll the canvas
let zoom = 1;                 // 1 = one SVG unit per screen pixel
let viewW = 0, viewH = 0;     // size of the drawing in SVG units
const undoStack = [];         // snapshots of the draft before each change
const redoStack = [];

// ------------------------------------------------------------------ editing
function commit(change) {
  undoStack.push(JSON.stringify(draft));
  redoStack.length = 0;
  change();
  dirty = true;
  refresh();
}

function undo() {
  if (!undoStack.length) return;
  redoStack.push(JSON.stringify(draft));
  draft = JSON.parse(undoStack.pop());
  afterHistoryJump();
}

function redo() {
  if (!redoStack.length) return;
  undoStack.push(JSON.stringify(draft));
  draft = JSON.parse(redoStack.pop());
  afterHistoryJump();
}

function afterHistoryJump() {
  if (selected?.kind === "room" && !roomByKey(selected.key)) selected = null;
  if (selected?.kind === "gate" && !draft.gates[selected.index]) selected = null;
  if (selected?.kind === "powerup" && !powerup(selected.key)) selected = null;
  dirty = true;
  refresh();
}

function refresh() {
  render();
  renderInspector();
  renderPowerups();
  updateChrome();
  schedulePreview();
}

const roomByKey = (key) => draft.rooms.find((r) => r.key === key);
const roomAt = (x, y) => draft.rooms.find((r) => r.x === x && r.y === y);
const gateBetween = (a, b) => draft.gates.findIndex((g) => (g.a === a && g.b === b) || (g.a === b && g.b === a));

function newRoomKey() {
  let n = draft.rooms.length + 1;
  while (roomByKey(`room${n}`)) n++;
  return `room${n}`;
}

function addRoom(x, y) {
  const key = newRoomKey();
  commit(() => draft.rooms.push({ key, name: "New room", x, y, seconds: 10, item: null }));
  select({ kind: "room", key });
}

function deleteSelected() {
  if (!selected) return;
  if (selected.kind === "room") {
    const key = selected.key;
    if (key === draft.start || key === draft.boss) return toast("Pick a different start or boss room before deleting this one.");
    commit(() => {
      draft.rooms = draft.rooms.filter((r) => r.key !== key);
      draft.gates = draft.gates.filter((g) => g.a !== key && g.b !== key);
    });
  } else {
    const index = selected.index;
    commit(() => draft.gates.splice(index, 1));
  }
  select(null);
}

function renameRoom(oldKey, newKey) {
  newKey = newKey.trim().toLowerCase();
  if (newKey === oldKey) return;
  if (!/^[a-z0-9_-]+$/.test(newKey)) return toast("Room keys use letters, numbers, - or _ only."), renderInspector();
  if (roomByKey(newKey)) return toast(`A room with key "${newKey}" already exists.`), renderInspector();
  commit(() => {
    roomByKey(oldKey).key = newKey;
    for (const g of draft.gates) {
      if (g.a === oldKey) g.a = newKey;
      if (g.b === oldKey) g.b = newKey;
    }
    if (draft.start === oldKey) draft.start = newKey;
    if (draft.boss === oldKey) draft.boss = newKey;
  });
  select({ kind: "room", key: newKey });
}

function select(sel) {
  selected = sel;
  render();
  renderInspector();
  renderPowerups();
}

// ------------------------------------------------------------------ drawing
function el(name, attrs = {}, parent = null) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
}

const cx = (r) => r.x * CELL_X + CELL_X / 2 + PAD;
const cy = (r) => r.y * CELL_Y + CELL_Y / 2 + PAD;

function render() {
  if (drag || connect) return;   // never rebuild the canvas mid-gesture
  // Always leave a few empty cells right and below, so there is space to grow into.
  const cols = Math.max(10, ...draft.rooms.map((r) => r.x + 3));
  const rows = Math.max(6, ...draft.rooms.map((r) => r.y + 3));
  viewW = cols * CELL_X + PAD * 2;
  viewH = rows * CELL_Y + PAD * 2;
  svg.setAttribute("viewBox", `0 0 ${viewW} ${viewH}`);
  applyZoom();
  svg.replaceChildren();

  const reachable = new Set(report?.valid ? report.reachable : draft.rooms.map((r) => r.key));
  const blocked = new Set(report?.valid ? report.blocked_gates : []);
  const traps = new Set(report?.valid ? report.trap_rooms : []);
  const held = report?.held_reachable ? new Set(report.held_reachable) : null;
  const badGates = new Set((report?.errors || []).filter((e) => e.gate !== undefined).map((e) => e.gate));

  // empty grid cells: click targets for the Add room tool
  const cells = el("g", { class: "designer-cell-layer" }, svg);
  for (let x = 0; x < cols; x++) {
    for (let y = 0; y < rows; y++) {
      if (roomAt(x, y)) continue;
      el("rect", {
        class: "designer-cell-slot", "data-cell": `${x},${y}`,
        x: x * CELL_X + PAD + (CELL_X - ROOM_W) / 2, y: y * CELL_Y + PAD + (CELL_Y - ROOM_H) / 2,
        width: ROOM_W, height: ROOM_H, rx: 3,
      }, cells);
    }
  }

  draft.gates.forEach((g, i) => {
    const a = roomByKey(g.a), b = roomByKey(g.b);
    if (!a || !b) return;
    let cls = "mapsvg-edge-line";
    if (g.one_way) cls += " is-oneway";
    if (blocked.has(i)) cls += " is-blocked";
    if (selected?.kind === "gate" && selected.index === i) cls += " is-selected";
    if (held && !(held.has(g.a) && held.has(g.b))) cls += " is-faded";
    el("line", { class: cls, x1: cx(a), y1: cy(a), x2: cx(b), y2: cy(b) }, svg);
    if (g.one_way) {
      const t = 0.72, px = cx(a) + (cx(b) - cx(a)) * t, py = cy(a) + (cy(b) - cy(a)) * t;
      const ang = Math.atan2(cy(b) - cy(a), cx(b) - cx(a)) * 180 / Math.PI;
      el("polygon", { class: "mapsvg-edge-arrow", points: "-6,-6 6,0 -6,6", transform: `translate(${px} ${py}) rotate(${ang})` }, svg);
    }
  });

  for (const r of draft.rooms) {
    const group = el("g", { "data-room": r.key, transform: `translate(${cx(r) - ROOM_W / 2} ${cy(r) - ROOM_H / 2})`, class: "designer-room-group" }, svg);
    let cls = "mapsvg-room-box";
    if (!reachable.has(r.key)) cls += " is-dead";
    if (traps.has(r.key)) cls += " is-danger";
    if (r.key === draft.start) cls += " is-start";
    if (r.key === draft.boss) cls += " is-boss";
    if (selected?.kind === "room" && selected.key === r.key) cls += " is-selected";
    if (held && !held.has(r.key)) cls += " is-faded";
    el("rect", { class: cls, width: ROOM_W, height: ROOM_H, rx: 3 }, group);
    el("text", { class: "mapsvg-room-name", x: ROOM_W / 2, y: ROOM_H / 2 + 4 }, group).textContent = r.name;
    const tag = r.key === draft.start ? "START" : r.key === draft.boss ? "BOSS" : "";
    if (tag) el("text", { class: "mapsvg-room-tag", x: 6, y: 12 }, group).textContent = tag;
    el("text", { class: "mapsvg-room-time", x: 6, y: ROOM_H - 6 }, group).textContent = `${r.seconds}s`;
    if (r.item) {
      el("circle", { class: "mapsvg-item-dot", style: `fill:${colorOf(r.item)}`, cx: ROOM_W - 10, cy: 10, r: 8 }, group);
      el("text", { class: "mapsvg-item-letter", x: ROOM_W - 10, y: 13.5 }, group).textContent = r.item;
    }
  }

  // door badges go last so they sit on top of lines and rooms
  draft.gates.forEach((g, i) => {
    const a = roomByKey(g.a), b = roomByKey(g.b);
    if (!a || !b) return;
    const label = g.rule ? g.rule.replace(/\s+/g, "") : "·";
    const w = Math.max(22, label.length * 6.8 + 12), mx = (cx(a) + cx(b)) / 2, my = (cy(a) + cy(b)) / 2;
    const single = abilities().some((p) => p.key === label.toUpperCase()) ? label.toUpperCase() : null;
    const kind = !g.rule ? "open" : single ? "single" : "compound";
    let cls = `mapsvg-gate-badge mapsvg-gate-${kind} is-link`;
    if (badGates.has(i)) cls += " is-error";
    const badge = el("g", { class: cls, "data-gate": i }, svg);
    const fill = single ? { style: `fill:${colorOf(single)}` } : {};   // inline style beats the stylesheet
    el("rect", { ...fill, x: mx - w / 2, y: my - 10, width: w, height: 20, rx: 10 }, badge);
    el("text", { x: mx, y: my + 3.6 }, badge).textContent = label;
  });
  renderLegend();
}

function renderLegend() {
  document.getElementById("designer-legend").innerHTML =
    draft.powerups.map((p) => `<span><i style="background:${p.color}"></i>${p.key} · ${esc(p.name)}</span>`).join("") +
    "<span>Dim room = unreachable</span><span>Red door = blocks the player</span><span>Dashed outline = trap</span>";
}

// ------------------------------------------------------------------ power-ups
const SWATCHES = ["#f5c04a", "#4fd8ea", "#b08cff", "#6fe08a", "#ff7aa0", "#ff8a3d", "#5aa9ff", "#e45cff", "#c8f05a", "#ff5a5a", "#46e0ff", "#f0f0f0"];
const MAX_POWERUPS = 16, MAX_ABILITIES = 10;

const powerup = (key) => draft.powerups.find((p) => p.key === key);
const abilities = () => draft.powerups.filter((p) => p.progression);
const colorOf = (key) => powerup(key)?.color || "#8392bb";
// A whole-letter match: "J" in "J | (D & G)", but never the A inside "AND".
const letterRe = (key) => new RegExp(`(^|[^A-Za-z])${key}(?![A-Za-z])`, "gi");

function usesOf(key) {
  const rooms = draft.rooms.filter((r) => r.item === key).length;
  const doors = draft.gates.filter((g) => letterRe(key).test(g.rule || "")).length;
  return { rooms, doors };
}

function addPowerup() {
  if (draft.powerups.length >= MAX_POWERUPS) return toast(`A map can have at most ${MAX_POWERUPS} power-ups.`);
  const used = new Set(draft.powerups.map((p) => p.key));
  const key = [..."ABCFHIKLNOPQRSTUVWXYZDEGJM"].find((k) => !used.has(k));
  const usedColors = new Set(draft.powerups.map((p) => p.color));
  const color = SWATCHES.find((c) => !usedColors.has(c)) || SWATCHES[0];
  const progression = abilities().length < MAX_ABILITIES;
  commit(() => draft.powerups.push({ key, name: "New power-up", color, progression, short: "", description: "" }));
  select({ kind: "powerup", key });
}

function changePowerupKey(oldKey, value) {
  const key = value.trim().toUpperCase();
  if (key === oldKey) return;
  if (!/^[A-Z]$/.test(key)) return toast("A power-up letter must be one letter A–Z."), renderInspector();
  if (powerup(key)) return toast(`${powerup(key).name} already uses ${key}.`), renderInspector();
  selected = { kind: "powerup", key };     // follow the power-up to its new letter
  commit(() => {
    powerup(oldKey).key = key;
    for (const r of draft.rooms) if (r.item === oldKey) r.item = key;
    // Rewrite door rules too, so "W & D" becomes "X & D" when W is renamed to X.
    for (const g of draft.gates) g.rule = (g.rule || "").replace(letterRe(oldKey), (m, before) => before + key);
  });
  select({ kind: "powerup", key });
}

function setPowerupKind(key, progression) {
  const p = powerup(key);
  if (!progression && usesOf(key).doors) {
    renderInspector();
    return toast(`Doors still need ${p.name}. Take ${key} out of those rules before making it a collectible.`);
  }
  if (progression && abilities().length >= MAX_ABILITIES) {
    renderInspector();
    return toast(`A map can have at most ${MAX_ABILITIES} abilities.`);
  }
  commit(() => { p.progression = progression; });
}

function deletePowerup(key) {
  const p = powerup(key);
  const uses = usesOf(key);
  if (uses.doors) return toast(`${uses.doors} door rule(s) use ${key}. Change those doors first.`);
  if (draft.powerups.length === 1) return toast("A map needs at least one power-up.");
  commit(() => {
    draft.powerups = draft.powerups.filter((q) => q.key !== key);
    for (const r of draft.rooms) if (r.item === key) r.item = null;
  });
  select(null);
  if (uses.rooms) toast(`Deleted ${p.name} and emptied ${uses.rooms} room(s) that held it.`);
}

function renderPowerups() {
  const list = document.getElementById("designer-powerups");
  list.innerHTML = draft.powerups.map((p) => {
    const u = usesOf(p.key);
    const sel = selected?.kind === "powerup" && selected.key === p.key;
    return `<li><button type="button" class="designer-powerup-row${sel ? " is-selected" : ""}" data-powerup="${p.key}">
      <span class="designer-powerup-badge" style="background:${p.color}">${p.key}</span>
      <span class="designer-powerup-name"><b>${esc(p.name)}</b><small>${p.progression ? "Ability · opens doors" : "Collectible · +energy"}</small></span>
      <span class="designer-powerup-uses">${u.rooms}▣ ${u.doors}⇄</span></button></li>`;
  }).join("");
  list.querySelectorAll("[data-powerup]").forEach((b) => b.addEventListener("click", () => select({ kind: "powerup", key: b.dataset.powerup })));
  document.getElementById("designer-add-powerup").disabled = draft.powerups.length >= MAX_POWERUPS;

  // The "test with abilities" chips follow the power-up list, keeping ticks that still exist.
  const box = document.getElementById("designer-abilities");
  const ticked = new Set(heldAbilities());
  box.innerHTML = abilities().map((p) =>
    `<label class="base-form-chip"><input type="checkbox" value="${p.key}" ${ticked.has(p.key) ? "checked" : ""}><i style="background:${p.color}"></i>${esc(p.name)}</label>`).join("");
  box.querySelectorAll("input").forEach((i) => i.addEventListener("change", schedulePreview));
}

// ------------------------------------------------------------------ zoom and pan
const ZOOM_MIN = 0.25, ZOOM_MAX = 3;

function applyZoom() {
  svg.setAttribute("width", Math.round(viewW * zoom));
  svg.setAttribute("height", Math.round(viewH * zoom));
  const pct = Math.round(zoom * 100);
  document.getElementById("designer-zoom-value").textContent = `${pct}%`;
  document.getElementById("designer-zoom-range").value = pct;
}

// Zoom so the point under `anchor` (a mouse position) stays put, like a map app.
function setZoom(next, anchor = null) {
  next = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, next));
  const box = scroller.getBoundingClientRect();
  const ax = anchor ? anchor.clientX - box.left : box.width / 2;
  const ay = anchor ? anchor.clientY - box.top : box.height / 2;
  const contentX = (scroller.scrollLeft + ax) / zoom;
  const contentY = (scroller.scrollTop + ay) / zoom;
  zoom = next;
  applyZoom();
  scroller.scrollLeft = contentX * zoom - ax;
  scroller.scrollTop = contentY * zoom - ay;
}

function fitZoom() {
  const used = draft.rooms.length ? {
    w: (Math.max(...draft.rooms.map((r) => r.x)) + 1) * CELL_X + PAD * 2,
    h: (Math.max(...draft.rooms.map((r) => r.y)) + 1) * CELL_Y + PAD * 2,
  } : { w: viewW, h: viewH };
  zoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.min((scroller.clientWidth - 4) / used.w, (scroller.clientHeight - 4) / used.h)));
  applyZoom();
  scroller.scrollLeft = 0;
  scroller.scrollTop = 0;
}

scroller.addEventListener("wheel", (evt) => {
  if (!(evt.ctrlKey || evt.metaKey)) return;     // plain scroll still scrolls
  evt.preventDefault();
  setZoom(zoom * Math.exp(-evt.deltaY * 0.0015), evt);
}, { passive: false });

document.getElementById("designer-zoom-in").addEventListener("click", () => setZoom(zoom * 1.2));
document.getElementById("designer-zoom-out").addEventListener("click", () => setZoom(zoom / 1.2));
document.getElementById("designer-zoom-fit").addEventListener("click", fitZoom);
document.getElementById("designer-zoom-reset").addEventListener("click", () => setZoom(1));
document.getElementById("designer-zoom-range").addEventListener("input", (e) => setZoom(Number(e.target.value) / 100));

// Two fingers on a touch screen: pinch to zoom.
const touches = new Map();
let pinch = null;
svg.addEventListener("pointerdown", (evt) => {
  if (evt.pointerType !== "touch") return;
  touches.set(evt.pointerId, evt);
  if (touches.size === 2) {
    const [a, b] = [...touches.values()];
    pinch = { dist: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY), zoom };
    cancelGesture();
  }
}, true);
svg.addEventListener("pointermove", (evt) => {
  if (!touches.has(evt.pointerId)) return;
  touches.set(evt.pointerId, evt);
  if (pinch && touches.size === 2) {
    const [a, b] = [...touches.values()];
    const mid = { clientX: (a.clientX + b.clientX) / 2, clientY: (a.clientY + b.clientY) / 2 };
    setZoom(pinch.zoom * Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY) / pinch.dist, mid);
  }
}, true);
["pointerup", "pointercancel"].forEach((t) => svg.addEventListener(t, (evt) => {
  touches.delete(evt.pointerId);
  if (touches.size < 2) pinch = null;
}, true));

function cancelGesture() {
  if (drag) { drag.el.classList.remove("is-dragging"); drag = null; }
  if (connect) { connect = null; }
  pan = null;
  scroller.classList.remove("is-panning");
  render();
}

// ------------------------------------------------------------------ pointer input
function svgPoint(evt) {
  const pt = new DOMPoint(evt.clientX, evt.clientY);
  return pt.matrixTransform(svg.getScreenCTM().inverse());
}

svg.addEventListener("pointerdown", (evt) => {
  if (pinch) return;
  const roomEl = evt.target.closest("[data-room]");
  const gateEl = evt.target.closest("[data-gate]");
  const cellEl = evt.target.closest("[data-cell]");
  const p = svgPoint(evt);

  if (evt.button === 1 || (!roomEl && !gateEl && !(cellEl && tool === "add"))) {
    // Middle button anywhere, or any button on empty space: pan the canvas.
    evt.preventDefault();
    pan = { x: evt.clientX, y: evt.clientY, left: scroller.scrollLeft, top: scroller.scrollTop, moved: false };
    scroller.classList.add("is-panning");
    svg.setPointerCapture(evt.pointerId);
  } else if (roomEl && tool === "door") {
    const from = roomByKey(roomEl.dataset.room);
    connect = { from: from.key, line: el("line", { class: "designer-temp-line", x1: cx(from), y1: cy(from), x2: p.x, y2: p.y }, svg) };
    svg.setPointerCapture(evt.pointerId);
  } else if (roomEl) {
    const r = roomByKey(roomEl.dataset.room);
    drag = { key: r.key, el: roomEl, startX: p.x, startY: p.y, moved: false };
    roomEl.classList.add("is-dragging");
    svg.setPointerCapture(evt.pointerId);
  } else if (gateEl) {
    select({ kind: "gate", index: Number(gateEl.dataset.gate) });
  } else if (cellEl && tool === "add") {
    const [x, y] = cellEl.dataset.cell.split(",").map(Number);
    addRoom(x, y);
  }
});

svg.addEventListener("pointermove", (evt) => {
  if (pan) {
    const dx = evt.clientX - pan.x, dy = evt.clientY - pan.y;
    if (Math.hypot(dx, dy) > 3) pan.moved = true;
    scroller.scrollLeft = pan.left - dx;
    scroller.scrollTop = pan.top - dy;
    return;
  }
  const p = svgPoint(evt);
  if (drag) {
    const dx = p.x - drag.startX, dy = p.y - drag.startY;
    if (Math.hypot(dx, dy) > 4) drag.moved = true;
    const r = roomByKey(drag.key);
    drag.el.setAttribute("transform", `translate(${cx(r) - ROOM_W / 2 + dx} ${cy(r) - ROOM_H / 2 + dy})`);
  } else if (connect) {
    connect.line.setAttribute("x2", p.x);
    connect.line.setAttribute("y2", p.y);
  }
});

svg.addEventListener("pointerup", (evt) => {
  if (pan) {
    const moved = pan.moved;
    pan = null;
    scroller.classList.remove("is-panning");
    if (!moved) select(null);     // a click on empty space clears the selection
    return;
  }
  if (drag) {
    const d = drag;
    drag = null;
    const r = roomByKey(d.key);
    if (!d.moved) return select({ kind: "room", key: d.key });
    const p = svgPoint(evt);
    // snap the room's centre to the nearest cell
    const x = Math.max(0, Math.round((cx(r) + p.x - d.startX - PAD - CELL_X / 2) / CELL_X));
    const y = Math.max(0, Math.round((cy(r) + p.y - d.startY - PAD - CELL_Y / 2) / CELL_Y));
    const other = roomAt(x, y);
    if (other && other.key !== r.key) {
      toast(`${other.name} already sits there.`);
      render();
    } else if (x !== r.x || y !== r.y) {
      commit(() => { r.x = x; r.y = y; });
    } else {
      render();
    }
  } else if (connect) {
    const c = connect;
    connect = null;
    const target = document.elementFromPoint(evt.clientX, evt.clientY)?.closest("[data-room]");
    render();
    if (!target || target.dataset.room === c.from) return;
    const existing = gateBetween(c.from, target.dataset.room);
    if (existing >= 0) {
      toast("Those rooms already have a door. Edit it in the side panel.");
      return select({ kind: "gate", index: existing });
    }
    commit(() => draft.gates.push({ a: c.from, b: target.dataset.room, rule: "", one_way: false }));
    select({ kind: "gate", index: draft.gates.length - 1 });
  }
});

// ------------------------------------------------------------------ side panel
function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function renderInspector() {
  const box = document.getElementById("designer-inspector");
  if (selected?.kind === "room") {
    const r = roomByKey(selected.key);
    const fixed = r.key === draft.start || r.key === draft.boss;
    box.innerHTML = `
      <h2 class="base-panel-title">Room</h2>
      <label class="base-form-field"><span>Name</span><input id="insp-name" maxlength="60" value="${esc(r.name)}"></label>
      <div class="base-form-pair">
        <label class="base-form-field"><span>Key</span><input id="insp-key" class="base-input-mono" value="${esc(r.key)}"></label>
        <label class="base-form-field"><span>Seconds</span><input id="insp-seconds" type="number" min="1" max="999" value="${r.seconds}"></label>
      </div>
      <label class="base-form-field"><span>Item</span><select id="insp-item"><option value="">None</option>
        ${draft.powerups.map((p) => `<option value="${p.key}" ${r.item === p.key ? "selected" : ""}>${p.key} · ${esc(p.name)}</option>`).join("")}</select></label>
      <div class="base-btn-row">
        <button type="button" class="base-btn-action" id="insp-start" ${r.key === draft.start ? "disabled" : ""}>Make start</button>
        <button type="button" class="base-btn-action" id="insp-boss" ${r.key === draft.boss ? "disabled" : ""}>Make boss</button>
        <button type="button" class="base-btn-action is-danger" id="insp-delete" ${fixed ? "disabled" : ""}>Delete room</button>
      </div>`;
    box.querySelector("#insp-name").addEventListener("change", (e) => commit(() => { r.name = e.target.value.trim() || r.key; }));
    box.querySelector("#insp-key").addEventListener("change", (e) => renameRoom(r.key, e.target.value));
    box.querySelector("#insp-seconds").addEventListener("change", (e) => {
      const s = Math.min(999, Math.max(1, parseInt(e.target.value, 10) || 1));
      commit(() => { r.seconds = s; });
    });
    box.querySelector("#insp-item").addEventListener("change", (e) => commit(() => { r.item = e.target.value || null; }));
    box.querySelector("#insp-start").addEventListener("click", () => commit(() => { draft.start = r.key; }));
    box.querySelector("#insp-boss").addEventListener("click", () => commit(() => { draft.boss = r.key; }));
    box.querySelector("#insp-delete").addEventListener("click", deleteSelected);
  } else if (selected?.kind === "gate") {
    const g = draft.gates[selected.index];
    const err = (report?.errors || []).find((e) => e.gate === selected.index);
    box.innerHTML = `
      <h2 class="base-panel-title">Door</h2>
      <p class="base-text-muted">${esc(roomByKey(g.a).name)} ${g.one_way ? "→" : "↔"} ${esc(roomByKey(g.b).name)}</p>
      <label class="base-form-field"><span>Rule (blank = open)</span>
        <input id="insp-rule" class="base-input-mono" value="${esc(g.rule)}" placeholder="e.g. J | (D & G)" spellcheck="false" autocomplete="off"></label>
      ${err ? `<p class="is-bad">${esc(err.message)}</p>` : ""}
      <label class="base-form-chip"><input type="checkbox" id="insp-oneway" ${g.one_way ? "checked" : ""}> One-way (first room to second only)</label>
      <div class="base-btn-row">
        <button type="button" class="base-btn-action" id="insp-flip">Flip direction</button>
        <button type="button" class="base-btn-action is-danger" id="insp-delete">Delete door</button>
      </div>`;
    box.querySelector("#insp-rule").addEventListener("change", (e) => commit(() => { g.rule = e.target.value.trim(); }));
    box.querySelector("#insp-oneway").addEventListener("change", (e) => commit(() => { g.one_way = e.target.checked; }));
    box.querySelector("#insp-flip").addEventListener("click", () => commit(() => { [g.a, g.b] = [g.b, g.a]; }));
    box.querySelector("#insp-delete").addEventListener("click", deleteSelected);
  } else if (selected?.kind === "powerup") {
    const p = powerup(selected.key);
    const u = usesOf(p.key);
    box.innerHTML = `
      <h2 class="base-panel-title">Power-up</h2>
      <div class="base-form-pair">
        <label class="base-form-field"><span>Letter (used in rules)</span><input id="insp-pkey" class="base-input-mono" maxlength="1" value="${p.key}" autocomplete="off"></label>
        <label class="base-form-field"><span>Short label</span><input id="insp-pshort" maxlength="14" value="${esc(p.short)}" placeholder="${esc(p.name.split(" ").pop())}"></label>
      </div>
      <label class="base-form-field"><span>Name</span><input id="insp-pname" maxlength="40" value="${esc(p.name)}"></label>
      <div class="base-form-field"><span>Colour</span>
        <div class="designer-swatch-row">
          ${SWATCHES.map((c) => `<button type="button" class="designer-swatch-btn" data-swatch="${c}" style="background:${c}" aria-label="Colour ${c}" aria-pressed="${c === p.color}"></button>`).join("")}
          <input type="color" id="insp-pcolor" value="${p.color}" aria-label="Custom colour">
        </div></div>
      <fieldset class="base-form-radio"><legend>Type</legend>
        <label><input type="radio" name="insp-pkind" value="ability" ${p.progression ? "checked" : ""}> <span><b>Ability</b>: can open doors in rules</span></label>
        <label><input type="radio" name="insp-pkind" value="collectible" ${p.progression ? "" : "checked"}> <span><b>Collectible</b>: opens nothing, adds max energy in the game</span></label>
      </fieldset>
      <label class="base-form-field"><span>Description (shown when picked up)</span><textarea id="insp-pdesc" rows="2" maxlength="160">${esc(p.description)}</textarea></label>
      <p class="base-text-muted">Placed in ${u.rooms} room(s) · used by ${u.doors} door rule(s).</p>
      <div class="base-btn-row"><button type="button" class="base-btn-action is-danger" id="insp-pdelete">Delete power-up</button></div>`;
    box.querySelector("#insp-pkey").addEventListener("change", (e) => changePowerupKey(p.key, e.target.value));
    box.querySelector("#insp-pname").addEventListener("change", (e) => commit(() => { p.name = e.target.value.trim() || p.key; }));
    box.querySelector("#insp-pshort").addEventListener("change", (e) => commit(() => { p.short = e.target.value.trim(); }));
    box.querySelector("#insp-pdesc").addEventListener("change", (e) => commit(() => { p.description = e.target.value.trim(); }));
    box.querySelector("#insp-pcolor").addEventListener("change", (e) => commit(() => { p.color = e.target.value; }));
    box.querySelectorAll("[data-swatch]").forEach((b) => b.addEventListener("click", () => commit(() => { p.color = b.dataset.swatch; })));
    box.querySelectorAll("[name=insp-pkind]").forEach((r) => r.addEventListener("change", () => setPowerupKind(p.key, r.value === "ability")));
    box.querySelector("#insp-pdelete").addEventListener("click", () => deletePowerup(p.key));
  } else {
    box.innerHTML = `
      <h2 class="base-panel-title">Map</h2>
      <label class="base-form-field"><span>Name</span><input id="insp-mapname" maxlength="80" value="${esc(draft.name)}"></label>
      <label class="base-form-field"><span>Description</span><textarea id="insp-mapdesc" rows="2">${esc(draft.description)}</textarea></label>
      <p class="base-text-muted">${draft.rooms.length} rooms · ${draft.gates.length} doors. Click a room or door to edit it. Press Delete to remove the selected one.</p>`;
    box.querySelector("#insp-mapname").addEventListener("change", (e) => commit(() => { draft.name = e.target.value.trim() || "Untitled map"; }));
    box.querySelector("#insp-mapdesc").addEventListener("change", (e) => commit(() => { draft.description = e.target.value; }));
  }
}

// ------------------------------------------------------------------ live check
let previewTimer = null, previewSeq = 0;

function heldAbilities() {
  return [...document.querySelectorAll("#designer-abilities input:checked")].map((i) => i.value).join("");
}

function schedulePreview() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(runPreview, 200);
}

async function runPreview() {
  const seq = ++previewSeq;
  try {
    const res = await fetch(root.dataset.previewUrl, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ map: draft, abilities: heldAbilities() }),
    });
    const data = await res.json();
    if (seq !== previewSeq) return;     // a newer check has already started
    report = data;
  } catch {
    report = { valid: false, errors: [{ message: "Couldn't reach the server. Is it still running?" }] };
  }
  render();
  renderReport();
  if (selected?.kind === "gate") renderInspector();
}

function renderReport() {
  const chip = document.getElementById("designer-status");
  const box = document.getElementById("designer-report");
  if (!report.valid) {
    if (selected?.kind !== "powerup" && report.errors.some((e) => e.powerups)) renderPowerups();
    chip.textContent = "Invalid";
    chip.className = "base-status-chip is-warn";
    box.innerHTML = `<ul class="base-list-rows">${report.errors.map((e) => `<li><span class="base-list-key is-bad">✕</span><span>${esc(e.message)}</span></li>`).join("")}</ul>`;
    return;
  }
  chip.textContent = report.beatable ? "Beatable" : "Soft-locked";
  chip.className = `base-status-chip ${report.beatable ? "is-ok" : "is-bad"}`;
  const total = draft.rooms.length, reach = report.reachable.length;
  box.innerHTML = `
    <ul class="base-list-rows">
      <li><span class="base-list-key">Reach</span><span>${reach} of ${total} rooms can be reached</span></li>
      <li><span class="base-list-key">Route</span><span>${report.fastest_seconds !== null ? `Fastest finish: ${report.fastest_seconds}s` : "No route to the boss"}</span></li>
      <li><span class="base-list-key ${report.trap_rooms.length ? "is-bad" : "is-ok"}">Traps</span><span>${report.trap_rooms.length
        ? `Players can get stuck in ${report.trap_rooms.map((k) => esc(roomByKey(k)?.name ?? k)).join(", ")}`
        : "No room can trap the player"}</span></li>
      ${report.blocked_gates.length ? `<li><span class="base-list-key is-bad">Doors</span><span>${report.blocked_gates.length} door(s) stay locked. They're shown in red.</span></li>` : ""}
    </ul>`;
}

// ------------------------------------------------------------------ toolbar, saving, keys
function updateChrome() {
  document.getElementById("designer-title").textContent = draft.name;
  document.getElementById("designer-undo").disabled = !undoStack.length;
  document.getElementById("designer-redo").disabled = !redoStack.length;
  const dirtyEl = document.getElementById("designer-dirty");
  if (dirtyEl) dirtyEl.hidden = !dirty;
}

let toastTimer = null;
function toast(message) {
  const t = document.getElementById("designer-toast");
  t.textContent = message;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 3200);
}

document.querySelectorAll("[data-tool]").forEach((btn) => btn.addEventListener("click", () => {
  tool = btn.dataset.tool;
  document.querySelectorAll("[data-tool]").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
  svg.dataset.tool = tool;
}));
svg.dataset.tool = tool;

document.getElementById("designer-undo").addEventListener("click", undo);
document.getElementById("designer-redo").addEventListener("click", redo);

document.getElementById("designer-add-powerup").addEventListener("click", addPowerup);

// Play the draft in a new tab without saving it. localStorage is shared between tabs of this site.
document.getElementById("designer-play").addEventListener("click", () => {
  try {
    localStorage.setItem("tcsmetroid-play-draft", JSON.stringify(draft));
  } catch {
    return toast("Your browser blocked local storage, so the draft can't be handed to the game.");
  }
  window.open(root.dataset.playUrl, "_blank");
});

async function sendMap(url, method) {
  const res = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft) });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `The server answered ${res.status}.`);
  return body;
}

document.getElementById("designer-save")?.addEventListener("click", async () => {
  try {
    const body = await sendMap(root.dataset.saveUrl, "PUT");
    dirty = false;
    updateChrome();
    toast(body.cleared_seeds ? `Saved. Cleared ${body.cleared_seeds} stored seeds because the map changed.` : "Saved.");
  } catch (err) {
    toast(`Not saved: ${err.message}`);
  }
});

document.getElementById("designer-save-new")?.addEventListener("click", async () => {
  try {
    const body = await sendMap(root.dataset.createUrl, "POST");
    window.location.href = root.dataset.designerUrl.replace("/0/", `/${body.id}/`);
  } catch (err) {
    toast(`Not saved: ${err.message}`);
  }
});

document.getElementById("designer-export")?.addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(draft, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${(draft.name || "map").toLowerCase().replace(/[^a-z0-9]+/g, "-")}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
});

document.addEventListener("keydown", (evt) => {
  if (evt.target.closest("input, textarea, select")) return;
  const mod = evt.ctrlKey || evt.metaKey;
  if (mod && evt.key.toLowerCase() === "z" && !evt.shiftKey) { evt.preventDefault(); undo(); }
  else if (mod && (evt.key.toLowerCase() === "y" || (evt.key.toLowerCase() === "z" && evt.shiftKey))) { evt.preventDefault(); redo(); }
  else if (evt.key === "Delete" || evt.key === "Backspace") { evt.preventDefault(); deleteSelected(); }
  else if (evt.key === "Escape") select(null);
  else if (!mod && (evt.key === "+" || evt.key === "=")) setZoom(zoom * 1.2);
  else if (!mod && (evt.key === "-" || evt.key === "_")) setZoom(zoom / 1.2);
  else if (!mod && evt.key === "0") fitZoom();
  else if (!mod && evt.key === "1") setZoom(1);
  else if (!mod && ["v", "d", "r"].includes(evt.key.toLowerCase())) {
    const want = { v: "move", d: "door", r: "add" }[evt.key.toLowerCase()];
    document.querySelector(`[data-tool="${want}"]`).click();
  }
});

window.addEventListener("beforeunload", (evt) => {
  if (MODE === "designer" && dirty) { evt.preventDefault(); evt.returnValue = ""; }
});

refresh();
fitZoom();
dirty = false;
updateChrome();
