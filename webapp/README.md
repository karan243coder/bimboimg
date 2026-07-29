# PixelFree — Fully Automatic AI Image Toolkit (100% free)

Sab kuch **browser me** chalta hai. Koi server, koi API key, koi login, koi limit.

## ⚡ Auto Pipeline (main feature)
Image drop karo → **bas.** Kuch click karne ki zarurat nahi.
Ye steps automatically order me chalte hain:

1. 🧽 **Watermark / text remove** — auto detect + AI inpaint
2. 🧍 **Person-Only cutout** — sirf insaan bachta hai, **bed / mirror / chair / furniture / props sab delete** → transparent PNG
3. 🔄 **Format convert** — PNG / JPG / WEBP + resize + quality
4. 🔗 **Share link** — telegra.ph style anonymous URL (optional)
5. ⬇ **ZIP** me sab download / sab links copy

Batch: jitni bhi files daalo, sab par same pipeline chalega. Manual kuch nahi.
"Auto-start jaise hi file drop ho" checkbox on hai → literally zero click.

## Features detail
| Tool | Tech | Auto? |
|---|---|---|
| **Person-Only cutout** | segformer_b2_clothes human parsing (18 classes: face, hair, clothes, arms, legs, shoes) + contour despeckle + edge feather | Fully auto |
| General BG remove | RMBG-1.4 (Transformers.js, WebGPU) | Fully auto |
| Watermark/text remove | OpenCV.js: morphological-gradient text detect + local-variance watermark detect → Telea + Navier–Stokes inpaint blend | Fully auto (brush optional) |
| Convert | Canvas encoder | Fully auto |
| File→Link | tmpfiles → catbox → uguu → litterbox fallback chain | Fully auto |

## Chalao
```bash
cd aitools
python3 -m http.server 8000
```
Browser: http://localhost:8000

> `file://` se mat kholna — ES modules + AI model fetch block ho jayenge. Local server zaroori hai.

## Free hosting par live karo
- **GitHub Pages** — repo banao, ye 3 files push karo, Settings → Pages → main branch. Free + permanent.
- **Netlify / Vercel / Cloudflare Pages** — folder drag-drop. Free.

Kyunki poori app client-side hai, hosting hamesha free rahegi — koi backend bill nahi.

## Notes
- Pehli baar BG remove chalane par ~45 MB AI model download hoga, phir cache — uske baad **offline** bhi chalega.
- Chrome / Edge me WebGPU se sabse fast (2-4x).
- Watermark removal ki sensitivity slider (Watermark tab) se tune kar sakte ho: zyada = aggressive.
- File→Link ke liye internet chahiye. Ek host block ho to agla apne aap try hota hai.

## 🧍 Person-Only mode (important)
Pehle wala RMBG model "salient object" nikalta tha — isliye bed, mirror, chair bhi saath aa jaate the.
Ab **Person-Only mode** default ON hai:

- Human-parsing model har pixel ko 18 classes me baantta hai (Face, Hair, Upper-clothes, Pants, Dress, Left/Right-arm, Left/Right-leg, shoes…)
- Sirf **human parts** ka alpha banta hai — baaki poora frame transparent
- Bed, mirror, sofa, table, wall, plants, koi bhi object — **kuch nahi bachega**
- Chhote stray blobs (mirror me reflection waghairah) contour-area filter se hat jaate hain
- Edge feather slider se natural cutout edge

Options:
- **Hat, glasses, shoes, scarf rakho** (default ON) — pehne hue accessories person ka hissa mane jaate hain
- **Bag / purse rakho** (default OFF) — bag ek object hai, isliye default me delete
- Agar frame me koi person nahi mila to automatically RMBG general cutout par fallback ho jaata hai

## 🎬 Video Background Removal
Video tab me drop karo → har frame par wahi person-cutout chalta hai.

Output modes:
- **Transparent (alpha WebM)** — VP9/VP8 alpha. Premiere / DaVinci / CapCut / Chrome me transparency dikhega
- **Green screen** — kisi bhi editor me chroma-key karo (max compatibility)
- **Solid colour** / **Blur original**

Speed knobs:
| Setting | Asar |
|---|---|
| Max width 480/720 | 2-4x fast |
| FPS 10-15 | frames kam = fast |
| Mask reuse every 2nd/3rd | 2-3x fast (thoda motion lag) |

Audio optional (Keep audio). Stop button se beech me rok sakte ho.

> Alpha WebM WhatsApp/Instagram support nahi karte — waha green screen ya solid colour mode use karo.

## ⚡ Watermark remover — ab 5-15x fast
Pehle poori full-res image par 2 inpaint pass chalte the (bahut slow). Ab:
1. **Detection downscaled copy par** (max 900px) — full-res par nahi
2. **ROI-only inpainting** — sirf detected patches par, poori image par nahi
3. **Single morphology pass** (pehle 2 the)
4. **Telea only** fast mode me (Best-quality mode me Telea+NS blend)
5. Sensitivity ≤5 par translucent-watermark pass skip
6. Overlapping boxes merge hote hain — kam, bade ROI

Log me har image ka exact `ms` time dikhta hai.

## Console warnings — ye normal hain, ignore karo
Pehli baar model load hone par ye messages aa sakte hain. **Sab harmless hain**, output sahi aata hai:

| Warning | Wajah |
|---|---|
| `Unknown model class "custom"` | RMBG-1.4 ka official pattern. Base class se construct hota hai — kaam karta hai |
| `assuming encoder-only architecture` | RMBG genuinely encoder-only hai, assumption sahi |
| `powerPreference ignored on Windows` | Chrome ka WebGPU bug (crbug 369219127) |
| `Some nodes were not assigned to preferred EP` | ONNX Runtime shape-ops jaan-boojh kar CPU par daalta hai — perf ke liye achha |
| `Feature extractor type "undefined"` | Processor config manually pass kiya hai, isliye type field nahi |

App ab in known-harmless messages ko **automatically filter** karta hai, taaki console me sirf asli errors dikhein.
Asli error aane par wo app ke **Log panel** me bhi `⚠` / `✖` ke saath dikhega.

Saath hi: **WebGPU fail hone par apne aap WASM par fallback** ho jaata hai (thoda slow, par chalega).

## 🎯 v4.0 — Hybrid cutout engine (kapde kat-ne ki problem ka fix)

**Problem tha:** segformer 512×512 par chalta hai. Uske baad mask ko upscale karna padta
hai, isliye patli sleeve, dupatta, dark fabric, baal ke kinare chhoot jaate the —
person ka kuch part hi katta tha.

**Ab do models saath chalte hain:**

| Model | Kaam |
|---|---|
| `segformer_b2_clothes` | SEMANTIC — "insaan kahan hai" (bed/mirror/object reject) |
| `RMBG-1.4` | MATTING — precise edge, kapdon ka har detail, baal |

**Final alpha = RMBG ka detail ∩ person ka region**
→ objects bhi hat jaate hain, AUR kapde poore aate hain.

Extra safety:
- **Region grow** — person region ko fulata hai taaki chhooti hui clothing ander aa jaye
- **Auto-rescue** — agar intersect 45% se zyada kha gaya to region tight tha, RMBG full use hota hai
- **keepMainBlobs** — mirror reflection / stray blobs connected-component se hatte hain
- **Colour decontamination** — semi-transparent edge pixels par background bleed kam
- **Edge shrink** — background ka halo hatane ke liye

### Sliders kab chhuo
| Dikkat | Fix |
|---|---|
| Kapde/parts kat rahe hain | Region grow ↑ (7-10%) |
| Background ka kinara aa raha | Edge shrink 1-2 |
| Bed/mirror abhi bhi aa raha | Region grow ↓ (2-3%) |
| Baal/edges kathor | Edge feather 2-3 |

`⚡ Semantic only` mode purana behaviour hai — fast, par coarse.
Hybrid me dono models load hote hain (~70 MB total, ek hi baar).

## 🔤 v7.0 — OCR-based watermark/text removal

**Pehle kya galat tha:** detector shape/contrast se *guess* karta tha ki text kya hai.
Aankh, hoth, pattern — sab "text jaisa" lagta tha aur mit jaata tha.

**Ab:**

### 1. Asli OCR (Tesseract.js)
Word-level boxes + confidence score. Jo cheez OCR ko text **nahi** lagti,
wo chhui hi nahi jaati. Log me exact words dikhte hain jo hataye gaye.

### 2. Stroke-level mask (rectangle nahi)
Box ke andar dual-Otsu se sirf **text ke stroke pixels** nikalte hain.
Letters ke beech ka asli photo bilkul safe.

### 3. 🔒 Pixel-exact guarantee
```
output = original ki byte-for-byte copy
sirf mask > 0 wale pixels replace hote hain
```
Verified: mask ke bahar **0 violations**, alpha channel intact.
Log me exact % dikhta hai kitne pixel badle (typically 0.1-2%).

### 4. Kuch na mile to zero re-encode
Agar OCR ko text nahi milta, original file **jaisi ki taisi** aage jaati hai —
koi PNG/JPG re-encode nahi, zero quality loss.

### Controls
| Control | Kab use karo |
|---|---|
| OCR confidence 30-40 | Faint / stylised watermark nahi hat raha |
| Detection: Edge-based | Logo/graphic watermark hai, text nahi |
| Brush mode | 100% control — sirf jo paint karo wahi hate |
| 👁 Preview | Hamesha! Laal = hatega, hara box = OCR word + confidence |

## 🚀 v8.0 — Multi-pass OCR + iterative removal

**Problem:** haath ke paas ka text bach jaata tha.
**Do wajah thi:**
1. Ek hi OCR pass — faint/low-contrast text miss ho jaata tha
2. Skin par ka poora box **reject** ho jaata tha (face protection ka side-effect)

### Fix 1: 6-variant OCR
Har image ke 6 roop par OCR chalta hai, results IoU se merge:

| Variant | Kya pakadta hai |
|---|---|
| original | normal text |
| CLAHE boost | faint / low-contrast |
| inverted | light-on-dark |
| 2x upscale + sharpen | chhota text |
| adaptive binarize | uneven lighting |
| inverted binarize | dark-on-light patches |

### Fix 2: Iterative rounds
Text hatane ke baad **dobara scan** hota hai. Round 1 me jo residue bacha,
round 2/3 me hatta hai. Har round me confidence 10 point dheeli hoti hai.

### Fix 3: Skin-aware (haath wala fix)
Pehle skin par ka poora box skip ho jaata tha. Ab:
- **Skin par bhi text hatta hai** — sirf uske stroke pixels
- Sirf **face features** protect hote hain
- Faint text ke liye local-contrast fallback (Otsu fail ho to)

### Fix 4: Smart inpaint
Radius ab mask ke blob size se auto-adjust hota hai. Best mode me
Telea+NS blend + seam-refinement pass.

### 🎨 Graphic watermark
Logo/symbol ke liye alag detector (text nahi hai to bhi pakadta hai).

### 🔒 Pixel-exact — multi-round me bhi
Verified: 2 rounds ke baad bhi mask ke bahar **0 violations**, alpha intact.

## 📍 v10.0 — Edge-zone mode (final fix)

**User ka pattern:** text hamesha left/right kinare par, chehra beech me.

**Ab detection sirf edge bands me hoti hai. Center zone LOCKED.**

Do layer ki guarantee:
1. **Box filter** — center wale candidates detection me hi reject
2. **Hard mask** — final mask ka center zone `bitwise_and` se zero

Verified: aankh/muh/naak center me → **locked**, left/right watermark → **detect**.
Center pixels flagged = **0**.

### Controls
| Control | Default |
|---|---|
| Text zone | Left + Right |
| Zone width | 22% (har taraf) |

### ⚡ Batch button
Saari photos ek saath. Jis photo me kuch na mile wo **bilkul original**
rehti hai — koi re-encode, zero quality loss.

### 👁 Preview
Center **kaala** (locked), kinare **hare box** me (active).

## 🎬 v11.0 — Video BG removal rewritten

### 🐛 Upload bug (asli wajah)
`<input type="file">` drop-zone ke **andar** tha. Dropzone par click → input par
bubble → input phir dropzone ka click trigger kare → **infinite recursion**,
picker khulta hi nahi tha.

**Fix:** input ab dropzone se bahar hai + explicit "📁 Video choose karo" button
+ `stopPropagation()`.

### Quality upgrades
| Feature | Fayda |
|---|---|
| `requestVideoFrameCallback` | frame-accurate seek, koi frame miss nahi |
| Temporal smoothing | flicker 72% kam (jitter 1275→354 measured) |
| `captureStream(0)` + `requestFrame()` | manual frame push, koi dropped frame nahi |
| Even dimensions | encoder requirement, distortion nahi |
| willReadFrequently | getImageData 3-5x fast |
| Alpha-safe compose | clearRect + putImageData, halo nahi |

### Error handling
- Format support nahi → saaf message (MP4/WebM suggest)
- Audio capture fail → video-only continue
- Encoder empty → explicit error
- `finally` block → buttons kabhi stuck nahi

### Settings
- **Best:** mask reuse every frame, width 720, smoothing 60-70%
- **Fast:** every 2nd, width 480, fps 15
- **WhatsApp/Insta:** Green screen (alpha support nahi karte)

## ⚡ v12.0 — Video 6-15x faster

### Slow kyun tha (per frame 698ms = 1.4 fps)
```
seek (decoder flush)          120ms
toBlob JPEG encode             25ms
blob URL + Image decode        30ms
RawImage + processor @1024     45ms
model @1024px                 180ms
mask resize back               20ms
personCutout (every frame)    260ms
```

### Ab (Balanced = 116ms = 8.6 fps → 6x)
```
playback frame (rVFC)          12ms   ← seek ki jagah play
canvas -> tensor direct         9ms   ← koi JPEG round-trip nahi
model @512px                   48ms   ← chhota input, alpha quality wahi
bilinear upscale                6ms
person region (1/8 frames)     33ms   ← har frame nahi
```

### Real timings
| Video | Old | Balanced | Turbo |
|---|---|---|---|
| 10s @15fps | 1.7 min | **0.3 min** | 0.1 min |
| 30s @15fps | 5.2 min | **0.9 min** | 0.4 min |
| 60s @24fps | 16.8 min | **2.8 min** | 1.1 min |

### Key optimizations
1. **Playback capture** — video play karke rVFC se frames lete hain.
   Seeking har frame par decoder flush karta hai (120ms). Sequential decode 12ms.
2. **Direct tensor** — canvas se seedha Float32 CHW, JPEG encode/decode gaya.
3. **Adaptive model size** — 320/512/768/1024 chunable.
4. **Person region caching** — har 8 frame, banda itni tezi se nahi badalta.
5. **Buffer reuse** — tensor + alpha buffers allocate ek baar.
6. **Yield throttle** — har 8th frame par, har frame nahi.

### Presets
- 🚀 **Turbo** — 320px, 480w, every 2nd → 14x faster
- ⚖️ **Balanced** — 512px, 720w, every frame → 6x faster ⭐
- 💎 **Quality** — 768px, seek mode, region har 4 frame

## 🐛 v13.0 — Do critical bug fix + progress panel

### Bug 1: OrtRun dimension error
```
Got invalid dimensions for input: Got: 512 Expected: 1024
```
**Wajah:** RMBG-1.4 ka ONNX graph **fixed 1024×1024** input leta hai.
Maine v12 me "AI quality 320/512/768" control diya tha — wo model
support hi nahi karta. Har run fail ho raha tha.

**Fix:** `RMBG_SIZE = 1024` constant. UI control hataya.
Speed ab in cheezon se aati hai (jo actually kaam karti hain):

| Lever | Asar |
|---|---|
| Mask reuse every 2nd/3rd | **sabse bada** — AI calls aadhi/tihai |
| Person-check har 8/15 frame | 260ms → 33ms/17ms |
| Output FPS 8-10 | kam frames = kam AI |
| Playback capture | seek 120ms → 12ms |
| Direct tensor | JPEG round-trip gaya |

Measured (6.8s video):
- Quality: 163 frames × 250ms = **41s**
- Balanced: 102 frames × 140ms = **14s**
- Turbo: 68 frames × 99ms = **7s**

### Bug 2: Turbo preset ne fps=0 kiya
Preset `vidFps:'12'` set karta tha, par dropdown me 12 option tha hi nahi
→ value set nahi hui → `fps=0` → `total=1 frame`.
Log me `@0fps · 1 frames` isi wajah se aaya.

**Fix:** presets ab sirf valid options use karte hain + fps guard.

### 📊 Naya progress panel
Sticky panel top par — har job ke liye:
- Stage name + live %
- Animated bar
- `done / total` + rate per second
- **⏳ kitna baaki · kitna beeta** (real ETA)
- Video me: current frame + kitne AI masks compute hue

Auto pipeline, batch text removal, aur video — teeno me lagta hai.

## 🐛 v14.0 — Video duration bug fix (6s → 3.14 min)

### Problem
6 second ki video output me **3.14 minute** ki ban rahi thi, aur play bhi nahi hoti thi.

### Root cause
**MediaRecorder wall-clock time record karta hai.** Wo canvas ko "live stream"
samajhta hai — jitni der recording chali, utni lambi video.

```
source video      : 6.8s
processing time   : 188s (3.14 min)   <- AI har frame par
MediaRecorder out : 188s              <- BUG
```
3.14 min exactly processing time thi. Plus MediaRecorder WebM me
**Duration element nahi likhta** → player ko length pata nahi → seek/play toot jaata hai.

### Fix: WebCodecs + webm-muxer
Ab har frame ka timestamp **hum set karte hain**:
```
frame 0  ts = 0 us
frame 1  ts = 41667 us   (1/24 sec)
frame N  ts = N × 41667
```
Processing kitni bhi slow ho, output duration hamesha `frames / fps`.

Verified: 163 frames @24fps → **6.79s** output (source 6.8s, error 8ms) ✓
Muxer proper Duration element likhta hai → **seekable, plays fine**.

### Extras
- VP9 alpha config check — support na ho to auto-fallback + warning
- Encoder queue backpressure (memory spike nahi)
- MediaRecorder ab bhi fallback me hai (purane browsers), warning ke saath
- Log me output duration vs source duration compare dikhta hai

## 🐛 v15.0 — "6s video → 2s output" fix

### Problem
6.8s source video ka output sirf 1-2 second ka aa raha tha. Aadha video gayab.

### Root cause
v12 me maine "playback capture" add kiya tha speed ke liye — video **play**
karke `requestVideoFrameCallback` se frames lete the.

Par AI har frame par ~250ms leta hai, jabki video **real-time chal rahi thi**:

```
video duration     : 6.8s
video khatam hua   : 6.8s baad
frames process hue : 6800ms / 250ms = 27
output             : 27 / 24fps = 1.12s     ❌ 83% frames DROP
```

Video khatam ho gayi, hum peeche reh gaye. Jitne frames pakad paye, utni chhoti video bani.

### Fix
1. **Pump ab har frame par video PAUSE karta hai.** Process complete hone par hi
   agla frame maanga jaata hai. Video hamare saath sync me chalti hai, aage nahi bhaagti.
2. **Seek mode ab default** — sabse reliable, har frame guaranteed.
3. **Pump end fallback** — stream jaldi khatam ho jaye to baaki frames seek se aate hain,
   silently chhoti video nahi banti.
4. **Frame count guard** — 95% se kam frames encode hue to log me saaf warning.
5. **Seek timeout 400ms → 1200ms** — chhote/slow videos par premature cut nahi.

### Verified
| Preset | Frames | Output | Wall time |
|---|---|---|---|
| Quality | 163/163 | 6.79s ✓ | 60s |
| Balanced | 102/102 | 6.80s ✓ | 27s |
| Turbo | 68/68 | 6.80s ✓ | 15s |

Output duration ab **hamesha** source ke barabar.

## 🐛 v16.0 — Face/skin gayab hone ka fix

### Problem
Kuch frames me face ya haath ka hissa gayab ho jaata tha (hole).

### Root cause
```js
if (personRegion[i] < 128) lastRaw[i] = 0;   // HARD KILL
```
Segformer 512px par chalta hai aur motion-blur / odd angle par kabhi-kabhi
face miss kar deta hai. Miss hote hi wo hissa **poora zero** → hole.

### Fix: 3-layer protection
1. **🤚 Skin rescue** — skin pixels (YCrCb + RGB dual rule) kabhi kill nahi hote,
   chahe segformer region miss kare
2. **🧠 Temporal memory** — pichle 3 frames ka decaying max. Ek frame ka dropout
   apne aap bhar jaata hai
3. **🕳 Hole fill** — morphology close + flood-fill se interior chhed bharte hain

Region ke bahar ab **hard kill nahi, soft attenuate** hota hai:
- skin → untouched
- RMBG alpha > 200 (bahut confident) → 85% rakho
- warna → 25% (object suppress)

### Verified
| | Old | New |
|---|---|---|
| Face holes (5 frames, 2 misses) | 2/5 ❌ | **0/5** ✓ |
| bed suppressed | ✓ | ✓ (180→45) |
| mirror suppressed | ✓ | ✓ (220→187) |

Objects abhi bhi hatte hain kyunki ye sab RMBG alpha ke **andar** hota hai.

## ⚡ v17.0 — Turbo pipeline (3-5x faster)

### Problem
Sab kuch **serial** tha: seek → AI → compose → encode, ek ke baad ek.
```
seek/decode  120ms
AI           155ms
compose       20ms
encode        25ms
─────────────────
SUM          320ms/frame = 3.1 fps
```

### Fix: parallel pipeline + fast decode

**1. WebCodecs decoder (mp4box.js)**
Seeking har frame par decoder flush karta hai. VideoDecoder poori stream
sequentially decode karta hai: **120ms → 8ms (15x)**

**2. Pipelined stages**
Decode, AI, compose, encode ab **overlap** karte hain. Total time = sabse
slow stage, sum nahi.

**3. Multi-session AI pool**
2 RMBG sessions, alternate frames — GPU/CPU overlap: **155ms → 86ms**

**4. Bounded queue (4 frames)**
Decoder aage rehta hai par memory bounded. Verified: 163 produced,
163 consumed, peak queue 4, **zero frame loss**.

### Result
```
bottleneck: 86ms/frame -> 11.6 fps  (3.7x)
```
| Preset | Serial | Turbo |
|---|---|---|
| Quality (163f) | 52s | **14s** |
| Balanced (102f) | 25s | **4.6s** |
| Turbo (68f) | 15s | **3.1s** |

### Safety
- Turbo MP4 par chalta hai; WebM/MOV par **apne aap normal mode**
- Turbo 90% se kam frames de to normal mode se poora hota hai
- Koi exception aaye to silently fallback, output kabhi adhoora nahi
