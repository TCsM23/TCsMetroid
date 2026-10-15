// Playtest: walk the map room by room as the player would.
// The server sends each door's minimal ability sets, so the browser never has to
// parse rules itself: a door opens when one of its sets is fully inside the mask.
"use strict";

const game = JSON.parse(document.getElementById("play-data").textContent);
const mapWrap = document.getElementById("play-map");
const trapped = new Set(game.trapped);
let state;

const bitOf = (item) => game.bits[item] || 0;
const canOpen = (gate, mask) => gate.sets.some((set) => (set & mask) === set);
const letters = (mask) => Object.keys(game.bits).filter((k) => mask & game.bits[k]).join(" ") || "–";

function restart() {
  const startItem = game.placement[game.start];
  state = {
    room: game.start, mask: bitOf(startItem), moves: 0, seconds: 0, over: false,
    visited: new Set([game.start]), found: new Set(startItem ? [game.start] : []),
    log: [`You arrive in ${game.rooms[game.start].name}.`],
  };
  render();
}

function exits(room) {
  const out = [];
  game.gates.forEach((g) => {
    if (g.a === room) out.push({ to: g.b, gate: g });
    else if (g.b === room && !g.one_way) out.push({ to: g.a, gate: g });
  });
  return out;
}

function move(to) {
  if (state.over) return;
  const exit = exits(state.room).find((e) => e.to === to);
  if (!exit || !canOpen(exit.gate, state.mask)) return;
  state.room = to;
  state.moves += 1;
  state.seconds += game.rooms[to].seconds;
  state.visited.add(to);
  state.log.push(`Entered ${game.rooms[to].name}.`);

  const item = game.placement[to];
  if (item && !state.found.has(to)) {
    state.found.add(to);
    state.mask |= bitOf(item);
    state.log.push(`Picked up ${game.names[item]}!`);
  }
  if (to === game.boss) {
    state.over = true;
    state.log.push(`Reached the boss in ${state.moves} moves and ${state.seconds}s.`);
  }
  render();
}

function render() {
  const here = game.rooms[state.room];
  const isTrapped = !state.over && trapped.has(`${state.room}|${state.mask}`);

  document.getElementById("play-room").textContent = here.name;
  document.getElementById("play-moves").textContent = state.moves;
  document.getElementById("play-seconds").textContent = state.seconds;
  document.getElementById("play-held").textContent = letters(state.mask);

  const status = document.getElementById("play-status");
  const message = document.getElementById("play-message");
  if (state.over) {
    status.textContent = "Cleared";
    status.className = "base-status-chip is-ok";
    const diff = state.seconds - game.best_seconds;
    message.textContent = diff === 0
      ? `Perfect run: that's the fastest possible time (${game.best_seconds}s).`
      : `The fastest possible run takes ${game.best_seconds}s in ${game.best_moves} moves. You were ${diff}s slower.`;
  } else if (isTrapped) {
    status.textContent = "Trapped";
    status.className = "base-status-chip is-bad";
    message.textContent = "Soft-locked: with what you're holding, no path from here reaches the boss. A designer would fix this room. Press Restart.";
  } else {
    status.textContent = "Exploring";
    status.className = "base-status-chip is-warn";
    message.textContent = "";
  }

  const list = document.getElementById("play-exits");
  list.replaceChildren();
  for (const { to, gate } of exits(state.room)) {
    const open = canOpen(gate, state.mask) && !state.over;
    const li = document.createElement("li");
    const key = document.createElement("span");
    key.className = `base-list-key ${canOpen(gate, state.mask) ? "is-ok" : "is-bad"}`;
    key.textContent = canOpen(gate, state.mask) ? "Open" : "Locked";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "base-btn-action playtest-exit-btn";
    btn.disabled = !open;
    btn.textContent = `${game.rooms[to].name}${gate.rule && !canOpen(gate, state.mask) ? `  · needs ${gate.rule}` : ""}`;
    btn.addEventListener("click", () => move(to));
    li.append(key, btn);
    list.append(li);
  }

  const log = document.getElementById("play-log");
  log.replaceChildren(...state.log.slice(-12).reverse().map((line) => {
    const li = document.createElement("li");
    li.textContent = line;
    return li;
  }));

  // map highlighting
  mapWrap.querySelectorAll("[data-room]").forEach((g) => {
    const key = g.dataset.room;
    const rect = g.querySelector("rect");
    rect.classList.toggle("is-current", key === state.room);
    rect.classList.toggle("is-on-route", state.visited.has(key) && key !== state.room);
    g.classList.toggle("is-found", state.found.has(key));
    g.classList.toggle("is-reachable-exit", exits(state.room).some((e) => e.to === key && canOpen(e.gate, state.mask)));
  });
}

mapWrap.addEventListener("click", (evt) => {
  const g = evt.target.closest("[data-room]");
  if (g) move(g.dataset.room);
});
document.getElementById("play-restart").addEventListener("click", restart);
document.getElementById("play-fog").addEventListener("change", (e) => mapWrap.classList.toggle("is-fog", e.target.checked));
mapWrap.classList.toggle("is-fog", document.getElementById("play-fog").checked);

restart();
