import subprocess

from . import state
from .log import _log


def _prompt_model_setup():
    """No transcription model installed yet — open Settings → Models for the user."""
    if state._app and state._app._panel:
        state._app._panel.show()
        state._app._panel._js("go('models')")


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
