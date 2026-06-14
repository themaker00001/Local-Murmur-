#!/usr/bin/env python3.13
"""
Local Flow — Voice Dictation for Apple Silicon
- rumps menu bar  (Cocoa NSRunLoop)
- NSVisualEffectView frosted-glass HUD  (no emoji, coloured dot)
- WKWebView settings panel  (monochrome, accent picker, hotkey picker, mic test)
- Keyboard monitoring via system-Python subprocess + pynput  (user-configurable key)
- whisper.cpp Metal for transcription
"""

import subprocess, threading, tempfile, warnings
warnings.filterwarnings("ignore", ".*ObjCPointer.*")   # suppress CGColor C-pointer noise

_LF_LOG = open('/tmp/lf_bundle.log', 'w', buffering=1)
def _log(msg: str):
    try: _LF_LOG.write(msg + '\n'); _LF_LOG.flush()
    except Exception: pass
_log("=== flow.py loaded ===")

import os, sys, time, json, queue, signal, urllib.request
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    _bundle_dir = Path(sys._MEIPASS)
    WHISPER_BIN   = _bundle_dir / "whisper-cli"
else:
    WHISPER_BIN   = Path.home() / "whisper.cpp" / "build" / "bin" / "whisper-cli"
WHISPER_LANG    = "en"
WHISPER_THREADS = 8

# ── Models ───────────────────────────────────────────────────────────────────
# Models are downloaded on demand (not bundled) — keeps the app small and lets
# users pick the speed/accuracy tradeoff that fits their Mac.
MODELS_DIR        = Path.home() / "Library" / "Application Support" / "Local Flow" / "models"
_LEGACY_MODELS_DIR = Path.home() / "whisper.cpp" / "models"   # from older Setup.sh runs
MODEL_BASE_URL    = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"

MODEL_CATALOG = [
    {"id": "tiny",           "file": "ggml-tiny.bin",           "size_mb": 75,
     "label": "Tiny",           "speed": "Fastest",  "accuracy": "Basic",
     "desc": "Smallest download. Good for quick English notes."},
    {"id": "base",           "file": "ggml-base.bin",           "size_mb": 142,
     "label": "Base",           "speed": "Very fast","accuracy": "Good",
     "desc": "Light and snappy for everyday dictation."},
    {"id": "small",          "file": "ggml-small.bin",          "size_mb": 466,
     "label": "Small",          "speed": "Fast",     "accuracy": "Great",
     "desc": "Best balance of speed and accuracy. Recommended."},
    {"id": "medium",         "file": "ggml-medium.bin",         "size_mb": 1500,
     "label": "Medium",         "speed": "Moderate", "accuracy": "Excellent",
     "desc": "Best for Hinglish & mixed-language speech."},
    {"id": "large-v3-turbo", "file": "ggml-large-v3-turbo.bin", "size_mb": 1620,
     "label": "Large v3 Turbo", "speed": "Fast",     "accuracy": "Excellent",
     "desc": "Large-model accuracy at small-model speed."},
    {"id": "large-v3",       "file": "ggml-large-v3.bin",       "size_mb": 3100,
     "label": "Large v3",       "speed": "Slow",     "accuracy": "Best",
     "desc": "Top accuracy across every language. Big download."},
]
_MODEL_BY_ID     = {m["id"]: m for m in MODEL_CATALOG}
DEFAULT_MODEL_ID = "small"

def _model_path(model_id: str) -> Path:
    m = _MODEL_BY_ID.get(model_id, _MODEL_BY_ID[DEFAULT_MODEL_ID])
    p = MODELS_DIR / m["file"]
    if p.exists(): return p
    legacy = _LEGACY_MODELS_DIR / m["file"]
    return legacy if legacy.exists() else p

def _model_downloaded(model_id: str) -> bool:
    m = _MODEL_BY_ID.get(model_id)
    if not m: return False
    return (MODELS_DIR / m["file"]).exists() or (_LEGACY_MODELS_DIR / m["file"]).exists()

def _model_status() -> dict:
    return {m["id"]: {"downloaded": _model_downloaded(m["id"]),
                       "active": m["id"] == MODEL_ID} for m in MODEL_CATALOG}

MODEL_ID      = DEFAULT_MODEL_ID
WHISPER_MODEL = _model_path(MODEL_ID)

OLLAMA_MODEL    = "llama3.2"
OLLAMA_URL      = "http://localhost:11434/api/generate"
USE_LLM_CLEANUP = False
SOUND_START     = True
ACCENT_COLOR    = "#FFFFFF"
HOTKEY          = "alt_r"          # pynput key name

# Human-readable labels for each key option shown in settings
HOTKEY_LABELS = {
    "alt_r":   ("Right Option",  "⌥"),
    "cmd_r":   ("Right Command", "⌘"),
    "ctrl_r":  ("Right Control", "^"),
    "shift_r": ("Right Shift",   "⇧"),
    "f13":     ("F13",           "F13"),
    "f14":     ("F14",           "F14"),
}
# ─────────────────────────────────────────────────────────────────────────────

try:
    import sounddevice as sd
    import numpy as np
except ImportError:
    sys.exit("Missing: pip install sounddevice numpy")

try:
    import rumps
except ImportError:
    sys.exit("Missing: pip install rumps")

try:
    from AppKit import (
        NSPanel, NSWindow, NSWindowStyleMaskBorderless, NSBackingStoreBuffered,
        NSColor, NSTextField, NSFont, NSView,
        NSScreen, NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
        NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskResizable,
        NSVisualEffectView,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
    )
    from Foundation import NSMakeRect, NSObject, NSURL
    HAS_HUD = True
except Exception as e:
    _log(f"AppKit import error: {e}"); HAS_HUD = False

try:
    from WebKit import WKWebView, WKWebViewConfiguration, WKUserContentController
    HAS_WEBVIEW = True
except Exception as e:
    _log(f"WebKit import error: {e}"); HAS_WEBVIEW = False

SAMPLE_RATE  = 16000
recording    = False
audio_buf    = []
lock         = threading.Lock()
_target_app  = ""
_ui_queue    = queue.Queue()
_app         = None
_kbd_proc    = None          # current pynput subprocess

# ── Settings ──────────────────────────────────────────────────────────────────
_SETTINGS_PATH = Path.home() / ".localflow" / "settings.json"

def _load_settings():
    global USE_LLM_CLEANUP, SOUND_START, ACCENT_COLOR, HOTKEY, MODEL_ID, WHISPER_MODEL
    try:
        if _SETTINGS_PATH.exists():
            d = json.loads(_SETTINGS_PATH.read_text())
            USE_LLM_CLEANUP = bool(d.get("use_llm_cleanup", USE_LLM_CLEANUP))
            SOUND_START     = bool(d.get("sound_start",     SOUND_START))
            ACCENT_COLOR    = str(d.get("accent_color",     ACCENT_COLOR))
            k               = str(d.get("hotkey",           HOTKEY))
            if k in HOTKEY_LABELS: HOTKEY = k
            mid             = str(d.get("model_id",         MODEL_ID))
            if mid in _MODEL_BY_ID: MODEL_ID = mid
        elif (_LEGACY_MODELS_DIR / "ggml-medium.bin").exists():
            # Fresh install, but an older Setup.sh already downloaded "medium" — use it.
            MODEL_ID = "medium"
    except Exception as e:
        _log(f"_load_settings: {e}")
    WHISPER_MODEL = _model_path(MODEL_ID)

def _save_settings():
    try:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_PATH.write_text(json.dumps({
            "use_llm_cleanup": USE_LLM_CLEANUP,
            "sound_start":     SOUND_START,
            "accent_color":    ACCENT_COLOR,
            "hotkey":          HOTKEY,
            "model_id":        MODEL_ID,
        }, indent=2))
    except Exception as e:
        _log(f"_save_settings: {e}")

_load_settings()

# ── History ───────────────────────────────────────────────────────────────────
_history = []

def _add_history(text: str):
    _history.insert(0, {"time": time.strftime("%H:%M"), "text": text})
    if len(_history) > 200: _history.pop()


# ── Persistent floating pill  (always visible — like Wispr Flow) ──────────────
#
#  Idle      →  small pill  "● Local Flow"   positioned just above dock
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


# ── Settings HTML  ────────────────────────────────────────────────────────────
# Written to a temp file so WKWebView gets a file:// origin — required for
# both window.webkit.messageHandlers and navigator.mediaDevices.getUserMedia.

_SETTINGS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
:root {
  --bg:         #000000;
  --sidebar:    #000000;
  --surface:    #1A1A1A;
  --surface2:   #1A1A1A;
  --border:     #1E1E1E;
  --border2:    #2A2A2A;
  --text:       #ECECEC;
  --muted:      #8E8E8E;
  --muted2:     #555555;
  --accent:     #FFFFFF;
  --accent-rgb: 255 255 255;
}
*, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif;
  background: var(--bg); color: var(--text);
  height: 100vh; display: flex; overflow: hidden;
  -webkit-user-select: none; cursor: default; font-size: 13.5px;
}

/* ── Sidebar ──── */
.sidebar {
  width: 192px; background: var(--sidebar);
  border-right: 1px solid var(--border);
  display: flex; flex-direction: column; flex-shrink: 0;
}
.app-header {
  display: flex; align-items: center; gap: 11px;
  padding: 22px 16px 18px; border-bottom: 1px solid var(--border);
}
.app-icon { width: 28px; height: 28px; flex-shrink: 0; }
.app-icon svg { display: block; width: 100%; height: 100%; border-radius: 6px; }
.app-name { font-size: 14px; font-weight: 600; color: var(--text); letter-spacing: -.2px; }
.app-ver  { font-size: 11px; color: var(--muted); margin-top: 2px; }

nav { padding: 6px; flex: 1; }
.nav-item {
  display: flex; align-items: center; gap: 9px;
  padding: 8px 12px; border-radius: 8px;
  color: var(--muted); cursor: pointer;
  transition: background .13s, color .13s; margin-bottom: 2px;
}
.nav-item:hover { background: rgba(255,255,255,.05); color: var(--text); }
.nav-item.active { background: rgb(var(--accent-rgb)/.14); color: var(--accent); }
.nav-item.active .ni { color: var(--accent); }
.ni { width: 18px; text-align: center; font-size: 14px; }

/* ── Content ──── */
.content { flex: 1; overflow-y: auto; padding: 28px 32px 28px; }
.content::-webkit-scrollbar { width: 4px; }
.content::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 2px; }

.page-title { font-size: 21px; font-weight: 700; letter-spacing: -.4px; margin-bottom: 5px; color: #F0F0F0; }
.page-sub   { font-size: 12.5px; color: var(--muted); margin-bottom: 22px; line-height: 1.55; }

/* Status pill */
.status-pill {
  display: inline-flex; align-items: center; gap: 8px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 100px; padding: 7px 16px 7px 10px; margin-bottom: 22px; color: var(--muted);
}
.dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--muted2); transition: background .3s, box-shadow .3s; flex-shrink: 0;
}
.dot.recording    { background:#FF453A; box-shadow: 0 0 7px #FF453A88; }
.dot.transcribing { background:#0A84FF; box-shadow: 0 0 7px #0A84FF88; }
.dot.done         { background:#30D158; box-shadow: 0 0 7px #30D15888; }

.sec { font-size: 10.5px; font-weight: 600; letter-spacing: .9px; text-transform: uppercase; color: var(--muted); margin-bottom: 10px; }

/* Chips */
.chip-row { display: flex; gap: 8px; align-items: center; margin-bottom: 22px; flex-wrap: wrap; }
.chip { display: inline-flex; align-items: center; padding: 6px 14px; border-radius: 8px; font-size: 13px; font-weight: 500; }
.chip.accent { background: var(--accent); color: #000; }
.chip.muted  { background: var(--surface2); border: 1px solid var(--border2); color: var(--muted); }

/* Hotkey picker */
.key-grid { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 22px; }
.key-opt {
  padding: 10px 16px; border-radius: 10px; font-size: 13px; font-weight: 500;
  background: #141414; border: 1px solid #2A2A2A;
  color: var(--muted); cursor: pointer; transition: all .13s;
  display: flex; flex-direction: column; align-items: center; gap: 3px; min-width: 72px;
}
.key-opt:hover { background: #202020; border-color: #3A3A3A; color: var(--text); }
.key-opt.selected { background: #202020; border-color: var(--text); color: var(--text); }
.key-sym  { font-size: 18px; line-height: 1; }
.key-name { font-size: 10.5px; color: inherit; opacity: .8; }

.divider { height: 1px; background: var(--border); margin: 20px 0; }

/* Toggle group */
.tgroup { border-radius: 12px; overflow: hidden; border: 1px solid #1E1E1E; }
.trow {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 18px; background: #141414; border-bottom: 1px solid #1E1E1E; gap: 16px;
}
.trow:last-child { border-bottom: none; }
.tlabel { font-size: 14px; color: var(--text); font-weight: 500; }
.tdesc  { font-size: 12px; color: var(--muted); margin-top: 3px; }
.sw { position: relative; width: 44px; height: 26px; flex-shrink: 0; }
.sw input { opacity: 0; width: 0; height: 0; }
.track {
  position: absolute; inset: 0; background: #2A2A2A; border-radius: 13px;
  cursor: pointer; transition: background .2s;
}
.track::after {
  content: ''; position: absolute; top: 3px; left: 3px;
  width: 20px; height: 20px; background: #fff; border-radius: 50%;
  transition: transform .2s; box-shadow: 0 1px 4px rgba(0,0,0,.5);
}
.sw input:checked ~ .track { background: var(--accent); }
.sw input:checked ~ .track::after { transform: translateX(18px); background: #111; }

/* Info rows */
.igroup { border-radius: 12px; overflow: hidden; border: 1px solid #1E1E1E; }
.irow {
  display: flex; align-items: center; padding: 14px 18px;
  background: #141414; border-bottom: 1px solid #1E1E1E;
}
.irow:last-child { border-bottom: none; }
.ikey { width: 130px; font-size: 13px; color: var(--muted); }
.ival { font-size: 13px; color: var(--text); font-family: "SF Mono","Menlo",monospace; }

/* Appearance swatches */
.swatch-grid { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 22px; }
.swatch {
  width: 34px; height: 34px; border-radius: 50%;
  cursor: pointer; border: 2.5px solid transparent;
  transition: transform .14s, border-color .14s;
  display: flex; align-items: center; justify-content: center; font-size: 14px;
}
.swatch:hover { transform: scale(1.12); }
.swatch.selected { border-color: var(--text); }
.swatch-check { display: none; }
.swatch.selected .swatch-check { display: block; }

/* Models */
.setup-banner {
  background: rgb(var(--accent-rgb)/.08); border: 1px solid rgb(var(--accent-rgb)/.2);
  border-radius: 12px; padding: 14px 16px; font-size: 13px; color: var(--text);
  line-height: 1.6; margin-bottom: 22px;
}
.model-list { display: flex; flex-direction: column; gap: 10px; }
.model-card {
  background: #141414; border: 1px solid #1E1E1E; border-radius: 12px;
  padding: 14px 16px;
}
.model-card.active { border-color: var(--accent); }
.mc-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 4px; gap: 10px; }
.mc-name { font-size: 14px; font-weight: 600; color: var(--text); }
.mc-size { font-size: 12px; color: var(--muted); font-family: "SF Mono","Menlo",monospace; flex-shrink: 0; }
.mc-desc { font-size: 12.5px; color: var(--muted); line-height: 1.5; margin-bottom: 8px; }
.mc-tags { display: flex; gap: 8px; margin-bottom: 10px; }
.mc-tag {
  font-size: 11px; color: var(--muted); background: var(--surface2);
  border: 1px solid var(--border2); border-radius: 6px; padding: 3px 8px;
}
.mc-actions { display: flex; align-items: center; gap: 14px; }
.mc-btn {
  display: inline-flex; align-items: center; padding: 7px 14px; border-radius: 8px;
  font-size: 12.5px; font-weight: 500; cursor: pointer; transition: all .13s;
  background: var(--surface2); border: 1px solid var(--border2); color: var(--text);
}
.mc-btn:hover { border-color: #3A3A3A; }
.mc-btn.primary { background: var(--accent); color: #000; border-color: var(--accent); }
.mc-btn.primary:hover { opacity: .88; }
.mc-btn.disabled { opacity: .35; cursor: default; }
.mc-btn.disabled:hover { border-color: var(--border2); }
.mc-link { font-size: 12.5px; color: var(--muted); cursor: pointer; }
.mc-link:hover { color: var(--text); }
.mc-del:hover { color: #FF453A; }
.model-badge {
  display: inline-flex; align-items: center; font-size: 11px; font-weight: 600;
  padding: 4px 10px; border-radius: 100px;
}
.model-badge.rec { background: rgb(var(--accent-rgb)/.12); color: var(--accent); margin-left: 8px; font-size: 10px; padding: 2px 8px; }
.model-badge.active { background: var(--accent); color: #000; }
.dl-row { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
.dl-track { flex: 1; height: 6px; background: var(--border2); border-radius: 3px; overflow: hidden; }
.dl-fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width .15s ease-out; }
.dl-pct { font-size: 11.5px; color: var(--muted); width: 38px; text-align: right; font-family: "SF Mono",monospace; }
.dl-sub { font-size: 11.5px; color: var(--muted); display: flex; justify-content: space-between; }
.dl-err { font-size: 11.5px; color: #FF453A; margin-top: 4px; }

/* Mic test */
.test-btn {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 10px 20px; border-radius: 10px;
  background: rgb(var(--accent-rgb)/.08);
  border: 1px solid rgb(var(--accent-rgb)/.2);
  color: var(--accent); font-size: 13.5px; font-weight: 500;
  cursor: pointer; transition: background .15s; -webkit-user-select: none;
}
.test-btn:hover  { background: rgb(var(--accent-rgb)/.14); }
.test-btn.active { background: rgb(var(--accent-rgb)/.04); color: var(--muted); border-color: var(--border2); }

.vu-wrap {
  display: none; margin-top: 18px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 20px 20px 16px;
}
.vu-wrap.on { display: block; }

.vu-bars {
  display: flex; align-items: flex-end;
  gap: 4px; height: 56px; margin-bottom: 14px;
}
.vu-bar {
  flex: 1; border-radius: 3px 3px 1px 1px;
  background: var(--accent); height: 4px;
  transition: height .07s ease-out, opacity .07s; opacity: .15;
}
.vu-row { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.vu-track { flex: 1; height: 4px; background: var(--border2); border-radius: 2px; overflow: hidden; }
.vu-fill  { height: 100%; width: 0%; background: var(--accent); border-radius: 2px; transition: width .07s ease-out; }
.vu-pct   { font-size: 12px; color: var(--muted); width: 34px; text-align: right; font-family: "SF Mono",monospace; }
.vu-status { font-size: 12.5px; color: var(--muted); display: flex; align-items: center; gap: 6px; }
.vu-sdot  { width: 6px; height: 6px; border-radius: 50%; background: var(--muted2); transition: background .3s; }
.vu-sdot.ok { background: #30D158; }
.mic-err  { font-size: 12.5px; color: #FF453A; margin-top: 12px; display: none; }

/* History */
.hlist { display: flex; flex-direction: column; gap: 6px; }
.hcard {
  display: flex; gap: 12px; padding: 12px 14px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
}
.hts  { font-size: 11px; color: var(--muted); font-family: "SF Mono",monospace; white-space: nowrap; padding-top: 2px; min-width: 36px; }
.htxt { font-size: 13px; color: #C0C0C0; line-height: 1.5; }
.empty { text-align: center; color: var(--muted); padding: 64px 0; line-height: 1.8; }

/* About */
.about  { text-align: center; padding: 16px 0; }
.aico   { width: 64px; height: 64px; margin: 0 auto 14px; }
.aico svg { display: block; width: 100%; height: 100%; border-radius: 14px; }
.atitle { font-size: 26px; font-weight: 700; letter-spacing: -.5px; margin-bottom: 4px; }
.aver   { font-size: 13px; color: var(--muted); margin-bottom: 16px; }
.adesc  { font-size: 13.5px; color: var(--muted); line-height: 1.7; max-width: 320px; margin: 0 auto 26px; }
.badges { display: flex; justify-content: center; gap: 8px; flex-wrap: wrap; }
.badge  { padding: 5px 13px; background: var(--surface); border: 1px solid var(--border); border-radius: 100px; font-size: 12px; color: var(--muted); }
</style>
</head>
<body>

<div class="sidebar">
  <div class="app-header">
    <div class="app-icon"><svg viewBox='0 0 1024 1024' xmlns='http://www.w3.org/2000/svg'><rect width='1024' height='1024' rx='224' fill='#0D0D0D'/><rect x='2' y='2' width='1020' height='1020' rx='222' fill='none' stroke='#fff' stroke-opacity='.08' stroke-width='4'/><path d='M214 372A372 372 0 00214 652' fill='none' stroke='#fff' stroke-width='26' stroke-linecap='round' opacity='.35'/><path d='M810 372A372 372 0 01810 652' fill='none' stroke='#fff' stroke-width='26' stroke-linecap='round' opacity='.35'/><g transform='translate(512 498)'><rect x='-92' y='-230' width='184' height='320' rx='92' fill='#fff'/><path d='M-196-20A196 196 0 00196-20' fill='none' stroke='#fff' stroke-width='40' stroke-linecap='round'/><rect x='-20' y='160' width='40' height='110' rx='20' fill='#fff'/><rect x='-120' y='248' width='240' height='40' rx='20' fill='#fff'/></g></svg></div>
    <div><div class="app-name">Local Flow</div><div class="app-ver">v1.2.0</div></div>
  </div>
  <nav id="nav">
    <div class="nav-item active" onclick="go('hotkey')"  data-page="hotkey">  <span class="ni">&#9000;</span> Hotkey</div>
    <div class="nav-item"        onclick="go('appear')"  data-page="appear">  <span class="ni">&#9680;</span> Appearance</div>
    <div class="nav-item"        onclick="go('models')"  data-page="models">  <span class="ni">&#9830;</span> Models</div>
    <div class="nav-item"        onclick="go('mic')"     data-page="mic">     <span class="ni">&#9670;</span> Microphone</div>
    <div class="nav-item"        onclick="go('history')" data-page="history"> <span class="ni">&#9654;</span> History</div>
    <div class="nav-item"        onclick="go('about')"   data-page="about">   <span class="ni">&#9432;</span> About</div>
  </nav>
</div>

<div class="content" id="content"></div>

<script>
/* ── State ─── */
var S = {
  status:'idle', settings:{use_llm_cleanup:false,sound_start:true},
  accent:'#FFFFFF', hotkey:'alt_r', micOn:false,
  history:[], model:'Small', threads:'8', lang:'en',
  modelId:'small', defaultModelId:'small', catalog:[], modelStatus:{}, dl:null
};
var PAGE = 'hotkey';

var SM = {
  idle:         {cls:'',             txt:'Idle — hold activation key to dictate'},
  recording:    {cls:'recording',    txt:'Listening…'},
  transcribing: {cls:'transcribing', txt:'Transcribing…'},
  done:         {cls:'done',         txt:'Done!'}
};

var SWATCHES = [
  {hex:'#FFFFFF',label:'White'}, {hex:'#E0E0E0',label:'Silver'},
  {hex:'#7B61FF',label:'Indigo'},{hex:'#0A84FF',label:'Blue'},
  {hex:'#5AC8FA',label:'Teal'},  {hex:'#30D158',label:'Green'},
  {hex:'#FFB340',label:'Amber'}, {hex:'#FF453A',label:'Red'}
];

var KEY_OPTS = [
  {key:'alt_r',  sym:'⌥',label:'Right Option'},
  {key:'cmd_r',  sym:'⌘',label:'Right Cmd'},
  {key:'ctrl_r', sym:'⌃',label:'Right Ctrl'},
  {key:'shift_r',sym:'⇧',label:'Right Shift'},
  {key:'f13',    sym:'F13',   label:'F13'},
  {key:'f14',    sym:'F14',   label:'F14'}
];

/* ── Helpers ─── */
function x(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function trow(k,l,d,on){
  return '<div class="trow"><div><div class="tlabel">'+x(l)+'</div><div class="tdesc">'+x(d)+'</div></div>'
    +'<label class="sw"><input type="checkbox" '+(on?'checked':'')
    +' onchange="saveSetting(\''+k+'\',this.checked)"><div class="track"></div></label></div>';
}
function irow(k,v){ return '<div class="irow"><div class="ikey">'+x(k)+'</div><div class="ival">'+x(v)+'</div></div>'; }

/* ── Pages ─── */
function pageHotkey(){
  var sm=SM[S.status]||SM.idle;
  var keyLabel = '';
  KEY_OPTS.forEach(function(o){ if(o.key===S.hotkey) keyLabel=o.sym+' '+o.label; });

  var grid = KEY_OPTS.map(function(o){
    return '<div class="key-opt'+(o.key===S.hotkey?' selected':'')+'" onclick="pickHotkey(\''+o.key+'\')">'
      +'<span class="key-sym">'+o.sym+'</span>'
      +'<span class="key-name">'+o.label+'</span>'
      +'</div>';
  }).join('');

  return '<div class="page-title">Hotkey</div>'
    +'<div class="page-sub">Hold the key, speak, then release to transcribe.</div>'
    +'<div class="status-pill"><div class="dot '+sm.cls+'" id="sdot"></div><span id="stxt">'+sm.txt+'</span></div>'
    +'<div class="sec">Activation key</div>'
    +'<div class="key-grid">'+grid+'</div>'
    +'<div class="divider"></div>'
    +'<div class="sec">Options</div>'
    +'<div class="tgroup">'
    +trow('use_llm_cleanup','LLM Cleanup','Remove filler words via Ollama (runs locally)',S.settings.use_llm_cleanup)
    +trow('sound_start','Sound feedback','Play a beep when recording starts and stops',S.settings.sound_start)
    +'</div>';
}

function pageAppear(){
  var sw = SWATCHES.map(function(s){
    var sel=s.hex.toLowerCase()===S.accent.toLowerCase();
    var fg=s.hex==='#FFFFFF'||s.hex==='#E0E0E0'?'#111':'#fff';
    return '<div class="swatch'+(sel?' selected':'')+'" style="background:'+s.hex+';color:'+fg+';" onclick="pickAccent(\''+s.hex+'\')" title="'+s.label+'">'
      +'<span class="swatch-check">✓</span></div>';
  }).join('');
  return '<div class="page-title">Appearance</div>'
    +'<div class="page-sub">Choose an accent colour. Applied to highlights,<br>nav icons, toggles, and the mic meter.</div>'
    +'<div class="sec">Accent colour</div>'
    +'<div class="swatch-grid">'+sw+'</div>'
    +'<div class="divider"></div>'
    +'<div class="igroup">'+irow('Current',S.accent)+'</div>';
}

function fmtSize(mb){
  return mb>=1000 ? (mb/1024).toFixed(1)+' GB' : mb+' MB';
}

function modelCard(m){
  var st = S.modelStatus[m.id] || {downloaded:false, active:false};
  var dl  = (S.dl && S.dl.id===m.id) ? S.dl : null;
  var rec = (m.id===S.defaultModelId) ? ' <span class="model-badge rec">Recommended</span>' : '';

  var head = '<div class="mc-head"><div class="mc-name">'+x(m.label)+rec+'</div>'
    +'<div class="mc-size">'+fmtSize(m.size_mb)+'</div></div>';
  var desc = '<div class="mc-desc">'+x(m.desc)+'</div>';
  var tags = '<div class="mc-tags"><span class="mc-tag">Speed: '+x(m.speed)+'</span><span class="mc-tag">Accuracy: '+x(m.accuracy)+'</span></div>';

  var action;
  if(dl && (dl.status==='downloading')){
    action = '<div class="dl-row"><div class="dl-track"><div class="dl-fill" style="width:'+dl.pct.toFixed(0)+'%"></div></div>'
      +'<div class="dl-pct">'+dl.pct.toFixed(0)+'%</div></div>'
      +'<div class="dl-sub"><span>'+dl.downloadedMB+' / '+dl.totalMB+' MB</span><span class="mc-link" onclick="cancelDownload()">Cancel</span></div>';
  } else if(dl && dl.status==='error'){
    action = '<div class="mc-actions"><div class="mc-btn primary" onclick="downloadModel(\''+m.id+'\')">Retry download</div></div>'
      +'<div class="dl-err">'+x(dl.error||'Download failed')+'</div>';
  } else if(st.active){
    action = '<div class="model-badge active">Active</div>';
  } else if(st.downloaded){
    action = '<div class="mc-actions"><div class="mc-btn" onclick="useModel(\''+m.id+'\')">Use this model</div>'
      +'<span class="mc-link mc-del" onclick="deleteModel(\''+m.id+'\')">Delete</span></div>';
  } else if(S.dl && S.dl.status==='downloading'){
    action = '<div class="mc-actions"><div class="mc-btn primary disabled">Download</div></div>';
  } else {
    action = '<div class="mc-actions"><div class="mc-btn primary" onclick="downloadModel(\''+m.id+'\')">Download</div></div>';
  }

  return '<div class="model-card'+(st.active?' active':'')+'">'+head+desc+tags+action+'</div>';
}

function pageModels(){
  var anyDownloaded = Object.keys(S.modelStatus).some(function(k){ return S.modelStatus[k].downloaded; });
  var banner = anyDownloaded ? '' :
    '<div class="setup-banner"><b>Welcome to Local Flow!</b> Pick a model below and download it to '
    +'get started — Local Flow needs at least one model installed to transcribe your voice.</div>';

  var current = anyDownloaded ?
    '<div class="igroup">'+irow('Active model',S.model)+irow('Threads',S.threads)+irow('Language',S.lang)+irow('Engine','whisper.cpp (Metal)')+'</div><div class="divider"></div>'
    : '';

  var cards = (S.catalog||[]).map(modelCard).join('');

  return '<div class="page-title">Models</div>'
    +'<div class="page-sub">Choose how Local Flow turns speech into text. Bigger models are more accurate but take longer to download and run.</div>'
    +banner+current
    +'<div class="sec">Available models</div>'
    +'<div class="model-list">'+cards+'</div>';
}

function pageMic(){
  return '<div class="page-title">Microphone</div>'
    +'<div class="page-sub">Verify your mic is working before you dictate.</div>'
    +'<div class="sec">Live test</div>'
    +'<div class="test-btn'+(S.micOn?' active':'')+'" id="testBtn" onclick="toggleMicTest()">'
    +'<span id="testIco">'+(S.micOn?'■':'▶')+'</span>'
    +'<span id="testTxt">'+(S.micOn?'Stop test':'Start microphone test')+'</span>'
    +'</div>'
    +'<div class="vu-wrap'+(S.micOn?' on':'')+'" id="vuWrap">'
    +'<div class="vu-bars" id="vuBars">'
    +function(){var h='';for(var i=0;i<16;i++)h+='<div class="vu-bar" id="vb'+i+'"></div>';return h;}()
    +'</div>'
    +'<div class="vu-row"><div class="vu-track"><div class="vu-fill" id="vuFill"></div></div><div class="vu-pct" id="vuPct">0%</div></div>'
    +'<div class="vu-status"><div class="vu-sdot" id="vuSdot"></div><span id="vuMsg">Waiting for signal…</span></div>'
    +'</div>'
    +'<div class="mic-err" id="micErr"></div>';
}

function pageHistory(){
  if(!S.history.length)
    return '<div class="page-title">History</div><div class="empty">No transcriptions yet.<br>Hold your activation key and speak.</div>';
  var c=S.history.length;
  return '<div class="page-title">History</div>'
    +'<div class="page-sub">'+c+' transcription'+(c!==1?'s':'')+'</div>'
    +'<div class="hlist">'+S.history.map(function(h){
      return '<div class="hcard"><div class="hts">'+x(h.time)+'</div><div class="htxt">'+x(h.text)+'</div></div>';
    }).join('')+'</div>';
}

function pageAbout(){
  return '<div class="about"><div class="aico"><svg viewBox=\'0 0 1024 1024\' xmlns=\'http://www.w3.org/2000/svg\'><rect width=\'1024\' height=\'1024\' rx=\'224\' fill=\'#0D0D0D\'/><rect x=\'2\' y=\'2\' width=\'1020\' height=\'1020\' rx=\'222\' fill=\'none\' stroke=\'#fff\' stroke-opacity=\'.08\' stroke-width=\'4\'/><path d=\'M214 372A372 372 0 00214 652\' fill=\'none\' stroke=\'#fff\' stroke-width=\'26\' stroke-linecap=\'round\' opacity=\'.35\'/><path d=\'M810 372A372 372 0 01810 652\' fill=\'none\' stroke=\'#fff\' stroke-width=\'26\' stroke-linecap=\'round\' opacity=\'.35\'/><g transform=\'translate(512 498)\'><rect x=\'-92\' y=\'-230\' width=\'184\' height=\'320\' rx=\'92\' fill=\'#fff\'/><path d=\'M-196-20A196 196 0 00196-20\' fill=\'none\' stroke=\'#fff\' stroke-width=\'40\' stroke-linecap=\'round\'/><rect x=\'-20\' y=\'160\' width=\'40\' height=\'110\' rx=\'20\' fill=\'#fff\'/><rect x=\'-120\' y=\'248\' width=\'240\' height=\'40\' rx=\'20\' fill=\'#fff\'/></g></svg></div>'
    +'<div class="atitle">Local Flow</div><div class="aver">Version 1.2.0</div>'
    +'<div class="adesc">Voice dictation for Apple Silicon. Powered by whisper.cpp with Metal. Your voice never leaves your Mac.</div>'
    +'<div class="badges"><span class="badge">100% Local</span><span class="badge">No Cloud</span>'
    +'<span class="badge">No Subscription</span><span class="badge">Apple Silicon</span></div></div>';
}

var PAGES={hotkey:pageHotkey,appear:pageAppear,models:pageModels,mic:pageMic,history:pageHistory,about:pageAbout};

/* ── Navigation ─── */
function go(page){
  PAGE=page;
  document.querySelectorAll('.nav-item').forEach(function(el){
    el.classList.toggle('active',el.dataset.page===page);
  });
  document.getElementById('content').innerHTML=(PAGES[page]||pageHotkey)();
}

/* ── Accent ─── */
function applyAccent(hex){
  S.accent=hex;
  document.documentElement.style.setProperty('--accent',hex);
  var r=parseInt(hex.slice(1,3),16),g=parseInt(hex.slice(3,5),16),b=parseInt(hex.slice(5,7),16);
  document.documentElement.style.setProperty('--accent-rgb',r+' '+g+' '+b);
}
function pickAccent(hex){
  applyAccent(hex);
  pyPost({action:'saveAccentColor',value:hex});
  if(PAGE==='appear') go('appear');
}

/* ── Hotkey ─── */
function pickHotkey(key){
  S.hotkey=key;
  pyPost({action:'saveHotkey',value:key});
  if(PAGE==='hotkey') go('hotkey');
}

/* ── Mic test  (Web Audio API — no Python polling needed) ─── */
var _micStream=null, _micCtx=null, _micRaf=null;

function toggleMicTest(){
  S.micOn=!S.micOn;
  var btn=document.getElementById('testBtn');
  var ico=document.getElementById('testIco');
  var txt=document.getElementById('testTxt');
  var vw =document.getElementById('vuWrap');
  if(btn) btn.className='test-btn'+(S.micOn?' active':'');
  if(ico) ico.textContent=S.micOn?'■':'▶';
  if(txt) txt.textContent=S.micOn?'Stop test':'Start microphone test';
  if(vw)  vw.className='vu-wrap'+(S.micOn?' on':'');
  if(S.micOn){ startMicAudio(); } else { stopMicAudio(); resetVU(); }
}

function startMicAudio(){
  var err=document.getElementById('micErr');
  if(err){ err.style.display='none'; err.textContent=''; }
  navigator.mediaDevices.getUserMedia({audio:true,video:false})
    .then(function(stream){
      _micStream=stream;
      _micCtx=new (window.AudioContext||window.webkitAudioContext)();
      var src=_micCtx.createMediaStreamSource(stream);
      var ana=_micCtx.createAnalyser();
      ana.fftSize=256;
      src.connect(ana);
      var buf=new Uint8Array(ana.frequencyBinCount);
      function tick(){
        if(!S.micOn){ return; }
        ana.getByteFrequencyData(buf);
        var sum=0;
        for(var i=0;i<buf.length;i++) sum+=buf[i];
        var level=Math.min(100,(sum/buf.length/255)*100*4);
        updateMicLevel(level);
        _micRaf=requestAnimationFrame(tick);
      }
      tick();
    })
    .catch(function(e){
      S.micOn=false;
      var btn=document.getElementById('testBtn');
      var ico=document.getElementById('testIco');
      var txt=document.getElementById('testTxt');
      var vw =document.getElementById('vuWrap');
      if(btn) btn.className='test-btn';
      if(ico) ico.textContent='▶';
      if(txt) txt.textContent='Start microphone test';
      if(vw)  vw.className='vu-wrap';
      var err=document.getElementById('micErr');
      if(err){ err.style.display='block'; err.textContent='Mic access denied: '+e.message; }
    });
}

function stopMicAudio(){
  if(_micRaf){ cancelAnimationFrame(_micRaf); _micRaf=null; }
  if(_micStream){ _micStream.getTracks().forEach(function(t){t.stop();}); _micStream=null; }
  if(_micCtx){ _micCtx.close(); _micCtx=null; }
}

function resetVU(){
  for(var i=0;i<16;i++){
    var b=document.getElementById('vb'+i);
    if(b){ b.style.height='4px'; b.style.opacity='0.15'; }
  }
  var f=document.getElementById('vuFill'),p=document.getElementById('vuPct');
  var d=document.getElementById('vuSdot'),s=document.getElementById('vuMsg');
  if(f) f.style.width='0%';
  if(p) p.textContent='0%';
  if(d) d.className='vu-sdot';
  if(s) s.textContent='Waiting for signal…';
}

function updateMicLevel(level){
  for(var i=0;i<16;i++){
    var b=document.getElementById('vb'+i);
    if(!b) continue;
    var th=(i/16)*100, active=level>th;
    b.style.height=(active?Math.min(56,4+(level-th)*1.8):4)+'px';
    b.style.opacity=active?'1':'0.12';
  }
  var f=document.getElementById('vuFill'),p=document.getElementById('vuPct');
  var d=document.getElementById('vuSdot'),s=document.getElementById('vuMsg');
  if(f) f.style.width=Math.min(100,level)+'%';
  if(p) p.textContent=Math.round(level)+'%';
  if(d) d.className='vu-sdot'+(level>2?' ok':'');
  if(s) s.textContent=level>2?'Microphone working ✔':'No signal detected';
}

/* ── Python -> JS ─── */
function updateState(state){
  S.status=state;
  if(PAGE!=='hotkey') return;
  var sm=SM[state]||SM.idle;
  var d=document.getElementById('sdot'),t=document.getElementById('stxt');
  if(d) d.className='dot '+sm.cls;
  if(t) t.textContent=sm.txt;
}
function loadSettings(data){ S.settings=data; if(PAGE==='hotkey') go('hotkey'); }
function loadAccentColor(h){ applyAccent(h); if(PAGE==='appear') go('appear'); }
function loadHotkey(k){ S.hotkey=k; if(PAGE==='hotkey') go('hotkey'); }
function loadHistory(items){ S.history=items; if(PAGE==='history') go('history'); }
function loadModelInfo(info){
  if(info.model)     S.model=info.model;
  if(info.modelId)   S.modelId=info.modelId;
  if(info.threads)   S.threads=String(info.threads);
  if(info.lang)      S.lang=info.lang;
  if(info.catalog)   S.catalog=info.catalog;
  if(info.status)    S.modelStatus=info.status;
  if(info.defaultId) S.defaultModelId=info.defaultId;
  if(PAGE==='models') go('models');
}
function downloadProgress(d){
  S.dl = (d.status==='downloading' || d.status==='error') ? d : null;
  if(PAGE==='models') go('models');
  if(d.status==='done' || d.status==='cancelled') pyPost({action:'getModelInfo'});
}

/* ── JS -> Python ─── */
function pyPost(msg){
  try{ window.webkit.messageHandlers.api.postMessage(msg); }
  catch(e){ console.warn('pyPost failed',e); }
}
function saveSetting(k,v){ pyPost({action:'saveSetting',key:k,value:v}); }
function downloadModel(id){ pyPost({action:'downloadModel', value:id}); }
function cancelDownload(){ pyPost({action:'cancelDownload'}); }
function useModel(id){ pyPost({action:'setActiveModel', value:id}); }
function deleteModel(id){ pyPost({action:'deleteModel', value:id}); }

/* ── Init ─── */
go('hotkey');
setTimeout(function(){
  pyPost({action:'getSettings'});
  pyPost({action:'getHistory'});
  pyPost({action:'getModelInfo'});
  pyPost({action:'getAccentColor'});
  pyPost({action:'getHotkey'});
}, 100);
</script>
</body>
</html>"""


# ── Module-level API helpers (kept outside NSObject to avoid pyobjc issues) ───

def _api_save_setting(body: dict):
    global USE_LLM_CLEANUP, SOUND_START
    key, val = body.get("key",""), body.get("value", False)
    if key == "use_llm_cleanup": USE_LLM_CLEANUP = bool(val)
    elif key == "sound_start":   SOUND_START     = bool(val)
    _save_settings(); _log(f"setting {key}={val}")

def _api_save_accent(body: dict):
    global ACCENT_COLOR
    ACCENT_COLOR = str(body.get("value", ACCENT_COLOR))
    _save_settings(); _log(f"accent={ACCENT_COLOR}")

def _api_save_hotkey(body: dict):
    global HOTKEY
    k = str(body.get("value", HOTKEY))
    if k not in HOTKEY_LABELS:
        _log(f"hotkey rejected — unknown key: {k!r}")
        return
    HOTKEY = k
    _save_settings()
    _log(f"hotkey changing to {HOTKEY} — restarting monitor")
    _start_keyboard_monitor()
    _log(f"hotkey monitor restarted: {HOTKEY}")

# ── Model download manager ────────────────────────────────────────────────────
_dl_lock  = threading.Lock()
_dl_state = {"id": None, "cancel": None}

def _download_model_async(model_id: str, panel):
    m = _MODEL_BY_ID.get(model_id)
    if not m: return
    with _dl_lock:
        if _dl_state["id"] is not None:
            return  # a download is already running
        cancel = threading.Event()
        _dl_state["id"], _dl_state["cancel"] = model_id, cancel

    def _emit(status: str, downloaded: int = 0, total: int = 0, error: str = ""):
        if not panel: return
        pct = (downloaded / total * 100) if total else 0
        panel._js("downloadProgress(" + json.dumps({
            "id": model_id, "status": status, "pct": pct,
            "downloadedMB": round(downloaded / 1048576, 1),
            "totalMB":      round(total / 1048576, 1),
            "error":        error,
        }) + ")")

    def _run():
        global MODEL_ID, WHISPER_MODEL
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        dest = MODELS_DIR / m["file"]
        tmp  = dest.with_name(dest.name + ".part")
        url  = f"{MODEL_BASE_URL}/{m['file']}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LocalFlow"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                total = int(resp.headers.get("Content-Length") or m["size_mb"] * 1024 * 1024)
                downloaded, last = 0, 0.0
                with open(tmp, "wb") as out:
                    while True:
                        if cancel.is_set(): raise InterruptedError
                        chunk = resp.read(1 << 20)
                        if not chunk: break
                        out.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        if now - last > 0.15:
                            _emit("downloading", downloaded, total)
                            last = now
            tmp.replace(dest)
            _log(f"model downloaded: {dest}")
            # First model ever installed becomes the active one automatically.
            if not _model_downloaded(MODEL_ID) or MODEL_ID == model_id:
                MODEL_ID = model_id
                WHISPER_MODEL = _model_path(MODEL_ID)
                _save_settings()
            _emit("done", downloaded, downloaded or total)
        except InterruptedError:
            tmp.unlink(missing_ok=True)
            _emit("cancelled")
            _log(f"model download cancelled: {model_id}")
        except Exception as e:
            tmp.unlink(missing_ok=True)
            _log(f"model download failed: {e}")
            _emit("error", error=str(e))
        finally:
            with _dl_lock:
                _dl_state["id"], _dl_state["cancel"] = None, None

    threading.Thread(target=_run, daemon=True, name="model-dl").start()

def _cancel_download():
    with _dl_lock:
        if _dl_state["cancel"]: _dl_state["cancel"].set()


def _api_download_model(body: dict):
    mid = str(body.get("value", ""))
    if mid not in _MODEL_BY_ID: return
    _download_model_async(mid, _ApiHandler._panel_ref)

def _api_cancel_download(_body: dict):
    _cancel_download()

def _api_set_active_model(body: dict):
    global MODEL_ID, WHISPER_MODEL
    mid = str(body.get("value", ""))
    if mid not in _MODEL_BY_ID or not _model_downloaded(mid): return
    MODEL_ID = mid
    WHISPER_MODEL = _model_path(MODEL_ID)
    _save_settings()
    _log(f"active model -> {MODEL_ID}")
    if _ApiHandler._panel_ref: _ApiHandler._panel_ref._push_model_info()

def _api_delete_model(body: dict):
    mid = str(body.get("value", ""))
    m = _MODEL_BY_ID.get(mid)
    if not m or mid == MODEL_ID: return
    for base in (MODELS_DIR, _LEGACY_MODELS_DIR):
        p = base / m["file"]
        if p.exists():
            try: p.unlink()
            except Exception as e: _log(f"delete model: {e}")
    if _ApiHandler._panel_ref: _ApiHandler._panel_ref._push_model_info()


def _api_panel_push(method: str):
    ref = _ApiHandler._panel_ref
    if ref: getattr(ref, method)()


class _ApiHandler(NSObject):
    _panel_ref = None

    def userContentController_didReceiveScriptMessage_(self, _, message):
        try:
            body = message.body()
            if not isinstance(body, dict): return
            dispatch = {
                "saveSetting":    lambda: _api_save_setting(body),
                "saveAccentColor":lambda: _api_save_accent(body),
                "saveHotkey":     lambda: _api_save_hotkey(body),
                "getSettings":    lambda: _api_panel_push("_push_settings"),
                "getHistory":     lambda: _api_panel_push("_push_history"),
                "getModelInfo":   lambda: _api_panel_push("_push_model_info"),
                "getAccentColor": lambda: _api_panel_push("_push_accent"),
                "getHotkey":      lambda: _api_panel_push("_push_hotkey"),
                "downloadModel":  lambda: _api_download_model(body),
                "cancelDownload": lambda: _api_cancel_download(body),
                "setActiveModel": lambda: _api_set_active_model(body),
                "deleteModel":    lambda: _api_delete_model(body),
            }
            fn = dispatch.get(body.get("action",""))
            if fn: fn()
        except Exception as e:
            _log(f"_ApiHandler: {e}")


# Quit the whole app (and take the pill with it) when the settings window is closed.
class _SettingsDelegate(NSObject):
    def windowWillClose_(self, notification):
        rumps.quit_application()


# Signals when the WKWebView has finished loading _SETTINGS_HTML so queued
# _js() calls (e.g. the initial loadModelInfo with the full catalog) aren't
# lost by firing before the page's <script> has run.
class _WebViewNavDelegate(NSObject):
    def webView_didFinishNavigation_(self, webview, navigation):
        panel = _ApiHandler._panel_ref
        if panel:
            panel._ready = True
            panel._flush_js_queue()


# ── Settings panel (WKWebView loaded from file://) ────────────────────────────
class SettingsPanel:
    W, H = 660, 480

    def __init__(self):
        self._win = self._webview = None
        self._ready = False
        self._js_queue = []
        _log(f"SettingsPanel HUD={HAS_HUD} WEB={HAS_WEBVIEW}")
        if not (HAS_HUD and HAS_WEBVIEW): return
        try:   self._build()
        except Exception as e:
            _log(f"SettingsPanel init: {e}")
            import traceback; _log(traceback.format_exc())

    def _build(self):
        sc = NSScreen.mainScreen().frame()
        x  = (sc.size.width  - self.W) / 2
        y  = (sc.size.height - self.H) / 2

        self._win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, self.W, self.H),
            NSWindowStyleMaskTitled      |
            NSWindowStyleMaskClosable    |
            NSWindowStyleMaskMiniaturizable |
            NSWindowStyleMaskResizable,
            NSBackingStoreBuffered, False)
        self._win.setTitle_("Local Flow")
        self._win.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces)
        # Quit the whole app (and take the pill with it) when the window closes.
        self._delegate = _SettingsDelegate.alloc().init()
        self._win.setDelegate_(self._delegate)

        uc  = WKUserContentController.alloc().init()
        hdl = _ApiHandler.alloc().init()
        _ApiHandler._panel_ref = self
        uc.addScriptMessageHandler_name_(hdl, "api")

        cfg = WKWebViewConfiguration.alloc().init()
        cfg.setUserContentController_(uc)

        self._webview = WKWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(0, 0, self.W, self.H), cfg)
        self._nav_delegate = _WebViewNavDelegate.alloc().init()
        self._webview.setNavigationDelegate_(self._nav_delegate)

        # file:// base URL gives the page a secure origin so that
        # window.webkit.messageHandlers and getUserMedia both work.
        base_url = NSURL.fileURLWithPath_("/")
        self._webview.loadHTMLString_baseURL_(_SETTINGS_HTML, base_url)

        self._win.setContentView_(self._webview)
        _log("SettingsPanel._build OK")

    def show(self):
        if not self._win: return
        try:
            from AppKit import NSApplication
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            self._win.makeKeyAndOrderFront_(None)
            _log("SettingsPanel.show: window raised")
            self._push_settings(); self._push_history()
            self._push_model_info(); self._push_accent(); self._push_hotkey()
        except Exception as e:
            _log(f"SettingsPanel.show: {e}")

    def _js(self, code: str):
        if not self._webview: return
        if not self._ready:
            self._js_queue.append(code)
            return
        def _cb(result, error):
            if error:
                _log(f"_js error on {code[:60]!r}: {error}")
        self._webview.evaluateJavaScript_completionHandler_(code, _cb)

    def _flush_js_queue(self):
        queued, self._js_queue = self._js_queue, []
        for code in queued:
            self._js(code)

    def update(self, state: str):
        self._js(f"updateState('{state}')")

    def _push_settings(self):
        d = json.dumps({"use_llm_cleanup": USE_LLM_CLEANUP, "sound_start": SOUND_START})
        self._js(f"loadSettings({d})")

    def _push_history(self):
        self._js(f"loadHistory({json.dumps(_history[:50])})")

    def _push_model_info(self):
        info = json.dumps({
            "model":     _MODEL_BY_ID[MODEL_ID]["label"],
            "modelId":   MODEL_ID,
            "threads":   str(WHISPER_THREADS),
            "lang":      WHISPER_LANG,
            "catalog":   MODEL_CATALOG,
            "status":    _model_status(),
            "defaultId": DEFAULT_MODEL_ID,
        })
        self._js(f"loadModelInfo({info})")

    def _push_accent(self):
        self._js(f"loadAccentColor('{ACCENT_COLOR}')")

    def _push_hotkey(self):
        self._js(f"loadHotkey('{HOTKEY}')")


# ── Menu bar app ──────────────────────────────────────────────────────────────
class MenuBarApp(rumps.App):
    _ICONS  = {"idle":"\U0001f399","recording":"\U0001f534","transcribing":"⏳","done":"✅"}
    _LABELS = {
        "idle":         "● Idle — hold key to dictate",
        "recording":    "\U0001f534 Listening…",
        "transcribing": "⏳ Transcribing…",
        "done":         "✅ Done!",
    }

    def __init__(self):
        super().__init__("\U0001f399", quit_button="Quit Local Flow")
        self._hud    = FloatingHUD()
        self._panel  = SettingsPanel()
        self._status = rumps.MenuItem("● Idle — hold key to dictate")
        self.menu    = [self._status, None,
                        rumps.MenuItem("Open Settings", callback=self._open_settings)]
        self._timer  = rumps.Timer(self._poll, 0.05)
        self._timer.start()
        self._hb = 0                   # heartbeat counter
        set_ui_state("idle")           # show pill immediately once RunLoop fires
        # Auto-open settings once on launch — land on Models if none is installed yet.
        def _open_once(t):
            t.stop()
            self._panel.show()
            if not _model_downloaded(MODEL_ID):
                self._panel._js("go('models')")
        rumps.Timer(_open_once, 0.5).start()

        # Request microphone permission via AVFoundation after RunLoop starts
        # (must happen on main thread with active RunLoop — not before run())
        def _request_mic(t):
            t.stop()
            try:
                from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
                status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
                _log(f"mic auth status: {status}")  # 0=notDetermined 2=denied 3=authorized
                if status != 3:
                    def _on_granted(granted):
                        _log(f"mic permission granted={granted}")
                    AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                        AVMediaTypeAudio, _on_granted)
            except Exception as e:
                _log(f"mic request: {e}")
        rumps.Timer(_request_mic, 1.0).start()

    def _open_settings(self, _):
        self._panel.show()

    def _poll(self, _):
        # ── process state changes ──────────────────────────────────────────────
        try:
            while True:
                state = _ui_queue.get_nowait()
                self.title         = self._ICONS.get(state, "\U0001f399")
                self._status.title = self._LABELS.get(state, "● Idle")
                self._hud.update(state)
                self._panel.update(state)
        except queue.Empty:
            pass

        # ── track dock position every tick so pill follows auto-hide dock ────────
        self._hud.sync_position()

        # ── heartbeat: re-raise pill every 500 ms so it never stays hidden ──────
        self._hb += 1
        if self._hb >= 10:             # 10 × 50 ms = 500 ms
            self._hb = 0
            self._hud.keep_visible()


def set_ui_state(state: str):
    _ui_queue.put(state)


# ── App focus helpers ─────────────────────────────────────────────────────────
def get_frontmost_app() -> str:
    """Return the bundle ID of the frontmost app using NSWorkspace (no Apple Events)."""
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return app.bundleIdentifier() or ""
    except Exception as e:
        _log(f"get_frontmost_app: {e}")
        return ""

def activate_app(bundle_id: str):
    """Bring the target app to front using NSWorkspace — no Apple Events needed."""
    if not bundle_id: return
    try:
        from AppKit import NSWorkspace
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            if app.bundleIdentifier() == bundle_id:
                app.activateWithOptions_(2)  # NSApplicationActivateIgnoringOtherApps
                return
    except Exception as e:
        _log(f"activate_app: {e}")


# ── Audio ─────────────────────────────────────────────────────────────────────
def beep(freq=880, duration=0.08):
    if not SOUND_START: return
    try:
        t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
        sd.play((np.sin(2 * np.pi * freq * t) * 0.3).astype(np.float32), SAMPLE_RATE)
        sd.wait()
    except Exception: pass

def audio_callback(indata, *_):
    if recording:
        with lock: audio_buf.append(indata.copy())


# ── Transcription ─────────────────────────────────────────────────────────────
def transcribe(wav_path: str) -> str:
    if not WHISPER_BIN.exists(): return "[whisper-cli not found]"
    if not WHISPER_MODEL.exists(): return "[no model installed]"
    r = subprocess.run(
        [str(WHISPER_BIN), "-m", str(WHISPER_MODEL), "-f", wav_path,
         "-l", WHISPER_LANG, "-t", str(WHISPER_THREADS), "--no-timestamps", "-np"],
        capture_output=True, text=True)
    lines = [l.strip() for l in r.stdout.splitlines() if l.strip() and not l.startswith("[")]
    return " ".join(lines)


# ── LLM cleanup ───────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = (
    "You are a transcription editor. The user speaks Hinglish (Hindi + English).\n"
    "Remove filler words: um, uh, like, basically, you know, so, hmm, "
    "actually, matlab, arey, haan toh, woh, bhai.\n"
    "Fix obvious transcription errors. Keep the Hindi/English mix.\n"
    "Return ONLY the cleaned text — no explanation, no quotes."
)

def clean_with_ollama(text: str) -> str:
    payload = json.dumps({"model": OLLAMA_MODEL,
                          "prompt": f"{_SYSTEM_PROMPT}\n\nTranscript:\n{text}",
                          "stream": False}).encode()
    try:
        req = urllib.request.Request(OLLAMA_URL, data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read()).get("response", text).strip()
    except Exception as e:
        _log(f"Ollama: {e}"); return text


# ── Paste ─────────────────────────────────────────────────────────────────────
_PASTE_SCRIPT = (
    "from pynput.keyboard import Controller, Key\n"
    "import time; time.sleep(0.05)\n"
    "kb = Controller()\n"
    "kb.press(Key.cmd); kb.press('v'); kb.release('v'); kb.release(Key.cmd)\n"
)

def paste_text(text: str, target_app: str = ""):
    try: subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
    except Exception as e: _log(f"pbcopy: {e}"); return
    _log(f"paste_text: clipboard set, target_app={target_app!r}")
    if target_app:
        activate_app(target_app)
        time.sleep(0.35)
    else:
        time.sleep(0.05)
    # Use pynput (same Accessibility permission as keyboard monitor — no Apple Events needed)
    python3 = _find_system_python()
    if python3:
        r = subprocess.run([python3, "-c", _PASTE_SCRIPT], capture_output=True, text=True)
        if r.returncode != 0:
            _log(f"paste via pynput failed (rc={r.returncode}): {r.stderr.strip()}")
        else:
            _log("paste OK")
    else:
        _log("paste skipped — no system python found")


# ── Processing pipeline ───────────────────────────────────────────────────────
def process_recording(frames, target_app: str = ""):
    set_ui_state("transcribing")
    audio = np.concatenate(frames, axis=0).flatten()
    duration_sec = len(audio) / SAMPLE_RATE
    rms = float(np.sqrt(np.mean(audio ** 2)))
    _log(f"recording: {len(frames)} frames, {duration_sec:.2f}s, RMS={rms:.5f}")
    if rms < 0.001:
        _log("audio too quiet — microphone permission may be denied")
        set_ui_state("idle")
        threading.Thread(target=_show_mic_alert, daemon=True).start()
        return
    wav_path = None
    try:
        import wave
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(SAMPLE_RATE)
            wf.writeframes((audio * 32767).astype(np.int16).tobytes())
        raw = transcribe(wav_path)
        _log(f"transcribed: {raw!r}")
        if raw == "[no model installed]":
            set_ui_state("idle")
            threading.Thread(target=_prompt_model_setup, daemon=True).start()
            return
        if not raw: set_ui_state("idle"); return
        final = clean_with_ollama(raw) if USE_LLM_CLEANUP else raw
        _add_history(final)
        if _app and _app._panel: _app._panel._push_history()
        paste_text(final, target_app)
        set_ui_state("done"); time.sleep(0.6); set_ui_state("idle")
    except Exception as e:
        _log(f"process_recording: {e}")
        import traceback; _log(traceback.format_exc())
        set_ui_state("idle")
    finally:
        if wav_path and os.path.exists(wav_path): os.unlink(wav_path)


# ── Hotkey handlers ───────────────────────────────────────────────────────────
def _on_key_down():
    global recording, audio_buf, _target_app
    if recording: return
    _target_app = get_frontmost_app()
    recording = True; audio_buf = []
    set_ui_state("recording"); beep(660)

def _on_key_up():
    global recording
    if not recording: return
    recording = False; beep(440)
    with lock: frames = list(audio_buf)
    if frames:
        threading.Thread(target=process_recording, args=(frames, _target_app), daemon=True).start()
    else:
        set_ui_state("idle")


# ── Keyboard monitor ──────────────────────────────────────────────────────────
_PYNPUT_TMPL = """\
import sys
from pynput import keyboard

try:
    TARGET = getattr(keyboard.Key, '{key}')
except AttributeError:
    TARGET = keyboard.Key.alt_r

# Get virtual key code so we can match even when pynput reports
# a modifier as a raw KeyCode instead of the named Key enum value.
try:
    TARGET_VK = TARGET.value.vk
except Exception:
    TARGET_VK = None

def _matches(k):
    if k == TARGET:
        return True
    if TARGET_VK is not None:
        try:
            return k.vk == TARGET_VK
        except AttributeError:
            pass
    return False

def on_press(k):
    if _matches(k):
        sys.stdout.write("1\\n")
        sys.stdout.flush()

def on_release(k):
    if _matches(k):
        sys.stdout.write("0\\n")
        sys.stdout.flush()

with keyboard.Listener(on_press=on_press, on_release=on_release) as _l:
    _l.join()
"""

_PYTHON_CANDIDATES = [
    "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3",
    "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3",
    "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3",
    "/opt/homebrew/bin/python3",
    "/usr/local/bin/python3",
]

def _find_system_python() -> str:
    for p in _PYTHON_CANDIDATES:
        if not os.path.exists(p): continue
        r = subprocess.run([p, "-c", "import pynput"], capture_output=True, timeout=5)
        if r.returncode == 0: return p
    return ""

def _prompt_model_setup():
    """No transcription model installed yet — open Settings → Models for the user."""
    if _app and _app._panel:
        _app._panel.show()
        _app._panel._js("go('models')")

def _show_mic_alert():
    """Prompt the user to grant Microphone permission."""
    try:
        r = subprocess.run(
            ["osascript", "-e",
             'display dialog "Local Flow cannot hear you — Microphone access may be denied.'
             '\n\nOpen System Settings → Privacy & Security → Microphone'
             ' and enable Local Flow, then relaunch the app."'
             ' buttons {"Open Settings", "OK"} default button "OK"'],
            capture_output=True, text=True, timeout=60)
        if "Open Settings" in r.stdout:
            subprocess.run(
                ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"],
                capture_output=True)
    except Exception as e:
        _log(f"mic alert: {e}")

def _show_accessibility_alert():
    """Prompt the user to grant Accessibility permission when pynput fails."""
    try:
        r = subprocess.run(
            ["osascript", "-e",
             'display dialog "Local Flow needs Accessibility access to detect hotkeys.'
             '\n\nOpen System Settings → Privacy & Security → Accessibility,'
             ' enable Local Flow, then relaunch the app."'
             ' buttons {"Open Settings", "OK"} default button "OK"'],
            capture_output=True, text=True, timeout=60)
        if "Open Settings" in r.stdout:
            subprocess.run(
                ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
                capture_output=True)
    except Exception as e:
        _log(f"accessibility alert: {e}")

def _start_keyboard_monitor():
    global _kbd_proc
    python3 = _find_system_python()
    if not python3:
        _log("No system Python with pynput")
        threading.Thread(target=_show_accessibility_alert, daemon=True).start()
        return

    # Kill previous process if key changed
    if _kbd_proc and _kbd_proc.poll() is None:
        _kbd_proc.terminate()
        try: _kbd_proc.wait(timeout=2)
        except subprocess.TimeoutExpired: _kbd_proc.kill()

    script = _PYNPUT_TMPL.format(key=HOTKEY)
    _kbd_proc = subprocess.Popen(
        [python3, "-c", script],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def _reader():
        for line in _kbd_proc.stdout:
            s = line.strip()
            if s == "1": _on_key_down()
            elif s == "0": _on_key_up()

    def _err_watcher():
        # Read and log every stderr line; if the process dies with a non-zero
        # exit code it almost always means Accessibility permission was denied.
        err_lines = []
        for line in _kbd_proc.stderr:
            _log(f"kbd: {line.rstrip()}")
            err_lines.append(line)
        ret = _kbd_proc.wait()
        if ret != 0:
            _log(f"kbd monitor exited with code {ret}")
            threading.Thread(target=_show_accessibility_alert, daemon=True).start()

    threading.Thread(target=_reader,      daemon=True, name="kbd-reader").start()
    threading.Thread(target=_err_watcher, daemon=True, name="kbd-err").start()
    _log(f"Keyboard monitor: {python3}  key={HOTKEY}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    global _app
    print("=" * 55)
    print("  \U0001f399  Local Flow — Voice Dictation")
    print("=" * 55)

    if not WHISPER_BIN.exists():
        sys.exit("\n❌ whisper-cli not found inside the app bundle. Please reinstall Local Flow.")

    if not WHISPER_MODEL.exists():
        print("\n⚠️  No transcription model installed yet.")
        print("   Open Settings → Models and download one to get started.\n")
    else:
        print(f"\n✅ Ready. Hold {HOTKEY_LABELS.get(HOTKEY, ('?','?'))[0]} in any app to speak.\n")

    _log("main() ready")

    stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                            callback=audio_callback, blocksize=1024)
    try: stream.start()
    except Exception as e:
        print(f"⚠️  Audio: {e} — grant Microphone permission then restart")

    _start_keyboard_monitor()

    _log("creating MenuBarApp")
    try: _app = MenuBarApp()
    except Exception as e:
        _log(f"MenuBarApp FAILED: {e}")
        import traceback; _log(traceback.format_exc()); raise
    _log("MenuBarApp created — calling run()")

    signal.signal(signal.SIGINT, lambda *_: rumps.quit_application())
    _app.run()
    _log("run() returned")
    stream.stop(); stream.close()


if __name__ == "__main__":
    main()
