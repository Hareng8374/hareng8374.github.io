/* Avatar component. Vanilla, no dependencies, no build step.
 *
 * Classic script so test-avatar.html opens straight off disk:
 *   <script src="src/components/avatar.js"></script>
 *   const a = window.Avatar.create(document.querySelector('#avatar'));
 *
 * Design notes worth knowing before editing:
 *
 *  - One rAF loop. Pointer handlers only stash a target; all work happens in
 *    the loop, and each animated element gets at most one transform write per
 *    frame. Three elements move (parallax container, tilt, pupils) because the
 *    spec requires pupils to track independently of the head and the head to
 *    tilt independently of the parallax translate.
 *  - Breathing is a CSS animation and the anticipation squash is WAAPI, both on
 *    dedicated wrapper elements. Neither touches the loop, and neither can
 *    collide with a JS transform write.
 *  - No layout reads in the steady state. The element rect is cached and only
 *    re-read on the frame after a resize or scroll.
 */
(function (global) {
  'use strict';

  /* Poses. `eyes` says whether the pupils/blink layers register against this
   * pose. The layers are cut from idle-still.webp, and the flag is set from the
   * measured compositing error over each pose's own irises -- mean |delta| on
   * the pixels the pupil layer paints:
   *
   *   idle-still  1.6   <- the only pose that registers
   *   wave1      18.2     wave2 17.6     surprised 31.3
   *   thumbsup   32.7     dance1 45.0    dance2 50.3     point 58.0
   *
   * Vertical eye-line offset is a poor proxy here: wave1 sits only 2px off
   * idle's eye line yet still misregisters badly, because each pose is a
   * separate render with its irises in a different place horizontally. Anything
   * but idle-still draws a visible second set of irises. */
  var POSES = {
    'idle-still': { file: 'idle-still.webp', eyes: true },
    'wave1':      { file: 'wave1.webp',      eyes: false },
    'wave2':      { file: 'wave2.webp',      eyes: false },
    'point':      { file: 'point.webp',      eyes: false },
    'thumbsup':   { file: 'thumbsup.webp',   eyes: false },
    'dance1':     { file: 'dance1.webp',     eyes: false },
    'dance2':     { file: 'dance2.webp',     eyes: false },
    'surprised':  { file: 'surprised.webp',  eyes: false }
  };

  var ALIAS = {
    idle: 'idle-still', wave: 'wave1', dance: 'dance1',
    thumbs: 'thumbsup', shock: 'surprised'
  };

  var K = {
    fade: 420,          // pose crossfade; long and eased so it reads as a blend
    parallaxX: 5,       // deliberately small -- the avatar should sit still and
    parallaxY: 3,       // act, not follow the cursor around the page
    tilt: 1,
    pupil: 3,
    lerp: 0.045,        // slower lerp = longer, softer trail
    blinkMs: 130,
    blinkMin: 3500,
    blinkMax: 7500,
    preloadAt: 20000,
    videoAt: 30000,
    videoIn: 600,
    videoOut: 400,
    seamFade: 300,
    seamLead: 0.45,
    wrapLead: 0.12,
    clickHold: 1400,
    cycleStart: 900     // beat before the ambient cycle begins
  };

  /* Ambient cycle. Returning to idle-still between beats gives the sequence a
   * resting pulse instead of a metronome of gestures, and it is the only pose
   * the eye layers register against, so it is also where blinking happens.
   * Holds are uneven on purpose -- equal holds read mechanical. */
  var CYCLE = [
    ['idle-still', 2600],
    ['ballspin',  15000],   // the ball leads: first thing after the opening pose
    ['idle-still', 2400],
    ['wave1',      1500],
    ['wave2',      1700],
    ['idle-still', 2600],
    ['thumbsup',   2400],
    ['point',      2600],
    ['idle-still', 2800],
    ['surprised',  2200],
    ['dance1',     1800],
    ['dance2',     1800],
    ['dance1',     1600],
    ['idle-still', 3200]
  ];

  /* 709-byte VP9+alpha probe: left half opaque green, right half fully clear.
   * Safari decodes VP9 but drops the alpha channel, so canPlayType reports
   * support it does not have -- the only reliable test is to decode a frame and
   * read the alpha back. Checking BOTH halves matters: a clear-only probe reads
   * alpha 0 when the video fails to load at all, which would false-positive. */
  var PROBE = 'data:video/webm;base64,GkXfo59ChoEBQveBAULygQRC84EIQoKEd2VibUKHgQJChYECGFOAZwEAAAAAAAKVEU2bdLpNu4tTq4QVSalmU6yBoU27i1OrhBZUrmtTrIHWTbuMU6uEElTDZ1OsggEnTbuMU6uEHFO7a1OsggJ/7AEAAAAAAABZAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAVSalmsCrXsYMPQkBNgIxMYXZmNjEuNy4xMDBXQYxMYXZmNjEuNy4xMDBEiYhAb0AAAAAAABZUrmvMrgEAAAAAAABD14EBc8WIpM5PUlUprtKcgQAitZyDdW5kiIEAhoVWX1ZQOYOBASPjg4QE95DV4JSwgUC6gUCagQJTwIEBVbCEVbmBARJUw2dAf3Nzn2PAgGfImUWjh0VOQ09ERVJEh4xMYXZmNjEuNy4xMDBzc9pjwItjxYikzk9SVSmu0mfIpUWjh0VOQ09ERVJEh5hMYXZjNjEuMTkuMTAwIGxpYnZweC12cDlnyKFFo4hEVVJBVElPTkSHkzAwOjAwOjAwLjI1MDAwMDAwMAAfQ7Z1QM3ngQCg4qGzgQAAAIJJg0IAA/AD9gA4JBwYjAAAMGAAAFiM//4+f//3Rtb/////Vf2fP////i2tnsJgdaGqpqjugQGlo4JJg0IAA/AD9gA4JBwYjAAAMGAAACin//90D0///uerwAAAoLGhk4EAUwCGAECSnABUAAADIAAAVHB1oZamlO6BAaWPhgBAkpwAVAAAAyAAAFRw+4GtoLGhk4EApwCGAECSnABS4AADIAAAVHB1oZamlO6BAaWPhgBAkpwAUuAAAyAAAFRw+4GsHFO7a5G7j7OBALeK94EB8YIBrPCBAw==';

  var alphaProbe = null;

  function detectVp9Alpha() {
    if (alphaProbe) return alphaProbe;
    alphaProbe = new Promise(function (resolve) {
      var v = document.createElement('video');
      var done = false;
      var timer = setTimeout(function () { finish(false); }, 5000);   // runs at the 20s mark, video at 30s

      function finish(ok) {
        if (done) return;
        done = true;
        clearTimeout(timer);
        try { v.pause(); v.removeAttribute('src'); v.load(); } catch (e) {}
        resolve(ok);
      }
      var tries = 0;
      function read() {
        if (done) return;
        // readyState < 2 means no current frame; wait for another signal.
        if (v.readyState < 2 && tries++ < 20) {
          setTimeout(read, 50);
          return;
        }
        try {
          var c = document.createElement('canvas');
          c.width = 64; c.height = 64;
          var ctx = c.getContext('2d', { willReadFrequently: true });
          ctx.clearRect(0, 0, 64, 64);
          ctx.drawImage(v, 0, 0, 64, 64);
          var opaque = ctx.getImageData(16, 32, 1, 1).data[3];
          var clear = ctx.getImageData(48, 32, 1, 1).data[3];
          // Opaque half proves the frame actually decoded and drew;
          // clear half proves the alpha channel survived.
          finish(opaque > 250 && clear < 250);
        } catch (e) { finish(false); }
      }

      v.muted = true;
      v.defaultMuted = true;
      v.playsInline = true;
      v.preload = 'auto';
      v.setAttribute('muted', '');
      v.setAttribute('playsinline', '');

      // Prefer requestVideoFrameCallback: it fires when a frame is actually
      // presentable, which is the only signal that guarantees drawImage has
      // something to copy. loadeddata alone can land before the first frame is
      // compositable, and autoplay may be refused outright, so neither is
      // sufficient on its own.
      if (v.requestVideoFrameCallback) {
        v.requestVideoFrameCallback(function () { read(); });
      }
      v.addEventListener('loadeddata', function () {
        requestAnimationFrame(read);
      }, { once: true });
      v.addEventListener('canplay', function () {
        requestAnimationFrame(read);
      }, { once: true });
      v.addEventListener('error', function () { finish(false); }, { once: true });
      v.src = PROBE;
      v.load();
      var pl = v.play();
      if (pl && pl.catch) pl.catch(function () {});
    });
    return alphaProbe;
  }

  function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }

  function prefersReduced() {
    return !!(global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }
  function isTouch() {
    return !!(global.matchMedia && global.matchMedia('(hover: none), (pointer: coarse)').matches);
  }
  function saveData() {
    var c = navigator.connection;
    return !!(c && (c.saveData || /(^|-)2g$/.test(c.effectiveType || '')));
  }

  /* ------------------------------------------------------------- Avatar -- */

  function Avatar(el, opts) {
    opts = opts || {};
    this.root = el;
    this.assets = opts.assets || 'src/assets/avatar/';
    if (this.assets.slice(-1) !== '/') this.assets += '/';

    // Click-to-react is great on a demo page and noisy on a real site, where
    // every nav click would fire a pose change. Opt-out.
    this.clickReact = opts.clickReact !== false;
    // Pupil tracking is off by default. The iris layer slides while the sclera
    // and eyelids stay fixed, so at display size it reads as a drifting eye
    // rather than a glance. Blinking still runs.
    this.pupilTrack = opts.pupilTrack === true;
    this.touch = isTouch();
    this.reduced = prefersReduced();
    this.noVideo = this.touch || this.reduced || saveData();

    this.base = 'idle-still';     // resting pose
    this.pose = 'idle-still';     // what is on screen
    this.transient = null;        // hover / click / sequence override
    this.videoOn = false;
    this.destroyed = false;

    // motion state
    this.tx = 0; this.ty = 0; this.cx = 0; this.cy = 0;   // parallax cur/target
    this.tRot = 0; this.cRot = 0;
    this.tPx = 0; this.tPy = 0; this.cPx = 0; this.cPy = 0;
    this.rect = null;
    this.rectDirty = true;
    this.pointer = null;

    this.timers = [];
    this.seq = [];
    this.raf = 0;
    this.lastIdle = Date.now();
    this.alphaOk = null;
    this.videos = null;
    this.activeVid = 0;
    this.seaming = false;

    this._build();
    this._bind();
    this._preload();

    if (this.reduced) this.root.classList.add('is-reduced');
    this.raf = requestAnimationFrame(this._frame.bind(this));

    if (opts.cycle !== false) this._startCycle();
    this._scheduleBlink();
  }

  Avatar.prototype._build = function () {
    var self = this;
    this.root.classList.add('hg-avatar');
    this.root.innerHTML = '';
    // One source of truth for the fade: JS owns it, CSS reads it.
    this.root.style.setProperty('--hg-fade', K.fade + 'ms');
    this.root.style.setProperty('--hg-seam', K.seamFade + 'ms');

    function div(cls, parent) {
      var d = document.createElement('div');
      d.className = cls;
      parent.appendChild(d);
      return d;
    }
    this.tiltEl = div('hg-avatar__tilt', this.root);
    this.breatheEl = div('hg-avatar__breathe', this.tiltEl);
    this.squashEl = div('hg-avatar__squash', this.breatheEl);
    this.stack = div('hg-avatar__stack', this.squashEl);

    this.poseEls = {};
    Object.keys(POSES).forEach(function (name) {
      var img = document.createElement('img');
      img.className = 'hg-avatar__layer hg-avatar__pose';
      img.setAttribute('data-pose', name);
      img.src = self.assets + POSES[name].file;
      img.alt = '';
      img.decoding = 'async';
      img.draggable = false;
      self.stack.appendChild(img);
      self.poseEls[name] = img;
    });
    this.poseEls[this.pose].classList.add('is-on');

    this.pupilsEl = document.createElement('img');
    this.pupilsEl.className = 'hg-avatar__layer hg-avatar__pupils';
    this.pupilsEl.src = this.assets + 'pupils.webp';
    this.pupilsEl.alt = '';
    this.pupilsEl.draggable = false;
    this.stack.appendChild(this.pupilsEl);

    this.eyesEl = document.createElement('img');
    this.eyesEl.className = 'hg-avatar__layer hg-avatar__eyes';
    this.eyesEl.src = this.assets + 'eyes-closed.webp';
    this.eyesEl.alt = '';
    this.eyesEl.draggable = false;
    this.stack.appendChild(this.eyesEl);

    this.posterEl = document.createElement('img');
    this.posterEl.className = 'hg-avatar__layer hg-avatar__poster';
    this.posterEl.alt = '';
    this.posterEl.draggable = false;
    this.stack.appendChild(this.posterEl);

    this._syncEyes();
  };

  Avatar.prototype._preload = function () {
    var self = this;
    var imgs = Object.keys(this.poseEls).map(function (k) { return self.poseEls[k]; });
    var decoded = Promise.all(imgs.map(function (i) {
      return i.decode ? i.decode().catch(function () {}) : Promise.resolve();
    }));
    // Waiting on decode() is what buys a flicker-free first swap, but it must
    // not be able to withhold the intro: decode() can hang indefinitely in some
    // engines and for images that never get laid out. Race it so the sequence
    // runs either way -- worst case the first frame decodes a beat late.
    this.ready = Promise.race([
      decoded,
      new Promise(function (res) { self._after(600, res); })
    ]);
  };

  /* ------------------------------------------------------------- events -- */

  Avatar.prototype._bind = function () {
    var self = this;
    this._h = {};

    this._h.move = function (e) {
      self.pointer = { x: e.clientX, y: e.clientY };
      self._activity();
    };
    this._h.leave = function () { self.pointer = null; };
    this._h.down = function () { self._activity(); self.play('surprised', K.clickHold); };
    this._h.act = function () { self._activity(); };
    this._h.dirty = function () { self.rectDirty = true; };

    this._h.over = function (e) {
      var t = e.target.closest && e.target.closest('[data-avatar-react]');
      if (!t) return;
      var pose = self._resolve(t.getAttribute('data-avatar-react'));
      if (pose) self._setTransient(pose);
    };
    this._h.out = function (e) {
      var t = e.target.closest && e.target.closest('[data-avatar-react]');
      if (!t) return;
      var to = e.relatedTarget;
      if (to && t.contains(to)) return;
      self._setTransient(null);
    };

    if (!this.touch) {
      global.addEventListener('pointermove', this._h.move, { passive: true });
      global.addEventListener('pointerleave', this._h.leave, { passive: true });
      document.addEventListener('mouseover', this._h.over, true);
      document.addEventListener('mouseout', this._h.out, true);
      document.addEventListener('focusin', this._h.over, true);
      document.addEventListener('focusout', this._h.out, true);
    }
    if (this.clickReact) document.addEventListener('pointerdown', this._h.down, { passive: true });
    else document.addEventListener('pointerdown', this._h.act, { passive: true });
    global.addEventListener('keydown', this._h.act, { passive: true });
    global.addEventListener('wheel', this._h.act, { passive: true });
    global.addEventListener('touchstart', this._h.act, { passive: true });
    global.addEventListener('scroll', this._h.dirty, { passive: true });
    global.addEventListener('resize', this._h.dirty, { passive: true });
  };

  Avatar.prototype._activity = function () {
    this.lastIdle = Date.now();
    // Only bail out of the video if it was the idle screensaver. When the ball
    // is a scheduled beat of the cycle, exiting on input meant the faintest
    // mouse movement cancelled it -- so it was effectively never watchable.
    if (this.videoOn && this.videoReason === 'idle') this._exitVideo();
  };

  /* --------------------------------------------------------------- poses -- */

  Avatar.prototype._resolve = function (name) {
    if (!name) return null;
    name = String(name).trim();
    if (POSES[name]) return name;
    if (ALIAS[name] && POSES[ALIAS[name]]) return ALIAS[name];
    return null;
  };

  Avatar.prototype._setTransient = function (pose) {
    // A requested pose always wins over the video. Without this the pose fades
    // in on a layer BELOW the video, and because the clip has an alpha channel
    // you see both at once -- the pose ghosting through wherever the video is
    // transparent. Exiting also resets base to idle-still, so releasing the
    // hover lands somewhere sensible rather than back on a dismissed clip.
    if (pose && this.videoOn) this._exitVideo();
    this.transient = pose;
    this._render();
  };

  Avatar.prototype._render = function () {
    var want = this.transient || this.base;
    if (want === 'ballspin') return;   // video owns the frame
    this._swap(want);
  };

  /* Swap is now a plain layered crossfade. The anticipation squash that used to
   * run here fired on every beat of the sequence, and a 200ms scaleY pop every
   * 320ms is what read as choppy -- at this pace the fade alone carries it. */
  Avatar.prototype._swap = function (name) {
    if (this.destroyed || name === this.pose || !POSES[name]) return;
    this._apply(name);
  };

  Avatar.prototype._apply = function (name) {
    if (this.destroyed || !this.poseEls[name]) return;
    var self = this;
    var out = this.poseEls[this.pose];
    var incoming = this.poseEls[name];

    // Incoming rides above the outgoing for the length of the fade so the
    // overlapping body never dips in opacity mid-dissolve.
    Object.keys(this.poseEls).forEach(function (k) {
      self.poseEls[k].classList.remove('is-incoming');
    });
    incoming.classList.add('is-incoming');
    incoming.classList.add('is-on');
    if (out && out !== incoming) out.classList.remove('is-on');

    this.pose = name;
    this._syncEyes();
    this._after(K.fade + 40, function () {
      if (!self.destroyed && self.pose === name) incoming.classList.remove('is-incoming');
    });
  };

  /* Pupils and blink only exist where they register. */
  Avatar.prototype._syncEyes = function () {
    var p = POSES[this.pose];
    var ok = !!(p && p.eyes) && !this.videoOn && !this.reduced;
    this.eyesActive = ok;
    this.pupilsEl.classList.toggle('is-on', ok && this.pupilTrack);
    if (!ok) this.eyesEl.classList.remove('is-on');
  };

  Avatar.prototype._scheduleBlink = function () {
    var self = this;
    var wait = K.blinkMin + Math.random() * (K.blinkMax - K.blinkMin);
    this._after(wait, function () {
      if (self.destroyed) return;
      if (self.eyesActive) {
        self.eyesEl.classList.add('is-on');
        self._after(K.blinkMs, function () { self.eyesEl.classList.remove('is-on'); });
      }
      self._scheduleBlink();
    });
  };

  /* ---------------------------------------------------------- sequences -- */

  Avatar.prototype._after = function (ms, fn) {
    var self = this;
    var id = setTimeout(function () {
      self.timers = self.timers.filter(function (t) { return t !== id; });
      fn();
    }, ms);
    this.timers.push(id);
    return id;
  };

  Avatar.prototype._clearSeq = function () {
    this.seq.forEach(clearTimeout);
    this.seq = [];
  };

  /* steps: [[pose, holdMs], ...]; pose null returns to base. */
  Avatar.prototype._runSeq = function (steps, startDelay) {
    var self = this;
    this._clearSeq();
    var t = startDelay || 0;
    steps.forEach(function (s) {
      var id = setTimeout(function () { self._setTransient(s[0]); }, t);
      self.seq.push(id);
      t += s[1];
    });
    var end = setTimeout(function () { self._setTransient(null); }, t);
    this.seq.push(end);
  };

  /* The ambient behaviour: walk the cycle forever, driving the RESTING pose.
   * Hover and click set a transient that overrides it, and when the transient
   * clears the cycle is simply wherever it got to -- no resume bookkeeping, and
   * no chance of the two fighting over the same layer. */
  Avatar.prototype._startCycle = function () {
    var self = this, i = 0;
    this.cycleOn = true;
    // The ball is the second beat now, so the two-beat lookahead below would
    // fire too late to have it decoded. Start the fetch up front when it leads.
    for (var k = 0; k < 3; k++) {
      if (CYCLE[k] && CYCLE[k][0] === 'ballspin') { this._preloadVideo(); break; }
    }
    function step() {
      if (self.destroyed || !self.cycleOn) return;
      var s = CYCLE[i % CYCLE.length];
      i++;
      // Fetch the clip two beats before it is due rather than on page load, so
      // the 430KB is spent only by someone who actually stayed.
      var soon = CYCLE[(i + 1) % CYCLE.length];
      if (soon && soon[0] === 'ballspin') self._preloadVideo();

      if (s[0] === 'ballspin') {
        self._enterVideo('cycle');
      } else {
        if (self.videoOn) self._exitVideo();
        self.base = s[0];
        self._render();
      }
      self._after(s[1], step);
    }
    this._after(K.cycleStart, step);
  };

  Avatar.prototype._stopCycle = function () { this.cycleOn = false; };

  /* -------------------------------------------------------------- video -- */

  Avatar.prototype._makeVideos = function () {
    if (this.videos) return;
    var self = this;
    this.videos = [0, 1].map(function () {
      var v = document.createElement('video');
      v.className = 'hg-avatar__layer hg-avatar__video';
      v.muted = true;
      v.defaultMuted = true;
      v.playsInline = true;
      v.preload = 'none';
      v.setAttribute('muted', '');
      v.setAttribute('playsinline', '');
      // Deliberately NO loop attribute: the seam is handled by hand.
      v.addEventListener('ended', function () {
        try { v.currentTime = 0; v.play(); } catch (e) {}
      });
      self.stack.appendChild(v);
      return v;
    });
  };

  Avatar.prototype._preloadVideo = function () {
    if (this.noVideo || this.videoLoading) return;
    this.videoLoading = true;
    var self = this;
    this._makeVideos();
    detectVp9Alpha().then(function (ok) {
      self.alphaOk = ok;
      if (self.destroyed) return;
      if (ok) {
        self.videos.forEach(function (v) {
          v.preload = 'auto';
          v.src = self.assets + 'ballspin.webm';
          v.load();
        });
      } else {
        self.posterEl.src = self.assets + 'ballspin-poster.webp';
      }
    });
  };

  Avatar.prototype._enterVideo = function (reason) {
    if (this.videoOn || this.noVideo || this.destroyed) return;
    var self = this;
    this._preloadVideo();
    this.videoOn = true;
    this.videoReason = reason || 'idle';
    this.base = 'ballspin';
    this._syncEyes();

    detectVp9Alpha().then(function (ok) {
      if (self.destroyed || !self.videoOn) return;
      if (!ok) {
        self.posterEl.src = self.assets + 'ballspin-poster.webp';
        self.posterEl.style.transitionDuration = K.videoIn + 'ms';
        self.posterEl.classList.add('is-on');
        return;
      }
      var a = self.videos[0], b = self.videos[1];
      var d = a.duration || 4.1667;
      self.dur = d;
      try {
        a.currentTime = 0;
        b.currentTime = d / 2;      // half-clip offset: the two seams never coincide
      } catch (e) {}
      [a, b].forEach(function (v) {
        var p = v.play();
        if (p && p.catch) p.catch(function () {});
      });
      self.activeVid = 0;
      a.style.transitionDuration = K.videoIn + 'ms';
      a.classList.add('is-on');
    });
    Object.keys(this.poseEls).forEach(function (k) {
      self.poseEls[k].style.transitionDuration = K.videoIn + 'ms';
      self.poseEls[k].classList.remove('is-on');
    });
    this.pupilsEl.classList.remove('is-on');
  };

  Avatar.prototype._exitVideo = function () {
    if (!this.videoOn) return;
    var self = this;
    this.videoOn = false;
    this.videoReason = null;
    this.base = 'idle-still';
    this.lastIdle = Date.now();

    if (this.videos) {
      this.videos.forEach(function (v) {
        v.style.transitionDuration = K.videoOut + 'ms';
        v.classList.remove('is-on');
      });
      this._after(K.videoOut, function () {
        if (self.videos && !self.videoOn) {
          self.videos.forEach(function (v) { try { v.pause(); } catch (e) {} });
        }
      });
    }
    this.posterEl.style.transitionDuration = K.videoOut + 'ms';
    this.posterEl.classList.remove('is-on');

    var target = this.transient || 'idle-still';
    var el = this.poseEls[target];
    if (el) {
      el.style.transitionDuration = K.videoOut + 'ms';
      el.classList.add('is-on');
      this.pose = target;
    }
    this._syncEyes();
    this._after(K.videoOut, function () {
      Object.keys(self.poseEls).forEach(function (k) {
        self.poseEls[k].style.transitionDuration = '';
      });
    });
  };

  /* The clip does not loop cleanly, so two copies run half a duration apart and
   * whichever is visible hands over ~0.45s before its own end. The one that
   * wraps is always the hidden one. */
  Avatar.prototype._seam = function () {
    if (!this.videoOn || !this.videos || this.seaming || !this.alphaOk) return;
    var self = this;
    var d = this.dur || this.videos[0].duration;
    if (!d || !isFinite(d)) return;

    var cur = this.videos[this.activeVid];
    var other = this.videos[1 - this.activeVid];

    if (cur.currentTime >= d - K.seamLead) {
      this.seaming = true;
      cur.style.transitionDuration = K.seamFade + 'ms';
      other.style.transitionDuration = K.seamFade + 'ms';
      other.classList.add('is-on');
      cur.classList.remove('is-on');
      this.activeVid = 1 - this.activeVid;
      this._after(K.seamFade, function () { self.seaming = false; });
    }

    // Wrap whichever is hidden, well clear of the crossfade window.
    var hidden = this.videos[1 - this.activeVid];
    if (hidden.currentTime >= d - K.wrapLead) {
      try {
        hidden.currentTime = 0;
        var p = hidden.play();
        if (p && p.catch) p.catch(function () {});
      } catch (e) {}
    }
  };

  /* ---------------------------------------------------------- rAF loop -- */

  Avatar.prototype._frame = function () {
    if (this.destroyed) return;

    // One layout read, and only on the frame after a scroll/resize.
    if (this.rectDirty) {
      this.rect = this.root.getBoundingClientRect();
      this.rectDirty = false;
    }

    var moving = !this.reduced && !this.touch;
    if (moving && this.pointer && this.rect) {
      var ox = this.rect.left + this.rect.width / 2;
      var oy = this.rect.top + this.rect.height / 2;
      var nx = clamp((this.pointer.x - ox) / (global.innerWidth / 2 || 1), -1, 1);
      var ny = clamp((this.pointer.y - oy) / (global.innerHeight / 2 || 1), -1, 1);
      this.tx = nx * K.parallaxX;
      this.ty = ny * K.parallaxY;
      this.tRot = nx * K.tilt;
      this.tPx = nx * K.pupil;
      this.tPy = ny * K.pupil;
    } else {
      this.tx = this.ty = this.tRot = this.tPx = this.tPy = 0;
    }

    // Lerp so the avatar trails the cursor rather than snapping to it.
    this.cx += (this.tx - this.cx) * K.lerp;
    this.cy += (this.ty - this.cy) * K.lerp;
    this.cRot += (this.tRot - this.cRot) * K.lerp;
    var pupilsLive = this.pupilTrack && this.eyesActive && !this.videoOn;
    this.cPx += ((pupilsLive ? this.tPx : 0) - this.cPx) * K.lerp;
    this.cPy += ((pupilsLive ? this.tPy : 0) - this.cPy) * K.lerp;

    if (this.videoOn) this._seam();

    // Idle escalation.
    var idleFor = Date.now() - this.lastIdle;
    if (!this.noVideo && !this.videoOn) {
      if (idleFor > K.preloadAt && !this.videoLoading) this._preloadVideo();
      if (idleFor > K.videoAt) this._enterVideo('idle');
    }

    // Exactly one transform write per animated element, batched at the end.
    if (!this.reduced) {
      this.root.style.transform =
        'translate3d(' + this.cx.toFixed(2) + 'px,' + this.cy.toFixed(2) + 'px,0)';
      this.tiltEl.style.transform = 'rotate(' + this.cRot.toFixed(3) + 'deg)';
      this.pupilsEl.style.transform =
        'translate3d(' + this.cPx.toFixed(2) + 'px,' + this.cPy.toFixed(2) + 'px,0)';
    }

    this.raf = requestAnimationFrame(this._frame.bind(this));
  };

  /* ----------------------------------------------------------------- API -- */

  Avatar.prototype.play = function (name, holdMs) {
    var pose = this._resolve(name);
    if (!pose) return this;
    var self = this;
    this._clearSeq();
    // 'wave' is the four-beat sequence; 'wave1'/'wave2' are the single frames.
    if (name === 'wave') {
      if (this.videoOn) this._exitVideo();
      this._runSeq([['wave1', 1500], ['wave2', 1700],
                    ['wave1', 1500], ['wave2', 1700]], 0);
      return this;
    }
    if (this.videoOn) this._exitVideo();
    this._setTransient(pose);
    // Default hold: a one-off pose should hand back to the ambient cycle rather
    // than freezing the avatar on whatever was last requested.
    var hold = holdMs || 2200;
    if (hold) {
      var id = setTimeout(function () { self._setTransient(null); }, hold);
      this.seq.push(id);
    }
    return this;
  };

  Avatar.prototype.setIdle = function (name) {
    if (name === 'ballspin') {
      this.noVideo = this.reduced;      // explicit request overrides touch/saveData
      this._enterVideo();
    } else if (name === 'cycle') {
      this._exitVideo();
      if (!this.cycleOn) this._startCycle();
    } else {
      var pose = this._resolve(name) || 'idle-still';
      this._exitVideo();
      this._stopCycle();          // an explicit resting pose wins over the cycle
      this.base = pose;
      this._render();
    }
    return this;
  };

  Avatar.prototype.forceVideo = function (on) {
    if (on) {
      this.noVideo = this.reduced;
      this._enterVideo();
    } else {
      this.noVideo = this.touch || this.reduced || saveData();
      this._exitVideo();
    }
    return this;
  };

  Avatar.prototype.setReducedMotion = function (on) {
    this.reduced = !!on;
    this.root.classList.toggle('is-reduced', this.reduced);
    this.root.classList.toggle('is-motion-ok', !this.reduced && prefersReduced());
    if (this.reduced) {
      this.noVideo = true;
      this._exitVideo();
      this.root.style.transform = '';
      this.tiltEl.style.transform = '';
      this.pupilsEl.style.transform = '';
    } else {
      this.noVideo = this.touch || saveData();
    }
    this._syncEyes();
    return this;
  };

  Avatar.prototype.getState = function () {
    return {
      pose: this.pose,
      base: this.base,
      transient: this.transient,
      video: this.videoOn,
      alphaOk: this.alphaOk,
      idleMs: Date.now() - this.lastIdle,
      reduced: this.reduced,
      touch: this.touch,
      eyes: !!this.eyesActive
    };
  };

  Avatar.prototype.destroy = function () {
    if (this.destroyed) return;
    this.destroyed = true;
    cancelAnimationFrame(this.raf);
    this.timers.forEach(clearTimeout);
    this.seq.forEach(clearTimeout);
    this.timers = []; this.seq = [];

    if (!this.touch) {
      global.removeEventListener('pointermove', this._h.move);
      global.removeEventListener('pointerleave', this._h.leave);
      document.removeEventListener('mouseover', this._h.over, true);
      document.removeEventListener('mouseout', this._h.out, true);
      document.removeEventListener('focusin', this._h.over, true);
      document.removeEventListener('focusout', this._h.out, true);
    }
    document.removeEventListener('pointerdown', this._h.down);
    document.removeEventListener('pointerdown', this._h.act);
    global.removeEventListener('keydown', this._h.act);
    global.removeEventListener('wheel', this._h.act);
    global.removeEventListener('touchstart', this._h.act);
    global.removeEventListener('scroll', this._h.dirty);
    global.removeEventListener('resize', this._h.dirty);

    if (this.videos) {
      this.videos.forEach(function (v) {
        try { v.pause(); v.removeAttribute('src'); v.load(); } catch (e) {}
      });
      this.videos = null;
    }
    this.root.classList.remove('hg-avatar', 'is-reduced', 'is-motion-ok');
    this.root.style.transform = '';
    this.root.innerHTML = '';
  };

  global.Avatar = {
    create: function (el, opts) { return new Avatar(el, opts); },
    poses: Object.keys(POSES),
    detectVp9Alpha: detectVp9Alpha
  };
})(window);
