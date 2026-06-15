import queue
import threading
import time

SAMPLE_RATE = 16000

# ── Recording buffer (written by the keyboard monitor, read by the audio
#    callback / transcription pipeline) ─────────────────────────────────────────
recording   = False
audio_buf   = []
lock        = threading.Lock()
_target_app = ""

# ── UI plumbing ─────────────────────────────────────────────────────────────────
_ui_queue = queue.Queue()
_app      = None   # set once by flow.main() to the running MenuBarApp


def set_ui_state(state: str):
    _ui_queue.put(state)


# ── History ───────────────────────────────────────────────────────────────────
_history = []


def _add_history(text: str):
    _history.insert(0, {"time": time.strftime("%H:%M"), "text": text})
    if len(_history) > 200: _history.pop()
