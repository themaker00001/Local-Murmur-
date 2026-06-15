/* ── State ─── */
var S = {
  status:'idle', settings:{use_llm_cleanup:false,sound_start:true},
  accent:'#FFFFFF', hotkey:'alt_r', micOn:false,
  history:[], model:'Small', threads:'8', lang:'en',
  modelId:'small', defaultModelId:'small', catalog:[], modelStatus:{}, dl:null
};
var PAGE = 'hotkey';

var SM = {
  idle:         {cls:'',             txt:'Idle — hold activation key to dictate'},
  recording:    {cls:'recording',    txt:'Listening…'},
  transcribing: {cls:'transcribing', txt:'Transcribing…'},
  done:         {cls:'done',         txt:'Done!'}
};

var SWATCHES = [
  {hex:'#FFFFFF',label:'White'}, {hex:'#E0E0E0',label:'Silver'},
  {hex:'#7B61FF',label:'Indigo'},{hex:'#0A84FF',label:'Blue'},
  {hex:'#5AC8FA',label:'Teal'},  {hex:'#30D158',label:'Green'},
  {hex:'#FFB340',label:'Amber'}, {hex:'#FF453A',label:'Red'}
];

var KEY_OPTS = [
  {key:'alt_r',  sym:'⌥',label:'Right Option'},
  {key:'cmd_r',  sym:'⌘',label:'Right Cmd'},
  {key:'ctrl_r', sym:'⌃',label:'Right Ctrl'},
  {key:'shift_r',sym:'⇧',label:'Right Shift'},
  {key:'f13',    sym:'F13',   label:'F13'},
  {key:'f14',    sym:'F14',   label:'F14'}
];

/* ── Helpers ─── */
function x(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function trow(k,l,d,on){
  return '<div class="trow"><div><div class="tlabel">'+x(l)+'</div><div class="tdesc">'+x(d)+'</div></div>'
    +'<label class="sw"><input type="checkbox" '+(on?'checked':'')
    +' onchange="saveSetting(\''+k+'\',this.checked)"><div class="track"></div></label></div>';
}
function irow(k,v){ return '<div class="irow"><div class="ikey">'+x(k)+'</div><div class="ival">'+x(v)+'</div></div>'; }

/* ── Pages ─── */
function pageHotkey(){
  var sm=SM[S.status]||SM.idle;
  var keyLabel = '';
  KEY_OPTS.forEach(function(o){ if(o.key===S.hotkey) keyLabel=o.sym+' '+o.label; });

  var grid = KEY_OPTS.map(function(o){
    return '<div class="key-opt'+(o.key===S.hotkey?' selected':'')+'" onclick="pickHotkey(\''+o.key+'\')">'
      +'<span class="key-sym">'+o.sym+'</span>'
      +'<span class="key-name">'+o.label+'</span>'
      +'</div>';
  }).join('');

  return '<div class="page-title">Hotkey</div>'
    +'<div class="page-sub">Hold the key, speak, then release to transcribe.</div>'
    +'<div class="status-pill"><div class="dot '+sm.cls+'" id="sdot"></div><span id="stxt">'+sm.txt+'</span></div>'
    +'<div class="sec">Activation key</div>'
    +'<div class="key-grid">'+grid+'</div>'
    +'<div class="divider"></div>'
    +'<div class="sec">Options</div>'
    +'<div class="tgroup">'
    +trow('use_llm_cleanup','LLM Cleanup','Remove filler words via Ollama (runs locally)',S.settings.use_llm_cleanup)
    +trow('sound_start','Sound feedback','Play a beep when recording starts and stops',S.settings.sound_start)
    +'</div>';
}

function pageAppear(){
  var sw = SWATCHES.map(function(s){
    var sel=s.hex.toLowerCase()===S.accent.toLowerCase();
    var fg=s.hex==='#FFFFFF'||s.hex==='#E0E0E0'?'#111':'#fff';
    return '<div class="swatch'+(sel?' selected':'')+'" style="background:'+s.hex+';color:'+fg+';" onclick="pickAccent(\''+s.hex+'\')" title="'+s.label+'">'
      +'<span class="swatch-check">✓</span></div>';
  }).join('');
  return '<div class="page-title">Appearance</div>'
    +'<div class="page-sub">Choose an accent colour. Applied to highlights,<br>nav icons, toggles, and the mic meter.</div>'
    +'<div class="sec">Accent colour</div>'
    +'<div class="swatch-grid">'+sw+'</div>'
    +'<div class="divider"></div>'
    +'<div class="igroup">'+irow('Current',S.accent)+'</div>';
}

function fmtSize(mb){
  return mb>=1000 ? (mb/1024).toFixed(1)+' GB' : mb+' MB';
}

function modelCard(m){
  var st = S.modelStatus[m.id] || {downloaded:false, active:false};
  var dl  = (S.dl && S.dl.id===m.id) ? S.dl : null;
  var rec = (m.id===S.defaultModelId) ? ' <span class="model-badge rec">Recommended</span>' : '';

  var head = '<div class="mc-head"><div class="mc-name">'+x(m.label)+rec+'</div>'
    +'<div class="mc-size">'+fmtSize(m.size_mb)+'</div></div>';
  var desc = '<div class="mc-desc">'+x(m.desc)+'</div>';
  var tags = '<div class="mc-tags"><span class="mc-tag">Speed: '+x(m.speed)+'</span><span class="mc-tag">Accuracy: '+x(m.accuracy)+'</span></div>';

  var action;
  if(dl && (dl.status==='downloading')){
    action = '<div class="dl-row"><div class="dl-track"><div class="dl-fill" style="width:'+dl.pct.toFixed(0)+'%"></div></div>'
      +'<div class="dl-pct">'+dl.pct.toFixed(0)+'%</div></div>'
      +'<div class="dl-sub"><span>'+dl.downloadedMB+' / '+dl.totalMB+' MB</span><span class="mc-link" onclick="cancelDownload()">Cancel</span></div>';
  } else if(dl && dl.status==='error'){
    action = '<div class="mc-actions"><div class="mc-btn primary" onclick="downloadModel(\''+m.id+'\')">Retry download</div></div>'
      +'<div class="dl-err">'+x(dl.error||'Download failed')+'</div>';
  } else if(st.active){
    action = '<div class="model-badge active">Active</div>';
  } else if(st.downloaded){
    action = '<div class="mc-actions"><div class="mc-btn" onclick="useModel(\''+m.id+'\')">Use this model</div>'
      +'<span class="mc-link mc-del" onclick="deleteModel(\''+m.id+'\')">Delete</span></div>';
  } else if(S.dl && S.dl.status==='downloading'){
    action = '<div class="mc-actions"><div class="mc-btn primary disabled">Download</div></div>';
  } else {
    action = '<div class="mc-actions"><div class="mc-btn primary" onclick="downloadModel(\''+m.id+'\')">Download</div></div>';
  }

  return '<div class="model-card'+(st.active?' active':'')+'">'+head+desc+tags+action+'</div>';
}

function pageModels(){
  var anyDownloaded = Object.keys(S.modelStatus).some(function(k){ return S.modelStatus[k].downloaded; });
  var banner = anyDownloaded ? '' :
    '<div class="setup-banner"><b>Welcome to Local Flow!</b> Pick a model below and download it to '
    +'get started — Local Flow needs at least one model installed to transcribe your voice.</div>';

  var current = anyDownloaded ?
    '<div class="igroup">'+irow('Active model',S.model)+irow('Threads',S.threads)+irow('Language',S.lang)+irow('Engine','whisper.cpp (Metal)')+'</div><div class="divider"></div>'
    : '';

  var cards = (S.catalog||[]).map(modelCard).join('');

  return '<div class="page-title">Models</div>'
    +'<div class="page-sub">Choose how Local Flow turns speech into text. Bigger models are more accurate but take longer to download and run.</div>'
    +banner+current
    +'<div class="sec">Available models</div>'
    +'<div class="model-list">'+cards+'</div>';
}

function pageMic(){
  return '<div class="page-title">Microphone</div>'
    +'<div class="page-sub">Verify your mic is working before you dictate.</div>'
    +'<div class="sec">Live test</div>'
    +'<div class="test-btn'+(S.micOn?' active':'')+'" id="testBtn" onclick="toggleMicTest()">'
    +'<span id="testIco">'+(S.micOn?'■':'▶')+'</span>'
    +'<span id="testTxt">'+(S.micOn?'Stop test':'Start microphone test')+'</span>'
    +'</div>'
    +'<div class="vu-wrap'+(S.micOn?' on':'')+'" id="vuWrap">'
    +'<div class="vu-bars" id="vuBars">'
    +function(){var h='';for(var i=0;i<16;i++)h+='<div class="vu-bar" id="vb'+i+'"></div>';return h;}()
    +'</div>'
    +'<div class="vu-row"><div class="vu-track"><div class="vu-fill" id="vuFill"></div></div><div class="vu-pct" id="vuPct">0%</div></div>'
    +'<div class="vu-status"><div class="vu-sdot" id="vuSdot"></div><span id="vuMsg">Waiting for signal…</span></div>'
    +'</div>'
    +'<div class="mic-err" id="micErr"></div>';
}

function pageHistory(){
  if(!S.history.length)
    return '<div class="page-title">History</div><div class="empty">No transcriptions yet.<br>Hold your activation key and speak.</div>';
  var c=S.history.length;
  return '<div class="page-title">History</div>'
    +'<div class="page-sub">'+c+' transcription'+(c!==1?'s':'')+'</div>'
    +'<div class="hlist">'+S.history.map(function(h){
      return '<div class="hcard"><div class="hts">'+x(h.time)+'</div><div class="htxt">'+x(h.text)+'</div></div>';
    }).join('')+'</div>';
}

function pageAbout(){
  return '<div class="about"><div class="aico"><svg viewBox=\'0 0 1024 1024\' xmlns=\'http://www.w3.org/2000/svg\'><rect width=\'1024\' height=\'1024\' rx=\'224\' fill=\'#0D0D0D\'/><rect x=\'2\' y=\'2\' width=\'1020\' height=\'1020\' rx=\'222\' fill=\'none\' stroke=\'#fff\' stroke-opacity=\'.08\' stroke-width=\'4\'/><path d=\'M214 372A372 372 0 00214 652\' fill=\'none\' stroke=\'#fff\' stroke-width=\'26\' stroke-linecap=\'round\' opacity=\'.35\'/><path d=\'M810 372A372 372 0 01810 652\' fill=\'none\' stroke=\'#fff\' stroke-width=\'26\' stroke-linecap=\'round\' opacity=\'.35\'/><g transform=\'translate(512 498)\'><rect x=\'-92\' y=\'-230\' width=\'184\' height=\'320\' rx=\'92\' fill=\'#fff\'/><path d=\'M-196-20A196 196 0 00196-20\' fill=\'none\' stroke=\'#fff\' stroke-width=\'40\' stroke-linecap=\'round\'/><rect x=\'-20\' y=\'160\' width=\'40\' height=\'110\' rx=\'20\' fill=\'#fff\'/><rect x=\'-120\' y=\'248\' width=\'240\' height=\'40\' rx=\'20\' fill=\'#fff\'/></g></svg></div>'
    +'<div class="atitle">Local Flow</div><div class="aver">Version 1.2.0</div>'
    +'<div class="adesc">Voice dictation for Apple Silicon. Powered by whisper.cpp with Metal. Your voice never leaves your Mac.</div>'
    +'<div class="badges"><span class="badge">100% Local</span><span class="badge">No Cloud</span>'
    +'<span class="badge">No Subscription</span><span class="badge">Apple Silicon</span></div></div>';
}

var PAGES={hotkey:pageHotkey,appear:pageAppear,models:pageModels,mic:pageMic,history:pageHistory,about:pageAbout};

/* ── Navigation ─── */
function go(page){
  PAGE=page;
  document.querySelectorAll('.nav-item').forEach(function(el){
    el.classList.toggle('active',el.dataset.page===page);
  });
  document.getElementById('content').innerHTML=(PAGES[page]||pageHotkey)();
}

/* ── Accent ─── */
function applyAccent(hex){
  S.accent=hex;
  document.documentElement.style.setProperty('--accent',hex);
  var r=parseInt(hex.slice(1,3),16),g=parseInt(hex.slice(3,5),16),b=parseInt(hex.slice(5,7),16);
  document.documentElement.style.setProperty('--accent-rgb',r+' '+g+' '+b);
}
function pickAccent(hex){
  applyAccent(hex);
  pyPost({action:'saveAccentColor',value:hex});
  if(PAGE==='appear') go('appear');
}

/* ── Hotkey ─── */
function pickHotkey(key){
  S.hotkey=key;
  pyPost({action:'saveHotkey',value:key});
  if(PAGE==='hotkey') go('hotkey');
}

/* ── Mic test  (Web Audio API — no Python polling needed) ─── */
var _micStream=null, _micCtx=null, _micRaf=null;

function toggleMicTest(){
  S.micOn=!S.micOn;
  var btn=document.getElementById('testBtn');
  var ico=document.getElementById('testIco');
  var txt=document.getElementById('testTxt');
  var vw =document.getElementById('vuWrap');
  if(btn) btn.className='test-btn'+(S.micOn?' active':'');
  if(ico) ico.textContent=S.micOn?'■':'▶';
  if(txt) txt.textContent=S.micOn?'Stop test':'Start microphone test';
  if(vw)  vw.className='vu-wrap'+(S.micOn?' on':'');
  if(S.micOn){ startMicAudio(); } else { stopMicAudio(); resetVU(); }
}

function startMicAudio(){
  var err=document.getElementById('micErr');
  if(err){ err.style.display='none'; err.textContent=''; }
  navigator.mediaDevices.getUserMedia({audio:true,video:false})
    .then(function(stream){
      _micStream=stream;
      _micCtx=new (window.AudioContext||window.webkitAudioContext)();
      var src=_micCtx.createMediaStreamSource(stream);
      var ana=_micCtx.createAnalyser();
      ana.fftSize=256;
      src.connect(ana);
      var buf=new Uint8Array(ana.frequencyBinCount);
      function tick(){
        if(!S.micOn){ return; }
        ana.getByteFrequencyData(buf);
        var sum=0;
        for(var i=0;i<buf.length;i++) sum+=buf[i];
        var level=Math.min(100,(sum/buf.length/255)*100*4);
        updateMicLevel(level);
        _micRaf=requestAnimationFrame(tick);
      }
      tick();
    })
    .catch(function(e){
      S.micOn=false;
      var btn=document.getElementById('testBtn');
      var ico=document.getElementById('testIco');
      var txt=document.getElementById('testTxt');
      var vw =document.getElementById('vuWrap');
      if(btn) btn.className='test-btn';
      if(ico) ico.textContent='▶';
      if(txt) txt.textContent='Start microphone test';
      if(vw)  vw.className='vu-wrap';
      var err=document.getElementById('micErr');
      if(err){ err.style.display='block'; err.textContent='Mic access denied: '+e.message; }
    });
}

function stopMicAudio(){
  if(_micRaf){ cancelAnimationFrame(_micRaf); _micRaf=null; }
  if(_micStream){ _micStream.getTracks().forEach(function(t){t.stop();}); _micStream=null; }
  if(_micCtx){ _micCtx.close(); _micCtx=null; }
}

function resetVU(){
  for(var i=0;i<16;i++){
    var b=document.getElementById('vb'+i);
    if(b){ b.style.height='4px'; b.style.opacity='0.15'; }
  }
  var f=document.getElementById('vuFill'),p=document.getElementById('vuPct');
  var d=document.getElementById('vuSdot'),s=document.getElementById('vuMsg');
  if(f) f.style.width='0%';
  if(p) p.textContent='0%';
  if(d) d.className='vu-sdot';
  if(s) s.textContent='Waiting for signal…';
}

function updateMicLevel(level){
  for(var i=0;i<16;i++){
    var b=document.getElementById('vb'+i);
    if(!b) continue;
    var th=(i/16)*100, active=level>th;
    b.style.height=(active?Math.min(56,4+(level-th)*1.8):4)+'px';
    b.style.opacity=active?'1':'0.12';
  }
  var f=document.getElementById('vuFill'),p=document.getElementById('vuPct');
  var d=document.getElementById('vuSdot'),s=document.getElementById('vuMsg');
  if(f) f.style.width=Math.min(100,level)+'%';
  if(p) p.textContent=Math.round(level)+'%';
  if(d) d.className='vu-sdot'+(level>2?' ok':'');
  if(s) s.textContent=level>2?'Microphone working ✔':'No signal detected';
}

/* ── Python -> JS ─── */
function updateState(state){
  S.status=state;
  if(PAGE!=='hotkey') return;
  var sm=SM[state]||SM.idle;
  var d=document.getElementById('sdot'),t=document.getElementById('stxt');
  if(d) d.className='dot '+sm.cls;
  if(t) t.textContent=sm.txt;
}
function loadSettings(data){ S.settings=data; if(PAGE==='hotkey') go('hotkey'); }
function loadAccentColor(h){ applyAccent(h); if(PAGE==='appear') go('appear'); }
function loadHotkey(k){ S.hotkey=k; if(PAGE==='hotkey') go('hotkey'); }
function loadHistory(items){ S.history=items; if(PAGE==='history') go('history'); }
function loadModelInfo(info){
  if(info.model)     S.model=info.model;
  if(info.modelId)   S.modelId=info.modelId;
  if(info.threads)   S.threads=String(info.threads);
  if(info.lang)      S.lang=info.lang;
  if(info.catalog)   S.catalog=info.catalog;
  if(info.status)    S.modelStatus=info.status;
  if(info.defaultId) S.defaultModelId=info.defaultId;
  if(PAGE==='models') go('models');
}
function downloadProgress(d){
  S.dl = (d.status==='downloading' || d.status==='error') ? d : null;
  if(PAGE==='models') go('models');
  if(d.status==='done' || d.status==='cancelled') pyPost({action:'getModelInfo'});
}

/* ── JS -> Python ─── */
function pyPost(msg){
  try{ window.webkit.messageHandlers.api.postMessage(msg); }
  catch(e){ console.warn('pyPost failed',e); }
}
function saveSetting(k,v){ pyPost({action:'saveSetting',key:k,value:v}); }
function downloadModel(id){ pyPost({action:'downloadModel', value:id}); }
function cancelDownload(){ pyPost({action:'cancelDownload'}); }
function useModel(id){ pyPost({action:'setActiveModel', value:id}); }
function deleteModel(id){ pyPost({action:'deleteModel', value:id}); }

/* ── Init ─── */
go('hotkey');
setTimeout(function(){
  pyPost({action:'getSettings'});
  pyPost({action:'getHistory'});
  pyPost({action:'getModelInfo'});
  pyPost({action:'getAccentColor'});
  pyPost({action:'getHotkey'});
}, 100);
