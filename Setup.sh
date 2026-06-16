#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Setup.sh — Local Murmur one-time setup for Apple Silicon
#  Run once:  chmod +x Setup.sh && ./Setup.sh
# ─────────────────────────────────────────────────────────────
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${GREEN}[✓]${NC} $1"; }
warn()    { echo -e "${YELLOW}[!]${NC} $1"; }
error()   { echo -e "${RED}[✗]${NC} $1"; exit 1; }
section() { echo -e "\n${YELLOW}── $1 ──${NC}"; }

echo ""
echo "  🎙️  Local Murmur — Setup for Apple Silicon"
echo "  ──────────────────────────────────────────"
echo ""

# ── 1. Homebrew ───────────────────────────────────────────────
section "Homebrew"
if ! command -v brew &>/dev/null; then
    warn "Homebrew not found — installing…"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null || true
else
    info "Homebrew already installed"
fi

# ── 2. System deps ────────────────────────────────────────────
section "System dependencies"
brew install cmake portaudio 2>/dev/null || true
info "cmake + portaudio ready"

# ── 3. Whisper.cpp ────────────────────────────────────────────
section "Whisper.cpp"
WHISPER_DIR="$HOME/whisper.cpp"

if [ ! -d "$WHISPER_DIR" ]; then
    info "Cloning whisper.cpp…"
    git clone https://github.com/ggml-org/whisper.cpp.git "$WHISPER_DIR"
else
    info "whisper.cpp already cloned — pulling latest"
    git -C "$WHISPER_DIR" pull --ff-only 2>/dev/null || true
fi

info "Building with Metal (Apple Neural Engine)…"
cd "$WHISPER_DIR"
cmake -B build -DWHISPER_METAL=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j"$(sysctl -n hw.logicalcpu)"
info "Build complete"

# ── 4. Whisper model ──────────────────────────────────────────
section "Whisper model  (medium, ~1.5 GB)"
MODEL_PATH="$WHISPER_DIR/models/ggml-medium.bin"

if [ ! -f "$MODEL_PATH" ]; then
    info "Downloading medium model…"
    cd "$WHISPER_DIR"
    bash models/download-ggml-model.sh medium
else
    info "Model already downloaded"
fi

# ── 5. Python deps ────────────────────────────────────────────
section "Python packages  (sounddevice · numpy · pynput)"
if ! command -v python3 &>/dev/null; then
    brew install python3
fi

pip3 install --upgrade sounddevice numpy pynput rumps \
    pyobjc-framework-WebKit pyobjc-framework-AVFoundation 2>/dev/null || \
    pip3 install --break-system-packages sounddevice numpy pynput rumps \
    pyobjc-framework-WebKit pyobjc-framework-AVFoundation
info "Python packages installed"

# ── 6. Ollama (optional — only used when USE_LLM_CLEANUP=True) ─
section "Ollama  (optional — Hinglish cleanup)"
if ! command -v ollama &>/dev/null; then
    warn "Ollama not found — installing…"
    brew install ollama
else
    info "Ollama already installed"
fi
info "Pulling llama3.2…"
ollama pull llama3.2

# ── 7. Permissions reminder ───────────────────────────────────
section "macOS Permissions  (System Settings → Privacy & Security)"
echo ""
echo "  ✅ Microphone       — voice capture"
echo "  ✅ Accessibility    — simulate Cmd+V paste"
echo "  ✅ Input Monitoring — global hotkey"
echo ""

# ── Done ──────────────────────────────────────────────────────
echo "════════════════════════════════════════════════════════"
echo "  ✅  Setup complete!"
echo ""
echo "  Re-open Local Murmur from your Applications folder."
echo "════════════════════════════════════════════════════════"
echo ""
