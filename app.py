# app.py
# Simple MIDI inspector web UI (Flask)
from flask import Flask, request, render_template_string
import io, html

app = Flask(__name__, static_folder=None)

def read_vlq(b, i):
    v = 0
    while True:
        c = b[i]; i += 1
        v = (v << 7) | (c & 0x7F)
        if not (c & 0x80): break
    return v, i

def u16(b, i): return (b[i] << 8) | b[i+1]
def u32(b, i): return (b[i] << 24) | (b[i+1] << 16) | (b[i+2] << 8) | b[i+3]

NOTE_NAMES = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
def note_name(n): return f"{NOTE_NAMES[n%12]}{(n//12)-1}"

def key_name(sf, mi):
    names = ['Cb','Gb','Db','Ab','Eb','Bb','F','C','G','D','A','E','B','F#','C#']
    idx = sf + 7
    base = names[idx] if 0 <= idx < len(names) else f"sf({sf})"
    return f"{base} {'minor' if mi else 'major'}"

def inspect_midi_bytes(b: bytes) -> str:
    out = []
    i = 0
    if b[i:i+4] != b'MThd': raise RuntimeError("Not a MIDI file (missing MThd)")
    i += 4
    hdr_len = u32(b, i); i += 4
    if hdr_len != 6: raise RuntimeError(f"Unexpected header length {hdr_len}")
    fmt = u16(b, i); i += 2
    ntrks = u16(b, i); i += 2
    div = u16(b, i); i += 2
    out.append("Header:")
    out.append(f"- Format: {fmt}")
    out.append(f"- Tracks: {ntrks}")
    if div & 0x8000:
        fps = 256 - (div >> 8); tpf = div & 0xFF
        out.append(f"- SMPTE: {fps} fps, ticks/frame {tpf}")
        ppq = None
    else:
        out.append(f"- PPQ: {div}")
        ppq = div

    for t in range(ntrks):
        if b[i:i+4] != b'MTrk': raise RuntimeError("Missing MTrk")
        i += 4
        length = u32(b, i); i += 4
        end = i + length
        out.append(f"")
        out.append(f"Track {t+1} (len {length} bytes):")

        running = None
        abs_ticks = 0
        name = None
        tempos = []
        meters = []
        keys = []
        texts = []
        markers = []
        prog = {}
        vol = {}
        pan = {}
        note_on_cnt = [0]*16
        note_off_cnt = [0]*16
        pitch_min = [128]*16
        pitch_max = [-1]*16
        vel_min = [128]*16
        vel_max = [-1]*16

        while i < end:
            dv, i = read_vlq(b, i); abs_ticks += dv
            status = b[i]; data1 = None
            if status < 0x80:
                if running is None: raise RuntimeError("Running status without prior status")
                data1 = status; status = running
            else:
                i += 1; running = status if status < 0xF0 else None

            if status == 0xFF:
                mtype = b[i]; i += 1
                mlen, i = read_vlq(b, i)
                data = b[i:i+mlen]; i += mlen
                if mtype == 0x51 and len(data) == 3:
                    mpqn = (data[0]<<16)|(data[1]<<8)|data[2]
                    bpm = 60000000 / mpqn
                    tempos.append((abs_ticks, bpm))
                elif mtype == 0x58 and len(data) >= 2:
                    numer, denom_pow = data[0], data[1]
                    meters.append((abs_ticks, numer, 1<<denom_pow))
                elif mtype == 0x59 and len(data) >= 2:
                    sf = int.from_bytes(bytes([data[0]]), 'big', signed=True)
                    mi = data[1]; keys.append((abs_ticks, sf, mi))
                elif mtype == 0x03: name = data.decode('utf8', 'replace')
                elif mtype == 0x01: texts.append((abs_ticks, data.decode('utf8','replace')))
                elif mtype == 0x06: markers.append((abs_ticks, data.decode('utf8','replace')))
                elif mtype == 0x2F: pass
            elif status in (0xF0, 0xF7):
                slen, j = read_vlq(b, i); i = j + slen
            else:
                hi = status & 0xF0; ch = status & 0x0F
                if data1 is None: data1 = b[i]; i += 1
                data2 = None if hi in (0xC0, 0xD0) else b[i]; 
                if data2 is not None: i += 1
                if hi == 0x90:
                    n, v = data1, (0 if data2 is None else data2)
                    if v == 0: note_off_cnt[ch] += 1
                    else:
                        note_on_cnt[ch] += 1
                        pitch_min[ch] = min(pitch_min[ch], n)
                        pitch_max[ch] = max(pitch_max[ch], n)
                        vel_min[ch] = min(vel_min[ch], v)
                        vel_max[ch] = max(vel_max[ch], v)
                elif hi == 0x80:
                    note_off_cnt[ch] += 1
                elif hi == 0xB0:
                    cc, val = data1, (0 if data2 is None else data2)
                    if cc == 7: vol[ch] = val
                    elif cc == 10: pan[ch] = val
                elif hi == 0xC0:
                    prog[ch] = data1

        if name: out.append(f"  TrackName: {name}")
        for (tick,bpm) in tempos: out.append(f"  Tempo @ {tick}: {bpm:.3f} bpm")
        for (tick,n,d) in meters: out.append(f"  TimeSig @ {tick}: {n}/{d}")
        for (tick,sf,mi) in keys: out.append(f"  KeySig @ {tick}: {key_name(sf,mi)} (sf={sf}, mi={mi})")
        for (tick,txt) in texts[:20]: out.append(f"  Text @ {tick}: {txt}")
        for (tick,mk) in markers[:50]: out.append(f"  Marker @ {tick}: {mk}")
        for ch,p in sorted(prog.items()): out.append(f"  Channel {ch+1} Program: {p}")
        for ch,v in sorted(vol.items()): out.append(f"  Channel {ch+1} Volume: {v}")
        for ch,v in sorted(pan.items()): out.append(f"  Channel {ch+1} Pan: {v}")
        for ch in range(16):
            if note_on_cnt[ch] or note_off_cnt[ch]:
                pr = f"{note_name(pitch_min[ch])}-{note_name(pitch_max[ch])}" if pitch_max[ch] >= 0 else "-"
                vr = f"{vel_min[ch]}-{vel_max[ch]}" if vel_max[ch] >= 0 else "-"
                out.append(f"  Channel {ch+1}: notes on/off {note_on_cnt[ch]}/{note_off_cnt[ch]}  pitch {pr}  vel {vr}")

    return "\n".join(out)

PAGE = """
<!doctype html>
<title>MIDI Inspector</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 body{font-family:system-ui,Segoe UI,Arial;padding:24px;background:#f6f7fb;color:#111}
 .card{max-width:900px;margin:0 auto;background:#fff;border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.06);padding:20px}
 .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
 input[type=file]{padding:.6rem;border:1px solid #d1d5db;border-radius:10px;background:#fff}
 button{padding:.6rem 1rem;border:none;border-radius:999px;background:#2563eb;color:#fff;font-weight:700;cursor:pointer}
 pre{white-space:pre-wrap;background:#0b1020;color:#e6edf3;padding:14px;border-radius:10px;overflow:auto}
 .small{color:#6b7280;font-size:.9rem;margin-top:6px}
</style>
<div class="card">
  <h2>MIDI Inspector (Python Flask)</h2>
  <form class="row" method="post" enctype="multipart/form-data">
    <input type="file" name="mid" accept=".mid,.midi" required>
    <button type="submit">Inspect</button>
  </form>
  {% if result %}
    <h3>Result</h3>
    <pre>{{ result }}</pre>
  {% else %}
    <div class="small">Upload a .mid file to view header, tempo, meter, key signature, names, markers, and channel stats.</div>
  {% endif %}
</div>
"""

@app.route("/", methods=["GET","POST"])
def index():
    result = ""
    if request.method == "POST" and "mid" in request.files:
        f = request.files["mid"]
        data = f.read()
        try:
            result = inspect_midi_bytes(data)
        except Exception as e:
            result = "Error: " + html.escape(str(e))
    return render_template_string(PAGE, result=result)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)