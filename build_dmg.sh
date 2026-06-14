#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  build_dmg.sh — Build a distributable DMG for Local Flow
#
#  Uses PyInstaller to produce a real standalone macOS .app:
#    • Python bundled inside — stable dock icon, no shell launcher
#    • whisper-cli + its Metal/ggml dylibs are bundled (re-pathed to be
#      portable) so the app works on any Mac out of the box
#    • Whisper models are NOT bundled — the app downloads the model the
#      user picks from Settings → Models on first launch
#    • Works exactly like Wispr Flow
#
#  Output: dist/Local-Flow-1.1.0.dmg
# ─────────────────────────────────────────────────────────────

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
STEP=0
ok()      { echo -e "${GREEN}  ✓ PASS${NC}  $1"; }
fail()    { echo -e "${RED}  ✗ FAIL${NC}  $1"; }
section() { STEP=$((STEP+1)); echo -e "\n${BLUE}── Step $STEP: $1 ──${NC}"; }
warn()    { echo -e "${YELLOW}  ! WARN${NC}  $1"; }

trap 'echo -e "\n${RED}BUILD FAILED at Step $STEP — line $LINENO${NC}"; cleanup_on_fail' ERR
cleanup_on_fail() {
    [ -d "${STAGING_DIR:-}"  ] && rm -rf "$STAGING_DIR"
    [ -d "${WHISPER_STAGE:-}" ] && rm -rf "$WHISPER_STAGE"
    [ -f "${TEMP_DMG:-}"     ] && rm -f  "$TEMP_DMG"
}

APP_NAME="Local Flow"
VERSION="1.1.0"
BUNDLE_ID="com.localflow.dictation"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/dist"
STAGING_DIR="$SCRIPT_DIR/.dmg_staging"
FINAL_DMG="$OUTPUT_DIR/${APP_NAME// /-}-${VERSION}.dmg"
TEMP_DMG="$OUTPUT_DIR/tmp_rw.dmg"

echo ""
echo "  🎙️  Local Flow — DMG Builder  v${VERSION}  (PyInstaller)"
echo "  ──────────────────────────────────────────────────────"
echo "  Output : $FINAL_DMG"
echo ""

# ══════════════════════════════════════════════════════════════
# STEP 1 — Verify source files
# ══════════════════════════════════════════════════════════════
section "Verify source files"
for f in flow.py Setup.sh uninstall.sh; do
    [ -f "$SCRIPT_DIR/$f" ] && ok "Found: $f" || { fail "Missing: $f"; exit 1; }
done

# ══════════════════════════════════════════════════════════════
# STEP 2 — Check tools
# ══════════════════════════════════════════════════════════════
section "Check tools"
for t in hdiutil osascript python3; do
    command -v "$t" &>/dev/null && ok "Found: $t" || { fail "Missing: $t"; exit 1; }
done
python3 -c "import PyInstaller" 2>/dev/null \
    && ok "PyInstaller available" \
    || { warn "Installing PyInstaller…"; pip3 install pyinstaller --quiet; ok "PyInstaller installed"; }

# ══════════════════════════════════════════════════════════════
# STEP 3 — Clean build dirs
# ══════════════════════════════════════════════════════════════
section "Clean build dirs"
rm -rf "$STAGING_DIR" "$SCRIPT_DIR/build" "$OUTPUT_DIR/${APP_NAME}.app"
mkdir -p "$STAGING_DIR" "$OUTPUT_DIR"
[ -f "$FINAL_DMG" ] && { warn "Removing old DMG"; rm -f "$FINAL_DMG"; }
ok "Directories ready"

# ══════════════════════════════════════════════════════════════
# STEP 4 — Stage whisper-cli (portable, self-contained)
# ══════════════════════════════════════════════════════════════
section "Stage whisper-cli"

WHISPER_BUILD="$HOME/whisper.cpp/build"
WHISPER_STAGE="$SCRIPT_DIR/.whisper_stage"
rm -rf "$WHISPER_STAGE"; mkdir -p "$WHISPER_STAGE"

[ -f "$WHISPER_BUILD/bin/whisper-cli" ] || { fail "whisper-cli not built — run Setup.sh first"; exit 1; }

cp "$WHISPER_BUILD/bin/whisper-cli"                           "$WHISPER_STAGE/"
cp "$WHISPER_BUILD/src/libwhisper.1.dylib"                    "$WHISPER_STAGE/"
cp "$WHISPER_BUILD/ggml/src/libggml.0.dylib"                  "$WHISPER_STAGE/"
cp "$WHISPER_BUILD/ggml/src/libggml-cpu.0.dylib"              "$WHISPER_STAGE/"
cp "$WHISPER_BUILD/ggml/src/ggml-blas/libggml-blas.0.dylib"   "$WHISPER_STAGE/"
cp "$WHISPER_BUILD/ggml/src/ggml-metal/libggml-metal.0.dylib" "$WHISPER_STAGE/"
cp "$WHISPER_BUILD/ggml/src/libggml-base.0.dylib"             "$WHISPER_STAGE/"
chmod u+w "$WHISPER_STAGE"/*
ok "Copied whisper-cli + Metal/ggml dylibs ($(du -sh "$WHISPER_STAGE" | cut -f1))"

# whisper-cli is built with @rpath entries that point at this machine's
# whisper.cpp checkout. Rewrite them to @executable_path so the binary finds
# its dylibs sitting right next to it once bundled — and works on any Mac.
for f in "$WHISPER_STAGE"/*; do
    for dep in $(otool -L "$f" | tail -n +2 | awk '{print $1}' | grep '^@rpath/' || true); do
        install_name_tool -change "$dep" "@executable_path/${dep#@rpath/}" "$f"
    done
    install_name_tool -id "@executable_path/$(basename "$f")" "$f" 2>/dev/null || true
done
ok "Rewrote library paths to @executable_path"

# ══════════════════════════════════════════════════════════════
# STEP 5 — Build standalone .app with PyInstaller
# ══════════════════════════════════════════════════════════════
section "Build ${APP_NAME}.app  (PyInstaller — Python bundled inside)"
cd "$SCRIPT_DIR"

WHISPER_BINARIES=()
for f in "$WHISPER_STAGE"/*; do
    WHISPER_BINARIES+=( --add-binary "$f:." )
done

python3 -m PyInstaller \
    --windowed \
    --noconfirm \
    --name         "$APP_NAME" \
    --distpath     "$OUTPUT_DIR" \
    --workpath     "$SCRIPT_DIR/build" \
    "${WHISPER_BINARIES[@]}" \
    --collect-all  sounddevice \
    --collect-all  rumps \
    --collect-all  WebKit \
    --collect-all  AVFoundation \
    --hidden-import "AppKit" \
    --hidden-import "Foundation" \
    --hidden-import "WebKit" \
    --hidden-import "AVFoundation" \
    --hidden-import "objc" \
    --hidden-import "wave" \
    --exclude-module "tkinter" \
    --exclude-module "_tkinter" \
    --exclude-module "Tkinter" \
    --osx-bundle-identifier "$BUNDLE_ID" \
    flow.py 2>&1 | grep -v "^$" | sed 's/^/    /'

APP_SRC="$OUTPUT_DIR/${APP_NAME}.app"
[ -d "$APP_SRC" ] || { fail "PyInstaller did not produce ${APP_NAME}.app"; exit 1; }
ok "PyInstaller build complete"

# Patch Info.plist with permission descriptions PyInstaller doesn't add
PLIST="$APP_SRC/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :NSHighResolutionCapable true" "$PLIST" 2>/dev/null || \
    /usr/libexec/PlistBuddy -c "Add :NSHighResolutionCapable bool true" "$PLIST"
/usr/libexec/PlistBuddy -c \
    "Add :NSMicrophoneUsageDescription string 'Local Flow uses your microphone to capture voice for dictation.'" \
    "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c \
    "Add :NSAppleEventsUsageDescription string 'Local Flow uses AppleScript to paste dictated text into other apps.'" \
    "$PLIST" 2>/dev/null || true
ok "Info.plist patched with permission descriptions"

# Re-sign so the updated Info.plist is bound to the signature.
# Without this, macOS ignores NSMicrophoneUsageDescription for TCC prompts.
codesign --force --deep --sign - "$APP_SRC" 2>&1 | sed 's/^/    /'
ok "App re-signed with updated Info.plist"

# Clean PyInstaller build dir
rm -rf "$SCRIPT_DIR/build" "$SCRIPT_DIR/${APP_NAME}.spec"
ok "Cleaned build intermediates"

# ══════════════════════════════════════════════════════════════
# STEP 6 — Staging
# ══════════════════════════════════════════════════════════════
section "Prepare DMG staging"
cp -R "$APP_SRC" "$STAGING_DIR/"
ln -s /Applications "$STAGING_DIR/Applications"
ok "App and /Applications symlink in staging"

# Generate DMG background if Pillow is available
if python3 -c "from PIL import Image" 2>/dev/null; then
    python3 "$SCRIPT_DIR/make_dmg_bg.py" 2>&1 | sed 's/^/    /'
    mkdir -p "$STAGING_DIR/.background"
    cp "$SCRIPT_DIR/dmg_background.png" "$STAGING_DIR/.background/background.png"
    ok "DMG background image added"
else
    warn "Pillow not installed — DMG will have plain background  (pip3 install Pillow)"
fi

# ══════════════════════════════════════════════════════════════
# STEP 7 — Create writable disk image
# ══════════════════════════════════════════════════════════════
section "Create disk image"
hdiutil create \
    -volname "${APP_NAME} ${VERSION}" \
    -srcfolder "$STAGING_DIR" \
    -ov -format UDRW \
    "$TEMP_DMG" 2>&1 | sed 's/^/    /'
[ -f "$TEMP_DMG" ] || { fail "hdiutil create failed"; exit 1; }
ok "Writable DMG ready"

# ══════════════════════════════════════════════════════════════
# STEP 8 — Compress
# ══════════════════════════════════════════════════════════════
section "Compress to final DMG"
hdiutil convert "$TEMP_DMG" \
    -format UDZO -imagekey zlib-level=9 \
    -o "$FINAL_DMG" 2>&1 | sed 's/^/    /'
[ -f "$FINAL_DMG" ] || { fail "hdiutil convert failed"; exit 1; }
rm -f "$TEMP_DMG"
ok "Final DMG: $FINAL_DMG"

# ══════════════════════════════════════════════════════════════
# STEP 9 — Verify & clean
# ══════════════════════════════════════════════════════════════
section "Verify and clean up"
hdiutil verify "$FINAL_DMG" 2>&1 | grep -qiE "error|fail" \
    && { fail "DMG verify failed"; exit 1; } || ok "hdiutil verify passed"
DMG_SIZE=$(du -m "$FINAL_DMG" | awk '{print $1}')
ok "DMG size: ${DMG_SIZE} MB"
rm -rf "$STAGING_DIR" "$WHISPER_STAGE"
ok "Staging removed"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  ✅  BUILD COMPLETE  v${VERSION}"
echo ""
echo "  DMG  : $FINAL_DMG"
echo "  Size : ${DMG_SIZE} MB"
echo ""
echo "  Install:"
echo "    1. open \"$FINAL_DMG\""
echo "    2. Drag  Local Flow → Applications"
echo "    3. Double-click Local Flow — starts immediately, no Terminal"
echo "    4. On first launch, pick a transcription model under Settings → Models"
echo "════════════════════════════════════════════════════════"
echo ""
