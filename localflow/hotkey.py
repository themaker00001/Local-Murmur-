import subprocess
import threading

from . import config, state
from .alerts import _show_accessibility_alert
from .audio import beep, process_recording
from .log import _log
from .paste import _find_system_python, get_frontmost_app

_kbd_proc = None          # current pynput subprocess


# ── Hotkey handlers ───────────────────────────────────────────────────────────
def _on_key_down():
    if state.recording: return
    state._target_app = get_frontmost_app()
    state.recording = True; state.audio_buf = []
    state.set_ui_state("recording"); beep(660)


def _on_key_up():
    if not state.recording: return
    state.recording = False; beep(440)
    with state.lock: frames = list(state.audio_buf)
    if frames:
        threading.Thread(target=process_recording, args=(frames, state._target_app), daemon=True).start()
    else:
        state.set_ui_state("idle")


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

    script = _PYNPUT_TMPL.format(key=config.HOTKEY)
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
    _log(f"Keyboard monitor: {python3}  key={config.HOTKEY}")
