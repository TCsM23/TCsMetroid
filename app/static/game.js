// TCsMetroid play mode: a top-down Metroidvania built from a planner map.
//
// The server does the graph work (static/services.py -> game_data):
//   - every door comes with its minimal ability sets, so a door is open when
//     one set is fully inside the player's ability bitmask
//   - "trapped" lists (room|mask) states from which the boss can never be reached
// This file turns that data into rooms you can walk around, then runs the game loop.
"use strict";

// ------------------------------------------------------------------ constants
const W = 960, H = 600, T = 40;                 // logical screen size and tile size
const COLS = W / T, ROWS = H / T;               // 24 x 15 tiles per room
const PLAYER_HALF = 13, PLAYER_SPEED = 210;
const BEAM_SPEED = 640, BEAM_COOLDOWN = 0.2;
const BASE_ENERGY = 99, TANK_ENERGY = 100;

const $ = (id) => document.getElementById(id);
const stage = $("game-stage");
const canvas = $("game-canvas");
const ctx = canvas.getContext("2d");
const config = JSON.parse($("play-config").textContent);

// ------------------------------------------------------------------ small helpers
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

function hashString(s) {                         // FNV-1a: same room key -> same layout every visit
  let h = 2166136261;
  for (const ch of s) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return h >>> 0;
}

function seeded(seed) {                          // mulberry32 pseudo-random numbers
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function hexToRgba(hex, alpha) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

// ------------------------------------------------------------------ sound (tiny synth, no files)
let audio = null;
let muted = false;
try { muted = localStorage.getItem("tcsmetroid-muted") === "1"; } catch { /* storage blocked: default on */ }

function tone(freq, dur, { type = "square", vol = 0.05, slide = null, delay = 0 } = {}) {
  if (muted) return;
  try {
    audio ||= new (window.AudioContext || window.webkitAudioContext)();
    const t0 = audio.currentTime + delay;
    const osc = audio.createOscillator(), gain = audio.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, t0);
    if (slide) osc.frequency.exponentialRampToValueAtTime(slide, t0 + dur);
    gain.gain.setValueAtTime(vol, t0);
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    osc.connect(gain).connect(audio.destination);
    osc.start(t0);
    osc.stop(t0 + dur + 0.02);
  } catch { /* audio unavailable */ }
}

const sfx = {
  shoot: () => tone(920, 0.07, { slide: 420, vol: 0.025 }),
  hit: () => tone(240, 0.06, { type: "triangle", vol: 0.05 }),
  kill: () => tone(300, 0.18, { type: "sawtooth", slide: 60, vol: 0.04 }),
  hurt: () => tone(180, 0.22, { type: "sawtooth", slide: 70, vol: 0.06 }),
  door: () => tone(330, 0.14, { type: "sine", slide: 660, vol: 0.05 }),
  locked: () => tone(110, 0.16, { type: "square", vol: 0.03 }),
  pickup: () => [523, 659, 784, 1046].forEach((f, i) => tone(f, 0.16, { type: "triangle", vol: 0.06, delay: i * 0.09 })),
  boss: () => tone(70, 0.5, { type: "sawtooth", slide: 40, vol: 0.06 }),
  win: () => [392, 523, 659, 784, 1046].forEach((f, i) => tone(f, 0.25, { type: "triangle", vol: 0.07, delay: i * 0.12 })),
};

// ------------------------------------------------------------------ game data
let data = null;            // from the server
let powerupByKey = new Map();
let trapped = new Set();
let totalItems = 0;
let mapBounds = null;

function prepare(game) {
  data = game;
  powerupByKey = new Map(game.powerups.map((p) => [p.key, p]));
  trapped = new Set(game.trapped);
  totalItems = Object.values(game.rooms).filter((r) => r.item).length;
  const xs = Object.values(game.rooms).map((r) => r.x), ys = Object.values(game.rooms).map((r) => r.y);
  mapBounds = { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
  layouts.clear();
}

const canOpen = (sets, mask) => sets.some((s) => (s & mask) === s);
const powerupName = (key) => powerupByKey.get(key)?.name ?? key;

function setsToText(sets) {
  // [bits of J, bits of D|G] -> "Double Jump, or Dash Boots + Grapple Beam"
  return sets.map((s) => data.powerups.filter((p) => p.bit && (s & p.bit)).map((p) => p.name).join(" + ")).join(", or ");
}

function doorColors(sets) {
  const keys = new Set();
  for (const s of sets) for (const p of data.powerups) if (p.bit && (s & p.bit)) keys.add(p.key);
  return [...keys].map((k) => powerupByKey.get(k).color);
}

// ------------------------------------------------------------------ room layouts
const layouts = new Map();

// Which wall of room `a` a door to room `b` sits on, from their grid positions.
function wallFor(a, b) {
  const ra = data.rooms[a], rb = data.rooms[b];
  const dx = rb.x - ra.x, dy = rb.y - ra.y;
  if (dx !== 0 && Math.abs(dx) >= Math.abs(dy)) return dx > 0 ? "E" : "W";
  if (dy !== 0) return dy > 0 ? "S" : "N";
  return "E";
}

const PILLAR_PATTERNS = [
  [],
  [[5, 4, 2, 2], [17, 4, 2, 2], [5, 9, 2, 2], [17, 9, 2, 2]],
  [[7, 4, 1, 7], [16, 4, 1, 7]],
  [[5, 4, 4, 1], [15, 4, 4, 1], [5, 10, 4, 1], [15, 10, 4, 1]],
  [[6, 5, 1, 1], [9, 4, 1, 1], [14, 4, 1, 1], [17, 5, 1, 1], [6, 9, 1, 1], [9, 10, 1, 1], [14, 10, 1, 1], [17, 9, 1, 1]],
  [[5, 4, 3, 1], [5, 5, 1, 2], [16, 4, 3, 1], [18, 5, 1, 2], [5, 10, 3, 1], [5, 8, 1, 2], [16, 10, 3, 1], [18, 8, 1, 2]],
];

function getLayout(key) {
  if (layouts.has(key)) return layouts.get(key);
  const room = data.rooms[key];
  const hash = hashString(key);
  const solid = new Uint8Array(COLS * ROWS);
  for (let x = 0; x < COLS; x++) { solid[x] = 1; solid[(ROWS - 1) * COLS + x] = 1; }
  for (let y = 0; y < ROWS; y++) { solid[y * COLS] = 1; solid[y * COLS + COLS - 1] = 1; }

  const pattern = key === data.boss ? [] : PILLAR_PATTERNS[hash % PILLAR_PATTERNS.length];
  for (const [px, py, pw, ph] of pattern) {
    for (let x = px; x < px + pw; x++) for (let y = py; y < py + ph; y++) solid[y * COLS + x] = 1;
  }

  // Doors: group this room's gates by wall, then spread them out along it.
  const byWall = { N: [], S: [], E: [], W: [] };
  data.gates.forEach((g, i) => {
    if (g.a !== key && g.b !== key) return;
    const other = g.a === key ? g.b : g.a;
    byWall[wallFor(key, other)].push({ gate: i, to: other, g });
  });
  const doors = [];
  const doorAt = new Map();          // tile index -> door, for the wall tiles a door replaces
  for (const [wall, list] of Object.entries(byWall)) {
    const vertical = wall === "E" || wall === "W";
    list.sort((p, q) => {
      const a = data.rooms[p.to], b = data.rooms[q.to];
      return (vertical ? a.y - b.y || a.x - b.x : a.x - b.x || a.y - b.y) || p.gate - q.gate;
    });
    const length = vertical ? ROWS - 2 : COLS - 2;
    const size = list.length <= 3 ? 3 : 2;
    list.forEach((d, k) => {
      const start = clamp(Math.round(1 + (k + 1) * length / (list.length + 1) - size / 2), 2, (vertical ? ROWS : COLS) - 2 - size);
      const tiles = [];
      for (let s = start; s < start + size; s++) {
        const tx = vertical ? (wall === "W" ? 0 : COLS - 1) : s;
        const ty = vertical ? s : (wall === "N" ? 0 : ROWS - 1);
        tiles.push(ty * COLS + tx);
      }
      const door = {
        gate: d.gate, to: d.to, wall, tiles, sets: d.g.sets, rule: d.g.rule,
        // A one-way gate only goes from a to b, so from b's side it is a sealed hatch.
        sealed: d.g.one_way && d.g.b === key,
        colors: doorColors(d.g.sets), open: false,
        x: vertical ? (wall === "W" ? 0 : W - T) : start * T,
        y: vertical ? start * T : (wall === "N" ? 0 : H - T),
        w: vertical ? T : size * T, h: vertical ? size * T : T,
      };
      doors.push(door);
      for (const t of tiles) doorAt.set(t, door);
    });
  }

  const hue = (hash >> 8) % 360;
  const layout = { key, room, solid, doors, doorAt, hue, hash, background: null };
  layout.background = paintBackground(layout);
  layouts.set(key, layout);
  return layout;
}

// Walls, floor and pillars never change, so they are painted once per room into an offscreen canvas.
function paintBackground(layout) {
  const bg = document.createElement("canvas");
  bg.width = W; bg.height = H;
  const g = bg.getContext("2d");
  const { hue, solid } = layout;
  const floor = g.createRadialGradient(W / 2, H / 2, 40, W / 2, H / 2, W * 0.65);
  floor.addColorStop(0, `hsl(${hue}, 32%, 13%)`);
  floor.addColorStop(1, `hsl(${hue}, 40%, 6%)`);
  g.fillStyle = floor;
  g.fillRect(0, 0, W, H);
  g.strokeStyle = `hsla(${hue}, 60%, 60%, 0.07)`;
  g.lineWidth = 1;
  for (let x = 0; x <= W; x += T) { g.beginPath(); g.moveTo(x + 0.5, 0); g.lineTo(x + 0.5, H); g.stroke(); }
  for (let y = 0; y <= H; y += T) { g.beginPath(); g.moveTo(0, y + 0.5); g.lineTo(W, y + 0.5); g.stroke(); }

  for (let ty = 0; ty < ROWS; ty++) {
    for (let tx = 0; tx < COLS; tx++) {
      if (!solid[ty * COLS + tx]) continue;
      const x = tx * T, y = ty * T;
      g.fillStyle = `hsl(${hue}, 28%, 16%)`;
      g.fillRect(x, y, T, T);
      g.fillStyle = `hsl(${hue}, 35%, 24%)`;
      g.fillRect(x, y, T, 4);
      g.fillStyle = `hsl(${hue}, 30%, 9%)`;
      g.fillRect(x, y + T - 4, T, 4);
      g.strokeStyle = `hsla(${hue}, 50%, 50%, 0.25)`;
      g.strokeRect(x + 3.5, y + 6.5, T - 7, T - 13);
      g.fillStyle = `hsla(${hue}, 60%, 70%, 0.35)`;
      g.fillRect(x + 6, y + 9, 3, 3);
      g.fillRect(x + T - 9, y + 9, 3, 3);
    }
  }
  return bg;
}

// ------------------------------------------------------------------ run state
let state = "loading";       // loading | title | play | pause | dead | win | error
let run = null;
let player = null;
let layout = null;
let enemies = [], beams = [], shots = [], particles = [], pickups = [];
let boss = null;
let freeze = 0;              // seconds the action is frozen (power-up fanfare)
let shake = 0;
let lastTime = 0;
let toastTimer = 0, bannerTimer = 0, lockedCooldown = 0;
let alertDismissed = new Set();

function newRun() {
  run = {
    mask: 0, energy: BASE_ENERGY, maxEnergy: BASE_ENERGY,
    collected: new Set(), visited: new Set(), seen: new Set(),
    time: 0, moves: 0, deaths: 0, kills: 0, bossDown: false,
  };
  player = { x: W / 2, y: H / 2, face: { x: 0, y: 1 }, cooldown: 0, invuln: 0 };
  alertDismissed = new Set();
  enterRoom(data.start, null);
  updateHudAll();
}

function enterRoom(key, viaGate) {
  layout = getLayout(key);
  run.room = key;
  run.visited.add(key);
  for (const d of layout.doors) run.seen.add(d.to);
  beams = []; shots = []; particles = []; pickups = []; boss = null;

  const entry = viaGate === null ? null : layout.doors.find((d) => d.gate === viaGate);
  if (entry) {
    const mid = (a, b) => a + b / 2;
    player.x = entry.wall === "W" ? T * 1.7 : entry.wall === "E" ? W - T * 1.7 : mid(entry.x, entry.w);
    player.y = entry.wall === "N" ? T * 1.7 : entry.wall === "S" ? H - T * 1.7 : mid(entry.y, entry.h);
  } else {
    player.x = W / 2;
    player.y = H / 2 + T * 3;
  }
  refreshDoors();
  spawnEnemies();
  if (key === data.boss && !run.bossDown) spawnBoss();

  showBanner(data.rooms[key].name, key === data.boss ? "GUARDIAN CHAMBER" : `SECTOR ${data.rooms[key].x}-${data.rooms[key].y}`);
  $("hud-room").textContent = data.rooms[key].name;
  checkSoftLock();
  updateHudAll();
}

function refreshDoors() {
  for (const d of layout.doors) d.open = !d.sealed && canOpen(d.sets, run.mask);
}

function itemHere() {
  const item = data.rooms[run.room].item;
  return item && !run.collected.has(run.room) ? item : null;
}

function pedestalPos() {
  return run.room === data.boss ? { x: W / 2, y: H / 2 + T * 4.5 } : { x: W / 2, y: H / 2 };
}

// The server's soft-lock states assume the player grabs the item in a room on entry,
// so the item still lying here is counted as already held.
function checkSoftLock() {
  const item = itemHere();
  const bit = item ? powerupByKey.get(item)?.bit || 0 : 0;
  const stateKey = `${run.room}|${run.mask | bit}`;
  const stuck = trapped.has(stateKey) && !alertDismissed.has(stateKey);
  $("hud-alert").hidden = !stuck;
  if (stuck) $("hud-alert").dataset.state = stateKey;
}

// ------------------------------------------------------------------ enemies and boss
function freeSpot(rng, avoid) {
  for (let tries = 0; tries < 60; tries++) {
    const tx = 2 + Math.floor(rng() * (COLS - 4)), ty = 2 + Math.floor(rng() * (ROWS - 4));
    if (layout.solid[ty * COLS + tx]) continue;
    const p = { x: tx * T + T / 2, y: ty * T + T / 2 };
    if (avoid.every((a) => dist(a, p) > T * 4.5)) return p;
  }
  return null;
}

function spawnEnemies() {
  enemies = [];
  if (run.room === data.start || run.room === data.boss) return;
  const seconds = data.rooms[run.room].seconds;
  const count = clamp(Math.round(seconds / 8), 1, 4);
  const rng = Math.random;
  const avoid = [player, pedestalPos()];
  const turrets = layout.hash % 3 === 0;
  for (let i = 0; i < count; i++) {
    const p = freeSpot(rng, avoid);
    if (!p) continue;
    avoid.push(p);
    const turret = turrets && i % 2 === 1;
    enemies.push({ ...p, kind: turret ? "turret" : "drone", hp: turret ? 3 : 2, r: turret ? 15 : 13,
      vx: 0, vy: 0, think: 0, cooldown: 1 + Math.random(), flash: 0, phase: Math.random() * 6 });
  }
}

function spawnBoss() {
  const abilityCount = data.powerups.filter((p) => p.bit).length;
  const hp = 30 + abilityCount * 6;
  boss = { x: W / 2, y: H / 2 - T, r: 44, hp, maxHp: hp, t: 0, ring: 2, aim: 1.5, flash: 0, dying: 0 };
  $("hud-boss").hidden = false;
  sfx.boss();
}

// ------------------------------------------------------------------ collision
function solidAt(tx, ty) {
  tx = clamp(tx, 0, COLS - 1);
  ty = clamp(ty, 0, ROWS - 1);
  const i = ty * COLS + tx;
  const door = layout.doorAt.get(i);
  if (door) return !door.open;
  return layout.solid[i] === 1;
}

function hitTile(x, y, half) {
  const x0 = Math.floor((x - half) / T), x1 = Math.floor((x + half - 0.01) / T);
  const y0 = Math.floor((y - half) / T), y1 = Math.floor((y + half - 0.01) / T);
  for (let ty = y0; ty <= y1; ty++) for (let tx = x0; tx <= x1; tx++) if (solidAt(tx, ty)) return { tx, ty };
  return null;
}

// Move on one axis at a time so the body slides along walls instead of sticking.
function moveBody(body, dx, dy, half) {
  let bumped = null;
  body.x += dx;
  let hit = hitTile(body.x, body.y, half);
  if (hit) { body.x = dx > 0 ? hit.tx * T - half : (hit.tx + 1) * T + half; bumped = hit; }
  body.y += dy;
  hit = hitTile(body.x, body.y, half);
  if (hit) { body.y = dy > 0 ? hit.ty * T - half : (hit.ty + 1) * T + half; bumped = hit; }
  return bumped;
}

// ------------------------------------------------------------------ input
const keys = new Set();
const mouse = { down: false, x: 0, y: 0 };
const KEY_MAP = {
  ArrowUp: "up", KeyW: "up", ArrowDown: "down", KeyS: "down", ArrowLeft: "left", KeyA: "left",
  ArrowRight: "right", KeyD: "right", Space: "fire", KeyJ: "fire", KeyK: "fire",
};

window.addEventListener("keydown", (evt) => {
  if (evt.target.closest("input, textarea, select")) return;
  const action = KEY_MAP[evt.code];
  if (state === "play" && action) { evt.preventDefault(); keys.add(action); if (freeze > 0 && freeze < 1.2) freeze = 0; }
  if (evt.code === "Enter" && (state === "title" || state === "dead" || state === "win")) {
    evt.preventDefault();
    if (state === "title") startGame(); else if (state === "dead") continueRun(); else restartGame();
  }
  if ((evt.code === "Escape" || evt.code === "KeyP") && (state === "play" || state === "pause")) { evt.preventDefault(); togglePause(); }
  if (evt.code === "KeyM") toggleMute();
  if (evt.code === "KeyF" && state !== "loading") toggleFullscreen();
});
window.addEventListener("keyup", (evt) => { const a = KEY_MAP[evt.code]; if (a) keys.delete(a); });
window.addEventListener("blur", () => keys.clear());

function toLogical(evt) {
  const box = canvas.getBoundingClientRect();
  return { x: (evt.clientX - box.left) * W / box.width, y: (evt.clientY - box.top) * H / box.height };
}
canvas.addEventListener("pointerdown", (evt) => {
  stage.focus();
  if (state !== "play") return;
  Object.assign(mouse, toLogical(evt), { down: true });
});
canvas.addEventListener("pointermove", (evt) => Object.assign(mouse, toLogical(evt)));
window.addEventListener("pointerup", () => { mouse.down = false; });

document.querySelectorAll("[data-touch]").forEach((btn) => {
  const action = btn.dataset.touch;
  btn.addEventListener("pointerdown", (e) => { e.preventDefault(); keys.add(action); });
  ["pointerup", "pointerleave", "pointercancel"].forEach((t) => btn.addEventListener(t, () => keys.delete(action)));
});

stage.addEventListener("click", (evt) => {
  const btn = evt.target.closest("[data-action]");
  if (!btn) return;
  const act = btn.dataset.action;
  if (act === "start") startGame();
  else if (act === "resume") togglePause();
  else if (act === "restart") restartGame();
  else if (act === "continue") continueRun();
  else if (act === "dismiss") { alertDismissed.add($("hud-alert").dataset.state); $("hud-alert").hidden = true; stage.focus(); }
});

$("game-fullscreen").addEventListener("click", toggleFullscreen);

function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen?.();
  else stage.requestFullscreen?.().catch(() => {});
}

function toggleMute() {
  muted = !muted;
  try { localStorage.setItem("tcsmetroid-muted", muted ? "1" : "0"); } catch { /* ignore */ }
  showToast(muted ? "Sound off" : "Sound on", "#00e3ff");
}

// ------------------------------------------------------------------ screens
function showScreen(id) {
  for (const s of ["screen-start", "screen-pause", "screen-dead", "screen-win", "screen-error"]) $(s).hidden = s !== id;
  $("game-hud").hidden = !(id === null || id === "screen-pause");
  $("game-hud-layer").hidden = id !== null;
}

function startGame() {
  newRun();
  state = "play";
  showScreen(null);
  stage.focus();
}

function restartGame() { startGame(); }

function continueRun() {
  run.energy = run.maxEnergy;
  run.deaths++;
  player.invuln = 1.5;
  enterRoom(data.start, null);
  state = "play";
  showScreen(null);
  stage.focus();
}

function togglePause() {
  if (state === "play") {
    state = "pause";
    keys.clear();
    drawMap($("pause-map"), true);
    $("pause-stats").innerHTML = statsHtml();
    showScreen("screen-pause");
  } else if (state === "pause") {
    state = "play";
    showScreen(null);
    stage.focus();
  }
}

function statsHtml() {
  const rooms = Object.keys(data.rooms).length;
  return [
    ["Time", fmtTime(run.time)], ["Rooms", `${run.visited.size}/${rooms}`],
    ["Items", `${run.collected.size}/${totalItems}`], ["Moves", run.moves], ["Deaths", run.deaths], ["Kills", run.kills],
  ].map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");
}

function fmtTime(t) {
  const s = Math.floor(t);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

// ------------------------------------------------------------------ HUD
function showBanner(title, sub) {
  $("hud-banner").innerHTML = `<small>${esc(sub)}</small>${esc(title)}`;
  $("hud-banner").classList.add("is-shown");
  bannerTimer = 1.8;
}

function showToast(text, color = "#ffc94a") {
  const t = $("hud-toast");
  t.textContent = text;
  t.style.color = color;
  t.style.borderColor = color;
  t.classList.add("is-shown");
  toastTimer = 2.4;
}

let hudCache = {};
function setText(id, value) {
  if (hudCache[id] === value) return;
  hudCache[id] = value;
  $(id).textContent = value;
}

function updateHudAll() {
  hudCache = {};
  const box = $("hud-powerups");
  const counts = {};
  for (const r of Object.values(data.rooms)) if (r.item) counts[r.item] = (counts[r.item] || 0) + 1;
  const got = {};
  for (const key of run.collected) { const it = data.rooms[key].item; got[it] = (got[it] || 0) + 1; }
  box.innerHTML = data.powerups.filter((p) => counts[p.key]).map((p) => {
    const owned = p.bit ? (run.mask & p.bit) !== 0 : (got[p.key] || 0) > 0;
    const sub = p.bit ? "" : `<sub>${got[p.key] || 0}/${counts[p.key]}</sub>`;
    return `<span class="game-hud-chip${owned ? " is-owned" : ""}" style="--chip:${p.color}" title="${esc(p.name)}">${p.key}${sub}</span>`;
  }).join("");
  const tanks = (run.maxEnergy - BASE_ENERGY) / TANK_ENERGY;
  $("hud-tanks").innerHTML = Array.from({ length: tanks }, () => "<i></i>").join("");
  updateHud();
}

function updateHud() {
  // Metroid-style energy: full tanks show as squares, the number is what's left over.
  const tanks = (run.maxEnergy - BASE_ENERGY) / TANK_ENERGY;
  const full = Math.min(tanks, Math.floor(run.energy / TANK_ENERGY));
  const shown = Math.max(0, Math.ceil(run.energy - full * TANK_ENERGY));
  setText("hud-energy", String(shown).padStart(2, "0"));
  $("hud-energy").classList.toggle("is-low", run.energy < 30);
  const icons = $("hud-tanks").children;
  for (let i = 0; i < icons.length; i++) icons[i].classList.toggle("is-full", i < full);
  $("hud-energy-bar").style.width = `${(run.energy / run.maxEnergy) * 100}%`;
  setText("hud-time", fmtTime(run.time));
  setText("hud-explored", `${Math.round(run.visited.size / Object.keys(data.rooms).length * 100)}%`);
  setText("hud-items", `${run.collected.size}/${totalItems}`);
  if (boss) $("hud-boss-bar").style.width = `${Math.max(0, boss.hp / boss.maxHp) * 100}%`;
  else $("hud-boss").hidden = true;
}

// Minimap and pause map share one drawing function.
function drawMap(target, big) {
  const g = target.getContext("2d");
  const w = target.width, h = target.height;
  g.clearRect(0, 0, w, h);
  const cols = mapBounds.maxX - mapBounds.minX + 1, rows = mapBounds.maxY - mapBounds.minY + 1;
  const cell = Math.min((w - 20) / cols, (h - 20) / rows);
  const ox = (w - cell * cols) / 2, oy = (h - cell * rows) / 2;
  const rw = cell * 0.72, rh = cell * 0.5;
  const centre = (k) => ({ x: ox + (data.rooms[k].x - mapBounds.minX + 0.5) * cell, y: oy + (data.rooms[k].y - mapBounds.minY + 0.5) * cell });
  const known = (k) => run.visited.has(k) || run.seen.has(k);

  g.lineWidth = Math.max(2, cell * 0.06);
  for (const gate of data.gates) {
    if (!(run.visited.has(gate.a) || run.visited.has(gate.b)) || !known(gate.a) || !known(gate.b)) continue;
    const a = centre(gate.a), b = centre(gate.b);
    const open = canOpen(gate.sets, run.mask);
    g.strokeStyle = open ? "rgba(0,227,255,.55)" : hexToRgba(doorColors(gate.sets)[0] || "#ffc94a", 0.8);
    g.setLineDash(gate.one_way ? [cell * 0.08, cell * 0.08] : []);
    g.beginPath(); g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); g.stroke();
  }
  g.setLineDash([]);
  const blink = Math.floor(performance.now() / 350) % 2 === 0;
  for (const key of Object.keys(data.rooms)) {
    if (!known(key)) continue;
    const c = centre(key), visited = run.visited.has(key);
    g.fillStyle = visited ? (key === run.room ? (blink ? "#ff8a3d" : "#b85a20") : "#1f4f8f") : "rgba(20,32,60,.6)";
    g.strokeStyle = key === data.boss ? "#ff5a76" : visited ? "#6fb6ff" : "rgba(111,182,255,.35)";
    g.lineWidth = key === data.boss ? 2.5 : 1.5;
    g.beginPath(); g.roundRect(c.x - rw / 2, c.y - rh / 2, rw, rh, 3); g.fill(); g.stroke();
    const item = data.rooms[key].item;
    if (visited && item && !run.collected.has(key)) {
      g.fillStyle = powerupByKey.get(item)?.color || "#fff";
      g.beginPath(); g.arc(c.x + rw / 2 - 6, c.y - rh / 2 + 6, Math.max(3, cell * 0.06), 0, Math.PI * 2); g.fill();
    }
    if (big && visited) {
      g.fillStyle = "#e4ecff";
      g.font = `600 ${Math.max(11, Math.min(15, cell * 0.14))}px "Orbitron", sans-serif`;
      g.textAlign = "center";
      g.fillText(data.rooms[key].name, c.x, c.y + 4, rw - 6);
    }
  }
}

// ------------------------------------------------------------------ update
function update(dt) {
  run.time += dt;
  player.cooldown -= dt;
  player.invuln -= dt;
  lockedCooldown -= dt;

  // movement
  let mx = (keys.has("right") ? 1 : 0) - (keys.has("left") ? 1 : 0);
  let my = (keys.has("down") ? 1 : 0) - (keys.has("up") ? 1 : 0);
  if (mx || my) {
    const len = Math.hypot(mx, my);
    mx /= len; my /= len;
    player.face = { x: mx, y: my };
    const bump = moveBody(player, mx * PLAYER_SPEED * dt, my * PLAYER_SPEED * dt, PLAYER_HALF);
    if (bump) reportBump(bump);
  }

  // leaving through a door: the centre has crossed into the wall's outer half
  if (player.x < T * 0.4 || player.x > W - T * 0.4 || player.y < T * 0.4 || player.y > H - T * 0.4) {
    const tx = clamp(Math.floor(player.x / T), 0, COLS - 1), ty = clamp(Math.floor(player.y / T), 0, ROWS - 1);
    const door = layout.doorAt.get(ty * COLS + tx);
    if (door && door.open) {
      run.moves++;
      sfx.door();
      return enterRoom(door.to, door.gate);
    }
  }

  // firing
  if ((keys.has("fire") || mouse.down) && player.cooldown <= 0) {
    let dir = player.face;
    if (mouse.down) {
      const len = Math.hypot(mouse.x - player.x, mouse.y - player.y) || 1;
      dir = { x: (mouse.x - player.x) / len, y: (mouse.y - player.y) / len };
      player.face = dir;
    }
    beams.push({ x: player.x + dir.x * 16, y: player.y + dir.y * 16, vx: dir.x * BEAM_SPEED, vy: dir.y * BEAM_SPEED, life: 0.9 });
    player.cooldown = BEAM_COOLDOWN;
    sfx.shoot();
  }

  // pick up the power-up on the pedestal
  const item = itemHere();
  if (item && dist(player, pedestalPos()) < 30) collect(item);

  updateBeams(dt);
  updateEnemies(dt);
  updateBoss(dt);
  updateShots(dt);

  for (const p of pickups) {
    p.life -= dt;
    if (dist(p, player) < 22) { run.energy = Math.min(run.maxEnergy, run.energy + 12); p.life = 0; tone(880, 0.08, { type: "sine", vol: 0.04 }); }
  }
  pickups = pickups.filter((p) => p.life > 0);
}

function reportBump(tile) {
  const door = layout.doorAt.get(tile.ty * COLS + tile.tx);
  if (!door || door.open || lockedCooldown > 0) return;
  lockedCooldown = 1.6;
  sfx.locked();
  if (door.sealed) showToast("ONE-WAY · this door only opens from the other side");
  else showToast(`LOCKED · needs ${setsToText(door.sets)}`, door.colors[0] || "#ffc94a");
}

function collect(item) {
  const p = powerupByKey.get(item);
  run.collected.add(run.room);
  if (p.bit) {
    run.mask |= p.bit;
    refreshDoors();
  } else {
    run.maxEnergy += TANK_ENERGY;
  }
  run.energy = run.maxEnergy;
  freeze = 1.6;
  keys.clear();
  sfx.pickup();
  for (let i = 0; i < 40; i++) {
    const a = Math.random() * Math.PI * 2, s = 60 + Math.random() * 220;
    particles.push({ x: pedestalPos().x, y: pedestalPos().y, vx: Math.cos(a) * s, vy: Math.sin(a) * s, life: 0.9, color: p.color, size: 3 });
  }
  showBanner(p.name, p.bit ? "ABILITY ACQUIRED" : "MAX ENERGY +100");
  showToast(p.description || (p.bit ? "New doors will open for you." : "Your energy capacity grew."), p.color);
  updateHudAll();
  const chip = [...$("hud-powerups").children].find((c) => c.textContent.startsWith(item));
  chip?.classList.add("is-new");
  checkSoftLock();
}

function updateBeams(dt) {
  for (const b of beams) {
    b.x += b.vx * dt; b.y += b.vy * dt; b.life -= dt;
    if (solidAt(Math.floor(b.x / T), Math.floor(b.y / T)) || b.x < 0 || b.x > W || b.y < 0 || b.y > H) {
      b.life = 0;
      sparks(b.x, b.y, "#00e3ff", 6);
      continue;
    }
    for (const e of enemies) {
      if (e.hp > 0 && Math.hypot(e.x - b.x, e.y - b.y) < e.r + 5) {
        b.life = 0; e.hp--; e.flash = 0.12; sfx.hit();
        if (e.hp <= 0) killEnemy(e);
        break;
      }
    }
    if (b.life > 0 && boss && boss.dying <= 0 && Math.hypot(boss.x - b.x, boss.y - b.y) < boss.r) {
      b.life = 0; boss.hp--; boss.flash = 0.08; sfx.hit(); shake = Math.max(shake, 2);
      sparks(b.x, b.y, "#ff5a76", 5);
      if (boss.hp <= 0) { boss.dying = 1.6; sfx.boss(); }
    }
  }
  beams = beams.filter((b) => b.life > 0);
}

function killEnemy(e) {
  run.kills++;
  sfx.kill();
  sparks(e.x, e.y, e.kind === "turret" ? "#ffc94a" : "#e45cff", 18);
  if (Math.random() < 0.4) pickups.push({ x: e.x, y: e.y, life: 8 });
}

function sparks(x, y, color, n) {
  for (let i = 0; i < n; i++) {
    const a = Math.random() * Math.PI * 2, s = 40 + Math.random() * 160;
    particles.push({ x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s, life: 0.4 + Math.random() * 0.3, color, size: 2 });
  }
}

function hurt(amount, from) {
  if (player.invuln > 0) return;
  run.energy -= amount;
  player.invuln = 1;
  shake = 7;
  sfx.hurt();
  if (from) {
    const len = Math.hypot(player.x - from.x, player.y - from.y) || 1;
    moveBody(player, (player.x - from.x) / len * 22, (player.y - from.y) / len * 22, PLAYER_HALF);
  }
  if (run.energy <= 0) {
    run.energy = 0;
    updateHud();
    state = "dead";
    showScreen("screen-dead");
  }
}

function updateEnemies(dt) {
  for (const e of enemies) {
    if (e.hp <= 0) continue;
    e.flash -= dt;
    e.phase += dt;
    if (e.kind === "drone") {
      e.think -= dt;
      const d = dist(e, player);
      if (d < 300) {
        e.vx = (player.x - e.x) / d * 85; e.vy = (player.y - e.y) / d * 85;
      } else if (e.think <= 0) {
        const a = Math.random() * Math.PI * 2;
        e.vx = Math.cos(a) * 50; e.vy = Math.sin(a) * 50; e.think = 1.2 + Math.random();
      }
      const bump = moveBody(e, e.vx * dt, e.vy * dt, 12);
      if (bump && d >= 300) e.think = 0;
    } else {
      e.cooldown -= dt;
      if (e.cooldown <= 0 && dist(e, player) < 520) {
        const d = dist(e, player) || 1;
        shots.push({ x: e.x, y: e.y, vx: (player.x - e.x) / d * 230, vy: (player.y - e.y) / d * 230, life: 3, r: 5, dmg: 10 });
        e.cooldown = 1.8;
        tone(520, 0.06, { type: "square", vol: 0.015 });
      }
    }
    if (dist(e, player) < e.r + PLAYER_HALF) hurt(15, e);
  }
  enemies = enemies.filter((e) => e.hp > 0);
}

function updateBoss(dt) {
  if (!boss) return;
  boss.flash -= dt;
  if (boss.dying > 0) {
    boss.dying -= dt;
    shake = 5;
    if (Math.random() < 0.5) sparks(boss.x + (Math.random() - 0.5) * 80, boss.y + (Math.random() - 0.5) * 80, Math.random() < 0.5 ? "#ff5a76" : "#ffc94a", 6);
    if (boss.dying <= 0) win();
    return;
  }
  boss.t += dt;
  boss.x = W / 2 + Math.sin(boss.t * 0.6) * 240;
  boss.y = H / 2 - T + Math.sin(boss.t * 1.2) * 110;
  boss.ring -= dt;
  boss.aim -= dt;
  const angry = boss.hp < boss.maxHp / 2;
  if (boss.ring <= 0) {
    const n = angry ? 16 : 12, off = boss.t;
    for (let i = 0; i < n; i++) {
      const a = off + i * Math.PI * 2 / n;
      shots.push({ x: boss.x, y: boss.y, vx: Math.cos(a) * 170, vy: Math.sin(a) * 170, life: 4, r: 7, dmg: 12 });
    }
    boss.ring = angry ? 1.6 : 2.3;
    tone(140, 0.2, { type: "sawtooth", vol: 0.03 });
  }
  if (boss.aim <= 0) {
    const d = dist(boss, player) || 1;
    const base = Math.atan2(player.y - boss.y, player.x - boss.x);
    for (const spread of angry ? [-0.2, 0, 0.2] : [0]) {
      shots.push({ x: boss.x, y: boss.y, vx: Math.cos(base + spread) * 280, vy: Math.sin(base + spread) * 280, life: 3, r: 6, dmg: 12 });
    }
    boss.aim = angry ? 0.9 : 1.4;
    void d;
  }
  if (dist(boss, player) < boss.r + PLAYER_HALF) hurt(20, boss);
}

function updateShots(dt) {
  for (const s of shots) {
    s.x += s.vx * dt; s.y += s.vy * dt; s.life -= dt;
    if (solidAt(Math.floor(s.x / T), Math.floor(s.y / T))) { s.life = 0; sparks(s.x, s.y, "#ff9aac", 3); continue; }
    if (Math.hypot(s.x - player.x, s.y - player.y) < s.r + PLAYER_HALF - 3) { s.life = 0; hurt(s.dmg, s); }
  }
  shots = shots.filter((s) => s.life > 0);
}

function win() {
  run.bossDown = true;
  boss = null;
  state = "win";
  sfx.win();
  $("win-stats").innerHTML = statsHtml();
  const par = data.best_moves;
  $("win-text").textContent = par != null
    ? `The planner's fastest route reaches the guardian in ${par} room moves. You took ${run.moves}${run.moves <= par ? ". That's a perfect route!" : "."}`
    : "";
  showScreen("screen-win");
}

// ------------------------------------------------------------------ drawing
function draw(now) {
  ctx.save();
  if (shake > 0) ctx.translate((Math.random() - 0.5) * shake, (Math.random() - 0.5) * shake);
  ctx.drawImage(layout.background, 0, 0);
  drawDoors(now);
  drawPedestal(now);
  for (const p of pickups) {
    ctx.fillStyle = `rgba(79, 227, 160, ${0.5 + 0.5 * Math.sin(now / 120)})`;
    ctx.beginPath(); ctx.arc(p.x, p.y, 7, 0, Math.PI * 2); ctx.fill();
  }
  for (const e of enemies) drawEnemy(e, now);
  if (boss) drawBoss(now);
  drawPlayer(now);

  ctx.fillStyle = "#b6f6ff";
  for (const b of beams) {
    ctx.save();
    ctx.shadowColor = "#00e3ff"; ctx.shadowBlur = 12;
    ctx.translate(b.x, b.y); ctx.rotate(Math.atan2(b.vy, b.vx));
    ctx.fillRect(-9, -2.5, 18, 5);
    ctx.restore();
  }
  for (const s of shots) {
    ctx.fillStyle = "#ff5a76";
    ctx.shadowColor = "#ff5a76"; ctx.shadowBlur = 10;
    ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2); ctx.fill();
    ctx.shadowBlur = 0;
  }
  for (const p of particles) {
    ctx.globalAlpha = clamp(p.life * 2, 0, 1);
    ctx.fillStyle = p.color;
    ctx.fillRect(p.x - p.size / 2, p.y - p.size / 2, p.size, p.size);
  }
  ctx.globalAlpha = 1;
  ctx.restore();

  // dark vignette so the HUD stays readable
  const v = ctx.createRadialGradient(W / 2, H / 2, H * 0.35, W / 2, H / 2, W * 0.75);
  v.addColorStop(0, "rgba(0,0,0,0)");
  v.addColorStop(1, "rgba(0,0,0,.55)");
  ctx.fillStyle = v;
  ctx.fillRect(0, 0, W, H);
}

function drawDoors(now) {
  for (const d of layout.doors) {
    const vertical = d.wall === "E" || d.wall === "W";
    // the opening itself
    ctx.fillStyle = "#03060d";
    ctx.fillRect(d.x, d.y, d.w, d.h);
    const frame = d.colors.length ? d.colors[0] : "#00e3ff";
    ctx.fillStyle = d.sealed ? "#55607a" : frame;
    if (vertical) { ctx.fillRect(d.x, d.y - 4, T, 4); ctx.fillRect(d.x, d.y + d.h, T, 4); }
    else { ctx.fillRect(d.x - 4, d.y, 4, T); ctx.fillRect(d.x + d.w, d.y, 4, T); }

    if (d.sealed) {
      ctx.fillStyle = "#2a3346";
      ctx.fillRect(d.x + 3, d.y + 3, d.w - 6, d.h - 6);
      ctx.strokeStyle = "#7d89a6"; ctx.lineWidth = 3;
      const cx = d.x + d.w / 2, cy = d.y + d.h / 2;
      const into = { N: [0, 1], S: [0, -1], W: [1, 0], E: [-1, 0] }[d.wall];
      ctx.beginPath();
      ctx.moveTo(cx - into[0] * 8 - into[1] * 10, cy - into[1] * 8 - into[0] * 10);
      ctx.lineTo(cx + into[0] * 8, cy + into[1] * 8);
      ctx.lineTo(cx - into[0] * 8 + into[1] * 10, cy - into[1] * 8 + into[0] * 10);
      ctx.stroke();
    } else if (!d.open) {
      // energy barrier in the colours of the power-ups that open it
      const grad = vertical ? ctx.createLinearGradient(0, d.y, 0, d.y + d.h) : ctx.createLinearGradient(d.x, 0, d.x + d.w, 0);
      d.colors.forEach((c, i) => grad.addColorStop(d.colors.length === 1 ? 0 : i / (d.colors.length - 1), hexToRgba(c, 0.75)));
      if (d.colors.length === 1) grad.addColorStop(1, hexToRgba(d.colors[0], 0.75));
      ctx.fillStyle = grad;
      ctx.globalAlpha = 0.65 + 0.25 * Math.sin(now / 200 + d.gate);
      ctx.fillRect(d.x + 4, d.y + 4, d.w - 8, d.h - 8);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = "rgba(255,255,255,.35)";
      ctx.lineWidth = 1;
      for (let k = 6; k < (vertical ? d.h : d.w) - 4; k += 8) {
        ctx.beginPath();
        if (vertical) { ctx.moveTo(d.x + 6, d.y + k); ctx.lineTo(d.x + T - 6, d.y + k); }
        else { ctx.moveTo(d.x + k, d.y + 6); ctx.lineTo(d.x + k, d.y + T - 6); }
        ctx.stroke();
      }
      // the rule as a readable tag: dark pill, white letters
      const label = (d.rule || "").replace(/\s+/g, "");
      ctx.save();
      ctx.translate(d.x + d.w / 2, d.y + d.h / 2);
      if (vertical) ctx.rotate(-Math.PI / 2);
      ctx.font = '700 14px "Roboto Mono", monospace';
      const tw = ctx.measureText(label).width + 14;
      ctx.fillStyle = "rgba(3, 6, 13, .85)";
      ctx.beginPath(); ctx.roundRect(-tw / 2, -11, tw, 22, 11); ctx.fill();
      ctx.strokeStyle = d.colors[0]; ctx.lineWidth = 1.5; ctx.stroke();
      ctx.fillStyle = "#ffffff";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(label, 0, 1);
      ctx.restore();
    } else {
      ctx.strokeStyle = hexToRgba(d.colors[0] || "#00e3ff", 0.5);
      ctx.lineWidth = 2;
      ctx.strokeRect(d.x + 2, d.y + 2, d.w - 4, d.h - 4);
    }
  }
}

function drawPedestal(now) {
  const item = itemHere();
  const pos = pedestalPos();
  ctx.fillStyle = "#1a2846";
  ctx.beginPath(); ctx.ellipse(pos.x, pos.y + 16, 26, 9, 0, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = "rgba(0,227,255,.35)"; ctx.lineWidth = 2; ctx.stroke();
  if (!item) return;
  const p = powerupByKey.get(item);
  const bob = Math.sin(now / 300) * 4;
  ctx.save();
  ctx.shadowColor = p.color; ctx.shadowBlur = 24;
  ctx.fillStyle = p.color;
  ctx.beginPath(); ctx.arc(pos.x, pos.y - 4 + bob, 14, 0, Math.PI * 2); ctx.fill();
  ctx.restore();
  ctx.strokeStyle = "rgba(255,255,255,.8)"; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.arc(pos.x, pos.y - 4 + bob, 19 + Math.sin(now / 160) * 2, 0, Math.PI * 2); ctx.stroke();
  ctx.fillStyle = "#07101f";
  ctx.font = '700 14px "Roboto Mono", monospace';
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(item, pos.x, pos.y - 3 + bob);
}

function drawPlayer(now) {
  if (player.invuln > 0 && Math.floor(now / 70) % 2 === 0) return;
  const { x, y, face } = player;
  ctx.save();
  ctx.translate(x, y);
  ctx.fillStyle = "rgba(0,0,0,.35)";
  ctx.beginPath(); ctx.ellipse(0, 14, 14, 5, 0, 0, Math.PI * 2); ctx.fill();
  const ang = Math.atan2(face.y, face.x);
  ctx.rotate(ang);
  // arm cannon
  ctx.fillStyle = "#c9d4ea";
  ctx.fillRect(6, 4, 16, 7);
  ctx.fillStyle = "#00e3ff";
  ctx.fillRect(20, 5, 3, 5);
  // body
  const body = ctx.createRadialGradient(-4, -4, 2, 0, 0, 16);
  body.addColorStop(0, "#ffb070"); body.addColorStop(1, "#d8551a");
  ctx.fillStyle = body;
  ctx.beginPath(); ctx.arc(0, 0, 14, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = "#7a2a06"; ctx.lineWidth = 2; ctx.stroke();
  // visor
  ctx.fillStyle = "#00e3ff";
  ctx.shadowColor = "#00e3ff"; ctx.shadowBlur = 10;
  ctx.beginPath(); ctx.ellipse(6, 0, 4, 8, 0, 0, Math.PI * 2); ctx.fill();
  ctx.restore();
}

function drawEnemy(e, now) {
  ctx.save();
  ctx.translate(e.x, e.y);
  if (e.kind === "drone") {
    ctx.rotate(e.phase * 3);
    ctx.fillStyle = e.flash > 0 ? "#fff" : "#a23bd6";
    ctx.beginPath();
    for (let i = 0; i < 12; i++) {
      const r = i % 2 ? 8 : e.r + 2, a = i * Math.PI / 6;
      ctx.lineTo(Math.cos(a) * r, Math.sin(a) * r);
    }
    ctx.closePath(); ctx.fill();
    ctx.fillStyle = "#ffd1ff";
    ctx.beginPath(); ctx.arc(0, 0, 4 + Math.sin(now / 100) * 1.5, 0, Math.PI * 2); ctx.fill();
  } else {
    ctx.fillStyle = e.flash > 0 ? "#fff" : "#7a5a14";
    ctx.fillRect(-e.r, -e.r, e.r * 2, e.r * 2);
    ctx.strokeStyle = "#ffc94a"; ctx.lineWidth = 2;
    ctx.strokeRect(-e.r, -e.r, e.r * 2, e.r * 2);
    ctx.rotate(Math.atan2(player.y - e.y, player.x - e.x));
    ctx.fillStyle = "#ffc94a";
    ctx.fillRect(0, -3, e.r + 8, 6);
  }
  ctx.restore();
}

function drawBoss(now) {
  const { x, y, r } = boss;
  ctx.save();
  ctx.translate(x, y);
  for (let i = 0; i < 6; i++) {
    const a = now / 600 + i * Math.PI / 3;
    ctx.fillStyle = "#5a1426";
    ctx.beginPath(); ctx.arc(Math.cos(a) * (r + 16), Math.sin(a) * (r + 16), 10, 0, Math.PI * 2); ctx.fill();
  }
  const core = ctx.createRadialGradient(0, 0, 6, 0, 0, r);
  core.addColorStop(0, boss.flash > 0 ? "#ffffff" : "#ffd0d8");
  core.addColorStop(0.35, "#ff5a76");
  core.addColorStop(1, "#4a0c1a");
  ctx.fillStyle = core;
  ctx.shadowColor = "#ff5a76"; ctx.shadowBlur = 30;
  ctx.beginPath(); ctx.arc(0, 0, r + Math.sin(now / 150) * 3, 0, Math.PI * 2); ctx.fill();
  ctx.shadowBlur = 0;
  ctx.fillStyle = "#14030a";
  const look = Math.atan2(player.y - y, player.x - x);
  ctx.beginPath(); ctx.arc(Math.cos(look) * 14, Math.sin(look) * 14, 11, 0, Math.PI * 2); ctx.fill();
  ctx.restore();
}

// ------------------------------------------------------------------ loop
function frame(now) {
  const dt = Math.min(0.05, (now - lastTime) / 1000 || 0);   // cap so a slow frame never tunnels through walls
  lastTime = now;
  if (state === "play") {
    if (freeze > 0) freeze -= dt;
    else update(dt);
    for (const p of particles) { p.x += p.vx * dt; p.y += p.vy * dt; p.vx *= 0.92; p.vy *= 0.92; p.life -= dt; }
    particles = particles.filter((p) => p.life > 0);
    shake = Math.max(0, shake - dt * 30);
    if ((bannerTimer -= dt) <= 0) $("hud-banner").classList.remove("is-shown");
    if ((toastTimer -= dt) <= 0) $("hud-toast").classList.remove("is-shown");
    updateHud();
    drawMap($("hud-map"), false);
  }
  if (layout && state !== "loading" && state !== "error") draw(now);
  requestAnimationFrame(frame);
}

function setupCanvas() {
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function fail(message) {
  state = "error";
  $("error-text").textContent = message;
  showScreen("screen-error");
}

async function loadGame() {
  const embedded = document.getElementById("play-data");
  if (embedded) return JSON.parse(embedded.textContent);
  let draft = null;
  try { draft = JSON.parse(localStorage.getItem("tcsmetroid-play-draft") || "null"); } catch { /* storage blocked */ }
  if (!draft) throw new Error("There's no sandbox draft to play. Open the sandbox or designer and press Play draft.");
  const res = await fetch(config.draft_url, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ map: draft }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `The server answered ${res.status}.`);
  return body;
}

async function boot() {
  setupCanvas();
  try {
    prepare(await loadGame());
  } catch (err) {
    return fail(err.message);
  }
  $("game-title").textContent = data.name || "Sandbox map";
  $("start-title").textContent = data.name || "Sandbox map";
  const rooms = Object.keys(data.rooms).length;
  $("start-text").textContent = `${rooms} rooms · ${totalItems} power-ups to find. Collect power-ups to open locked doors, then destroy the guardian.`;
  $("game-par").textContent = data.best_moves != null
    ? `The route finder's fastest finish (Dijkstra) visits the guardian after ${data.best_moves} room moves and ${data.best_seconds} map-seconds. Try to match it.`
    : "The route finder found no way to reach the guardian with this item placement, so this map can't be beaten yet.";
  newRun();
  state = "title";
  stage.querySelector('[data-action="start"]').disabled = false;
  requestAnimationFrame(frame);
}

boot();
