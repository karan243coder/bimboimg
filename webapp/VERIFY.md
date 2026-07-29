# ✅ Sahi file load hui ya nahi — 10 second check

## Tarika 1: Log panel dekho (sabse aasan)
Page kholte hi Log me **doosri line** aani chahiye:

```
🏷 build v3.1-mem · memory-safe · MAX_PIXELS=8MP · deviceMemory=8GB
```

Ye line **nahi** dikhi → purani file chal rahi hai.

## Tarika 2: Console check
F12 → Console → paste:
```js
document.getElementById('cleanCap') ? '✅ NEW BUILD' : '❌ OLD BUILD — file update nahi hui'
```

## Purani file chipki hui hai? Ye karo (order me)
1. **Hard refresh** — `Ctrl + Shift + R` (Windows) / `Cmd + Shift + R` (Mac)
2. Kaam nahi kiya → F12 → **Network** tab → ☑ *Disable cache* → refresh
3. Phir bhi nahi → F12 → **Application** → *Storage* → **Clear site data** → refresh
4. Ya URL me manually lagao: `http://localhost:8000/index.html?fresh=1`

## Server se serve kar rahe ho?
`python3 -m http.server` files ko cache karne ko kehta hai. Ye no-cache server use karo:

```bash
python3 nocache_server.py
```

## Files jo update honi chahiye
| File | MD5 |
|---|---|
| app.js | a10ddb8c881316742690104c6ff6a655 |
| index.html | bb7580b3cdbe231e0e23b9f3129c4cff |

Check karo:
```bash
md5sum app.js index.html
```
