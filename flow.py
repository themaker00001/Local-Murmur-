#!/usr/bin/env python3.13
"""
Local Flow — Voice Dictation for Apple Silicon
- rumps menu bar  (Cocoa NSRunLoop)
- NSVisualEffectView frosted-glass HUD  (no emoji, coloured dot)
- WKWebView settings panel  (monochrome, accent picker, hotkey picker, mic test)
- Keyboard monitoring via system-Python subprocess + pynput  (user-configurable key)
- whisper.cpp Metal for transcription
"""

import signal
import sys
import warnings

warnings.filterwarnings("ignore", ".*ObjCPointer.*")   # suppress CGColor C-pointer noise

from localflow import config, state
from localflow.audio import audio_callback
from localflow.hotkey import _start_keyboard_monitor
from localflow.log import _log
from localflow.menubar import MenuBarApp

import sounddevice as sd
import rumps

_log("=== flow.py loaded ===")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 55)
    print("  \U0001f399  Local Flow — Voice Dictation")
    print("=" * 55)

    if not config.WHISPER_BIN.exists():
        sys.exit("\n❌ whisper-cli not found inside the app bundle. Please reinstall Local Flow.")

    if not config.WHISPER_MODEL.exists():
        print("\n⚠️  No transcription model installed yet.")
        print("   Open Settings → Models and download one to get started.\n")
    else:
        print(f"\n✅ Ready. Hold {config.HOTKEY_LABELS.get(config.HOTKEY, ('?','?'))[0]} in any app to speak.\n")

    _log("main() ready")

    stream = sd.InputStream(samplerate=state.SAMPLE_RATE, channels=1, dtype="float32",
                            callback=audio_callback, blocksize=1024)
    try: stream.start()
    except Exception as e:
        print(f"⚠️  Audio: {e} — grant Microphone permission then restart")

    _start_keyboard_monitor()

    _log("creating MenuBarApp")
    try: state._app = MenuBarApp()
    except Exception as e:
        _log(f"MenuBarApp FAILED: {e}")
        import traceback; _log(traceback.format_exc()); raise
    _log("MenuBarApp created — calling run()")

    signal.signal(signal.SIGINT, lambda *_: rumps.quit_application())
    state._app.run()
    _log("run() returned")
    stream.stop(); stream.close()


if __name__ == "__main__":
    main()
