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
- ✅ **Avtomatik xabar**: test tugagach "Javoblar 5 daqiqa ichida chiqadi" xabari
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
# → FastAPI (localhost:8000), Ngrok tunnel, Telegram bot avtomatik boshlanadi
```

`.env` muhim maydonlari:

| Kalit | Izoh |
|-------|------|
| `BOT_TOKEN` | @BotFather dan olinadi |
| `ADMIN_IDS` | Admin Telegram ID'lari (vergul bilan) |
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@host:5432/dbname` |
| `STT_PROVIDER` | `groq` / `gemini` — ovozni matnga aylantiruvchi |
| `GROQ_API_KEY` | console.groq.com/keys |
| `NGROK_AUTHTOKEN` | dashboard.ngrok.com |

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

## Postgresql'ga o'tkazish

App PostgreSQL bilan ishlaydi. Yangi baza yaratish va jadvallarni tuzish avtomatik (`init_db`).

```bash
psql -U postgres -h localhost -c "CREATE DATABASE turkish;"
```

Keyin `.env` da:

```
DATABASE_URL=postgresql+asyncpg://postgres:123@localhost:5432/turkish
```