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

  /* .game-box is deliberately absent. It contains the shootaround canvas, and
     the drag-to-shoot aiming reads clientX minus the canvas rect -- which is
     only correct while the element is unrotated. Tilting it would quietly
     skew every shot. */
  var CARDS = '.project-card,.experience-card,.blog-card,.post-card,' +
              '.about-card,.stat-item,.skill-row';
  var MAGNETS = '.cta-button,.resume-button,.project-link,.contact-link,' +
                '.filter-pill,.repo-link,.read-more';

  /* Degrees. The home page is a showcase and can carry the full tilt; the
     working pages -- projects, resume, experience -- are there to be read,
     and the same angle on a wall of dense cards reads as restless rather
     than alive. Past ~8 the text starts to look warped anywhere. */
  var MAX_TILT = 6;
  var MAX_TILT_QUIET = 2.2;
  var LIFT = 6, LIFT_QUIET = 2.5;

  // which page a card lives on decides how far it is allowed to move
  function showy(el) {
    var page = el.closest ? el.closest('.page') : null;
    return !page || page.id === 'home';
  }
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
  function settle(el, force) {
    /* A CSS animation outranks an inline style, so while one is alive -- and
       these fill -- neither style.transform nor a var() the CSS reads can
       paint. The Web Animations API cannot stand it down either: cancelling a
       CSS animation whose animation-name is still set just restarts it, which
       is observable as getAnimations() going 1 -> 4. Removing the declaration
       is the only thing that works, and it is safe here because these are
       one-shot entrances that have already played by the time you hover. */
    if (force) el.style.animation = 'none';

    var as = el.getAnimations();
    for (var i = 0; i < as.length; i++) {
      var a = as[i];
      try {
        /* A WAAPI animation outranks even !important CSS while it is alive,
           and these fill forever -- so a card hovered mid-reveal would stay
           pinned at translateY(30px) with the tilt silently ignored. On a
           deliberate hover, snap the reveal to its end and bake it; you are
           looking straight at the card, so finishing early is invisible and
           far better than a dead card. finish() throws on an infinite
           animation, hence the guard. */
        if (a.playState !== 'finished') {
          if (!force) continue;
          a.finish();
        }
        a.commitStyles();
      } catch (e) { continue; }   // detached, infinite, or cross-origin
      a.cancel();
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
      showy: showy(el),
      apply: function (s) {
        /* Written to a custom property, not to style.transform. The sheet has
           `.project-card:hover{transform:none!important}` (and the same for
           .blog-card), and !important beats an inline declaration -- the tilt
           was being set every frame and thrown away on exactly the cards most
           worth tilting. The CSS reads var(--tilt) inside its own !important
           rule, so the cascade stops fighting us.

           translateY keeps the lift those :hover rules used to provide, since
           var(--tilt) now replaces them outright. */
        s.el.style.setProperty('--tilt',
          'perspective(900px) rotateX(' + s.x.toFixed(3) + 'deg) rotateY(' +
          s.y.toFixed(3) + 'deg) translateY(' + (-0.7 * s.z).toFixed(2) +
          'px) translateZ(' + s.z.toFixed(2) + 'px)');
      }
    };

    el.addEventListener('pointerenter', function () {
      settle(el, true);
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
      var amp = st.showy ? MAX_TILT : MAX_TILT_QUIET;
      st.tx = (py - 0.5) * -2 * amp;
      st.ty = (px - 0.5) * 2 * amp;
      st.tz = st.showy ? LIFT : LIFT_QUIET;
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
        s.el.style.setProperty('--mag', 'translate(' + s.x.toFixed(2) + 'px,' +
                               s.y.toFixed(2) + 'px)');
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
        if (s.tx || s.ty) { s.tx = s.ty = 0; join(s); }
        continue;
      }
      var cxp = r.left + r.width / 2, cyp = r.top + r.height / 2;
      var dx = mx - cxp, dy = my - cyp;
      var d = Math.sqrt(dx * dx + dy * dy);
      var reach = Math.max(r.width, r.height) / 2 + MAG_R;
      var f = Math.max(0, 1 - d / reach);
      /* Forced once, on first approach: buttons inherit an entrance animation
         from .cta-buttons, and the same cascade problem applies. */
      if (!s.freed) { settle(el, true); s.freed = true; }
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
