import queue

import rumps

from . import config, state
from .hud import FloatingHUD
from .log import _log
from .webui import SettingsPanel


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
        super().__init__("\U0001f399", quit_button="Quit Local Murmur")
        self._hud    = FloatingHUD()
        self._panel  = SettingsPanel()
        self._status = rumps.MenuItem("● Idle — hold key to dictate")
        self.menu    = [self._status, None,
                        rumps.MenuItem("Open Settings", callback=self._open_settings)]
        self._timer  = rumps.Timer(self._poll, 0.05)
        self._timer.start()
        self._hb = 0                   # heartbeat counter
        state.set_ui_state("idle")     # show pill immediately once RunLoop fires
        # Auto-open settings once on launch — land on Models if none is installed yet.
        def _open_once(t):
            t.stop()
            self._panel.show()
            if not config._model_downloaded(config.MODEL_ID):
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
                ui_state = state._ui_queue.get_nowait()
                self.title         = self._ICONS.get(ui_state, "\U0001f399")
                self._status.title = self._LABELS.get(ui_state, "● Idle")
                self._hud.update(ui_state)
                self._panel.update(ui_state)
        except queue.Empty:
            pass

        # ── track dock position every tick so pill follows auto-hide dock ────────
        self._hud.sync_position()

        # ── heartbeat: re-raise pill every 500 ms so it never stays hidden ──────
        self._hb += 1
        if self._hb >= 10:             # 10 × 50 ms = 500 ms
            self._hb = 0
            self._hud.keep_visible()
