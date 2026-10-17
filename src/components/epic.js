/* ===== EPIC =====
   The firelit layer behind the whole site: rising embers, falling ash, and the
   slow god-ray dust of a torchlit hall. Same architecture as forest.js -- one
   canvas, one rAF, everything procedural -- so the scene is a few KB of code
   rather than a few hundred KB of art, and redraws crisp at any size.

   Nothing here is traced from or sampled out of any film. The look is built
   from a palette and a set of motion rules: warm light rising, cold ash
   falling, and reveals that arrive with weight instead of bounce. */
(function () {
  'use strict';

  var cv = document.getElementById('epicCanvas');
  if (!cv) return;
  var reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  var cx = cv.getContext('2d', { alpha: true });
  var W = 0, H = 0, DPR = 1, raf = 0, t0 = performance.now();
  var embers = [], ash = [], dust = [];

  /* Long-form pages (the blog) get the scene as a short band at the foot of the
     document rather than a full-viewport wash -- prose scrolling under a
     quarter-screen of moving embers is simply hard to read. Same scene, turned
     down to a border. */
  var LONGFORM = !!document.querySelector('.blog-main,.post-main');
  if (LONGFORM) document.documentElement.classList.add('epic-longform');
  var K = LONGFORM ? 0.5 : 1;

  // Warm core -> cooler edge. Embers near the bottom are hottest and youngest.
  var EMBER_HUES = ['#FFD79A', '#F6B45C', '#E8703A', '#C9502A', '#F0D28A'];
  var ASH_HUES = ['#6B6054', '#7D7264', '#584F45'];

  function rand(a, b) { return a + Math.random() * (b - a); }
  function pick(a) { return a[(Math.random() * a.length) | 0]; }

  function build() {
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    /* A canvas is a replaced element: with inset:0 and height:auto it falls
       back to its intrinsic 300x150 rather than stretching, so the inline
       height is what actually makes it fill the viewport. It therefore cannot
       be measured to decide its own size -- that reads back our own last
       answer. The viewport drives the fixed case; the CSS band drives
       longform, read once with the inline size cleared so the number is the
       stylesheet's and not ours. */
    cv.style.width = ''; cv.style.height = '';
    if (LONGFORM) {
      W = innerWidth;
      H = parseInt(getComputedStyle(cv).height, 10) || 300;
    } else {
      W = innerWidth; H = innerHeight;
    }
    cv.width = Math.round(W * DPR); cv.height = Math.round(H * DPR);
    cv.style.width = W + 'px'; cv.style.height = H + 'px';
    cx.setTransform(DPR, 0, 0, DPR, 0, 0);

    /* Density scales with width so a phone never draws a desktop's worth.
       Tuned down hard after looking at the About section: at the first count
       the embers read as confetti over body copy rather than atmosphere
       behind it. This layer draws in FRONT of the content (cards have opaque
       fills, so it has to), which means every spark costs legibility. */
    embers = [];
    var en = Math.round(Math.min(44, Math.max(12, W / 34)) * K);
    for (var i = 0; i < en; i++) embers.push(newEmber(true));

    ash = [];
    var an = Math.round(Math.min(34, Math.max(10, W / 44)) * K);
    for (var j = 0; j < an; j++) {
      ash.push({
        x: Math.random() * W, y: Math.random() * H,
        vy: rand(0.10, 0.34), sz: rand(1.2, 3.4),
        ph: Math.random() * 6.283, drift: rand(0.2, 0.8),
        rot: Math.random() * 6.283, vr: rand(-0.012, 0.012),
        a: rand(0.07, 0.19), hue: pick(ASH_HUES)
      });
    }

    dust = [];
    var dn = Math.round(Math.min(24, W / 56) * K);
    for (var d = 0; d < dn; d++) {
      dust.push({ x: Math.random() * W, y: Math.random() * H, r: rand(0.5, 1.7),
                  s: rand(0.05, 0.18), ph: Math.random() * 6.283, a: rand(0.07, 0.20) });
    }
  }

  /* Embers are respawned rather than pooled-and-reset so each one carries a
     full life: they brighten as they rise out of the heat, then burn down. */
  function newEmber(seed) {
    return {
      x: Math.random() * W,
      y: seed ? Math.random() * H : H + rand(4, 40),
      vy: rand(0.22, 0.85),
      sway: rand(0.25, 1.1),
      ph: Math.random() * 6.283,
      sz: rand(0.9, 2.6),
      life: 0,
      span: rand(5.5, 13),
      hue: pick(EMBER_HUES)
    };
  }

  function draw(now) {
    raf = requestAnimationFrame(draw);
    var t = (now - t0) / 1000;
    cx.clearRect(0, 0, W, H);

    /* Draught: a slow swell with a faster gust riding on it, so the drift never
       settles into a visible loop. Embers and ash share it, which is what makes
       them read as being in the same room. */
    var draught = Math.sin(t * 0.21) * 0.7 + Math.sin(t * 0.67 + 1.1) * 0.3;

    // --- god-ray dust: slowest layer, sits furthest back -------------------
    cx.save();
    for (var d = 0; d < dust.length; d++) {
      var p = dust[d];
      p.y -= p.s;
      p.x += Math.sin(t * 0.4 + p.ph) * 0.22 + draught * 0.14;
      if (p.y < -6) { p.y = H + 6; p.x = Math.random() * W; }
      cx.beginPath();
      cx.fillStyle = 'rgba(232,192,106,' + (p.a * (0.6 + 0.4 * Math.sin(t * 1.4 + p.ph))) + ')';
      cx.arc(p.x, p.y, p.r, 0, 6.2832);
      cx.fill();
    }
    cx.restore();

    // --- ash: cold, falling, tumbling --------------------------------------
    for (var a = 0; a < ash.length; a++) {
      var s = ash[a];
      s.y += s.vy;
      s.x += Math.sin(t * 0.6 + s.ph) * s.drift + draught * 0.3;
      s.rot += s.vr;
      if (s.y > H + 8) { s.y = -8; s.x = Math.random() * W; }
      if (s.x < -10) s.x = W + 10; else if (s.x > W + 10) s.x = -10;
      cx.save();
      cx.translate(s.x, s.y);
      cx.rotate(s.rot);
      cx.globalAlpha = s.a;
      cx.fillStyle = s.hue;
      // a flake, not a dot -- the tumble is only legible on something with a long axis
      cx.fillRect(-s.sz, -s.sz * 0.42, s.sz * 2, s.sz * 0.84);
      cx.restore();
    }

    /* --- embers: hot, rising, additive ------------------------------------
       'lighter' is what makes overlapping embers pool into a brighter core the
       way real sparks do; drawn normally they just occlude each other. */
    cx.save();
    cx.globalCompositeOperation = 'lighter';
    for (var e = 0; e < embers.length; e++) {
      var m = embers[e];
      m.life += 0.016;
      m.y -= m.vy;
      m.x += Math.sin(t * 0.9 + m.ph) * m.sway * 0.5 + draught * 0.45;

      var k = m.life / m.span;
      if (k >= 1 || m.y < -12) { embers[e] = newEmber(false); continue; }

      /* Brighten out of the heat, then burn down. sin(pi*k) peaks mid-life,
         which is higher up the screen -- the same shape as a spark that catches
         air before it dies. */
      var glow = Math.sin(Math.PI * k);
      var flick = 0.72 + 0.28 * Math.sin(t * 7.3 + m.ph * 3.1);
      var alpha = glow * flick * 0.42;
      if (alpha <= 0.004) continue;

      var r = m.sz * (0.8 + glow * 0.5);
      var g = cx.createRadialGradient(m.x, m.y, 0, m.x, m.y, r * 4.5);
      g.addColorStop(0, m.hue);
      g.addColorStop(0.35, 'rgba(232,112,58,0.42)');
      g.addColorStop(1, 'rgba(201,80,42,0)');
      cx.globalAlpha = alpha;
      cx.fillStyle = g;
      cx.beginPath();
      cx.arc(m.x, m.y, r * 4.5, 0, 6.2832);
      cx.fill();

      // hot core, so the spark has a hard centre instead of being only a smudge
      cx.globalAlpha = Math.min(1, alpha * 1.15);
      cx.fillStyle = '#FFE9BE';
      cx.beginPath();
      cx.arc(m.x, m.y, r * 0.5, 0, 6.2832);
      cx.fill();
    }
    cx.restore();
  }

  function start() {
    cancelAnimationFrame(raf); raf = 0;
    build();
    if (reduced) { draw(performance.now()); cancelAnimationFrame(raf); raf = 0; return; }
    t0 = performance.now() - 1;
    raf = requestAnimationFrame(draw);
  }

  var rt;
  addEventListener('resize', function () {
    clearTimeout(rt); rt = setTimeout(start, 180);
  }, { passive: true });
  // a background scene has no business burning frames on a hidden tab
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) { cancelAnimationFrame(raf); raf = 0; }
    else if (!raf && !reduced) { t0 = performance.now() - 1; raf = requestAnimationFrame(draw); }
  });
  start();

  /* ---- scroll reveals -----------------------------------------------------
     Framer Motion is React-only and this site has no build step, so the spring
     is solved here and baked into a CSS linear() easing.

     The forest used a light, springy 150/20/1. This theme wants weight: more
     mass and heavier damping give a slower arrival with almost no overshoot,
     which is what makes a block of text land like stone rather than bounce. */
  function springEase(k, c, m, steps) {
    steps = steps || 60;
    var w0 = Math.sqrt(k / m), z = c / (2 * Math.sqrt(k * m));
    var wd = z < 1 ? w0 * Math.sqrt(1 - z * z) : 0, pts = [], dur = 0, tt, v;
    for (var i = 0; i <= 600; i++) {
      tt = i / 100;
      v = z < 1 ? 1 - Math.exp(-z * w0 * tt) * (Math.cos(wd * tt) + (z * w0 / wd) * Math.sin(wd * tt))
                : 1 - (1 + w0 * tt) * Math.exp(-w0 * tt);
      if (Math.abs(1 - v) < 0.001) { dur = tt; break; }
    }
    if (!dur) dur = 6;
    for (var s = 0; s <= steps; s++) {
      tt = dur * s / steps;
      v = z < 1 ? 1 - Math.exp(-z * w0 * tt) * (Math.cos(wd * tt) + (z * w0 / wd) * Math.sin(wd * tt))
                : 1 - (1 + w0 * tt) * Math.exp(-w0 * tt);
      pts.push(Math.round(v * 10000) / 10000);
    }
    return { easing: 'linear(' + pts.join(',') + ')', duration: Math.round(dur * 1000) };
  }
  var SPRING = springEase(92, 27, 1.7);

  /* Scoped to .page-content and the sections so the nav, the modals and
     anything inside the game canvas are left alone -- animating those would
     fight their own state. */
  var SEL = [
    '.page-content p', '.page-content li',
    '.section-eyebrow', '.projects-heading-wrap',
    '.project-card', '.experience-card', '.blog-card', '.game-box',
    '.skill-row', '.about-card', '.about-text-col>*', '.about-label',
    '.about-text', '.about-facts>div', '.stat-item', '.contact-link', '.contact-text',
    '.resume-button', '.filter-pill', '.timeline-item', '.exp-card'
  ].join(',');

  /* Headings come in a word at a time. Only text nodes are touched and the
     element structure is left alone, so <span class="em"> and links inside a
     heading keep working and the text still reads as one string to a screen
     reader. */
  function splitWords(root) {
    if (root.dataset.split) return [];
    root.dataset.split = '1';
    var out = [];
    (function walk(node) {
      var kids = [].slice.call(node.childNodes);
      kids.forEach(function (n) {
        if (n.nodeType === 3) {
          var parts = n.nodeValue.split(/(\s+)/);
          if (!parts.length) return;
          var frag = document.createDocumentFragment();
          parts.forEach(function (w) {
            if (!w) return;
            if (/^\s+$/.test(w)) { frag.appendChild(document.createTextNode(w)); return; }
            var sp = document.createElement('span');
            sp.className = 'fw';
            sp.textContent = w;
            frag.appendChild(sp);
            out.push(sp);
          });
          node.replaceChild(frag, n);
        } else if (n.nodeType === 1 && !/^(BR|IMG|SVG)$/.test(n.tagName)) {
          walk(n);
        }
      });
    })(root);
    return out;
  }

  var SPLIT = '.section-title,.about-title,.hero h1,.project-title,' +
              '.experience-title,.contact-title,.resume-title';

  function armWords() {
    if (reduced || !('IntersectionObserver' in window)) return;
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (en) {
        if (!en.isIntersecting) return;
        io.unobserve(en.target);
        var ws = en.target._words || [];
        ws.forEach(function (w, i) {
          w.classList.remove('pre');
          /* Words rise further and settle heavier than the forest's, and the
             per-word stagger is longer -- a title should assemble, not flicker. */
          w.animate([{ opacity: 0, transform: 'translateY(0.74em) scale(0.97)', filter: 'blur(5px)' },
                     { opacity: 1, transform: 'none', filter: 'blur(0)' }],
            { duration: SPRING.duration, easing: SPRING.easing,
              delay: Math.min(i, 16) * 62, fill: 'backwards' });
        });
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.05 });

    document.querySelectorAll(SPLIT).forEach(function (h) {
      if (h.dataset.split) return;
      var ws = splitWords(h);
      if (!ws.length) return;
      h._words = ws;
      ws.forEach(function (w) { w.classList.add('pre'); });
      h.style.opacity = '1';
      h.style.animation = 'none';          // the heading's own fade would fight this
      io.observe(h);
    });
  }

  function arm() {
    if (reduced || !('IntersectionObserver' in window)) return;
    var els = [].filter.call(document.querySelectorAll(SEL), function (e) {
      if (e.dataset.revealed) return false;      // re-armed on every SPA nav
      e.dataset.revealed = '1';
      return true;
    });
    var io = new IntersectionObserver(function (es) {
      var n = 0;
      es.forEach(function (en) {
        if (!en.isIntersecting) return;
        io.unobserve(en.target);
        en.target.animate(
          [{ opacity: 0, transform: 'translateY(44px) scale(0.985)' },
           { opacity: 1, transform: 'none' }],
          { duration: SPRING.duration, easing: SPRING.easing,
            delay: Math.min(n, 7) * 72, fill: 'both' });
        n++;
      });
    }, { rootMargin: '0px 0px -10% 0px', threshold: 0.08 });
    els.forEach(function (e) { io.observe(e); });
  }

  function armAll() { armWords(); arm(); }
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', armAll);
  else armAll();
  // SPA tabs swap content in, so re-arm whenever a page becomes active
  window.forestRearm = armAll;   // index.html calls this name on nav
  window.epicRearm = armAll;
})();
