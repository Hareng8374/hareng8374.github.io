# -*- coding: utf-8 -*-
"""Rebuild the Experience section as four cards sharing one component.

Every card is illustration zone + info zone, with identical borders, identical
logo box and identical zone geometry, so nothing is per-card except the brand
mark and the decorative SVG.
"""
import io
import re

P = "index.html"

CSS = """
/* ═══════════════════════════════════════════════════════════
   EXPERIENCE CARDS -- one shared two-zone component
   ═══════════════════════════════════════════════════════════ */
.experience-card {
  border: 1px solid rgba(28,24,17,0.30) !important;
  border-radius: 14px !important;
  background: var(--surface) !important;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.9) !important;
  overflow: hidden;
  padding: 0 !important;                 /* the zones own their padding */
}
.experience-card + .experience-card { margin-top: 1.5rem; }
.experience-card::before { display: none !important; }

/* Illustration zone. aspect-ratio rather than a fixed height, so the zone
   scales with the card and can never letterbox or leave a dead band under
   the logo. The fill is the PAGE background -- never a dark plate. */
.xp-illu {
  position: relative;
  height: clamp(118px, 16vw, 168px);
  background: var(--paper);
  border-bottom: 1px solid rgba(28,24,17,0.18);
  display: grid;
  place-items: center;
  overflow: hidden;
}
.xp-art { position: absolute; inset: 0; width: 100%; height: 100%; z-index: 1; }

/* Identical logo box on all four: height is what the eye compares, so it is
   pinned and width follows each mark's own ratio. */
.xp-logo-wrap {
  position: relative; z-index: 2;
  display: grid; place-items: center;
  padding: .55rem .9rem;
  border-radius: 10px;
  background: var(--surface);
  border: 1px solid rgba(28,24,17,0.18);
}
.xp-logo { display: block; height: 34px; width: auto; max-width: 210px; object-fit: contain; }
/* nebo's mark is a WHITE wordmark on its own cyan, so unlike the other three
   it cannot be keyed -- white on beige would vanish. It keeps that cyan as
   part of the mark and sits in the SAME chip as the others, so every logo box
   measures identically rather than one card being the odd one out. */
.xp-logo-wrap .xp-logo[src*="nebo"] { border-radius: 6px; }

/* nebo's zone is live footage rather than a flat drawing, so its logo chip
   gets a touch more weight to stay readable over moving video. */
.xp-video { object-fit: cover; }
.xp-illu:has(.xp-video) .xp-logo-wrap {
  background: rgba(251,247,240,0.94);
  border-color: rgba(28,24,17,0.28);
}
@media (prefers-reduced-motion: reduce) { .xp-video { display: none; } }

.xp-info { padding: 1.5rem 1.7rem 1.7rem; }
.xp-info .exp-meta { margin-bottom: .85rem; }

@media (max-width: 640px) {
  .xp-logo { height: 26px; max-width: 150px; }
  .xp-info { padding: 1.15rem 1.1rem 1.3rem; }
}

/* Decorative animation: transform/opacity only, all looping. */
@keyframes xpDrift { 0%,100%{transform:translateY(0)}  50%{transform:translateY(-7px)} }
@keyframes xpWave  { from{transform:translateX(0)}     to{transform:translateX(-160px)} }
@keyframes xpWag   { 0%,100%{transform:rotate(-18deg)} 50%{transform:rotate(14deg)} }
@keyframes xpFly   { from{offset-distance:0%}          to{offset-distance:100%} }
@keyframes xpBob   { 0%,100%{transform:translateY(0)}  50%{transform:translateY(-3px)} }

.xp-wave-1 { animation: xpWave 9s linear infinite; }
.xp-wave-2 { animation: xpWave 14s linear infinite; }
.xp-ship   { animation: xpBob 5s ease-in-out infinite; }
.xp-tail   { animation: xpWag .9s ease-in-out infinite; transform-origin: 885px 118px; }
.xp-plane  { offset-path: path("M70 140 Q300 18 500 34 T940 112");
             offset-rotate: auto; animation: xpFly 11s linear infinite; }
.xp-num    { animation: xpDrift 7s ease-in-out infinite; }

@media (prefers-reduced-motion: reduce) {
  .xp-wave-1, .xp-wave-2, .xp-ship, .xp-tail, .xp-plane, .xp-num {
    animation: none !important;
  }
  .xp-plane { offset-distance: 42%; }
}
"""

SHIP = """<svg class="xp-art" viewBox="0 0 1000 170" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
<g class="xp-ship">
<rect x="742" y="52" width="9" height="17" rx="2" fill="#9A3E12"/>
<rect x="716" y="69" width="44" height="12" rx="2" fill="#173A52"/>
<rect x="698" y="81" width="80" height="15" rx="2" fill="#12293D"/>
<path d="M690 96 h96 l-13 15 h-70 z" fill="#12293D"/>
</g>
<g class="xp-wave-2" opacity=".4"><path d="M0 124 q40 -9 80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 v60 H0 z" fill="#2E7DA8"/></g>
<g class="xp-wave-1" opacity=".7"><path d="M0 138 q40 -8 80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 v46 H0 z" fill="#1B5E86"/></g>
</svg>"""

NEBO = """<svg class="xp-art" viewBox="0 0 1000 170" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
<g stroke="#8A8175" stroke-width="3.4" stroke-linecap="round" fill="none" opacity=".75">
<path d="M92 118 v-19 M92 118 l-9 15 M92 118 l9 15 M92 104 l-20 -8 M92 104 l20 -8"/>
<path d="M164 118 v-19 M164 118 l-9 15 M164 118 l9 15 M164 104 l-20 -8 M164 104 l20 -8"/>
<path d="M236 118 v-19 M236 118 l-9 15 M236 118 l9 15 M236 104 l-20 -8 M236 104 l20 -8"/>
<path d="M700 118 v-19 M700 118 l-9 15 M700 118 l9 15 M700 104 l-20 -8 M700 104 l20 -8"/>
<path d="M772 118 v-19 M772 118 l-9 15 M772 118 l9 15 M772 104 l-20 -8 M772 104 l20 -8"/>
</g>
<g fill="#8A8175" opacity=".75">
<circle cx="92" cy="90" r="8"/><circle cx="164" cy="90" r="8"/><circle cx="236" cy="90" r="8"/>
<circle cx="700" cy="90" r="8"/><circle cx="772" cy="90" r="8"/>
</g>
<g>
<path class="xp-tail" d="M885 118 q13 -5 19 -16" stroke="#C08344" stroke-width="4.6" stroke-linecap="round" fill="none"/>
<ellipse cx="864" cy="119" rx="24" ry="15" fill="#D9A05B"/>
<path d="M851 132 v9 M877 132 v9" stroke="#C08344" stroke-width="5" stroke-linecap="round"/>
<circle cx="838" cy="106" r="14" fill="#E0AC69"/>
<path d="M827 96 q-10 -3 -10 10 q9 3 12 -4 z" fill="#C08344"/>
<circle cx="833" cy="104" r="2.1" fill="#3B2A17"/>
<circle cx="843" cy="103" r="2.1" fill="#3B2A17"/>
<circle cx="828" cy="110" r="1.9" fill="#3B2A17"/>
</g>
</svg>"""

OASIS = """<svg class="xp-art" viewBox="0 0 1000 170" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
<circle cx="112" cy="92" r="34" fill="none" stroke="#8A8175" stroke-width="2.2" opacity=".5"/>
<path d="M78 92 h68 M112 58 q18 34 0 68 M112 58 q-18 34 0 68" fill="none" stroke="#8A8175" stroke-width="1.6" opacity=".4"/>
<path d="M70 140 Q300 18 500 34 T940 112" fill="none" stroke="#9A3E12" stroke-width="2.4"
      stroke-linecap="round" stroke-dasharray="7 11" opacity=".6"/>
<g class="xp-plane">
<path d="M-15 0 L15 0 M-4 -10 L7 0 L-4 10 M-11 -6 L-5 0 L-11 6" fill="none"
      stroke="#12293D" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>
</g>
</svg>"""

KUMON = """<svg class="xp-art" viewBox="0 0 1000 170" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
<g font-family="'Bricolage Grotesque',sans-serif" font-weight="800" fill="#8A8175" opacity=".32">
<text class="xp-num" x="60"  y="60"  font-size="34" style="animation-duration:8s;animation-delay:0s">7</text>
<text class="xp-num" x="150" y="130" font-size="28" style="animation-duration:11s;animation-delay:-3s">+</text>
<text class="xp-num" x="248" y="52"  font-size="24" style="animation-duration:9s;animation-delay:-5s">x</text>
<text class="xp-num" x="318" y="136" font-size="22" style="animation-duration:13s;animation-delay:-8s">9</text>
<text class="xp-num" x="660" y="48"  font-size="26" style="animation-duration:10.5s;animation-delay:-4s">=</text>
<text class="xp-num" x="742" y="138" font-size="31" style="animation-duration:12s;animation-delay:-1.5s">3</text>
<text class="xp-num" x="846" y="58"  font-size="35" style="animation-duration:7.5s;animation-delay:-6s">A</text>
<text class="xp-num" x="912" y="132" font-size="29" style="animation-duration:8.5s;animation-delay:-2s">B</text>
</g>
</svg>"""


NEBO_VIDEO = (
    '<video class="xp-art xp-video" muted loop playsinline preload="none" '
    'poster="src/assets/img/nebo-poster.webp" aria-hidden="true" '
    'data-src="src/assets/img/nebo-loop.webm"></video>'
)


def zone(svg, logo, alt, brand=False):
    cls = "xp-logo-wrap"
    return ('<div class="xp-illu">' + svg + '<div class="' + cls + '">'
            '<img class="xp-logo" src="src/assets/logos/' + logo + '.webp" '
            'alt="' + alt + '" decoding="async"></div></div>')


NEBO_CARD = (
    '<div class="experience-card">'
    + zone(NEBO_VIDEO, "nebo", "Nebo Agency")
    + '<div class="xp-info">'
      '<div class="exp-meta">'
      '<span class="exp-tag">Aug 2026 &ndash; Present</span>'
      '<span class="exp-tag">Frontend</span>'
      '</div>'
      '<h3 class="experience-title">Frontend Engineering Intern</h3>'
      '<p class="experience-company">Nebo Agency</p>'
      '<p class="experience-description">Building web pages for clients.</p>'
    '</div></div>'
)


def matching_close(s, start):
    """Index just past the </div> that closes the <div> opening at `start`."""
    depth = 0
    k = s.index('>', start) + 1
    while True:
        nd = s.find('<div', k)
        ne = s.find('</div>', k)
        if ne == -1:
            raise ValueError("unbalanced markup")
        if nd != -1 and nd < ne:
            depth += 1
            k = nd + 4
        else:
            if depth == 0:
                return ne + 6
            depth -= 1
            k = ne + 6


def main():
    s = io.open(P, encoding="utf-8").read()

    # 1. remove the old cruise illustration wholesale -- it carried the black
    #    plaque (background rgba(26,23,20,.95)), a light chip the dark->light
    #    inversion had flipped to near-black.
    i = s.index('<div class="cruise-scene"')
    s = s[:i] + s[matching_close(s, i):]
    print("  removed old cruise-scene block (with its black plaque)")

    # 2. give every existing card the shared zone and wrap its body
    zones = [
        zone(SHIP, "carnival", "Carnival Corporation &amp; plc"),
        zone(OASIS, "oasis", "Oasis"),
        zone(KUMON, "kumon", "Kumon"),
    ]
    n = 0
    while True:
        m = re.search(r'<div class="experience-card[^"]*">', s)
        if not m or n >= 3:
            break
        end = matching_close(s, m.start())
        body = s[m.end():end - 6]
        card = ('<div class="experience-card" data-xp="' + str(n) + '">'
                + zones[n] + '<div class="xp-info">' + body + '</div></div>')
        s = s[:m.start()] + card + s[end:]
        n += 1
    print("  wrapped %d existing cards in the shared component" % n)

    # 3. Nebo is the current role, so it leads (the section is reverse-chron)
    first = s.index('<div class="experience-card"')
    s = s[:first] + NEBO_CARD + s[first:]
    print("  added the Nebo card at the top (Aug 2026 - present)")

    # 4. styles
    s = s.replace("</style>", CSS + "\n</style>", 1)

    io.open(P, "w", encoding="utf-8").write(s)
    print("  wrote index.html")


if __name__ == "__main__":
    main()
