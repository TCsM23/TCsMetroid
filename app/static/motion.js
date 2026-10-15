// TCsMetroid motion layer, loaded on every page by base.html.
//
//   1. Animated background, chosen per page with <body data-bg="...">:
//        constellation  drifting graph nodes and edges (like the maps the app works with)
//        grid           a perspective grid rolling toward you (build pages)
//        warp           stars streaking past, hyperspace style (the game)
//      All three sit over twinkling stars and two slow nebula glows.
//   2. Page motion: content fades up on load, panels reveal as you scroll,
//      the header tightens when you scroll, numbers count up.
//   3. Small helpers: light/dark switch, mobile menu, dismissable flash messages,
//      and starting each new page at the top.
//
// Everything respects "reduce motion" in the operating system: the background is
// drawn once and nothing animates.
"use strict";

(() => {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const root = document.documentElement;
  // The inline script in base.html's <head> already did this before the first paint;
  // repeating it here keeps motion.js working on its own.
  if (!reduceMotion) root.classList.add("is-motion");

  // ------------------------------------------------------------------ 1. background
  const canvas = document.getElementById("base-bg-canvas");
  if (canvas) startBackground(canvas);

  function startBackground(canvas) {
    const ctx = canvas.getContext("2d");
    const mode = document.body.dataset.bg || "constellation";
    const dpr = Math.min(1.5, window.devicePixelRatio || 1);
    let w = 0, h = 0, stars = [], nodes = [], pulses = [];
    let pal = {};                              // theme colours, read from CSS variables
    const pointer = { x: 0.5, y: 0.5 };       // 0..1, eased toward the mouse for parallax
    const target = { x: 0.5, y: 0.5 };

    function rand(a, b) { return a + Math.random() * (b - a); }

    // Each colour is stored in CSS as "r, g, b" (e.g. --bgfx-node: 0, 227, 255), so any alpha can be added here.
    function readPalette() {
      const css = getComputedStyle(root);
      const v = (name) => css.getPropertyValue(name).trim();
      pal = { star: v("--bgfx-star"), node: v("--bgfx-node"), hot: v("--bgfx-hot"), line: v("--bgfx-line"),
              glowA: v("--bgfx-glow-a"), glowB: v("--bgfx-glow-b"), k: Number(v("--bgfx-strength")) || 1 };
    }
    const rgba = (rgb, a) => `rgba(${rgb}, ${(a * pal.k).toFixed(3)})`;

    function resize() {
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      // Density follows screen area, so a phone isn't crowded and a big monitor isn't empty.
      const area = w * h;
      stars = Array.from({ length: Math.min(220, Math.round(area / 7000)) }, () => ({
        x: Math.random() * w, y: Math.random() * h, r: rand(0.3, 1.3),
        depth: rand(0.2, 1), phase: rand(0, Math.PI * 2), speed: rand(0.6, 1.8),
      }));
      nodes = Array.from({ length: Math.max(14, Math.min(46, Math.round(area / 32000))) }, () => ({
        x: Math.random() * w, y: Math.random() * h,
        vx: rand(-0.12, 0.12), vy: rand(-0.08, 0.08),
        r: rand(1.6, 3), hot: Math.random() < 0.15,   // a few orange "item" nodes
      }));
      pulses = [];
      warp = Array.from({ length: Math.min(260, Math.round(area / 5000)) }, newWarpStar);
      if (reduceMotion) draw(0);
    }

    const LINK = 170;   // nodes closer than this are joined by an edge

    // warp stars live in 3D: x, y around the centre and z = distance from the viewer
    let warp = [];
    function newWarpStar() { return { x: rand(-1, 1), y: rand(-1, 1), z: rand(0.15, 1), pz: 0 }; }

    function draw(t) {
      ctx.clearRect(0, 0, w, h);
      pointer.x += (target.x - pointer.x) * 0.04;
      pointer.y += (target.y - pointer.y) * 0.04;
      const px = (pointer.x - 0.5) * 30, py = (pointer.y - 0.5) * 30;

      // soft nebula glows that slowly breathe
      const glow = (x, y, r, color) => {
        const g = ctx.createRadialGradient(x, y, 0, x, y, r);
        g.addColorStop(0, color);
        g.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, w, h);
      };
      const breathe = reduceMotion ? 0 : Math.sin(t / 6000);
      glow(w * 0.85 - px, h * 0.1 - py, Math.max(w, h) * (0.55 + breathe * 0.04), rgba(pal.glowA, 0.08));
      glow(w * 0.08 - px, h * 0.35 - py, Math.max(w, h) * (0.45 - breathe * 0.04), rgba(pal.glowB, 0.07));

      // stars: deeper stars move less with the pointer (parallax) and twinkle
      for (const s of stars) {
        const a = 0.35 + 0.45 * Math.sin(t / 1000 * s.speed + s.phase);
        ctx.fillStyle = rgba(pal.star, reduceMotion ? 0.5 : a);
        ctx.fillRect(s.x - px * s.depth, s.y - py * s.depth, s.r, s.r);
      }

      if (mode === "grid") drawGrid(t, px, py);
      else if (mode === "warp") drawWarp(px, py);
      else drawConstellation(px, py);

      // a faint scan line that sweeps down the screen every few seconds
      if (!reduceMotion) {
        const y = ((t / 9000) % 1) * (h + 200) - 100;
        const g = ctx.createLinearGradient(0, y - 60, 0, y + 60);
        g.addColorStop(0, rgba(pal.node, 0));
        g.addColorStop(0.5, rgba(pal.node, 0.035));
        g.addColorStop(1, rgba(pal.node, 0));
        ctx.fillStyle = g;
        ctx.fillRect(0, y - 60, w, 120);
      }
    }

    function drawConstellation(px, py) {
      // constellation: drift, wrap at the edges, link close neighbours
      for (const n of nodes) {
        if (!reduceMotion) {
          n.x += n.vx; n.y += n.vy;
          if (n.x < -20) n.x = w + 20; else if (n.x > w + 20) n.x = -20;
          if (n.y < -20) n.y = h + 20; else if (n.y > h + 20) n.y = -20;
        }
      }
      ctx.lineWidth = 1;
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i], b = nodes[j];
          const d = Math.hypot(a.x - b.x, a.y - b.y);
          if (d > LINK) continue;
          ctx.strokeStyle = rgba(pal.line, 0.3 * (1 - d / LINK));
          ctx.beginPath();
          ctx.moveTo(a.x - px * 0.6, a.y - py * 0.6);
          ctx.lineTo(b.x - px * 0.6, b.y - py * 0.6);
          ctx.stroke();
          // now and then, send a pulse along an edge, like a search exploring the graph
          if (!reduceMotion && pulses.length < 6 && Math.random() < 0.0006) pulses.push({ a, b, t: 0 });
        }
      }
      for (const n of nodes) {
        ctx.fillStyle = n.hot ? rgba(pal.hot, 0.9) : rgba(pal.node, 0.8);
        ctx.beginPath();
        ctx.arc(n.x - px * 0.6, n.y - py * 0.6, n.r, 0, Math.PI * 2);
        ctx.fill();
      }
      for (const p of pulses) {
        p.t += 0.012;
        const x = p.a.x + (p.b.x - p.a.x) * p.t - px * 0.6, y = p.a.y + (p.b.y - p.a.y) * p.t - py * 0.6;
        ctx.fillStyle = rgba(pal.node, 1);
        ctx.shadowColor = rgba(pal.node, 1);
        ctx.shadowBlur = 10;
        ctx.beginPath();
        ctx.arc(x, y, 2.2, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;
      }
      pulses = pulses.filter((p) => p.t < 1 && Math.hypot(p.a.x - p.b.x, p.a.y - p.b.y) <= LINK);
    }

    // A floor grid in perspective: vertical lines run to a vanishing point on the horizon,
    // horizontal lines are spaced 1/z apart and slide toward the viewer over time.
    function drawGrid(t, px, py) {
      const horizon = h * 0.58 - py * 0.5, vx = w / 2 - px;
      const fade = ctx.createLinearGradient(0, horizon, 0, h);
      fade.addColorStop(0, rgba(pal.node, 0));
      fade.addColorStop(1, rgba(pal.node, 0.34));
      ctx.strokeStyle = fade;
      ctx.lineWidth = 1;
      for (let i = -14; i <= 14; i++) {
        ctx.beginPath();
        ctx.moveTo(vx + i * 6, horizon);
        ctx.lineTo(vx + i * (w / 7), h);
        ctx.stroke();
      }
      const shift = reduceMotion ? 0 : (t / 2400) % 1;
      for (let k = 0; k < 18; k++) {
        const z = 1 / (k + 1 - shift);                    // 1, 1/2, 1/3 ... sliding forward
        const y = horizon + (h - horizon) * z;
        if (y < horizon + 2) continue;
        ctx.strokeStyle = rgba(pal.node, 0.05 + 0.3 * z);
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }
      const sun = ctx.createRadialGradient(vx, horizon, 0, vx, horizon, w * 0.35);
      sun.addColorStop(0, rgba(pal.hot, 0.16));
      sun.addColorStop(1, rgba(pal.hot, 0));
      ctx.fillStyle = sun;
      ctx.fillRect(0, 0, w, h);
    }

    // Hyperspace: each star moves toward the viewer (z shrinks) and is drawn as a streak
    // from where it was last frame to where it is now, projected from the screen centre.
    function drawWarp(px, py) {
      const cx = w / 2 - px * 2, cy = h / 2 - py * 2, scale = Math.max(w, h) * 0.5;
      ctx.lineCap = "round";
      for (const s of warp) {
        s.pz = s.z;
        if (!reduceMotion) s.z -= 0.0035;
        if (s.z <= 0.02) { Object.assign(s, newWarpStar(), { z: 1 }); s.pz = 1; continue; }
        const x = cx + (s.x / s.z) * scale, y = cy + (s.y / s.z) * scale;
        const ox = cx + (s.x / s.pz) * scale, oy = cy + (s.y / s.pz) * scale;
        if (x < -50 || x > w + 50 || y < -50 || y > h + 50) { Object.assign(s, newWarpStar(), { z: 1 }); continue; }
        const near = 1 - s.z;
        ctx.strokeStyle = near > 0.85 ? rgba(pal.hot, near) : rgba(pal.star, Math.min(1, near * 1.2));
        ctx.lineWidth = 0.5 + near * 2.2;
        ctx.beginPath();
        ctx.moveTo(ox, oy);
        ctx.lineTo(x, y);
        ctx.stroke();
      }
    }

    let running = false;
    function loop(t) {
      if (!running) return;
      draw(t);
      requestAnimationFrame(loop);
    }
    function setRunning(on) {
      if (reduceMotion || on === running) return;
      running = on;
      if (on) requestAnimationFrame(loop);
    }

    window.addEventListener("resize", resize);
    // The theme switch fires this event; pick up the new colours (and redraw if nothing is animating).
    document.addEventListener("tcsmetroid:theme", () => { readPalette(); if (reduceMotion) draw(0); });
    readPalette();
    window.addEventListener("pointermove", (e) => { target.x = e.clientX / w; target.y = e.clientY / h; }, { passive: true });
    // Stop drawing when the tab is hidden, so a background tab costs nothing.
    document.addEventListener("visibilitychange", () => setRunning(!document.hidden));
    resize();
    setRunning(!document.hidden);
  }

  // ------------------------------------------------------------------ 2. page motion
  // (The stagger order of page blocks and map rooms comes from CSS and the templates,
  // so it is already in place on the very first frame.)

  // A fresh visit to a page starts at the top. Back/forward and links with a #target keep
  // their usual behaviour; this only stops the browser restoring an old scroll position.
  const nav = performance.getEntriesByType("navigation")[0];
  if (!location.hash && nav && (nav.type === "navigate" || nav.type === "reload")) {
    let touched = false;
    ["wheel", "touchstart", "keydown"].forEach((t) => addEventListener(t, () => { touched = true; }, { once: true, passive: true }));
    window.scrollTo(0, 0);
    // Some browsers restore the old position after the page finishes loading, so check again then.
    addEventListener("load", () => { if (!touched && window.scrollY > 0) window.scrollTo(0, 0); }, { once: true });
  }
  // Leaving for another page: fade this one out first, then go. Only plain left-clicks on links
  // to other pages of this site; downloads, new tabs and the JSON API are left alone.
  document.addEventListener("click", (e) => {
    const link = e.target.closest("a[href]");
    if (reduceMotion || !link || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (link.target || link.hasAttribute("download") || link.origin !== location.origin) return;
    if (link.pathname === location.pathname && link.hash) return;          // same-page jump, handled below
    if (/\/api\/|\/export/.test(link.pathname)) return;                     // files, not pages
    e.preventDefault();
    root.classList.add("is-leaving");
    setTimeout(() => { location.href = link.href; }, 170);
  });
  // Coming back with the Back button can show the faded page from the browser's cache: undo the fade.
  addEventListener("pageshow", () => root.classList.remove("is-leaving"));

  // Links to a spot on the same page (#new-map, #templates) glide there instead of jumping.
  document.addEventListener("click", (e) => {
    const link = e.target.closest('a[href*="#"]');
    if (!link || link.origin !== location.origin || link.pathname !== location.pathname || !link.hash) return;
    const target = document.getElementById(decodeURIComponent(link.hash.slice(1)));
    if (!target) return;
    e.preventDefault();
    target.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
    history.pushState(null, "", link.hash);
  });

  // Scroll reveal: anything below the fold fades up when it scrolls into view.
  const REVEAL = ".base-panel-box, .index-maplist-card, .index-feature-card, .game-info-row > *";
  if (!reduceMotion && "IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      }
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
    document.querySelectorAll(REVEAL).forEach((el) => {
      if (el.getBoundingClientRect().top > window.innerHeight * 0.92) {
        el.classList.add("is-reveal");
        observer.observe(el);
      }
    });
  }

  // Count numbers up from zero, e.g. the room and door counts on map cards.
  function countUp(el) {
    const end = Number(el.textContent.trim());
    if (!Number.isInteger(end) || end <= 0 || reduceMotion) return;
    const started = performance.now(), duration = 700 + Math.min(end, 50) * 10;
    const step = (now) => {
      const k = Math.min(1, (now - started) / duration);
      el.textContent = String(Math.round(end * (1 - Math.pow(1 - k, 3))));   // ease-out cubic
      if (k < 1) requestAnimationFrame(step);
    };
    el.textContent = "0";
    requestAnimationFrame(step);
  }
  document.querySelectorAll(".index-maplist-stats dd, [data-count]").forEach(countUp);

  // Header: a tighter look with a shadow once the page has scrolled.
  const header = document.querySelector(".base-header-bar");
  if (header) {
    const onScroll = () => header.classList.toggle("is-scrolled", window.scrollY > 8);
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  // ------------------------------------------------------------------ 3. helpers
  // Light / dark switch. The <head> script already chose a theme (saved choice, or the
  // operating system's); this button flips it and remembers the choice.
  const themeBtn = document.querySelector(".base-header-theme");
  function applyTheme(theme, animate) {
    if (animate && !reduceMotion) {
      root.classList.add("is-theme-switching");
      setTimeout(() => root.classList.remove("is-theme-switching"), 450);
    }
    root.dataset.theme = theme;
    if (themeBtn) themeBtn.setAttribute("aria-label", theme === "dark" ? "Switch to light mode" : "Switch to dark mode");
    document.dispatchEvent(new CustomEvent("tcsmetroid:theme", { detail: theme }));
  }
  if (themeBtn) {
    applyTheme(root.dataset.theme || "dark", false);
    themeBtn.addEventListener("click", () => {
      const next = root.dataset.theme === "light" ? "dark" : "light";
      try { localStorage.setItem("tcsmetroid-theme", next); } catch { /* not saved, still switches */ }
      applyTheme(next, true);
    });
  }
  // Until the user picks one, follow the operating system when it changes (e.g. at sunset).
  window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", (e) => {
    let saved = null;
    try { saved = localStorage.getItem("tcsmetroid-theme"); } catch { /* ignore */ }
    if (!saved) applyTheme(e.matches ? "light" : "dark", true);
  });

  // Mobile menu: the button opens and closes the main nav on small screens.
  const menuBtn = document.querySelector(".base-header-menu");
  if (menuBtn && header) {
    menuBtn.addEventListener("click", () => {
      const open = header.classList.toggle("is-open");
      menuBtn.setAttribute("aria-expanded", String(open));
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && header.classList.contains("is-open")) menuBtn.click();
    });
  }

  // Flash messages: a close button, and success messages fade out on their own.
  document.querySelectorAll(".base-flash-msg").forEach((msg) => {
    const close = document.createElement("button");
    close.type = "button";
    close.className = "base-flash-close";
    close.setAttribute("aria-label", "Dismiss message");
    close.textContent = "×";
    msg.append(close);
    const dismiss = () => {
      msg.classList.add("is-leaving");
      msg.addEventListener("animationend", () => msg.remove(), { once: true });
      if (reduceMotion) msg.remove();
    };
    close.addEventListener("click", dismiss);
    if (msg.classList.contains("is-ok")) setTimeout(dismiss, 6000);
  });
})();
