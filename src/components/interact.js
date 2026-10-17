/* ===== INTERACT =====
   Hover physics for the content layer: cards tilt toward the cursor and carry
   a light that follows it, buttons lean toward the pointer as it approaches.

   Everything here is transform and opacity only, so nothing in this file
   triggers layout. One shared rAF drives every active element rather than one
   per element, because a grid of cards under a fast cursor otherwise schedules
   a dozen callbacks a frame. */
(function () {
  'use strict';

  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  if (!('getAnimations' in Element.prototype)) return;

  var CARDS = '.project-card,.experience-card,.blog-card,.post-card,' +
              '.about-card,.stat-item,.skill-row,.game-box';
  var MAGNETS = '.cta-button,.resume-button,.project-link,.contact-link,' +
                '.filter-pill,.repo-link,.read-more';

  var MAX_TILT = 6;      // degrees; past ~8 the text starts to look warped
  var MAG_R = 90;        // px: how close the cursor gets before a button leans
  var MAG_PULL = 0.32;   // fraction of the offset the button actually travels

  var live = [];         // elements currently easing toward a target
  var raf = 0;

  /* The scroll reveals in forest.js animate transform with fill:'both', which
     outranks an inline transform for the life of the animation -- and a filled
     animation never ends. So a card that has finished revealing would simply
     refuse to tilt. Bake the final frame into the element and drop the
     animation, which hands transform back to us. Base CSS already has these at
     opacity 1, so there is nothing to flash. */
  function settle(el) {
    var as = el.getAnimations();
    for (var i = 0; i < as.length; i++) {
      var a = as[i];
      if (a.playState === 'finished') {
        try { a.commitStyles(); } catch (e) { /* cross-origin or detached */ }
        a.cancel();
      }
    }
  }

  function join(st) {
    if (live.indexOf(st) === -1) live.push(st);
    if (!raf) raf = requestAnimationFrame(tick);
  }

  function tick() {
    raf = 0;
    for (var i = live.length - 1; i >= 0; i--) {
      var s = live[i];
      s.x += (s.tx - s.x) * 0.14;
      s.y += (s.ty - s.y) * 0.14;
      s.z += (s.tz - s.z) * 0.14;
      s.apply(s);
      // settled: within half a hundredth of target on every axis
      if (Math.abs(s.tx - s.x) < 0.005 && Math.abs(s.ty - s.y) < 0.005 &&
          Math.abs(s.tz - s.z) < 0.005) {
        s.x = s.tx; s.y = s.ty; s.z = s.tz; s.apply(s);
        s.el.style.willChange = '';
        live.splice(i, 1);
      }
    }
    if (live.length) raf = requestAnimationFrame(tick);
  }

  // ── cards ───────────────────────────────────────────────────────────────
  function bindCard(el) {
    if (el.dataset.tilt) return;
    el.dataset.tilt = '1';

    /* The light needs its own element. ::before and ::after are already spoken
       for on project-card, experience-card and stat-item (ten rules between
       them), so taking one would silently delete an existing border or glow.
       Appended rather than prepended because :first-child selectors are the
       commoner of the two in this sheet, and it is position:absolute so it
       stays out of flex and grid flow either way. */
    var lit = document.createElement('span');
    lit.className = 'lit-layer';
    lit.setAttribute('aria-hidden', 'true');
    el.appendChild(lit);

    var st = {
      el: el, x: 0, y: 0, z: 0, tx: 0, ty: 0, tz: 0,
      apply: function (s) {
        s.el.style.transform =
          'perspective(900px) rotateX(' + s.x.toFixed(3) + 'deg) rotateY(' +
          s.y.toFixed(3) + 'deg) translateZ(' + s.z.toFixed(2) + 'px)';
      }
    };

    el.addEventListener('pointerenter', function () {
      settle(el);
      el.style.willChange = 'transform';
      el.classList.add('is-lit');
    });

    el.addEventListener('pointermove', function (e) {
      var r = el.getBoundingClientRect();
      if (!r.width || !r.height) return;
      var px = (e.clientX - r.left) / r.width;
      var py = (e.clientY - r.top) / r.height;
      // the light tracks the raw pointer; the tilt is eased
      el.style.setProperty('--mx', (px * 100).toFixed(1) + '%');
      el.style.setProperty('--my', (py * 100).toFixed(1) + '%');
      st.tx = (py - 0.5) * -2 * MAX_TILT;
      st.ty = (px - 0.5) * 2 * MAX_TILT;
      st.tz = 6;
      join(st);
    }, { passive: true });

    el.addEventListener('pointerleave', function () {
      st.tx = st.ty = st.tz = 0;
      el.classList.remove('is-lit');
      join(st);
    });
  }

  /* ── magnets ─────────────────────────────────────────────────────────────
     A button leans toward the cursor once it is close. Tracked on the window
     rather than per-button hover, so the lean begins BEFORE the pointer
     arrives -- which is the whole effect; bound to hover it would only ever
     fire once the cursor was already on the target. */
  var magnets = [];
  function bindMagnet(el) {
    if (el.dataset.magnet) return;
    el.dataset.magnet = '1';
    var st = {
      el: el, x: 0, y: 0, z: 0, tx: 0, ty: 0, tz: 0,
      apply: function (s) {
        s.el.style.transform = 'translate(' + s.x.toFixed(2) + 'px,' +
                               s.y.toFixed(2) + 'px)';
      }
    };
    el.__mag = st;
    magnets.push(st);
  }

  var mRaf = 0, mx = 0, my = 0;
  addEventListener('pointermove', function (e) {
    mx = e.clientX; my = e.clientY;
    if (!mRaf) mRaf = requestAnimationFrame(scanMagnets);
  }, { passive: true });

  function scanMagnets() {
    mRaf = 0;
    for (var i = 0; i < magnets.length; i++) {
      var s = magnets[i], el = s.el;
      if (!el.isConnected) { magnets.splice(i--, 1); continue; }
      var r = el.getBoundingClientRect();
      if (!r.width) continue;
      // cheap reject before the sqrt: most buttons are nowhere near the cursor
      if (mx < r.left - MAG_R || mx > r.right + MAG_R ||
          my < r.top - MAG_R || my > r.bottom + MAG_R) {
        if (s.tx || s.ty) { s.tx = s.ty = 0; settle(el); join(s); }
        continue;
      }
      var cxp = r.left + r.width / 2, cyp = r.top + r.height / 2;
      var dx = mx - cxp, dy = my - cyp;
      var d = Math.sqrt(dx * dx + dy * dy);
      var reach = Math.max(r.width, r.height) / 2 + MAG_R;
      var f = Math.max(0, 1 - d / reach);
      settle(el);
      el.style.willChange = 'transform';
      s.tx = dx * MAG_PULL * f;
      s.ty = dy * MAG_PULL * f;
      join(s);
    }
  }

  // ── wiring ──────────────────────────────────────────────────────────────
  function scan() {
    document.querySelectorAll(CARDS).forEach(bindCard);
    document.querySelectorAll(MAGNETS).forEach(bindMagnet);
  }
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', scan);
  else scan();

  // the SPA swaps sections in, so re-scan whenever a page becomes active
  window.interactRescan = scan;
  var prevRearm = window.forestRearm;
  window.forestRearm = function () {
    if (typeof prevRearm === 'function') prevRearm();
    scan();
  };
})();
