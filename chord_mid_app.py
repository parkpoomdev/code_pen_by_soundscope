# -*- coding: utf-8 -*-
from __future__ import print_function, unicode_literals
from flask import Flask, request, render_template_string, send_file
import io, re
from mido import Message, MidiFile, MidiTrack, MetaMessage, bpm2tempo

app = Flask(__name__)

NOTE_TO_SEMITONE = {"C":0,"C#":1,"Db":1,"D":2,"D#":3,"Eb":3,"E":4,"F":5,"F#":6,"Gb":6,"G":7,"G#":8,"Ab":8,"A":9,"A#":10,"Bb":10,"B":11}

BASE_TRIADS = {
  "maj":[0,4,7], "":[0,4,7], "m":[0,3,7], "dim":[0,3,6], "aug":[0,4,8], "+":[0,4,8], "sus2":[0,2,7], "sus4":[0,5,7]
}
SEVENTHS = {"maj7":11, "m7":10, "7":10}
TENSIONS = {"b9":13,"9":14,"#9":15,"11":17,"#11":18,"b13":20,"13":21}

# include '\u00f8' for ø
CHORD_RE = re.compile(
  r"^" +
  r"([A-G](?:#|b)?)" +
  r"(?:(m7b5|\u00f87|\u00f8|maj7|m7|7|maj|m|dim|aug|\+|sus2|sus4)?" +
  r"(maj7|m7|7)?)?" +
  r"((?:add9|madd9|maj9|m9|9|11|13|6|m6)?)" +
  r"((?:b9|#9|9|11|#11|b13|13)*)" +
  r"$", re.I
)

def split_tensions(s):
  return re.findall(r"(b9|#9|9|11|#11|b13|13)", s, flags=re.I)

def sanitize(s):
  # normalize: flats/sharps, dashes to spaces, collapse spaces
  return (s.replace(u"♭","b").replace(u"♯","#").replace(u"\u00f8", u"\u00f8")
            .replace("-", " ").replace(u"–"," ").replace(u"—"," ")
            .strip())

def build_intervals(baseQual, explicit7th, shorthand, extras):
  st = set()
  is_half_dim = bool(re.match(r"^(m7b5|\u00f87|\u00f8)$", baseQual or "", re.I))
  if is_half_dim:
    for x in (0,3,6,10): st.add(x)
  else:
    tri = BASE_TRIADS.get(baseQual or "", BASE_TRIADS[""])
    for x in tri: st.add(x)

  sh = (shorthand or "").lower()
  if sh == "m6":
    st.clear(); [st.add(x) for x in BASE_TRIADS["m"]]; st.add(9)
  elif sh == "6":
    st.add(9)
  if sh == "madd9":
    st.clear(); [st.add(x) for x in BASE_TRIADS["m"]]; st.add(14)
  elif sh == "add9":
    st.add(14)
  if sh == "maj9":
    st.clear(); [st.add(x) for x in BASE_TRIADS["maj"]]; st.add(11); st.add(14)
  if sh == "m9":
    st.clear(); [st.add(x) for x in BASE_TRIADS["m"]];   st.add(10); st.add(14)
  if sh == "9":  st.add(10); st.add(14)
  if sh == "11": st.add(10); st.add(17)
  if sh == "13": st.add(10); st.add(21)

  if explicit7th and not is_half_dim:
    st.add(SEVENTHS[explicit7th])

  for t in extras:
    key = t.replace(u"♭","b").replace(u"♯","#").lower()
    if key in TENSIONS: st.add(TENSIONS[key])

  return sorted(st)

def chord_token_to_midi_notes(token):
  m = CHORD_RE.match(token)
  if not m: return None
  rootRaw, qualA, qualB, shorthand, extraStr = m.groups()
  baseQual = (qualA or "").lower()
  if baseQual == "maj": baseQual = ""
  if baseQual == u"\u00f8": baseQual = u"\u00f87"  # ø -> ø7
  explicit7th = ""
  if qualB and qualB.lower() in ("maj7","m7","7"):
    explicit7th = qualB.lower()
  elif qualA and qualA.lower() in ("maj7","m7","7") and baseQual not in ("m7b5", u"\u00f87", u"\u00f8"):
    explicit7th = qualA.lower(); baseQual = ""
  extras = split_tensions(extraStr or "")
  rootName = rootRaw[0].upper() + (rootRaw[1:] if len(rootRaw)>1 else "")
  if rootName not in NOTE_TO_SEMITONE: return None
  intervals = build_intervals(baseQual, explicit7th, shorthand or "", extras)
  rootMidi = 60 + NOTE_TO_SEMITONE[rootName]
  notes = [rootMidi - 12] + [rootMidi + semi for semi in intervals]
  return [n-12 if n>76 else n for n in notes]

def write_mid(tokens, bpm=90, bars=1, numer=4, denom=4, program=0, velocity=96, track_name="Chord Track"):
  parsed = [chord_token_to_midi_notes(t) for t in tokens]
  if any(v is None for v in parsed):
    bad = tokens[[i for i,v in enumerate(parsed) if v is None][0]]
    raise ValueError("Unknown chord: {0}".format(bad))

  mid = MidiFile(type=0, ticks_per_beat=480)
  track = MidiTrack(); mid.tracks.append(track)

  track.append(MetaMessage('set_tempo', tempo=bpm2tempo(bpm), time=0))
  track.append(MetaMessage('time_signature', numerator=numer, denominator=denom, clocks_per_click=24, notated_32nd_notes_per_beat=8, time=0))
  track.append(MetaMessage('key_signature', key='C', time=0))
  track.append(MetaMessage('track_name', name=track_name, time=0))
  track.append(MetaMessage('text', text=(" ".join(tokens))[:120], time=0))
  track.append(Message('control_change', channel=0, control=7, value=100, time=0))
  track.append(Message('program_change', channel=0, program=program, time=0))

  chord_ticks = mid.ticks_per_beat * numer * bars
  for chord in parsed:
    for n in chord:
      track.append(Message('note_on', note=n, velocity=velocity, time=0))
    first = True
    for n in chord:
      track.append(Message('note_off', note=n, velocity=64, time=chord_ticks if first else 0))
      first = False

  track.append(MetaMessage('end_of_track', time=0))
  bio = io.BytesIO(); mid.save(file=bio); bio.seek(0)
  return bio

PAGE = """
<!doctype html>
<title>Text → Chord MIDI</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 body{font-family:system-ui,Segoe UI,Arial;padding:24px;background:#f6f7fb;color:#111}
 .card{max-width:920px;margin:0 auto;background:#fff;border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.06);padding:20px}
 textarea,input,select{padding:.6rem;border:1px solid #d1d5db;border-radius:10px}
 .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:.5rem 0}
 button{padding:.6rem 1rem;border:none;border-radius:999px;background:#2563eb;color:#fff;font-weight:700;cursor:pointer}
 button[disabled]{opacity:.6;cursor:not-allowed}
 .small{color:#6b7280;font-size:.9rem;margin-top:6px}
 /* timeline visualization */
 .timeline{position:relative;height:56px;border:2px solid #e5e7eb;border-radius:12px;overflow:hidden;margin-top:10px;background:#f9fafb}
 .tl-track{position:absolute;inset:0;display:flex}
 .tl-chord{flex:1 0 auto;display:flex;align-items:center;justify-content:center;font-weight:700;color:#374151;border-right:2px solid #fff;background:#e5e7eb}
 .tl-chord:last-child{border-right:none}
 .tl-chord.active{background:#3b82f6;color:#fff}
 .playhead{position:absolute;top:0;bottom:0;width:2px;background:#ef4444;box-shadow:0 0 0 1px rgba(239,68,68,.2);transform:translateX(0)}
</style>
<div class="card">
  <h2>Text → Chord MIDI</h2>
  <form method="post">
    <div class="row">
      <textarea name="chords" rows="3" style="flex:1;min-width:420px" placeholder="Dm7 G7 Cmaj7 A7 Dm7 G7 Em7b5">Dm7 G7 Cmaj7 A7 Dm7 G7 Em7b5</textarea>
    </div>
    <div class="row">
      <label>BPM <input type="number" name="bpm" value="90" min="30" max="240" style="width:90px"></label>
      <label>Bars/chord <input type="number" name="bars" value="1" min="1" max="8" style="width:90px"></label>
      <label>Time Sig <input type="number" name="numer" value="4" min="1" max="12" style="width:70px"> /
        <input type="number" name="denom" value="4" min="1" max="8" style="width:70px"></label>
      <label>Program <input type="number" name="program" value="0" min="0" max="127" style="width:90px"></label>
      <label>Vel <input type="number" name="vel" value="96" min="1" max="127" style="width:70px"></label>
    </div>
    <div class="row">
      <button type="button" id="preview_play">▶ Preview</button>
      <button type="button" id="preview_stop" disabled>⏹ Stop</button>
      <button type="submit">⬇ Export MIDI</button>
    </div>
    <div id="pv_timeline" class="timeline" aria-label="Chord timeline"></div>
    <div id="pv_msg" class="small"></div>
    <div class="small">Supported: maj/m/m7/m7b5/ø7/7/maj7, add9, 6/m6, maj9/m9/9/11/13, b9/#9/11/#11/b13/13; roots with #/b.</div>
    {% if error %}<p style="color:#b91c1c">{{ error }}</p>{% endif %}
  </form>
</div>

{% raw %}
<script>
(function(){
  const $ = s => document.querySelector(s);
  const msg = t => { const el=$('#pv_msg'); if (el) el.textContent=t||''; };

  // Show JS errors on page
  window.addEventListener('error', e => msg('JS error: ' + (e.error?.message || e.message)));

  // Parser copied from code_pen.html
  const NOTE_TO_SEMITONE = {C:0,"C#":1,Db:1,D:2,"D#":3,Eb:3,E:4,F:5,"F#":6,Gb:6,G:7,"G#":8,Ab:8,A:9,"A#":10,Bb:10,B:11};
  const BASE_TRIADS = {"maj":[0,4,7],"":[0,4,7],"m":[0,3,7],"dim":[0,3,6],"aug":[0,4,8],"+":[0,4,8],"sus2":[0,2,7],"sus4":[0,5,7]};
  const SEVENTHS = {"maj7":11,"m7":10,"7":10};
  const TENSIONS = {"b9":13,"9":14,"#9":15,"11":17,"#11":18,"b13":20,"13":21};
  const CHORD_RE = new RegExp("^([A-G](?:#|b)?)(?:(m7b5|ø7|ø|maj7|m7|7|maj|m|dim|aug|[+]|sus2|sus4)?(maj7|m7|7)?)?((?:add9|madd9|maj9|m9|9|11|13|6|m6)?)((?:b9|#9|9|11|#11|b13|13)*)$","i");
  function splitTensions(s){ const r=[],re=/(b9|#9|9|11|#11|b13|13)/gi; let m; while((m=re.exec(s))) r.push(m[1]); return r; }
  function sanitizeInput(s){ return s.replace(/♭/g,"b").replace(/♯/g,"#").replace(/ø/g,"ø").replace(/[-–—]/g," ").replace(/\s+/g," ").trim(); }
  function renderTimeline(tokens){
    const el=document.getElementById('pv_timeline'); if(!el) return;
    const track=document.createElement('div'); track.className='tl-track'; track.style.width='100%';
    tokens.forEach(t=>{ const c=document.createElement('div'); c.className='tl-chord'; c.textContent=t; track.appendChild(c); });
    const ph=document.createElement('div'); ph.className='playhead';
    el.innerHTML=''; el.appendChild(track); el.appendChild(ph);
  }
  function buildIntervals(baseQual, explicit7th, shorthand, extras){
    const set=new Set(); const isHalf=/^(m7b5|ø7|ø)$/i.test(baseQual||"");
    if(isHalf){ [0,3,6,10].forEach(x=>set.add(x)); } else { (BASE_TRIADS[baseQual||""]||BASE_TRIADS[""]).forEach(x=>set.add(x)); }
    const sh=(shorthand||"").toLowerCase();
    if(sh==="m6"){ set.clear(); BASE_TRIADS["m"].forEach(x=>set.add(x)); set.add(9); }
    else if(sh==="6"){ set.add(9); }
    if(sh==="madd9"){ set.clear(); BASE_TRIADS["m"].forEach(x=>set.add(x)); set.add(14); }
    else if(sh==="add9"){ set.add(14); }
    if(sh==="maj9"){ set.clear(); BASE_TRIADS["maj"].forEach(x=>set.add(x)); set.add(11); set.add(14); }
    if(sh==="m9"){ set.clear(); BASE_TRIADS["m"].forEach(x=>set.add(x)); set.add(10); set.add(14); }
    if(sh==="9"){ set.add(10); set.add(14); }
    if(sh==="11"){ set.add(10); set.add(17); }
    if(sh==="13"){ set.add(10); set.add(21); }
    if(explicit7th && !isHalf) set.add(SEVENTHS[explicit7th]);
    extras.forEach(t=>{ const k=t.replace("♭","b").replace("♯","#"); const v=TENSIONS[k]; if(v!=null) set.add(v); });
    return Array.from(set).sort((a,b)=>a-b);
  }
  function chordToNotes(tok){
    const m=tok.match(CHORD_RE); if(!m) return null;
    let [,rootRaw,qa="",qb="",sh="",extra=""]=m;
    let base=(qa||"").toLowerCase(); if(base==="maj") base=""; if(base==="ø") base="ø7";
    let exp=""; if(qb && /^(maj7|m7|7)$/i.test(qb)) exp=qb.toLowerCase();
    else if(qa && /^(maj7|m7|7)$/i.test(qa) && !/^(m7b5|ø7|ø)$/i.test(qa)){ exp=qa.toLowerCase(); base=""; }
    const rootName=rootRaw[0].toUpperCase()+(rootRaw[1]||""); if(!(rootName in NOTE_TO_SEMITONE)) return null;
    const ints=buildIntervals(base,exp,(sh||"").toLowerCase(),splitTensions(extra));
    const root=60+NOTE_TO_SEMITONE[rootName]; const notes=ints.map(s=>root+s); notes.unshift(root-12);
    return notes.map(n=>n>76?n-12:n);
  }
  function midiToFreq(m){ return 440*Math.pow(2,(m-69)/12); }

  // Audio
  const actx = new (window.AudioContext||window.webkitAudioContext)();
  let playing=false, idx=0, timer=null, parsed=[], chordDur=1;

  function playTone(freq,dur=0.18,vol=0.25){
    const now=actx.currentTime, osc=actx.createOscillator(), g=actx.createGain();
    osc.type='sine'; osc.frequency.value=freq;
    g.gain.setValueAtTime(0,now);
    g.gain.linearRampToValueAtTime(vol,now+0.002);
    g.gain.exponentialRampToValueAtTime(0.0005,now+dur);
    osc.connect(g).connect(actx.destination);
    osc.start(now); osc.stop(now+dur+0.02);
  }
  function playChord(freqs,dur){ freqs.forEach(f=>playTone(f, Math.min(dur*0.95, 2.5), 0.22)); }

  async function onPlay(){
    try{
      const text=sanitizeInput(document.querySelector('[name="chords"]').value||"");
      const tokens=text.split(/\s+/).filter(Boolean);
      if(!tokens.length){ msg("Enter chords first"); return; }
      renderTimeline(tokens);
      parsed=tokens.map(ch=>chordToNotes(ch));
      if(parsed.some(v=>!v)){ const bad=tokens[parsed.findIndex(v=>!v)]; msg("Unknown chord: "+bad); return; }
      const bpm=Math.max(30,Math.min(240,+document.querySelector('[name="bpm"]').value||90));
      const bars=Math.max(1,Math.min(8,+document.querySelector('[name="bars"]').value||1));
      const numer=Math.max(1,Math.min(12,+document.querySelector('[name="numer"]').value||4));
      const secPerBeat=60/bpm; chordDur=secPerBeat*numer*bars;

      await actx.resume(); // user gesture required
      playing=true; idx=0; $('#preview_play').disabled=true; $('#preview_stop').disabled=false; msg("Previewing...");
      step();
    }catch(e){ msg("Preview error: " + (e.message||e)); }
  }
  function step(){
    if(!playing) return;
    const freqs=parsed[idx].map(midiToFreq);
    playChord(freqs, chordDur);
    const tl=document.getElementById('pv_timeline');
    const ph=tl?.querySelector('.playhead');
    const blocks=tl?Array.from(tl.querySelectorAll('.tl-chord')):[];
    const total=parsed.length; const tlWidth=tl?.clientWidth||0; const bw=total? tlWidth/total : 0;
    if(ph && tlWidth>0){
      const sx=Math.floor(bw*idx), ex=Math.floor(bw*(idx+1));
      const st=performance.now(); const dur=chordDur*1000;
      blocks.forEach(b=>b.classList.remove('active')); if(blocks[idx]) blocks[idx].classList.add('active');
      function anim(){ if(!playing) return; const p=Math.min(1,(performance.now()-st)/dur); const x=sx+(ex-sx)*p; ph.style.transform=`translateX(${x}px)`; if(p<1) requestAnimationFrame(anim); }
      requestAnimationFrame(anim);
    }
    idx++;
    if(idx<parsed.length) timer=setTimeout(step, chordDur*1000);
    else onStop(true);
  }
  function onStop(done){
    playing=false; if(timer){ clearTimeout(timer); timer=null; }
    $('#preview_play').disabled=false; $('#preview_stop').disabled=true; msg(done?"Preview ended":"");
    const tl=document.getElementById('pv_timeline'); if(tl){ tl.querySelectorAll('.tl-chord').forEach(b=>b.classList.remove('active')); const ph=tl.querySelector('.playhead'); if(ph) ph.style.transform='translateX(0)'; }
  }

  document.getElementById('preview_play')?.addEventListener('click', onPlay);
  document.getElementById('preview_stop')?.addEventListener('click', ()=>onStop(false));
})();
</script>
{% endraw %}
"""

@app.route("/", methods=["GET","POST"])
def index():
  if request.method == "POST":
    text = sanitize(request.form.get("chords",""))
    tokens = [t for t in re.split(r"[\s,]+", text) if t and t != "-"]
    try:
      bpm   = max(30, min(240, int(request.form.get("bpm", "90") or 90)))
      bars  = max(1,  min(8,   int(request.form.get("bars","1") or 1)))
      numer = max(1,  min(12,  int(request.form.get("numer","4") or 4)))
      denom = int(request.form.get("denom","4") or 4)
      denom = denom if denom in (1,2,4,8) else 4
      prog  = max(0,  min(127, int(request.form.get("program","0") or 0)))
      vel   = max(1,  min(127, int(request.form.get("vel","96") or 96)))
      bio = write_mid(tokens, bpm=bpm, bars=bars, numer=numer, denom=denom, program=prog, velocity=vel)
      fname = "chords.mid"
      try:
        return send_file(bio, as_attachment=True, download_name=fname, mimetype="audio/midi")
      except TypeError:
        return send_file(bio, as_attachment=True, attachment_filename=fname, mimetype="audio/midi")
    except Exception as e:
      return render_template_string(PAGE, error=str(e))
  return render_template_string(PAGE, error=None)

if __name__ == "__main__":
  app.run(host="127.0.0.1", port=5000, debug=True)