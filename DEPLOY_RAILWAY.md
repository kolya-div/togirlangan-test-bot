# Railway'ga joylash (deploy) qo'llanmasi

Loyiha Railway uchun tayyor: `Dockerfile` (WebApp ham ichida build qilinadi)
va `railway.json` (healthcheck, qayta ishga tushish, 1 nusxa).
Railway'da **ngrok kerak emas** — Railway o'zi HTTPS domen beradi.

---

## 0. Muhim: lokal botni o'chiring

Bitta bot tokeni bilan **faqat bitta** joyda bot ishlashi mumkin. Railway'dagi
bot ishga tushishidan oldin kompyuteringizdagi `py run.py` ni to'xtating
(`Ctrl+C`). Aks holda Telegram `Conflict: terminated by other getUpdates`
xatosini beradi va xabarlar ikki joyga bo'linib ketadi.

---

## 1. Loyiha va baza

1. https://railway.com → **New Project** → **Deploy from GitHub repo** →
   `togirlangan-test-bot` ni tanlang (`main` branch).
   Railway `railway.json` ni o'qiydi va `Dockerfile` bilan build qiladi.
2. Shu loyihada **+ New** → **Database** → **PostgreSQL** qo'shing.

## 2. O'zgaruvchilar (Variables)

Bot servisini oching → **Variables** → quyidagilarni qo'shing:

| O'zgaruvchi | Qiymat |
|---|---|
| `BOT_TOKEN` | @BotFather tokeni |
| `ADMIN_IDS` | Admin Telegram ID'lari (vergul bilan) |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` — Railway o'zi to'ldiradi |
| `STT_PROVIDER` | `gemini` |
| `GEMINI_API_KEY` | Gemini kaliti (**pullik** tarif tavsiya etiladi) |
| `GEMINI_RPM_PER_KEY` | Kalitingizning haqiqiy daqiqalik limiti (pullik: 300+) |
| `REPORT_WORKERS` | `25` (pullik Gemini kaliti bilan) |
| `DB_POOL_SIZE` | `20` |
| `DB_MAX_OVERFLOW` | `20` |
| `REPORT_TIMEZONE` | `Asia/Tashkent` |

Qo'shimcha (kerak bo'lsa): `OPENAI_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEYS`,
`AUTO_REPORT_DELAY_SECONDS`.

**Qo'ymang:** `PORT` (Railway o'zi beradi), `NGROK_AUTHTOKEN` (kerak emas),
`WEBAPP_URL` (o'z domeningiz ulanmaguncha — Railway domeni avtomatik olinadi).

> `DATABASE_URL` Railway formatida (`postgresql://...`) bo'lsa ham bo'ladi —
> bot uni o'zi `postgresql+asyncpg://` ga o'giradi.

## 3. Volume (audio, rasmlar, arxiv saqlanishi uchun)

Railway har deploy'da konteyner diskini tozalaydi. Audio javoblar, savol
rasmlari, arxiv va hisobotlar yo'qolmasligi uchun:

- Bot servisi → **Volume** qo'shing (servisni o'ng tugma bilan bosib yoki
  `Ctrl+K` → "Volume") → **Mount path:** `/app/data`

Volume'siz bot ishlaydi, lekin har yangilashda audio va rasmlar o'chib ketadi.

## 4. Domen (Railway domeni)

Bot servisi → **Settings** → **Networking** → **Generate Domain**.
`https://<nom>.up.railway.app` ko'rinishidagi manzil chiqadi — bot WebApp
uchun shu manzilni **avtomatik** ishlatadi (`RAILWAY_PUBLIC_DOMAIN`).
Port so'ralsa — logdagi `Port :` qatoridagi raqamni kiriting.

## 5. Deploy va tekshirish

**Deploy** tugagach, servis **Logs** bo'limida shular bo'lishi kerak:

```
✅ webapp/dist tayyor (npm kerak emas).
🌐 WebApp URL: https://<nom>.up.railway.app
✅ FastAPI tayyor
Run polling for bot @sizning_bot
```

Brauzerda `https://<nom>.up.railway.app/health` → `{"status":"ok",...}`.

Keyin botda (admin sifatida):
1. `/start` → admin panel.
2. **Savollar** → docx'ni **qayta yuklang** (baza yangi — savollar bo'sh).
3. **Taklif havolasi** — yangisini yarating (eskisi lokal bazada qolgan).
4. **Testni faollashtirish**.

## 6. O'z domeningizni ulash

Subdomen ishlatish eng oson (masalan `test.sizningdomen.uz`):

1. Bot servisi → **Settings** → **Networking** → **Custom Domain** →
   `test.sizningdomen.uz` ni kiriting. Railway **CNAME** yozuvini ko'rsatadi.
2. Domen sotib olgan joyingizning DNS panelida yozuv qo'shing:
   - **Turi:** `CNAME`
   - **Nomi (Host):** `test`
   - **Qiymati:** Railway ko'rsatgan manzil (`....up.railway.app`)
3. Railway domenni tasdiqlashini va SSL (HTTPS) sertifikatini chiqarishini
   kuting (odatda bir necha daqiqa, DNS'ga qarab ko'proq bo'lishi mumkin).
4. Bot servisi → **Variables** → `WEBAPP_URL=https://test.sizningdomen.uz`
   qo'shing → servis qayta ishga tushadi.
5. Logda `🌐 WebApp URL: https://test.sizningdomen.uz` chiqishini tekshiring.
   Botdagi «Testni boshlash» tugmalari endi shu domenni ochadi.

> Asosiy domenni (`sizningdomen.uz`, subdomensiz) ulash uchun DNS
> provayderingiz CNAME flattening / ALIAS yozuvini qo'llashi kerak.

## 7. Yangilash

GitHub'dagi `main` branchga o'zgarish tushsa, Railway avtomatik qayta deploy
qiladi. Deploy paytida bot ~1 daqiqa ishlamasligi mumkin — **test ketayotganda
deploy qilmang**. Tekshirilayotgan javoblar yo'qolmaydi: bot qayta ishga
tushgach ularni navbatga qaytaradi.

## Eslatmalar

- Bot faqat **bitta nusxada** ishlashi kerak (hisobot navbati xotirada) —
  `railway.json` da `numReplicas: 1`. Replikalar sonini oshirmang.
- Har kecha 00:00 (Toshkent) da hisobot adminlarga yuboriladi va baza
  tozalanadi; audio va rasmlar `/app/data/archive/` da (Volume'da) qoladi.
- Telegram WebApp faqat **HTTPS** bilan ishlaydi — Railway domeni ham, o'z
  domeningiz ham HTTPS bilan beriladi.
