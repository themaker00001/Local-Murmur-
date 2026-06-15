document.addEventListener('DOMContentLoaded', () => {
  const btnTrigger = document.getElementById('btn-simulate-trigger');
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
  
  let isRunning = false;

  // Tab switching logic
  tabInput.addEventListener('click', () => {
    tabInput.classList.add('active');
    tabOutput.classList.remove('active');
    speechInput.classList.add('active');
    speechOutput.classList.remove('active');
  });

  tabOutput.addEventListener('click', () => {
    tabOutput.classList.add('active');
    tabInput.classList.remove('active');
    speechOutput.classList.add('active');
    speechInput.classList.remove('active');
  });

  // Typing effect helper
  function typeText(element, text, speed = 40) {
    return new Promise((resolve) => {
      element.innerHTML = '';
      let i = 0;
      function type() {
        if (i < text.length) {
          element.innerHTML += text.charAt(i);
          i++;
          // Auto-scroll inside editor area
          element.scrollTop = element.scrollHeight;
          setTimeout(type, speed);
        } else {
          resolve();
        }
      }
      type();
    });
  }

  // Dictation Simulator Flow
  btnTrigger.addEventListener('click', async () => {
    if (isRunning) return;
    isRunning = true;
    btnTrigger.disabled = true;
    btnTrigger.style.opacity = '0.7';

    // Step 1: Listening State (Whisper)
    micCircle.classList.add('recording');
    statusDot.className = 'status-dot recording';
    statusText.textContent = 'Listening (Right Option held)...';
    triggerLabel.textContent = 'Recording speech...';
    
    // Switch to input tab
    tabInput.click();
    speechInput.innerHTML = '<span class="typing-cursor"></span>';
    
    // Simulate typing the raw dictation text
    await typeText(speechInput, rawSpeechText, 50);
    
    // Brief delay once user "releases" hotkey
    micCircle.classList.remove('recording');
    statusDot.className = 'status-dot processing';
    statusText.textContent = 'Processing (Ollama + Llama 3.2)...';
    triggerLabel.textContent = 'Cleaning filler words...';
    
    // Step 2: Processing (Ollama)
    await new Promise((resolve) => setTimeout(resolve, 1500));
    
    // Switch to output tab
    tabOutput.click();
    speechOutput.innerHTML = '<span class="typing-cursor"></span>';
    statusDot.className = 'status-dot pasting';
    statusText.textContent = 'Pasting text...';
    triggerLabel.textContent = 'Formatting output...';

    // Step 3: Type polished output
    await typeText(speechOutput, polishedSpeechText, 35);
    
    // Step 4: Finished/Ready state
    statusDot.className = 'status-dot';
    statusText.textContent = 'Pasted successfully!';
    triggerLabel.textContent = 'Reset Simulator';
    btnTrigger.disabled = false;
    btnTrigger.style.opacity = '1';
    
    // Click again resets the simulator
    const resetHandler = () => {
      speechInput.innerHTML = '<span class="placeholder">Hold Right Option to speak...</span>';
      speechOutput.innerHTML = '<span class="placeholder">Polished text will appear here...</span>';
      statusText.textContent = 'Ready';
      triggerLabel.textContent = 'Click to Simulate Dictation';
      tabInput.click();
      btnTrigger.removeEventListener('click', resetHandler);
      isRunning = false;
    };
    
    setTimeout(() => {
      btnTrigger.addEventListener('click', resetHandler);
    }, 100);
  });
});
