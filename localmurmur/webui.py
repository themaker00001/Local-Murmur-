import json
import threading
import time
import urllib.request

from . import config, hotkey, state
from .log import _log

try:
    import rumps
except ImportError:
    import sys
    sys.exit("Missing: pip install rumps")

try:
    from AppKit import (
        NSWindow, NSBackingStoreBuffered,
        NSScreen, NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
        NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskResizable,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
    )
    from Foundation import NSMakeRect, NSObject, NSURL
    HAS_APPKIT = True
except Exception as e:
    _log(f"AppKit import error: {e}"); HAS_APPKIT = False

try:
    from WebKit import WKWebView, WKWebViewConfiguration, WKUserContentController
    HAS_WEBVIEW = True
except Exception as e:
    _log(f"WebKit import error: {e}"); HAS_WEBVIEW = False


# ── Module-level API helpers (kept outside NSObject to avoid pyobjc issues) ───

def _api_save_setting(body: dict):
    key, val = body.get("key",""), body.get("value", False)
    if key == "use_llm_cleanup": config.USE_LLM_CLEANUP = bool(val)
    elif key == "sound_start":   config.SOUND_START     = bool(val)
    config._save_settings(); _log(f"setting {key}={val}")


def _api_save_accent(body: dict):
    config.ACCENT_COLOR = str(body.get("value", config.ACCENT_COLOR))
    config._save_settings(); _log(f"accent={config.ACCENT_COLOR}")


def _api_save_hotkey(body: dict):
    k = str(body.get("value", config.HOTKEY))
    if k not in config.HOTKEY_LABELS:
        _log(f"hotkey rejected — unknown key: {k!r}")
        return
    config.HOTKEY = k
    config._save_settings()
    _log(f"hotkey changing to {config.HOTKEY} — restarting monitor")
    hotkey._start_keyboard_monitor()
    _log(f"hotkey monitor restarted: {config.HOTKEY}")


# ── Model download manager ────────────────────────────────────────────────────
_dl_lock  = threading.Lock()
_dl_state = {"id": None, "cancel": None}


def _download_model_async(model_id: str, panel):
    m = config._MODEL_BY_ID.get(model_id)
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
        config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
        dest = config.MODELS_DIR / m["file"]
        tmp  = dest.with_name(dest.name + ".part")
        url  = f"{config.MODEL_BASE_URL}/{m['file']}"
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
            if not config._model_downloaded(config.MODEL_ID) or config.MODEL_ID == model_id:
                config.MODEL_ID = model_id
                config.WHISPER_MODEL = config._model_path(config.MODEL_ID)
                config._save_settings()
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
    if mid not in config._MODEL_BY_ID: return
    _download_model_async(mid, _ApiHandler._panel_ref)


def _api_cancel_download(_body: dict):
    _cancel_download()


def _api_set_active_model(body: dict):
    mid = str(body.get("value", ""))
    if mid not in config._MODEL_BY_ID or not config._model_downloaded(mid): return
    config.MODEL_ID = mid
    config.WHISPER_MODEL = config._model_path(config.MODEL_ID)
    config._save_settings()
    _log(f"active model -> {config.MODEL_ID}")
    if _ApiHandler._panel_ref: _ApiHandler._panel_ref._push_model_info()


def _api_delete_model(body: dict):
    mid = str(body.get("value", ""))
    m = config._MODEL_BY_ID.get(mid)
    if not m or mid == config.MODEL_ID: return
    for base in (config.MODELS_DIR, config._LEGACY_MODELS_DIR):
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


# Signals when the WKWebView has finished loading settings.html so queued
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
        _log(f"SettingsPanel APPKIT={HAS_APPKIT} WEB={HAS_WEBVIEW}")
        if not (HAS_APPKIT and HAS_WEBVIEW): return
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

        # file:// URLs give the page a secure origin so that
        # window.webkit.messageHandlers and getUserMedia both work, while
        # allowingReadAccessToURL lets settings.html pull in settings.css/.js.
        html_url = NSURL.fileURLWithPath_(str(config.ASSETS_DIR / "settings.html"))
        dir_url  = NSURL.fileURLWithPath_(str(config.ASSETS_DIR))
        self._webview.loadFileURL_allowingReadAccessToURL_(html_url, dir_url)

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

    def update(self, ui_state: str):
        self._js(f"updateState('{ui_state}')")

    def _push_settings(self):
        d = json.dumps({"use_llm_cleanup": config.USE_LLM_CLEANUP, "sound_start": config.SOUND_START})
        self._js(f"loadSettings({d})")

    def _push_history(self):
        self._js(f"loadHistory({json.dumps(state._history[:50])})")

    def _push_model_info(self):
        info = json.dumps({
            "model":     config._MODEL_BY_ID[config.MODEL_ID]["label"],
            "modelId":   config.MODEL_ID,
            "threads":   str(config.WHISPER_THREADS),
            "lang":      config.WHISPER_LANG,
            "catalog":   config.MODEL_CATALOG,
            "status":    config._model_status(),
            "defaultId": config.DEFAULT_MODEL_ID,
        })
        self._js(f"loadModelInfo({info})")

    def _push_accent(self):
        self._js(f"loadAccentColor('{config.ACCENT_COLOR}')")

    def _push_hotkey(self):
        self._js(f"loadHotkey('{config.HOTKEY}')")
