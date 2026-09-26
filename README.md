# Turkish Speaking Test Bot

Telegram orqali turk tili speaking imtihonini o'tkazuvchi bot. Foydalanuvchi ovozli javoblarini yozadi, AI ularni matnga aylantirib, har bir javobni baholaydi va natijani (xatolar, ball, daraja) Telegram orqali yuboradi.

Test imtihon interfeysi — **React/Vite WebApp** (Telegram WebApp orqali ochiladi): savollar, tayyorlanish va javob vaqtlari, ovoz yozish tugmasi.

---

## Imkoniyatlar

- 🎙️ **STT (ovoz → matn)**: Groq (Whisper), Gemini yoki OpenAI orqali transkripsiya
- 🤖 **AI baholash**: grammatik xatolar, to'g'rilangan matn, xatolar izohi, ball
- 📊 **75 ballik shkala** va daraja: Below B1, B1, B2, C1
- 🧩 **Test sozlamalari**: kunlik/haftalik rejim, VIP limit, kunlik limitni avtomatik qaytarish
- 🚫 **Qayta kirishni bloklash**: test yakunlangan yoki boshlangan bo'lsa, qayta boshlab bo'lmaydi
- ✅ **Avtomatik xabar**: test tugagach "Javoblar 10 daqiqa ichida chiqadi" xabari
- 📬 **Hisobot**: har bir savol uchun audio yozuv, transcript, xatolar va umumiy ball/daraja
- 🔒 **Admin panel**: natijalar ro'yxati (sahifalash), foydalanuvchi qidiruv, blokdan chiqarish, eski ma'lumotlarni tozalash
- 🧹 **Avtomatik tozalash**: muallak qolgan testlar (30 daqiqa), eski yozuvlar (30 kun), yetim audio fayllar
- 📄 **Savollarni .docx dan yuklash**
- 🌐 **Ngrok tunnel** avtomatik — Telegram WebApp public URL ishlaydi

## Texnologiyalar

| Soha | Texnologiya |
|------|-------------|
| Backend | Python 3.13, FastAPI, SQLAlchemy 2 (async) |
| Bot | aiogram 3.x |
| DB | PostgreSQL (asyncpg) — yagona qo'llab-quvvatlanadigan DB |
| Frontend | React 18 + Vite (WebApp) |
| AI | Groq (Whisper / gpt-oss), Gemini, OpenAI |
| Tunnel | pyngrok |

## Ishga tushirish

```bash
# 1. Virtual muhit va bog'liqliklar
python -m venv .venv
.venv\Scripts\activate        # Windows eski: venv\Scripts\activate
pip install -r requirements.txt

# 2. Sozlamalar
copy .env.example .env        # Windows
# .env faylini to'ldiring: BOT_TOKEN, ADMIN_IDS, kalitlar, DATABASE_URL

# 3. Hamma narsani bitta buyruq bilan ishga tushirish
python run.py
# → kerak bo'lsa webapp uchun `npm install` va `npm run build` avtomatik
# → FastAPI (localhost:8000), Ngrok tunnel, Telegram bot avtomatik boshlanadi
```

> Node.js (npm) o'rnatilgan bo'lishi kerak. `run.py` `webapp/node_modules`
> yo'q yoki `package.json` o'zgargan bo'lsa `npm install`, `webapp/dist` yo'q
> yoki `webapp/src` o'zgargan bo'lsa `npm run build` ni o'zi bajaradi.

## .env Sozlamalari (To'liq)

### 📌 Majburiy sozlamalar

| Kalit | Izoh | Misol |
|-------|------|-------|
| `BOT_TOKEN` | @BotFather dan olinadi | `123456789:AAAbBcC...` |
| `ADMIN_IDS` | Admin Telegram ID'lari (vergul bilan) | `123456789,987654321` |
| `DATABASE_URL` | PostgreSQL ulanish URL | `postgresql+asyncpg://postgres:123@localhost:5432/turkish` |

### 🌐 WebApp & Tunnel

| Kalit | Default | Izoh |
|-------|---------|------|
| `WEBAPP_URL` | `http://localhost:8000` | WebApp URL (Ngrok avtomatik yangilaydi) |
| `NGROK_AUTHTOKEN` | bo'sh | dashboard.ngrok.com dan olinadi |

### 🎙️ STT (Ovoz → Matn)

| Kalit | Default | Izoh |
|-------|---------|------|
| `STT_PROVIDER` | `gemini` | Provider: `gemini`, `groq`, `openai` |
| `GEMINI_API_KEY` | bo'sh | Bitta Gemini kaliti |
| `GEMINI_API_KEYS` | bo'sh | Bir nechta Gemini kaliti (vergul bilan) |
| `GEMINI_STT_MODEL` | `gemini-3.6-flash` | Gemini STT modeli |
| `GROQ_API_KEY` | bo'sh | Groq kaliti |
| `GROQ_STT_MODEL` | `whisper-large-v3-turbo` | Groq STT modeli |

### 🤖 AI Baholash

| Kalit | Default | Izoh |
|-------|---------|------|
| `AI_PROVIDER` | `openai` | Baholash provideri: `openai`, `groq` |
| `OPENAI_API_KEY` | bo'sh | OpenAI kaliti (tavsiya: gpt-4o-mini) |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI baholash modeli |
| `GROQ_CHAT_MODEL` | `openai/gpt-oss-120b` | Groq chat modeli |
| `GROQ_VISION_MODEL` | `qwen/qwen3.6-27b` | Groq vision modeli (docx uchun) |

### ⚡ Performance sozlamalari (100+ user uchun)

| Kalit | Default | Izoh |
|-------|---------|------|
| `GEMINI_RPM_PER_KEY` | `300` | Gemini requests per minute (paid tier) |
| `DB_POOL_SIZE` | `30` | PostgreSQL connection pool hajmi |
| `DB_MAX_OVERFLOW` | `30` | Qo'shimcha connectionlar |
| `REPORT_WORKERS` | `8` | Parallel report workerlar soni |
| `UPLOAD_SEMAPHORE` | `100` | Bir vaqtda audio upload limiti |
| `TELEGRAM_RATE_PER_SECOND` | `30` | Telegram API yuborish tezligi |

### 📁 Fayl sozlamalari

| Kalit | Default | Izoh |
|-------|---------|------|
| `UPLOAD_DIR` | `data/audios` | Audio/rasm papkasi |
| `MAX_AUDIO_SIZE_MB` | `50` | Maksimal audio hajm (MB) |

### 🌍 CORS & Logging

| Kalit | Default | Izoh |
|-------|---------|------|
| `CORS_ORIGINS` | `*` | Ruxsat etilgan domenlar (vergul bilan) |
| `LOG_LEVEL` | `INFO` | Log darajasi: DEBUG, INFO, WARNING, ERROR |

## Gemini Paid (Pro) API — 100 User uchun optimallash

100 concurrent user uchun **Gemini paid (Pro) API** talab qilinadi:
- **Free tier**: 15 RPM har kalit → 3 kalit bilan 45 RPM (yetmaydi)
- **Paid Tier 1**: 300+ RPM har kalit → 1 kalit bilan yetadi

Sozlash:
1. Gemini AI Studio → Dashboard → Rate limits tekshiring
2. `.env` da `GEMINI_RPM_PER_KEY=300` qo'ying (yoki haqiqiy limitni kiriting)

## PostgreSQL sozlash

App PostgreSQL bilan ishlaydi. Yangi baza yaratish va jadvallarni tuzish avtomatik (`init_db`).

```bash
psql -U postgres -h localhost -c "CREATE DATABASE turkish;"
```

Keyin `.env` da:
```
DATABASE_URL=postgresql+asyncpg://postgres:123@localhost:5432/turkish
```

100+ user uchun PostgreSQL sozlamalari:
```sql
-- postgresql.conf
max_connections = 200
statement_timeout = 300000
idle_in_transaction_session_timeout = 60000
tcp_keepalives_idle = 60
tcp_keepalives_interval = 10
tcp_keepalives_count = 6
```

## Admin panel

Botda admin sifatida **"Foydalanuvchilar va natijalar"** tugmasi orqali:
- 📋 Test natijalari sahifalangan ro'yxat
- 🔎 Foydalanuvchi qidiruv (ID, username, ism)
- 🔓 Foydalanuvchini test qayta kirish blokidan chiqarish
- 🧹 Eski/takroriy ma'lumotlarni tozalash

## Yordamchi skriptlar

```bash
python scripts/cleanup.py          # Tozalash (--dry-run bilan tekshirish mumkin)
python scripts/unblock.py --user <telegram_id>   # Test blokidan chiqarish
```

## Struktura

```
app/
  api/          # FastAPI routerlar (test, audio, natijalar, notify)
  bot/          # aiogram handlerlar (start, user, voice, admin), keyboards, states
  database/     # modellar, repositorylar, session
  services/     # STT, baholash, hisobot, tozalash, docx, rate-limiter
webapp/          # React + Vite WebApp
scripts/         # foydali skriptlar
run.py           # asosiy ishga tushirish nuqtasi
```

## 100 Concurrent User uchun resurs talablari

| Resurs | Min | Tavsiya |
|--------|-----|---------|
| RAM | 2 GB | 4 GB |
| CPU | 2 yadro | 4 yadro |
| PostgreSQL connections | 60 | 200 |
| Gemini RPM | 300 | 600+ |
| Telegram msg/s | 30 | 30 |
