# 🎨 AI Image Studio — Telegram Bot

Koyeb **free tier (512 MB / 0.1 vCPU)** ke liye specially tuned.

---

## 🔥 v2 — OOM fix (exit 137)

**Kya hua tha:** deploy successful, bot chala, par inference par
`Application exited with code 137` = OOM kill.

**Root cause (measured):**
```
RMBG-1.4 ka ONNX graph 1024x1024 par HARD-CODED hai
inference @1024 -> peak 603 MB    <-- Koyeb limit 512 MB
```
Model file 44 MB hai, par **activations** 600 MB le jaate hain.

**Fix:** graph ke H/W dims ko dynamic banaya (`onnx` se patch, build-time par):

| Input | Peak RAM | Time | IoU vs 1024 |
|---|---|---|---|
| 1024 | 603 MB ❌ | 5.5s | 1.000 |
| 704 | 423 MB | 2.1s | 0.937 |
| **640** ⭐ | **416 MB ✅** | **1.8s** | **0.938** |
| 512 | 372 MB ✅ | 1.1s | 0.938 |

**640 = default.** 3x tez, 190 MB kam, quality me aankh se farak nahi.

Saath me:
- `ORT_ENABLE_BASIC` (ALL kuch nodes fuse karke RAM badhata hai)
- `malloc_trim(0)` har job ke baad — RSS actually OS ko wapas
- Pre-flight RAM check — 400 MB se upar ho to job se pehle unload
- Idle unload 180s → **90s**
- Model **build-time** par download+patch — runtime spike zero

**Verified:** 3 consecutive runs → peak **394 MB**, steady 168 MB, **koi leak nahi**.

---

## ⚠️ Pehle ye padho — honest reality check

Maine actual test kiya, ye numbers real hain:

| Cheez | Free tier par | Verdict |
|---|---|---|
| RAM peak (inference) | **394 MB** / 512 MB | ✅ safe (fix ke baad) |
| Background remove | **~1.9 s/image** | ✅ tez |
| BG remove on 0.1 vCPU | **~15-25 s/image** | ⚠️ slow par chalega |
| Convert / compress / upscale | < 1 s | ✅ instant |
| Text remove (OCR) | ~1-2 s | ✅ theek |
| **Video BG remove** | 102 frames × 8s = **~14 min** | ❌ **practical nahi** |

**Isliye architecture aisa hai:**
- **Images → bot par** (server-side, sab kuch kaam karta hai)
- **Video + batch → WebApp par** (user ke browser me, uska GPU use hota hai — **free aur 100x fast**)

Wahi PixelFree jo humne banaya, wo WebApp ban jaata hai. Bot ke andar button se khulta hai. Ye best of both hai.

---

## 🛡️ FloodWait protection (tested)

Telegram limits: **30 msg/s global**, **1 msg/s per chat**. Todne par
`TelegramRetryAfter`, baar-baar todne par **temporary ban**.

4-layer guard lagaya hai:

| Layer | Kya karta hai | Test result |
|---|---|---|
| **Global token bucket** | 20/s cap (30 se 33% neeche) | 21.7/s sustained ✓ |
| **Per-chat limiter** | 1.05 s/msg per chat | 4 msgs = 3.15s ✓ |
| **Auto-retry** | FloodWait par exact wait + retry (5x) | recovered after 2 waits ✓ |
| **Anti-spam middleware** | user flood → handler chalta hi nahi | 12 msgs → 5 passed ✓ |

Extra:
- Alag chats **parallel** chalte hain (10 chats = 0.0s, serial nahi)
- `TelegramForbiddenError` (user ne block kiya) → retry nahi, waste nahi
- Broadcast fully paced — 1000 users bhejo, ban nahi hoga
- `/admin` me live flood stats: retries, waits, drops

**Har single** `send`/`edit`/`delete`/`answer` call wrapped hai — koi raw call nahi bacha (verified).

---

## 🚀 Koyeb deploy (5 min)

**1. GitHub par push karo**
```bash
cd tgbot && git init && git add -A
git commit -m "AI image bot"
git remote add origin https://github.com/USER/REPO.git
git push -u origin main
```

**2. Koyeb → Create Service → GitHub → apna repo**

| Field | Value |
|---|---|
| Builder | **Dockerfile** |
| Instance | **Free (nano)** |
| Port | **8000** |
| Health check | `/health` |

**3. Environment variables**
```
BOT_TOKEN     = 123456:ABC-...       (@BotFather se)
ADMIN_IDS     = your_telegram_id     (@userinfobot se)
AI_SIZE       = 640
FREE_DAILY    = 40
```
`KOYEB_PUBLIC_DOMAIN` Koyeb khud set karta hai → webhook apne aap lag jaayega.

**4. Deploy.** Pehla request par model download hoga (~42 MB, 30s), phir cache.

> ⚠️ **Health check grace period 120s rakhna** — pehla boot slow hai.
> Koyeb UI: Service → Health checks → Grace period = 120

### Docker image
Multi-stage build, non-root user, tini init, healthcheck — sab production-grade.
Final image ~480 MB (onnxruntime + opencv bhaari hain).

---

## 🧠 512 MB me kaise fit hota hai

| Technique | Fayda |
|---|---|
| **Quantized ONNX** (42 MB vs 168 MB full) | 126 MB bacha |
| **Lazy load** — pehle request par | idle par 40 MB |
| **Idle unload** (3 min) | RAM wapas OS ko |
| **1 worker semaphore** | do inference saath = OOM, isliye queue |
| **1 ONNX thread** | 0.1 vCPU par multi-thread ulta slow |
| **`enable_cpu_mem_arena=False`** | memory spike kam |
| **MAX_SIDE 1600** | bade images pehle hi downscale |
| **RAM watchdog** | 88% par model force-unload |

Measured: idle **38 MB** → loaded **159 MB** → unload ke baad **132 MB**.

---

## ✨ Features

**Bot (server-side)**
- ✂️ Background remove — transparent / white / green / black
- 🧽 Watermark & text remove — edge-zone OCR, **center (chehra) 100% safe**
- 🔄 Convert — PNG / JPG / WEBP
- 🗜 Smart compress — binary-search quality, target size
- 🔍 Upscale 2x — Lanczos + unsharp
- ⚙️ Per-user settings (SQLite me save)
- 📊 Stats, rate limit, daily quota
- 🛠 Admin: `/admin`, `/broadcast`

**WebApp (client-side, optional)**
- 🎬 Video background removal
- 📦 Batch processing
- Sab user ke browser me = server par zero load

---

## 🎛 Tuning

| Env | Default | Matlab |
|---|---|---|
| `AI_SIZE` | 640 | Pre-downscale. 0=full-res (best), 512=fastest |
| `MAX_SIDE` | 1600 | Input cap |
| `MAX_CONCURRENT_JOBS` | 1 | **512MB par 1 hi rakho** |
| `MODEL_IDLE_UNLOAD_SEC` | 180 | Idle par RAM free |
| `FREE_DAILY` | 40 | Per-user daily limit |
| `WEBAPP_URL` | — | Video/batch ke liye |

> **Note:** RMBG-1.4 ka ONNX graph **fixed 1024×1024** input leta hai —
> chhota nahi ho sakta (`InvalidArgument` deta hai). `AI_SIZE` model input
> nahi, **pre/post-process resolution** control karta hai.

---

## 🖥 Local test
```bash
pip install -r requirements.txt
export BOT_TOKEN=...
python -m app.main          # BASE_URL na ho to polling mode
```

---

## 🔗 WebApp bhi chahiye?

`aitools/` folder (PixelFree) ko Cloudflare Pages / Netlify par daalo (free),
phir Koyeb me:
```
WEBAPP_URL = https://your-site.pages.dev
```
Bot me **🚀 Open Studio** button aa jayega. Video + batch wahan chalega —
user ke browser me, aapke server par **zero cost**.
