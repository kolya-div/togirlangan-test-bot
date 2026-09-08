# Ishga tushirish — GitHub'dan to ishlayotgan botgacha

Bu yo'riqnoma loyihani **GitHub'dan ko'chirishdan boshlab**, bot ishga tushguncha bo'lgan to'liq jarayonni ko'rsatadi (Windows uchun).

---

## 0. Kerakli dasturlar va hisoblar

| Narsa | Izoh | Havola |
|---|---|---|
| Python 3.11+ | O'rnatishda **"Add Python to PATH"** belgilanadi | python.org/downloads |
| Git | Reponi ko'chirish uchun | git-scm.com |
| PostgreSQL | Ma'lumotlar bazasi | postgresql.org/download/windows |
| Telegram bot token | @BotFather → `/newbot` | t.me/BotFather |
| Groq API kaliti | STT/AI uchun (bepul, `gsk_...`) | console.groq.com/keys |
| Gemini API kaliti | Muqobil STT | aistudio.google.com |
| Ngrok authtoken | WebApp public URL uchun | dashboard.ngrok.com |

> Node.js **shart emas** — `webapp/dist` oldindan build qilingan va FastAPI uni o'zi xizmat qiladi.

---

## 1. GitHub'dan ko'chirish

GitHub sahifasida **Code → HTTPS** manzilini nusxalang va terminalda:

```bash
git clone https://github.com/SIZ/Turkish-Speaking-Bot.git
cd Turkish-Speaking-Bot
```

---

## 2. Python muhiti va kutubxonalar

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

---

## 3. PostgreSQL — baza yaratish

PostgreSQL o'rnatilgach (Server: `localhost`, Port: `5432`), `psql` orqali baza yarating:

```bash
psql -U postgres -h localhost -c "CREATE DATABASE turkish;"
```

Parol — PostgreSQL o'rnatishda belgilagan parolingiz (masalan `123`).

---

## 4. `.env` faylni yaratish va to'ldirish

```bash
copy .env.example .env
```

`.env` ni odatiy (bloknot) bilan ochib to'ldiring:

| O'zgaruvchi | Qayerdan | Misol |
|---|---|---|
| `BOT_TOKEN` | @BotFather | `735281...:AAH...` |
| `ADMIN_IDS` | @userinfobot | `6237727606` |
| `DATABASE_URL` | PostgreSQL | `postgresql+asyncpg://postgres:123@localhost:5432/turkish` |
| `STT_PROVIDER` | tanlov | `groq` yoki `gemini` |
| `GROQ_API_KEY` | console.groq.com | `gsk_...` |
| `GEMINI_API_KEY` | aistudio.google.com | `AIza...` |
| `OPENAI_API_KEY` | platform.openai.com | ixtiyoriy |
| `NGROK_AUTHTOKEN` | dashboard.ngrok.com | `2abc...` |

> **DATABASE_URL formati:** `postgresql+asyncpg://Foydalanuvchi:Parol@Host:Port/Baza_nomi`
> ⚠️ Loyiha **faqat PostgreSQL** bilan ishlaydi — SQLite qo'llab-quvvatlanmaydi.

---

## 5. Ishga tushirish

```bash
python run.py
```

Konsolda bosqichma-bosqich chiqadi:
1. `✅ FastAPI tayyor: http://localhost:8000`
2. `✅ Ngrok HTTPS: https://xxxx.ngrok-free.dev` ← WebApp havolasi
3. `🤖 Bot ishga tushmoqda...` — polling boshlanadi

Baza birinchi ishga tushirishda **avtomatik yaratiladi** (jadvallar tuziladi).

---

## 6. Ishda sinash

1. Telegram'da botga **/start** bosing
2. Admin sifatida **"Foydalanuvchilar va natijalar"** ochiladi:
   - Savollarni `.docx` ko'rinishida yuklang (admin panel orqali)
   - Testni faollashtiring (kunlik/haftalik rejim, limit)
3. Foydalanuvchilar WebApp orqali test topshiradi (ovozli javoblar)
4. Test tugagach bot avtomatik yuboradi: "5 daqiqa" xabari, keyin har bir javob bo'yicha **audio + transcript + xatolar + ball + umumiy daraja**

WebApp'ni sinash: botdagi "Testni boshlash" → Telegram WebApp ochiladi.

---

## 7. Texnik eslatmalar

- `.env` faylda **maxfiy kalitlar** bor — uni hech kimga bermang va Git'ga yuklamang (`.gitignore` allaqachon yopgan)
- WebApp URL har ishga tushirishda ngrok orqali **avtomatik** yangilanadi
- Testga qayta kirish bloklanadi: tugallangan yoki boshlangan test yangidan boshlanmaydi. Admin **🔓 blokdan chiqarish** orqali hal qiladi
- Muallak qolgan testlar (30 daqiqa), eski yozuvlar (30 kun) **avtomatik** tozalanadi
- Admin qo'shimcha: `python scripts/cleanup.py` va `python scripts/unblock.py --user <tg_id>`

---

## Muammolar

| Xatolik | Yechim |
|---|---|
| `psycopg`/`asyncpg` bog'liq xato | `pip install "asyncpg>=0.29"` yana urinib ko'ring |
| `attached to a different loop` | Eski server jarayonini to'xtatib, `python run.py` qayta ishga tushiring |
| `port 8000 band` | Avvalgi FastAPI/ngrok jarayonlarini yoping |
| WebApp ochilmayapti | `NGROK_AUTHTOKEN` to'g'riligini tekshiring; ngrok ishlamasa qayta ishga tushiring |
| Xabarlar yuborilmayapti | `BOT_TOKEN` va admin panelda botning holatini tekshiring |