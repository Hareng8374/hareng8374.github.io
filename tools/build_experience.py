# -*- coding: utf-8 -*-
"""Rebuild the Experience section as four cards sharing one component.

Illustration zone + info zone. Every card uses the same 16:9 zone so the two
that carry real footage show the whole frame and the two that carry drawings
still match them exactly.
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
  padding: 0 !important;
}
.experience-card + .experience-card { margin-top: 1.5rem; }
.experience-card::before { display: none !important; }

/* 16:9 on every card. Two of the four are real 16:9 clips, and cropping them
   to a strip threw most of the frame away; matching the zone to the footage
   shows the whole shot AND keeps all four identical. */
.xp-illu {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;   /* no max-height: with aspect-ratio, capping the
                             height makes CSS shrink the WIDTH to keep the
                             ratio, which left the zone narrower than its card */
  background: var(--paper);
  border-bottom: 1px solid rgba(28,24,17,0.18);
  display: grid;
  place-items: center;
  overflow: hidden;
}
.xp-art { position: absolute; inset: 0; width: 100%; height: 100%; z-index: 1; }
.xp-video { object-fit: cover; }

/* Identical logo box on all four; height is what the eye compares. */
.xp-logo-wrap {
  position: relative; z-index: 2;
  display: grid; place-items: center;
  padding: .6rem 1rem;
  border-radius: 10px;
  background: rgba(251,247,240,0.95);
  border: 1px solid rgba(28,24,17,0.30);
  box-shadow: 0 2px 10px rgba(28,24,17,0.08);
}
.xp-logo { display: block; height: 38px; width: auto; max-width: 220px; object-fit: contain; }
.xp-logo-wrap .xp-logo[src*="nebo"] { border-radius: 6px; }

.xp-info { padding: 1.6rem 1.8rem 1.8rem; }
.xp-info .exp-meta { margin-bottom: .9rem; }

/* Every chip and panel in the section carries the same block border. */
.experience-card .exp-tag,
.experience-card .highlight,
.experience-card .cruise-stat {
  border: 1px solid rgba(28,24,17,0.30) !important;
  border-radius: 8px !important;
  background: var(--paper) !important;
}
.experience-card .highlight { padding: .95rem 1.15rem !important; }
.experience-card .cruise-stat { padding: 1rem 1.1rem !important; }

/* Emphasis inside the write-ups is solid black, not a tint. */
.experience-card strong,
.experience-card b,
.experience-card .highlight strong,
.experience-card .experience-description strong {
  color: #000 !important;
  font-weight: 700 !important;
}

@media (max-width: 640px) {
  .xp-logo { height: 26px; max-width: 150px; }
  .xp-info { padding: 1.15rem 1.1rem 1.3rem; }
  .experience-card .highlight { padding: .8rem .9rem !important; }
}

/* Decorative animation: transform/opacity only, all looping. */
@keyframes xpDrift { 0%,100%{transform:translateY(0)}   50%{transform:translateY(-9px)} }
@keyframes xpWave  { from{transform:translateX(0)}      to{transform:translateX(-200px)} }
@keyframes xpWag   { 0%,100%{transform:rotate(-18deg)}  50%{transform:rotate(14deg)} }
@keyframes xpBob   { 0%,100%{transform:translateY(0)}   50%{transform:translateY(-5px)} }
@keyframes xpGlow  { 0%,100%{opacity:.20; transform:scale(1)} 50%{opacity:.34; transform:scale(1.06)} }
@keyframes xpGull  { 0%{transform:translate(0,0)} 50%{transform:translate(40px,-10px)} 100%{transform:translate(80px,0)} }

.xp-wave-1 { animation: xpWave 11s linear infinite; }
.xp-wave-2 { animation: xpWave 17s linear infinite; }
.xp-ship   { animation: xpBob 6s ease-in-out infinite; }
.xp-sun    { animation: xpGlow 7s ease-in-out infinite; transform-origin: 190px 150px; }
.xp-gull   { animation: xpGull 14s ease-in-out infinite alternate; }
.xp-num    { animation: xpDrift 8s ease-in-out infinite; }

@media (prefers-reduced-motion: reduce) {
  .xp-wave-1, .xp-wave-2, .xp-ship, .xp-sun, .xp-gull, .xp-num {
    animation: none !important;
  }
  .xp-video { display: none; }
}
"""

# A full seascape: graded sky, sun with a soft corona, clouds, gulls, a proper
# liner with portholes and a red boot-topping, and light glinting on the water.
SHIP = (
 '<svg class="xp-art" viewBox="0 0 1000 562" preserveAspectRatio="xMidYMid slice" aria-hidden="true">'
 '<defs>'
 '<linearGradient id="xpSky" x1="0" y1="0" x2="0" y2="1">'
 '<stop offset="0" stop-color="#BBD9EC"/><stop offset="52%" stop-color="#E4EFF2"/>'
 '<stop offset="100%" stop-color="#F7EFE0"/></linearGradient>'
 '<linearGradient id="xpSea" x1="0" y1="0" x2="0" y2="1">'
 '<stop offset="0" stop-color="#5AA6C8"/><stop offset="55%" stop-color="#2C6E93"/>'
 '<stop offset="100%" stop-color="#123D5A"/></linearGradient>'
 '</defs>'
 '<rect width="1000" height="562" fill="url(#xpSky)"/>'
 '<g class="xp-sun"><circle cx="190" cy="150" r="92" fill="#F2C25C" opacity=".16"/>'
 '<circle cx="190" cy="150" r="62" fill="#F2C25C" opacity=".26"/></g>'
 '<circle cx="190" cy="150" r="40" fill="#F6CE72"/>'
 '<g fill="#FFFFFF" opacity=".8">'
 '<ellipse cx="470" cy="104" rx="66" ry="21"/><ellipse cx="516" cy="92" rx="46" ry="17"/>'
 '<ellipse cx="800" cy="150" rx="54" ry="17"/><ellipse cx="836" cy="140" rx="38" ry="13"/>'
 '</g>'
 '<g class="xp-gull" stroke="#5C6B75" stroke-width="2.6" fill="none" stroke-linecap="round" opacity=".7">'
 '<path d="M600 128 q10 -9 20 0 M620 128 q10 -9 20 0"/>'
 '<path d="M668 96 q8 -7 16 0 M684 96 q8 -7 16 0"/>'
 '</g>'
 '<g class="xp-ship">'
 '<rect x="726" y="212" width="16" height="34" rx="4" fill="#B4451F"/>'
 '<rect x="729" y="212" width="10" height="12" rx="3" fill="#F7F3EA"/>'
 '<rect x="684" y="246" width="86" height="22" rx="4" fill="#F4F1E8"/>'
 '<rect x="656" y="268" width="142" height="28" rx="4" fill="#FBF8F1"/>'
 '<g fill="#4E9AC0">'
 '<circle cx="678" cy="282" r="4"/><circle cx="702" cy="282" r="4"/><circle cx="726" cy="282" r="4"/>'
 '<circle cx="750" cy="282" r="4"/><circle cx="774" cy="282" r="4"/></g>'
 '<path d="M644 296 h166 l-24 32 h-118 z" fill="#12293D"/>'
 '<rect x="644" y="296" width="166" height="7" fill="#B4451F"/>'
 '</g>'
 '<g class="xp-wave-2" opacity=".6"><path d="M0 352 q50 -14 100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 v230 H0 z" fill="url(#xpSea)"/></g>'
 '<g class="xp-wave-1"><path d="M0 392 q50 -13 100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 v190 H0 z" fill="url(#xpSea)"/></g>'
 '<g stroke="#FFFFFF" stroke-width="4" stroke-linecap="round" opacity=".28">'
 '<path d="M150 430 h80"/><path d="M118 462 h130"/><path d="M176 492 h72"/>'
 '<path d="M560 448 h60"/><path d="M600 480 h96"/></g>'
 '</svg>'
)

# Bubble arithmetic: thick outline behind a soft fill via paint-order, in a
# restrained palette that still reads as "colourful" without shouting.
_K = [
 ("7",   96, 118, 76, "#E8A33D", "#8A5A17", 8.0,  "0s"),
 ("+",  208, 300, 62, "#5AA9C9", "#1F5A74", 7.0,  "-3s"),
 ("x",  118, 452, 54, "#C4744C", "#7A3A1C", 6.4,  "-5s"),
 ("9",  322, 500, 60, "#8FA860", "#4C5F2C", 7.0,  "-8s"),
 ("=",  700, 128, 58, "#5AA9C9", "#1F5A74", 6.8,  "-4s"),
 ("3",  842, 268, 74, "#E8A33D", "#8A5A17", 8.0,  "-1.5s"),
 ("A",  902, 452, 78, "#C4744C", "#7A3A1C", 8.4,  "-6s"),
 ("B",  686, 498, 64, "#8FA860", "#4C5F2C", 7.2,  "-2s"),
 ("5",  372, 118, 50, "#5AA9C9", "#1F5A74", 6.0,  "-10s"),
 ("-",  788, 372, 48, "#8FA860", "#4C5F2C", 5.6,  "-7s"),
]
KUMON = (
 '<svg class="xp-art" viewBox="0 0 1000 562" preserveAspectRatio="xMidYMid slice" aria-hidden="true">'
 '<g font-family="\'Bricolage Grotesque\',sans-serif" font-weight="800" text-anchor="middle"'
 ' stroke-linejoin="round" paint-order="stroke fill">'
 + "".join(
     '<text class="xp-num" x="%d" y="%d" font-size="%d" fill="%s" stroke="%s" stroke-width="%s"'
     ' style="animation-duration:%ss;animation-delay:%s">%s</text>'
     % (x, y, sz, fill, st, sw, 7 + i * 0.7, delay, ch)
     for i, (ch, x, y, sz, fill, st, sw, delay) in enumerate(_K))
 + '</g></svg>'
)

NEBO_VIDEO = (
 '<video class="xp-art xp-video" muted loop playsinline preload="none"'
 ' poster="src/assets/img/nebo-poster.webp" aria-hidden="true"'
 ' data-src="src/assets/img/nebo-loop.webm"></video>'
)
OASIS_VIDEO = (
 '<video class="xp-art xp-video" muted loop playsinline preload="none"'
 ' poster="src/assets/img/oasis-poster.webp" aria-hidden="true"'
 ' data-src="src/assets/img/oasis-loop.webm"></video>'
)


def zone(art, logo, alt):
    return ('<div class="xp-illu">' + art
            + '<div class="xp-logo-wrap"><img class="xp-logo" '
              'src="src/assets/logos/' + logo + '.webp" alt="' + alt + '" '
              'decoding="async"></div></div>')


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
    """Index just past the </div> closing the <div> that opens at `start`."""
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

    # Drop the old cruise illustration wholesale -- it carried the black plaque
    # (background rgba(26,23,20,.95)), a light chip the dark->light inversion
    # had flipped to near-black.
    i = s.index('<div class="cruise-scene"')
    s = s[:i] + s[matching_close(s, i):]
    print("  removed old cruise-scene block")

    zones = [
        zone(SHIP, "carnival", "Carnival Corporation &amp; plc"),
        zone(OASIS_VIDEO, "oasis", "Oasis"),
        zone(KUMON, "kumon", "Kumon"),
    ]
    n = 0
    while n < 3:
        m = re.search(r'<div class="experience-card[^"]*">', s)
        if not m:
            break
        end = matching_close(s, m.start())
        body = s[m.end():end - 6]
        s = (s[:m.start()]
             + '<div class="experience-card" data-xp="' + str(n) + '">'
             + zones[n] + '<div class="xp-info">' + body + '</div></div>'
             + s[end:])
        n += 1
    print("  wrapped %d existing cards" % n)

    first = s.index('<div class="experience-card"')
    s = s[:first] + NEBO_CARD + s[first:]
    print("  added the Nebo card at the top")

    s = s.replace("</style>", CSS + "\n</style>", 1)
    io.open(P, "w", encoding="utf-8").write(s)
    print("  wrote index.html")


if __name__ == "__main__":
    main()
