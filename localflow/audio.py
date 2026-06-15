import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

try:
    import sounddevice as sd
    import numpy as np
except ImportError:
    sys.exit("Missing: pip install sounddevice numpy")

from . import config, state
from .alerts import _prompt_model_setup, _show_mic_alert
from .log import _log
from .paste import paste_text


# ── Audio ─────────────────────────────────────────────────────────────────────
def beep(freq=880, duration=0.08):
    if not config.SOUND_START: return
    try:
        t = np.linspace(0, duration, int(state.SAMPLE_RATE * duration), False)
        sd.play((np.sin(2 * np.pi * freq * t) * 0.3).astype(np.float32), state.SAMPLE_RATE)
        sd.wait()
    except Exception: pass


def audio_callback(indata, *_):
    if state.recording:
        with state.lock: state.audio_buf.append(indata.copy())


# ── Transcription ─────────────────────────────────────────────────────────────
def transcribe(wav_path: str) -> str:
    if not config.WHISPER_BIN.exists(): return "[whisper-cli not found]"
    if not config.WHISPER_MODEL.exists(): return "[no model installed]"
    r = subprocess.run(
        [str(config.WHISPER_BIN), "-m", str(config.WHISPER_MODEL), "-f", wav_path,
         "-l", config.WHISPER_LANG, "-t", str(config.WHISPER_THREADS), "--no-timestamps", "-np"],
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
    payload = json.dumps({"model": config.OLLAMA_MODEL,
                          "prompt": f"{_SYSTEM_PROMPT}\n\nTranscript:\n{text}",
                          "stream": False}).encode()
    try:
        req = urllib.request.Request(config.OLLAMA_URL, data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read()).get("response", text).strip()
    except Exception as e:
        _log(f"Ollama: {e}"); return text


# ── Processing pipeline ───────────────────────────────────────────────────────
def process_recording(frames, target_app: str = ""):
    state.set_ui_state("transcribing")
    audio = np.concatenate(frames, axis=0).flatten()
    duration_sec = len(audio) / state.SAMPLE_RATE
    rms = float(np.sqrt(np.mean(audio ** 2)))
    _log(f"recording: {len(frames)} frames, {duration_sec:.2f}s, RMS={rms:.5f}")
    if rms < 0.001:
        _log("audio too quiet — microphone permission may be denied")
        state.set_ui_state("idle")
        threading.Thread(target=_show_mic_alert, daemon=True).start()
        return
    wav_path = None
    try:
        import wave
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(state.SAMPLE_RATE)
            wf.writeframes((audio * 32767).astype(np.int16).tobytes())
        raw = transcribe(wav_path)
        _log(f"transcribed: {raw!r}")
        if raw == "[no model installed]":
            state.set_ui_state("idle")
            threading.Thread(target=_prompt_model_setup, daemon=True).start()
            return
        if not raw: state.set_ui_state("idle"); return
        final = clean_with_ollama(raw) if config.USE_LLM_CLEANUP else raw
        state._add_history(final)
        if state._app and state._app._panel: state._app._panel._push_history()
        paste_text(final, target_app)
        state.set_ui_state("done"); time.sleep(0.6); state.set_ui_state("idle")
    except Exception as e:
        _log(f"process_recording: {e}")
        import traceback; _log(traceback.format_exc())
        state.set_ui_state("idle")
    finally:
        if wav_path and os.path.exists(wav_path): os.unlink(wav_path)
