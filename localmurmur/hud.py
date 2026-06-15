from .log import _log

try:
    from AppKit import (
        NSPanel, NSWindowStyleMaskBorderless, NSBackingStoreBuffered,
        NSColor, NSTextField, NSFont, NSView,
        NSScreen, NSVisualEffectView,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
    )
    from Foundation import NSMakeRect
    HAS_HUD = True
except Exception as e:
    _log(f"AppKit import error: {e}"); HAS_HUD = False


# ── Persistent floating pill  (always visible — like Wispr Flow) ──────────────
#
#  Idle      →  small pill  "● Local Murmur"   positioned just above dock
#  Recording →  full pill   "● Listening…"   expands on hotkey press
#  Done      →  briefly shows "● Done"       then shrinks back to idle
#
class FloatingHUD:
    # Flush with dock top edge — no gap, just like Wispr Flow
    _MARGIN  = 0
    _DOT_SZ  = 8   # CALayer circle diameter (no font clipping possible)

    _STATES = {
        "idle":         ( 36, 24, 12, (0.78, 0.78, 0.90), "",              12),
        "recording":    (178, 34, 17, (1.00, 0.27, 0.23), "Listening…",    12),
        "transcribing": (188, 34, 17, (0.04, 0.52, 1.00), "Transcribing…", 12),
        "done":         ( 76, 34, 17, (0.19, 0.82, 0.35), "Done",          12),
    }

    # ── helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _pill_y(*_) -> float:
        """Sit at the very screen bottom like Wispr Flow — level 1000 keeps
        the pill visually above the dock regardless of dock state."""
        return 2

    @staticmethod
    def _pill_x(w: float) -> float:
        return (NSScreen.mainScreen().frame().size.width - w) / 2

    # ── init / build ───────────────────────────────────────────────────────────
    def __init__(self):
        self._panel = self._vfx = self._dot_v = self._text_f = None
        self._cur = None
        if not HAS_HUD: return
        try:   self._build()
        except Exception as e: _log(f"FloatingHUD init: {e}")

    def _build(self):
        w, h, r, *_ = self._STATES["idle"]
        _NOACT = 128   # NSWindowStyleMaskNonactivatingPanel

        self._panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(self._pill_x(w), self._pill_y(h), w, h),
            NSWindowStyleMaskBorderless | _NOACT,
            NSBackingStoreBuffered, False)
        self._panel.setLevel_(1000)
        self._panel.setOpaque_(False)
        self._panel.setHasShadow_(False)
        self._panel.setBackgroundColor_(NSColor.clearColor())
        self._panel.setIgnoresMouseEvents_(True)
        self._panel.setHidesOnDeactivate_(False)
        self._panel.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces)

        # Frosted glass pill body
        self._vfx = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
        self._vfx.setMaterial_(13)
        self._vfx.setBlendingMode_(0)
        self._vfx.setState_(1)
        self._vfx.setWantsLayer_(True)
        self._vfx.layer().setCornerRadius_(r)
        self._vfx.layer().setMasksToBounds_(True)
        self._panel.setContentView_(self._vfx)

        # Dot — NSView with circular CALayer (no font-metric clipping)
        ds = self._DOT_SZ
        self._dot_v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, ds, ds))
        self._dot_v.setWantsLayer_(True)
        self._dot_v.layer().setCornerRadius_(ds / 2)
        self._dot_v.layer().setBackgroundColor_(
            NSColor.colorWithWhite_alpha_(0.85, 1.0).CGColor())
        self._vfx.addSubview_(self._dot_v)

        # Text label for active states
        self._text_f = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 1))
        self._text_f.setEditable_(False)
        self._text_f.setBordered_(False)
        self._text_f.setDrawsBackground_(False)
        self._text_f.setTextColor_(NSColor.colorWithWhite_alpha_(0.95, 1.0))
        self._text_f.setFont_(NSFont.boldSystemFontOfSize_(12))
        self._text_f.setStringValue_("")
        self._vfx.addSubview_(self._text_f)
        _log("FloatingHUD: built OK")

    # ── layout ─────────────────────────────────────────────────────────────────
    def _layout(self, w: int, h: int, has_text: bool):
        ds = self._DOT_SZ
        if has_text:
            # Dot on left, vertically centred
            self._dot_v.setFrame_(NSMakeRect(12, (h - ds) / 2, ds, ds))
            # Text fills remaining width
            txt_y = (h - 15) / 2
            self._text_f.setFrame_(NSMakeRect(26, txt_y, w - 34, 16))
        else:
            # Idle: dot precisely centred in pill — pixel-perfect circle
            self._dot_v.setFrame_(NSMakeRect((w - ds) / 2, (h - ds) / 2, ds, ds))
            self._text_f.setFrame_(NSMakeRect(0, 0, 0, 0))

    def _set_size(self, w: int, h: int, r: int):
        self._panel.setFrame_display_(
            NSMakeRect(self._pill_x(w), self._pill_y(h), w, h), True)
        self._vfx.setFrame_(NSMakeRect(0, 0, w, h))
        self._vfx.layer().setCornerRadius_(r)

    # ── public ─────────────────────────────────────────────────────────────────
    def update(self, state: str):
        if not self._panel: return
        self._panel.orderFrontRegardless()
        if state == self._cur: return
        self._cur = state
        try:
            w, h, r, rgb, txt, *_ = self._STATES.get(state, self._STATES["idle"])
            has_text = bool(txt)

            self._set_size(w, h, r)
            self._layout(w, h, has_text)

            # Colour the CALayer dot
            self._dot_v.layer().setBackgroundColor_(
                NSColor.colorWithRed_green_blue_alpha_(
                    rgb[0], rgb[1], rgb[2], 1.0).CGColor())

            self._text_f.setStringValue_(txt)
            self._panel.setAlphaValue_(0.62 if state == "idle" else 1.0)
            _log(f"FloatingHUD → {state}")
        except Exception as e:
            _log(f"FloatingHUD.update: {e}")

    def sync_position(self):
        """Called every 50 ms.  Forces the pill to stay pinned to the dock
        top edge at all times — including when the dock auto-hides/shows.
        Uses visibleFrame which macOS updates when dock visibility changes."""
        if not self._panel or not self._cur: return
        try:
            w, h, *_ = self._STATES.get(self._cur, self._STATES["idle"])
            target_y = self._pill_y(h)
            cur_y    = self._panel.frame().origin.y
            if abs(cur_y - target_y) > 0.5:
                # Smooth animation so pill follows dock slide-up / slide-down
                self._panel.setFrame_display_animate_(
                    NSMakeRect(self._pill_x(w), target_y, w, h), True, True)
                _log(f"HUD repositioned: y {cur_y:.0f}→{target_y:.0f}")
        except Exception as e:
            _log(f"FloatingHUD.sync_position: {e}")

    def keep_visible(self):
        """Heartbeat — re-raises pill every 500 ms."""
        if self._panel:
            self._panel.orderFrontRegardless()
