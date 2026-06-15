document.addEventListener('DOMContentLoaded', () => {
  const micCircle = document.getElementById('mic-circle');
  const triggerLabel = document.getElementById('trigger-label');
  const statusDot = document.querySelector('.status-dot');
  const statusText = document.getElementById('simulator-status');

  const tabInput = document.getElementById('tab-input');
  const tabOutput = document.getElementById('tab-output');
  const speechInput = document.getElementById('speech-input');
  const speechOutput = document.getElementById('speech-output');

  const rawSpeechText = "um... so yeah... the whisper model... like... should run completely... you know... offline on my mac and... uh... be super fast.";
  const polishedSpeechText = "The Whisper model should run completely offline on my Mac and be super fast.";

  // Manual tab switching stays available even while the demo loops
  tabInput.addEventListener('click', () => showTab(true));
  tabOutput.addEventListener('click', () => showTab(false));

  // App preview screenshot tabs (Hotkey / Models / History)
  document.querySelectorAll('.preview-tabs .tab-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.preview-tabs .tab-btn').forEach((b) => b.classList.remove('active'));
      document.querySelectorAll('.preview-img').forEach((img) => img.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(btn.dataset.target).classList.add('active');
    });
  });

  function showTab(showInput) {
    tabInput.classList.toggle('active', showInput);
    tabOutput.classList.toggle('active', !showInput);
    speechInput.classList.toggle('active', showInput);
    speechOutput.classList.toggle('active', !showInput);
  }

  function delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  // Typing effect helper
  function typeText(element, text, speed = 40) {
    return new Promise((resolve) => {
      element.innerHTML = '';
      let i = 0;
      function type() {
        if (i < text.length) {
          element.innerHTML += text.charAt(i);
          i++;
          element.scrollTop = element.scrollHeight;
          setTimeout(type, speed);
        } else {
          resolve();
        }
      }
      type();
    });
  }

  // One full record -> clean -> paste cycle of the live demo
  async function runCycle() {
    // Reset to idle
    showTab(true);
    speechInput.innerHTML = '<span class="placeholder">Hold Right Option to speak...</span>';
    speechOutput.innerHTML = '<span class="placeholder">Polished text will appear here...</span>';
    statusDot.className = 'status-dot';
    statusText.textContent = 'Ready';
    triggerLabel.textContent = 'Idle — waiting for hotkey';
    await delay(1500);

    // Recording (Whisper)
    micCircle.classList.add('recording');
    statusDot.className = 'status-dot recording';
    statusText.textContent = 'Listening (Right Option held)...';
    triggerLabel.textContent = 'Recording speech...';
    speechInput.innerHTML = '<span class="typing-cursor"></span>';
    await typeText(speechInput, rawSpeechText, 45);

    // Processing (Ollama)
    micCircle.classList.remove('recording');
    statusDot.className = 'status-dot processing';
    statusText.textContent = 'Processing (Ollama + Llama 3.2)...';
    triggerLabel.textContent = 'Cleaning filler words...';
    await delay(1200);

    // Pasting polished output
    showTab(false);
    speechOutput.innerHTML = '<span class="typing-cursor"></span>';
    statusDot.className = 'status-dot pasting';
    statusText.textContent = 'Pasting text...';
    triggerLabel.textContent = 'Formatting output...';
    await typeText(speechOutput, polishedSpeechText, 32);

    // Done
    statusDot.className = 'status-dot';
    statusText.textContent = 'Pasted successfully!';
    triggerLabel.textContent = 'Done — looping again...';
    await delay(2500);
  }

  async function loop() {
    // eslint-disable-next-line no-constant-condition
    while (true) {
      await runCycle();
    }
  }

  loop();
});
