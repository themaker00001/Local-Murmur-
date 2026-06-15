import json
import sys
from pathlib import Path

from .log import _log

# ── Bundled binaries / assets ──────────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    _bundle_dir = Path(sys._MEIPASS)
    WHISPER_BIN = _bundle_dir / "whisper-cli"
    ASSETS_DIR  = _bundle_dir / "localmurmur" / "assets"
else:
    WHISPER_BIN = Path.home() / "whisper.cpp" / "build" / "bin" / "whisper-cli"
    ASSETS_DIR  = Path(__file__).resolve().parent / "assets"

WHISPER_LANG      = "auto"  # auto-detect the spoken language
WHISPER_TRANSLATE = True    # translate the detected language to English
WHISPER_THREADS   = 8

# ── Models ───────────────────────────────────────────────────────────────────
# Models are downloaded on demand (not bundled) — keeps the app small and lets
# users pick the speed/accuracy tradeoff that fits their Mac.
MODELS_DIR         = Path.home() / "Library" / "Application Support" / "Local Murmur" / "models"
_LEGACY_MODELS_DIR = Path.home() / "whisper.cpp" / "models"   # from older Setup.sh runs
MODEL_BASE_URL     = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"

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
     "desc": "Best for multilingual & mixed-language speech."},
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

# ── Settings persistence ────────────────────────────────────────────────────────
_SETTINGS_PATH = Path.home() / ".localmurmur" / "settings.json"


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
