import os
import subprocess
import time

from .log import _log

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


# ── System Python lookup (for pynput-based paste & keyboard monitor) ───────────
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
