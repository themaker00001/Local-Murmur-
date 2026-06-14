#!/usr/bin/env python3
"""
Generates the DMG installer background PNG for Local Flow.
Requires: pip install Pillow
Output: dmg_background.png  (660 x 400 px)
"""

import sys
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("Run:  pip3 install Pillow")

W, H = 660, 400

# ── Colours ───────────────────────────────────────────────────────────────────
BG          = (18, 18, 20)        # near-black
CARD        = (30, 30, 33)        # card surface
ACCENT      = (250, 185, 0)       # amber — mic icon colour
TEXT_H      = (245, 245, 247)     # headline white
TEXT_S      = (140, 140, 148)     # secondary grey
ARROW       = (70, 70, 78)        # muted arrow
DIVIDER     = (45, 45, 50)        # subtle divider
PILL_BG     = (28, 28, 32, 220)   # HUD pill (semi-transparent)

img  = Image.new("RGB", (W, H), BG)
draw = ImageDraw.Draw(img, "RGBA")

# ── Background gradient suggestion (subtle top-to-bottom) ────────────────────
for y in range(H):
    alpha = int(10 * (1 - y / H))
    draw.line([(0, y), (W, y)], fill=(255, 255, 255, alpha))

# ── Divider line (centre) ────────────────────────────────────────────────────
cx = W // 2
draw.line([(cx, 60), (cx, H - 60)], fill=DIVIDER, width=1)

# ── Left side — app icon placeholder ─────────────────────────────────────────
icon_cx, icon_cy = cx // 2, 155
r = 56

# Glow ring
for dr in range(20, 0, -1):
    glow_alpha = int(4 * dr)
    draw.ellipse(
        [icon_cx - r - dr, icon_cy - r - dr,
         icon_cx + r + dr, icon_cy + r + dr],
        fill=(250, 185, 0, glow_alpha))

# Icon circle background
draw.ellipse(
    [icon_cx - r, icon_cy - r, icon_cx + r, icon_cy + r],
    fill=(35, 32, 20))

# Mic body
mw, mh = 22, 32
mx, my = icon_cx - mw // 2, icon_cy - mh // 2 - 4
draw.rounded_rectangle([mx, my, mx + mw, my + mh], radius=11, fill=ACCENT)

# Mic stand
sx = icon_cx
draw.line([(sx, my + mh), (sx, my + mh + 12)], fill=ACCENT, width=3)
draw.line([(sx - 12, my + mh + 12), (sx + 12, my + mh + 12)],
          fill=ACCENT, width=3)

# App name
try:
    font_big  = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 22)
    font_mid  = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 13)
    font_sm   = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 11)
except Exception:
    font_big = font_mid = font_sm = ImageFont.load_default()

draw.text((icon_cx, icon_cy + r + 20), "Local Flow",
          fill=TEXT_H, font=font_big, anchor="mm")
draw.text((icon_cx, icon_cy + r + 44), "Voice dictation. Local. Private.",
          fill=TEXT_S, font=font_mid, anchor="mm")

# ── Arrow ─────────────────────────────────────────────────────────────────────
ax, ay = cx + 2, H // 2 - 10
for i, ch in enumerate(["▸", "▸", "▸"]):
    alpha = 80 + i * 60
    draw.text((ax + i * 16, ay), ch, fill=(*ARROW, alpha), font=font_big,
              anchor="mm")

# ── Right side — Applications folder ─────────────────────────────────────────
fcx, fcy = cx + cx // 2, 155

# Folder body
fw, fh = 80, 60
fx, fy = fcx - fw // 2, fcy - fh // 2
draw.rounded_rectangle([fx, fy, fx + fw, fy + fh], radius=8,
                        fill=(55, 60, 80))
# Folder tab
draw.rounded_rectangle([fx, fy - 14, fx + 34, fy + 4], radius=4,
                        fill=(65, 70, 95))
# Folder shine
draw.rounded_rectangle([fx + 4, fy + 4, fx + fw - 4, fy + 20], radius=4,
                        fill=(75, 80, 110))

draw.text((fcx, fcy + fh // 2 + 20), "Applications",
          fill=TEXT_H, font=font_big, anchor="mm")
draw.text((fcx, fcy + fh // 2 + 44), "Drag here to install",
          fill=TEXT_S, font=font_mid, anchor="mm")

# ── Floating HUD preview (bottom centre) ─────────────────────────────────────
hw, hh = 240, 34
hx, hy = (W - hw) // 2, H - hh - 24
draw.rounded_rectangle([hx, hy, hx + hw, hy + hh],
                        radius=17, fill=PILL_BG)
draw.text((hx + 16, hy + hh // 2), "🔴",
          fill=(255, 255, 255, 220), font=font_mid, anchor="lm")
draw.text((hx + 42, hy + hh // 2), "Recording…    Hold ⌥  release to send",
          fill=(200, 200, 205, 200), font=font_sm, anchor="lm")

# ── Version badge ─────────────────────────────────────────────────────────────
draw.text((W - 16, H - 14), "v1.1.0",
          fill=TEXT_S, font=font_sm, anchor="rm")

# ── Save ──────────────────────────────────────────────────────────────────────
out = "dmg_background.png"
img.save(out, "PNG", dpi=(144, 144))
print(f"✅  Saved {out}  ({W}×{H} px)")
