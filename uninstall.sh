#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  uninstall.sh — Fully remove Local Murmur and everything
#                 installed by Setup.sh / the DMG
#  Run:  chmod +x uninstall.sh && ./uninstall.sh
# ─────────────────────────────────────────────────────────────

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

ok()      { echo -e "${GREEN}  ✓${NC}  $1"; }
skip()    { echo -e "${YELLOW}  -${NC}  $1 — not found, skipping"; }
removed() { echo -e "${GREEN}  ✓${NC}  Removed: $1${2:+  ($2 freed)}"; }
section() { echo -e "\n${BLUE}── $1 ──${NC}"; }
ask()     { read -r -p "$(echo -e "${YELLOW}  ?${NC}  $1 (y/N): ")" _ans
            [[ "$_ans" == "y" || "$_ans" == "Y" ]]; }

disk_size() { du -sh "$1" 2>/dev/null | cut -f1 || echo "?"; }

echo ""
echo "  🗑️  Local Murmur — Full Uninstaller"
echo "  ──────────────────────────────────"
echo ""

# ── Inventory ────────────────────────────────────────────────
section "What will be removed"

HAS_LAUNCHAGENT=false
HAS_FLOWPY=false
HAS_LOCALMURMUR_DIR=false
HAS_FW_CACHE=false
HAS_APP=false
HAS_WHISPER=false
HAS_OLLAMA_MODELS=false
HAS_OLLAMA_APP=false
HAS_PORTAUDIO=false
HAS_CMAKE=false
HAS_LOGS=false

PLIST_PATH="$HOME/Library/LaunchAgents/com.localmurmur.dictation.plist"
WHISPER_DIR="$HOME/whisper.cpp"
LOCALMURMUR_DIR="$HOME/.localmurmur"
FW_CACHE_DIR="$HOME/.cache/huggingface/hub"

[ -f "$PLIST_PATH" ] \
    && HAS_LAUNCHAGENT=true && echo "  • LaunchAgent plist"
pkill -0 -f "flow.py" 2>/dev/null \
    && echo "  • flow.py (running process)"
[ -f "$HOME/flow.py" ] \
    && HAS_FLOWPY=true && echo "  • ~/flow.py"
[ -d "$LOCALMURMUR_DIR" ] \
    && HAS_LOCALMURMUR_DIR=true \
    && echo "  • ~/.localmurmur/  venv + config  ($(disk_size "$LOCALMURMUR_DIR"))"
[ -d "/Applications/Local Murmur.app" ] \
    && HAS_APP=true && echo "  • /Applications/Local Murmur.app"
[ -d "$WHISPER_DIR" ] \
    && HAS_WHISPER=true \
    && echo "  • ~/whisper.cpp  ($(disk_size "$WHISPER_DIR"))"

# faster-whisper model cache (Systran/faster-whisper-* on HuggingFace)
if [ -d "$FW_CACHE_DIR" ]; then
    FW_MODEL_DIRS=$(find "$FW_CACHE_DIR" -maxdepth 1 -name "*faster-whisper*" -type d 2>/dev/null || true)
    if [ -n "$FW_MODEL_DIRS" ]; then
        HAS_FW_CACHE=true
        echo "$FW_MODEL_DIRS" | while read -r d; do
            echo "  • faster-whisper model cache: $(basename "$d")  ($(disk_size "$d"))"
        done
    fi
fi

if command -v ollama &>/dev/null; then
    OLLAMA_MODELS=$(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' || true)
    if echo "$OLLAMA_MODELS" | grep -qE "llama3|nomic"; then
        HAS_OLLAMA_MODELS=true
        echo "$OLLAMA_MODELS" | grep -E "llama3|nomic" | while read -r m; do
            echo "  • Ollama model: $m"
        done
    fi
    HAS_OLLAMA_APP=true
    echo "  • Ollama app  (optional — will ask)"
fi

command -v brew &>/dev/null && brew list portaudio &>/dev/null 2>&1 \
    && HAS_PORTAUDIO=true && echo "  • Homebrew: portaudio  (optional — will ask)"
command -v brew &>/dev/null && brew list cmake &>/dev/null 2>&1 \
    && HAS_CMAKE=true && echo "  • Homebrew: cmake  (optional — will ask)"

for f in /tmp/localmurmur.log /tmp/localmurmur.err "$HOME/Library/Logs/localmurmur.log"; do
    [ -f "$f" ] && HAS_LOGS=true && echo "  • Log: $f"
done

echo ""
echo "  System Python packages (faster-whisper, rumps, sounddevice, numpy, pynput) — will ask"
echo ""

ask "Proceed with uninstall?" || { echo ""; echo "  Cancelled. Nothing removed."; echo ""; exit 0; }

echo ""

# ══════════════════════════════════════════════════════════════
# 1. Stop and remove LaunchAgent
# ══════════════════════════════════════════════════════════════
section "LaunchAgent"
if $HAS_LAUNCHAGENT; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    removed "$PLIST_PATH"
else
    skip "LaunchAgent plist"
fi

# ══════════════════════════════════════════════════════════════
# 2. Kill running processes
# ══════════════════════════════════════════════════════════════
section "Stop running processes"
pkill -f "flow.py"     2>/dev/null && ok "flow.py stopped"     || skip "flow.py process"
pkill -f "whisper-cli" 2>/dev/null && ok "whisper-cli stopped" || true

# ══════════════════════════════════════════════════════════════
# 3. Remove Local Murmur.app
# ══════════════════════════════════════════════════════════════
section "Local Murmur.app"
if $HAS_APP; then
    SIZE=$(disk_size "/Applications/Local Murmur.app")
    rm -rf "/Applications/Local Murmur.app"
    removed "/Applications/Local Murmur.app" "$SIZE"
else
    skip "/Applications/Local Murmur.app"
fi

# ══════════════════════════════════════════════════════════════
# 4. Remove ~/flow.py  (legacy location from old setup)
# ══════════════════════════════════════════════════════════════
section "~/flow.py  (legacy)"
if $HAS_FLOWPY; then
    rm -f "$HOME/flow.py"
    removed "~/flow.py"
else
    skip "~/flow.py"
fi

# ══════════════════════════════════════════════════════════════
# 5. Remove ~/.localmurmur/  (venv, config, flow.py copy)
# ══════════════════════════════════════════════════════════════
section "~/.localmurmur/  (venv + app data)"
if $HAS_LOCALMURMUR_DIR; then
    SIZE=$(disk_size "$LOCALMURMUR_DIR")
    rm -rf "$LOCALMURMUR_DIR"
    removed "~/.localmurmur/" "$SIZE"
else
    skip "~/.localmurmur/"
fi

# ══════════════════════════════════════════════════════════════
# 6. Remove faster-whisper model cache
# ══════════════════════════════════════════════════════════════
section "faster-whisper model cache  (~/.cache/huggingface/hub)"
if $HAS_FW_CACHE; then
    echo "  These cached models are only used by Local Murmur."
    echo "  Skip this if you use faster-whisper in other projects."
    echo ""
    if ask "Remove faster-whisper model cache?"; then
        find "$FW_CACHE_DIR" -maxdepth 1 -name "*faster-whisper*" -type d 2>/dev/null | while read -r d; do
            SIZE=$(disk_size "$d")
            rm -rf "$d"
            removed "$(basename "$d")" "$SIZE"
        done
        # Remove parent dir if now empty
        rmdir "$FW_CACHE_DIR" 2>/dev/null && removed "~/.cache/huggingface/hub" || true
        rmdir "$HOME/.cache/huggingface" 2>/dev/null || true
    else
        ok "Kept faster-whisper model cache"
    fi
else
    skip "faster-whisper model cache"
fi

# ══════════════════════════════════════════════════════════════
# 7. Remove whisper.cpp  (C++ binary + ggml models)
# ══════════════════════════════════════════════════════════════
section "whisper.cpp + ggml models"
if $HAS_WHISPER; then
    SIZE=$(disk_size "$WHISPER_DIR")
    echo "  GGML models found:"
    find "$WHISPER_DIR/models" -name "*.bin" 2>/dev/null \
        | while read -r m; do echo "    - $(basename "$m")  ($(disk_size "$m"))"; done \
        || echo "    (none)"
    echo ""
    if ask "Remove ~/whisper.cpp and all ggml models?"; then
        rm -rf "$WHISPER_DIR"
        removed "~/whisper.cpp" "$SIZE"
    else
        ok "Kept ~/whisper.cpp"
    fi
else
    skip "~/whisper.cpp"
fi

# ══════════════════════════════════════════════════════════════
# 8. Remove Ollama models
# ══════════════════════════════════════════════════════════════
section "Ollama models"
if command -v ollama &>/dev/null; then
    ALL_MODELS=$(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' || true)
    if [ -n "$ALL_MODELS" ]; then
        echo "  Installed models:"
        echo "$ALL_MODELS" | while read -r m; do echo "    - $m"; done
        echo ""
        for model in llama3.2 nomic-embed-text; do
            if echo "$ALL_MODELS" | grep -q "$model"; then
                ollama rm "$model" 2>/dev/null && removed "Ollama model: $model" || true
            fi
        done
        REMAINING=$(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' || true)
        if [ -n "$REMAINING" ]; then
            echo ""
            echo "  Remaining models:"
            echo "$REMAINING" | while read -r m; do echo "    - $m"; done
            echo ""
            if ask "Remove ALL remaining Ollama models too?"; then
                echo "$REMAINING" | while read -r m; do
                    ollama rm "$m" 2>/dev/null && removed "Ollama model: $m" || true
                done
            else
                ok "Kept remaining Ollama models"
            fi
        fi
    else
        skip "No Ollama models found"
    fi
else
    skip "Ollama not installed"
fi

# ══════════════════════════════════════════════════════════════
# 9. Optionally remove Ollama app
# ══════════════════════════════════════════════════════════════
section "Ollama app"
if $HAS_OLLAMA_APP; then
    echo "  Ollama may be used by other tools on your Mac."
    if ask "Remove Ollama app completely?"; then
        launchctl unload "$HOME/Library/LaunchAgents/com.ollama.ollama.plist" 2>/dev/null || true
        pkill -f "ollama" 2>/dev/null || true
        brew uninstall ollama 2>/dev/null && removed "Ollama app" \
            || { brew uninstall --cask ollama 2>/dev/null && removed "Ollama (cask)"; } \
            || true
        if [ -d "$HOME/.ollama" ]; then
            SIZE=$(disk_size "$HOME/.ollama")
            rm -rf "$HOME/.ollama"
            removed "~/.ollama" "$SIZE"
        fi
    else
        ok "Kept Ollama app"
    fi
else
    skip "Ollama not installed"
fi

# ══════════════════════════════════════════════════════════════
# 10. Optionally remove Homebrew packages
# ══════════════════════════════════════════════════════════════
section "Homebrew packages  (portaudio, cmake)"
echo "  These may be used by other software on your Mac."
if ask "Remove portaudio and cmake via Homebrew?"; then
    $HAS_PORTAUDIO && { brew uninstall portaudio 2>/dev/null && removed "portaudio" || true; } \
        || skip "portaudio"
    $HAS_CMAKE && { brew uninstall cmake 2>/dev/null && removed "cmake" || true; } \
        || skip "cmake"
else
    ok "Kept Homebrew packages"
fi

# ══════════════════════════════════════════════════════════════
# 11. Optionally remove system Python packages
# ══════════════════════════════════════════════════════════════
section "System Python packages  (faster-whisper, rumps, sounddevice, numpy, pynput)"
echo "  These are global pip packages — may be used by other projects."
if ask "Remove system Python packages?"; then
    pip3 uninstall -y faster-whisper rumps sounddevice numpy pynput 2>/dev/null \
        || pip3 uninstall --break-system-packages -y \
               faster-whisper rumps sounddevice numpy pynput 2>/dev/null \
        || true
    ok "System Python packages removed"
else
    ok "Kept system Python packages"
fi

# ══════════════════════════════════════════════════════════════
# 12. Remove log files
# ══════════════════════════════════════════════════════════════
section "Log files"
REMOVED_LOGS=false
for f in /tmp/localmurmur.log /tmp/localmurmur.err "$HOME/Library/Logs/localmurmur.log"; do
    if [ -f "$f" ]; then
        rm -f "$f"
        removed "$f"
        REMOVED_LOGS=true
    fi
done
$REMOVED_LOGS || skip "Log files"

# ══════════════════════════════════════════════════════════════
# Done
# ══════════════════════════════════════════════════════════════
echo ""
echo "════════════════════════════════════════════════════"
echo "  ✅  Uninstall complete!"
echo "════════════════════════════════════════════════════"
echo ""
