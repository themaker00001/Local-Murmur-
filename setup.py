from setuptools import setup

APP = ["flow.py"]

OPTIONS = {
    # argv_emulation MUST be False on macOS 11+.
    # True intercepts Apple Events and causes the app to hang on launch.
    "argv_emulation": False,

    "packages": [
        "sounddevice",
        "_sounddevice_data",   # bundled portaudio binary
        "numpy",
        "pynput",
        "pynput.keyboard",
        "pynput.mouse",
        "pynput._util",
        "pynput._util.darwin",
    ],

    "includes": [
        "tkinter",
        "tkinter.font",
        "_tkinter",
        "wave",
        "tempfile",
        "threading",
        "subprocess",
        "json",
        "math",
        "signal",
        "urllib.request",
        "urllib.error",
        "pathlib",
    ],

    "excludes": [
        "matplotlib", "scipy", "PIL", "IPython",
        "pandas", "PyQt5", "PyQt6", "wx",
    ],

    "plist": {
        "CFBundleName":             "Local Murmur",
        "CFBundleDisplayName":      "Local Murmur",
        "CFBundleIdentifier":       "com.localmurmur.dictation",
        "CFBundleVersion":          "1.1.0",
        "CFBundleShortVersionString": "1.1.0",
        "NSHighResolutionCapable":  True,
        "NSMicrophoneUsageDescription":
            "Local Murmur uses your microphone to capture voice for dictation.",
        "NSAppleEventsUsageDescription":
            "Local Murmur uses AppleScript to paste dictated text into other apps.",
    },
}

setup(
    name="Local Murmur",
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
