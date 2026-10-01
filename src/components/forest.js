/* ===== FOREST =====
   The animated layer behind the whole site: swaying grass, drifting pollen and
   fireflies, on one canvas. Everything is procedural -- no sprites, no images,
   so the scene costs a few KB of code instead of a few hundred KB of art and
   redraws at any size.

   One canvas and one rAF for the lot. Grass is the expensive part, so each
   blade's shape is baked once into a path the draw loop only has to bend,
   rather than rebuilt per frame. */
(function () {
  'use strict';

  var cv = document.getElementById('forestCanvas');
  if (!cv) return;
  var reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  var cx = cv.getContext('2d', { alpha: true });
  var W = 0, H = 0, DPR = 1, raf = 0, t0 = performance.now();
  var blades = [], motes = [], flies = [];

  // Grass sits in three depth bands. The far band is darker, shorter and sways
  // less, which is what reads as distance -- not blur.
  var BANDS = [
    { n: 0.40, h: [0.050, 0.095], col: 'rgba(60,124,96,.40)',  sway: 0.45, y: 0.00 },
    { n: 0.34, h: [0.080, 0.150], col: 'rgba(34,96,73,.62)',   sway: 0.75, y: 0.03 },
    { n: 0.26, h: [0.120, 0.225], col: 'rgba(20,74,56,.86)',   sway: 1.00, y: 0.07 }
  ];

  function rand(a, b) { return a + Math.random() * (b - a); }

  function build() {
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    W = innerWidth; H = innerHeight;
    cv.width = Math.round(W * DPR); cv.height = Math.round(H * DPR);
    cv.style.width = W + 'px'; cv.style.height = H + 'px';
    cx.setTransform(DPR, 0, 0, DPR, 0, 0);

    blades = [];
    // density scales with width so a phone is not drawing a desktop's worth
    var total = Math.round(Math.min(230, Math.max(70, W / 7)));
    BANDS.forEach(function (b, bi) {
      var n = Math.round(total * b.n);
      for (var i = 0; i < n; i++) {
        blades.push({
          x: Math.random() * (W + 60) - 30,
          base: H * (1 + b.y),
          len: H * rand(b.h[0], b.h[1]),
          lean: rand(-0.34, 0.34),
          w: rand(1.4, 3.4) * (0.6 + bi * 0.26),
          sway: b.sway * rand(0.7, 1.3),
          phase: Math.random() * 6.283,
          col: b.col,
          band: bi
        });
      }
    });
    blades.sort(function (a, b) { return a.band - b.band; });

    motes = [];
    var mn = Math.round(Math.min(44, W / 30));
    for (var m = 0; m < mn; m++) {
      motes.push({ x: Math.random() * W, y: Math.random() * H, r: rand(0.6, 1.9),
                   s: rand(0.07, 0.22), d: Math.random() * 6.283, a: rand(0.10, 0.40) });
    }
    flies = [];
    var fn = Math.round(Math.min(11, W / 150));
    for (var f = 0; f < fn; f++) {
      flies.push({ x: Math.random() * W, y: rand(-H * 0.3, H),
                   vy: rand(0.16, 0.42), sw: rand(18, 52), ph: Math.random() * 6.283,
                   rot: Math.random() * 6.283, vr: rand(-0.012, 0.012),
                   sz: rand(5, 10), hue: Math.random() < 0.3 ? '#B8894A' : '#2F7A5C' });
    }
  }

  function draw(now) {
    raf = requestAnimationFrame(draw);
    var t = (now - t0) / 1000;
    cx.clearRect(0, 0, W, H);

    // wind: a slow base swell with a faster gust riding on it, so the motion
    // never settles into an obvious loop
    var wind = Math.sin(t * 0.26) * 0.62 + Math.sin(t * 0.73 + 1.3) * 0.26;

    for (var i = 0; i < blades.length; i++) {
      var b = blades[i];
      var bend = (wind + Math.sin(t * 1.15 + b.phase) * 0.34) * b.sway;
      var tipX = b.x + b.lean * b.len + bend * b.len * 0.42;
      var tipY = b.base - b.len;
      var midX = b.x + b.lean * b.len * 0.34 + bend * b.len * 0.12;
      var midY = b.base - b.len * 0.56;
      cx.beginPath();
      cx.moveTo(b.x - b.w / 2, b.base);
      cx.quadraticCurveTo(midX, midY, tipX, tipY);
      cx.quadraticCurveTo(midX + b.w * 0.6, midY, b.x + b.w / 2, b.base);
      cx.closePath();
      cx.fillStyle = b.col;
      cx.fill();
    }

    for (var m = 0; m < motes.length; m++) {
      var p = motes[m];
      p.y -= p.s;
      p.x += Math.sin(t * 0.4 + p.d) * 0.26;
      if (p.y < -6) { p.y = H + 6; p.x = Math.random() * W; }
      cx.beginPath(); cx.arc(p.x, p.y, p.r, 0, 6.283);
      cx.fillStyle = 'rgba(47,122,92,' + (p.a * 0.55) + ')'; cx.fill();
    }

    // leaves: fall, drift sideways on the same wind, and tumble as they go
    for (var f = 0; f < flies.length; f++) {
      var L = flies[f];
      L.y += L.vy;
      L.x += Math.sin(t * 0.6 + L.ph) * 0.5 + wind * 0.55;
      L.rot += L.vr + wind * 0.004;
      if (L.y > H + 24) { L.y = -24; L.x = Math.random() * W; }
      if (L.x < -30) L.x = W + 30; if (L.x > W + 30) L.x = -30;
      cx.save();
      cx.translate(L.x, L.y); cx.rotate(L.rot);
      cx.globalAlpha = 0.34;
      cx.beginPath();
      cx.moveTo(0, -L.sz);
      cx.quadraticCurveTo(L.sz * 0.78, 0, 0, L.sz);
      cx.quadraticCurveTo(-L.sz * 0.78, 0, 0, -L.sz);
      cx.fillStyle = L.hue; cx.fill();
      cx.globalAlpha = 1;
      cx.restore();
    }
  }

  function still() {
    // one static frame, so the scene is still there without motion
    cx.clearRect(0, 0, W, H);
    for (var i = 0; i < blades.length; i++) {
      var b = blades[i];
      cx.beginPath();
      cx.moveTo(b.x - b.w / 2, b.base);
      cx.quadraticCurveTo(b.x + b.lean * b.len * 0.34, b.base - b.len * 0.56,
                          b.x + b.lean * b.len, b.base - b.len);
      cx.quadraticCurveTo(b.x + b.lean * b.len * 0.34 + b.w * 0.6,
                          b.base - b.len * 0.56, b.x + b.w / 2, b.base);
      cx.closePath(); cx.fillStyle = b.col; cx.fill();
    }
  }

  function start() {
    build();
    cancelAnimationFrame(raf);
    if (reduced) { still(); return; }
    t0 = performance.now();
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
     is solved here and baked into a CSS linear() easing -- the same technique
     its vanilla sibling uses, for about a kilobyte instead of a dependency. */
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
  var SPRING = springEase(150, 20, 1);

  var SEL = '.project-card,.experience-card,.blog-card,.skill-row,.about-text-col>*,' +
            '.about-card,.section-title,.section-eyebrow,.stat-item,.contact-link,' +
            '.resume-button,.game-box,.projects-heading-wrap';
  function arm() {
    var els = document.querySelectorAll(SEL);
    if (reduced || !('IntersectionObserver' in window)) return;
    var io = new IntersectionObserver(function (es) {
      var n = 0;
      es.forEach(function (en) {
        if (!en.isIntersecting) return;
        io.unobserve(en.target);
        en.target.animate(
          [{ opacity: 0, transform: 'translateY(22px)' }, { opacity: 1, transform: 'none' }],
          { duration: SPRING.duration, easing: SPRING.easing, delay: n * 60, fill: 'both' });
        n++;
      });
    }, { rootMargin: '0px 0px -10% 0px', threshold: 0.08 });
    els.forEach(function (e) { io.observe(e); });
  }
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', arm);
  else arm();
  // SPA tabs swap content in, so re-arm whenever a page becomes active
  window.forestRearm = arm;
})();
