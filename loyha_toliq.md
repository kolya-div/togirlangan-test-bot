# Loyiha Toliq Hujjatlari — Turkish Speaking Test Bot

Bu hujjat loyihaning har bir papkasi, fayli va asosiy funksiyalarini to'liq tasvirlab beradi.

---

## 1. Loyiha tuzilishi

```
step_version_test/
├── .env.example              # .env namunasi
├── .gitignore                # Git dan chetlatilgan fayllar
├── .dockerignore             # Docker build dan chetlatilgan fayllar
├── docker-compose.yml        # PostgreSQL + app container
├── Dockerfile                # App Docker image
├── requirements.txt          # Python bog'liqliklari
├── run.py                   # Asosiy ishga tushirish nuqtasi
├── README.md                # Loyiha haqida qisqacha ma'lumot
├── loyha_toliq.md           # Bu hujjat
├── app/                     # Backend (Python/FastAPI)
│   ├── __init__.py          # (mavjud emas — namespace package)
│   ├── config.py            # Konfiguratsiya (pydantic-settings)
│   ├── main.py              # FastAPI app + startup/shutdown
│   ├── logging_config.py    # Logging sozlamalari
│   ├── api/                 # API endpointlar
│   │   ├── __init__.py      # Router export
│   │   └── routes.py        # FastAPI routerlar
│   ├── bot/                 # Telegram bot
│   │   ├── __init__.py      # Bot yaratish
│   │   ├── main.py          # Bot ishga tushirish
│   │   ├── keyboards.py     # Inline/reply keyboardlar
│   │   ├── states.py        # FSM holatlari
│   │   ├── callbacks.py     # CallbackData klasslari
│   │   ├── test_state.py    # Test holati boshqaruvi
│   │   └── handlers/        # Handlerlar
│   │       ├── __init__.py  # Routerlarni birlashtirish
│   │       ├── start.py     # /start handler
│   │       ├── admin.py     # Admin handlerlar
│   │       ├── registration.py  # Ro'yxatdan o'tish
│   │       ├── user.py      # Foydalanuvchi handlerlari
│   │       └── voice.py     # Ovozli xabar handler
│   ├── database/            # Ma'lumotlar bazasi
│   │   ├── __init__.py      # Database export
│   │   ├── database.py      # Engine, session, init_db
│   │   ├── models.py        # SQLAlchemy modellari
│   │   └── repositories.py  # DB operatsiyalari
│   ├── services/            # Xizmatlar
│   │   ├── ai_resource_manager.py   # AI resurs boshqaruvi
│   │   ├── ai_docx_service.py       # DOCX AI tahlil
│   │   ├── archive_service.py       # Audio ZIP arxiv
│   │   ├── base_wipe.py             # Bazani tozalash
│   │   ├── cleanup_service.py       # Eski ma'lumotlarni tozalash
│   │   ├── daily_export_wipe.py     # Kunlik eksport + tozalash
│   │   ├── docx_parser.py           # DOCX parser
│   │   ├── question_service.py      # Savol import
│   │   ├── rate_limiter.py          # API rate limiting
│   │   ├── report_service.py        # Hisobot generatsiya
│   │   ├── report_worker.py         # Hisobot workerlari
│   │   ├── telegram_rate_limiter.py # Telegram rate limit
│   │   ├── text_check_service.py    # Matn tekshirish
│   │   ├── transcription_service.py # Ovoz → matn
│   │   ├── user_report_exporter.py  # Foydalanuvchi hisoboti
│   │   └── user_scope.py           # Foydalanuvchi tanlash
│   └── utils/               # Yordamchi funksiyalar
│       ├── constants.py     # Konstantalar
│       └── helpers.py       # Yordamchi funksiyalar
├── webapp/                  # Frontend (React)
│   ├── package.json         # npm konfiguratsiya
│   ├── vite.config.ts       # Vite konfiguratsiya
│   ├── index.html           # HTML sahifa
│   └── src/
│       ├── main.jsx         # React kirish nuqtasi
│       ├── App.jsx          # Asosiy komponent
│       ├── api.js           # API chaqiruvlari
│       ├── style.css        # Stillar
│       └── components/      # React komponentlari
│           ├── AudioRecorder.jsx  # Audio yozish
│           ├── QuestionCard.jsx   # Savol kartasi
│           ├── Results.jsx        # Natijalar sahifasi
│           └── Timer.jsx          # Vaqt hisoblagich
├── scripts/                 # Yordamchi skriptlar
│   ├── cleanup.py           # Tozalash skripti
│   └── unblock.py           # Blokdan chiqarish
├── migrations/              # DB migratsiyalar
│   ├── 002_open_attempt_partial_unique_index.sql
│   └── 003_attempt_chat_id.sql
└── tests/                   # Testlar
    └── test_question_service.py
```

---

## 2. Asosiy fayllar tahlili

### 2.1 run.py — Ishga tushirish nuqtasi

```python
# Loyihani ishga tushiradi:
# 1. FastAPI server (uvicorn)
# 2. Telegram bot (aiogram)
# 3. Ngrok tunnel (avtomatik)
# 4. Kunlik export/wipe scheduler
```

**Funksiyalar:**
- `main()` — asosiy funksiya, hammasini parallel boshlaydi
- FastAPI: `host=0.0.0.0`, `port=8000`
- Bot: polling rejimida ishlaydi
- Ngrok: `NGROK_AUTHTOKEN` bo'lsa avtomatik tunnel yaratadi

---

### 2.2 app/config.py — Konfiguratsiya

Pydantic Settings orqali `.env` faylidan sozlamalarni o'qiydi.

**Asosiy maydonlar:**

| Maydon | Tur | Default | Izoh |
|--------|-----|---------|------|
| `BOT_TOKEN` | str | - | Telegram bot token |
| `ADMIN_IDS` | str | - | Admin ID'lari |
| `DATABASE_URL` | str | - | PostgreSQL URL |
| `STT_PROVIDER` | str | `gemini` | STT provideri |
| `GEMINI_API_KEY` | str | `""` | Bitta Gemini kaliti |
| `GEMINI_API_KEYS` | str | `""` | Bir nechta Gemini kaliti |
| `GEMINI_STT_MODEL` | str | `gemini-3.6-flash` | Gemini STT model |
| `GROQ_API_KEY` | str | `""` | Groq kaliti |
| `GROQ_STT_MODEL` | str | `whisper-large-v3-turbo` | Groq STT model |
| `AI_PROVIDER` | str | `openai` | Baholash provideri |
| `OPENAI_API_KEY` | str | `""` | OpenAI kaliti |
| `OPENAI_MODEL` | str | `gpt-4o-mini` | OpenAI model |
| `GEMINI_RPM_PER_KEY` | int | `300` | Gemini RPM limit |
| `DB_POOL_SIZE` | int | `30` | DB pool hajmi |
| `DB_MAX_OVERFLOW` | int | `30` | DB max overflow |
| `REPORT_WORKERS` | int | `8` | Report workerlar |
| `UPLOAD_SEMAPHORE` | int | `100` | Audio upload limit |
| `TELEGRAM_RATE_PER_SECOND` | int | `30` | Telegram rate limit |
| `UPLOAD_DIR` | str | `data/audios` | Audio papka |
| `MAX_AUDIO_SIZE_MB` | int | `50` | Maksimal audio hajm |
| `CORS_ORIGINS` | str | `*` | CORS domenlari |
| `LOG_LEVEL` | str | `INFO` | Log darajasi |

**Xususiyatlar:**
- `ADMIN_ID_LIST` — `ADMIN_IDS` ni listga aylantiradi
- `get_gemini_keys()` — Gemini kalitlarini ro'yxat qaytaradi
- `is_daily_wipe_enabled()` — kunlik tozalash yoqilganini tekshiradi

---

### 2.3 app/main.py — FastAPI app

```python
# FastAPI ilovasini yaratadi va sozlaydi:
# - CORS middleware
# - Static files (webapp/dist)
# - API routes
# - Startup: init_db, daily scheduler
# - Shutdown: DB connectionlarni yopish
```

**Asosiy komponentlar:**
- `app = FastAPI(title="Turkish Speaking Test Bot")`
- `app.include_router(api_router)` — API endpointlarni qo'shadi
- `app.mount("/", StaticFiles(...))` — WebApp statik fayllarni xizmat qiladi
- `@app.on_event("startup")` — DB va scheduler ni ishga tushiradi

---

### 2.4 app/database/database.py — Database sozlamalari

```python
# PostgreSQL ulanishni boshqaradi:
# - AsyncEngine yaratish
# - Session factory
# - Connection pool sozlash
# - Tablolarni yaratish (init_db)
```

**Asosiy komponentlar:**
- `engine` — AsyncEngine (pool_size=30, max_overflow=30)
- `SessionLocal` — AsyncSession factory
- `init_db()` — tablolarni yaratish (create_all)
- `get_db()` — dependency injection uchun session generator

**Pool sozlamalari (100+ user uchun):**
```python
engine = create_async_engine(
    DATABASE_URL,
    pool_size=30,        # Asosiy connectionlar
    max_overflow=30,     # Qo'shimcha connectionlar
    pool_pre_ping=True,  # Zeroval connectionlarni tekshirish
    pool_recycle=300,    # Connectionlarni yangilash (5 daqiqa)
)
```

---

### 2.5 app/database/models.py — SQLAlchemy modellari

**Jadvallar:**

| Jadval | Tavsif |
|--------|--------|
| `users` | Foydalanuvchilar (telegram_id, full_name, phone, is_admin, is_registered) |
| `questions` | Savollar (text, image_path, section, difficulty, order_index) |
| `test_attempts` | Test urinishlari (user_id, status, score, started_at, finished_at) |
| `answers` | Javoblar (attempt_id, question_id, audio_path, transcript, score) |
| `test_settings` | Test sozlamalari (is_active, mode, daily_limit, vip_limit) |

**Asosiy maydonlar:**

**users:**
- `id: int` — PK
- `telegram_id: int` — Unique, indexed
- `full_name: str`
- `phone: str`
- `is_admin: bool` — Default False
- `is_registered: bool` — Default False
- `created_at: datetime`

**test_attempts:**
- `id: int` — PK
- `user_id: int` → FK(users.id)
- `status: str` — `active`, `started`, `processing`, `finished`
- `score: float` — Default 0
- `started_at: datetime`
- `finished_at: datetime`
- `chat_id: int` — WebApp tugmasi yuborilgan chat

**answers:**
- `id: int` — PK
- `attempt_id: int` → FK(test_attempts.id)
- `question_id: int` → FK(questions.id)
- `audio_path: str` — Audio fayl yo'li
- `transcript: str` — AI transkripsiya
- `score: float` — Ball
- `grammar_score: float`
- `vocabulary_score: float`
- `pronunciation_score: float`
- `sentence_structure_score: float`
- `relevance_score: float`
- `feedback: str` — AI fikr-mulohaza
- `mistakes: JSON` — Xatolar ro'yxati
- `corrected_text: str` — To'g'rilangan matn

---

### 2.6 app/database/repositories.py — DB operatsiyalari

**Funksiyalar:**

| Funksiya | Tavsif |
|----------|--------|
| `get_user_by_telegram_id()` | Telegram ID bo'yicha foydalanuvchi topish |
| `create_user()` | Yangi foydalanuvchi yaratish |
| `update_user()` | Foydalanuvchi ma'lumotlarini yangilash |
| `get_active_attempt()` | Faol test attempt topish |
| `create_attempt()` | Yangi test attempt yaratish |
| `finish_attempt()` | Test attempt ni yakunlash |
| `get_questions()` | Savollarni olish |
| `create_question()` | Yangi savol qo'shish |
| `delete_questions()` | Savollarni o'chirish |
| `create_answer()` | Javob qo'shish |
| `get_answers()` | Javoblarni olish |
| `get_user_results()` | Foydalanuvchi natijalarini olish |
| `delete_user_attempts()` | Foydalanuvchi attemptlarini o'chirish |
| `wipe_user_data()` | Barcha ma'lumotlarni tozalash |

---

### 2.7 app/api/routes.py — API endpointlar

**Endpointlar:**

| Endpoint | Method | Tavsif |
|----------|--------|--------|
| `/api/init` | POST | WebApp avtorizatsiya (Telegram initData tekshirish) |
| `/api/questions` | GET | Savollarni olish |
| `/api/attempts` | POST | Test attempt yaratish |
| `/api/answers` | POST | Audio javob yuborish |
| `/api/finish` | POST | Testni yakunlash |
| `/api/notify-closed` | POST | Test yopilganini xabar qilish |
| `/api/results` | GET | Natijalarni olish |

**Xususiyatlar:**
- Har bir endpoint `get_db()` dependency ishlatadi
- Audio upload: `semaphore` bilan cheklangan (default 100)
- Xatoliklar: HTTPException bilan qaytariladi

---

### 2.8 app/bot/ — Telegram bot

#### 2.8.1 app/bot/__init__.py

```python
# Bot yaratadi va konfiguratsiya qiladi:
# - Dispatcher
# - Routerlarni qo'shish
# - Middleware qo'shish
```

#### 2.8.2 app/bot/main.py

```python
# Bot ishga tushiradi:
# - Polling boshlash
# - Webhook o'rnatish (ixtiyoriy)
```

#### 2.8.3 app/bot/keyboards.py

**Keyboard funksiyalari:**

| Funksiya | Tavsif |
|----------|--------|
| `admin_menu()` | Admin panel asosiy menyu |
| `questions_menu()` | Savollar boshqaruvi menyu |
| `results_menu()` | Natijalar menyu |
| `activate_test()` | Testni faollashtirish tugmasi |
| `confirm_reset_keyboard()` | Bazani tozalash tasdiq |
| `phone_keyboard()` | Telefon raqam so'rash |
| `webapp_keyboard()` | WebApp ochish tugmasi |
| `test_access_menu()` | Test kirish menyu (kunlik/VIP) |

#### 2.8.4 app/bot/states.py

**FSM holatlari:**

| State Group | Holatlar |
|-------------|----------|
| `RegistrationStates` | `waiting_full_name`, `waiting_phone` |
| `AdminQuestionsStates` | `menu`, `waiting_docx`, `waiting_docx_ai`, `confirm_delete` |
| `AdminActivateStates` | `confirm` |
| `AdminResultsStates` | `menu`, `search_user`, `unblock_user` |
| `AdminTestAccessStates` | `menu`, `waiting_vip_limit` |
| `TestStates` | `in_progress`, `answering`, `finished` |

#### 2.8.5 app/bot/callbacks.py

**CallbackData klasslari:**

| Klass | Maqsad |
|-------|--------|
| `AdminMenuCallback` | Admin menyu tugmalari |
| `QuestionCallback` | Savol boshqaruvi |
| `ResetCallback` | Bazani tozalash |
| `UserListCallback` | Foydalanuvchi ro'yxati |

#### 2.8.6 app/bot/test_state.py

```python
# Test holatini boshqaradi:
# - In-memory cache (tezlik uchun)
# - Database (yagona haqiqat manbai)
# - Bot ishga tushganda DB dan yuklaydi
```

**Funksiyalar:**
- `get_test_state()` — joriy test holatini olish
- `set_test_state()` — test holatini yangilash
- `load_test_state_from_db()` — DB dan yuklash
- `save_test_state_to_db()` — DB ga saqlash

#### 2.8.7 app/bot/handlers/start.py

```python
# /start handler:
# - Foydalanuvchini ro'yxatdan o'tkazish
# - Admin panelni ko'rsatish
# - WebApp tugmasini yuborish
```

**Handlerlar:**
- `start_handler()` — /start buyrug'i
- `webapp_handler()` — WebApp tugmasi bosilganda

#### 2.8.8 app/bot/handlers/admin.py

```python
# Admin handlerlar:
# - Savollarni boshqarish (docx yuklash, ko'rish, o'chirish)
# - Testni faollashtirish/to'xtatish
# - Natijalarni ko'rish (sahifalash, qidiruv)
# - Foydalanuvchilarni blokdan chiqarish
# - Bazani tozalash
```

**Asosiy handlerlar:**
- `admin_menu_handler()` — admin panel menyu
- `questions_handler()` — savollar menyu
- `upload_docx_handler()` — docx fayl yuklash
- `activate_test_handler()` — testni faollashtirish
- `results_handler()` — natijalar menyu
- `search_user_handler()` — foydalanuvchi qidirish
- `unblock_user_handler()` — blokdan chiqarish
- `cleanup_handler()` — tozalash

#### 2.8.9 app/bot/handlers/registration.py

```python
# Ro'yxatdan o'tish:
# - Ism so'rash
# - Telefon raqam so'rash
# - DB ga saqlash
```

**Handlerlar:**
- `registration_handler()` — ro'yxatdan o'tish boshlash
- `full_name_handler()` — ism qabul qilish
- `phone_handler()` — telefon qabul qilish

#### 2.8.10 app/bot/handlers/user.py

```python
# Foydalanuvchi handlerlari:
# - WebApp ochish
# - Test boshlash
```

**Handlerlar:**
- `webapp_handler()` — WebApp tugmasi
- `start_test_handler()` — testni boshlash

#### 2.8.11 app/bot/handlers/voice.py

```python
# Ovozli xabar handler:
# - Audio faylni qabul qilish
# - Transkripsiya (STT)
# - Matnni tekshirish
# - Natijani yuborish
```

**Handlerlar:**
- `voice_message_handler()` — ovozli xabar qabul qilish

**Jarayon:**
1. Foydalanuvchi ro'yxatdan o'tganini tekshirish
2. Audio hajmini tekshirish (max 20MB)
3. Transkripsiya (STT)
4. Matnni tekshirish (AI)
5. Natijani formatlash va yuborish

---

### 2.9 app/services/ — Xizmatlar

#### 2.9.1 app/services/transcription_service.py

```python
# Ovozni matnga aylantirish:
# - Telegram dan audio faylni olish
# - Provider bo'yicha transkripsiya
# - Gemini → Groq → OpenAI tartibida
```

**Funksiyalar:**
- `transcribe_audio_file()` — audio faylni matnga aylantirish
- `_transcribe_gemini()` — Gemini STT
- `_transcribe_groq()` — Groq STT
- `_transcribe_openai()` — OpenAI STT

#### 2.9.2 app/services/text_check_service.py

```python
# Turk tilidagi matnni tekshirish:
# - AI modelga yuborish
# - Xatolarni aniqlash
# - To'g'rilangan matn qaytarish
```

**Funksiyalar:**
- `check_turkish_text()` — matnni tekshirish
- `_parse_and_validate()` — javobni tekshirish
- `_validate_consistency()` — izchillikni tekshirish

**AI prompt tuzilishi:**
```
Siz turk tili grammatikasi ekspertisiz.
Matnni tekshiring va quyidagi formatda qaytaring:
{
  "corrected_text": "...",
  "mistakes": [
    {
      "original": "...",
      "correct": "...",
      "type": "...",
      "explanation_uz": "..."
    }
  ],
  "feedback_uz": "..."
}
```

#### 2.9.3 app/services/rate_limiter.py

```python
# API rate limiting:
# - Token bucket algoritmi
# - Har bir provider uchun alohida limit
# - Asinxron kutish
```

**Funksiyalar:**
- `RateLimiter` — asosiy klass
- `acquire()` — token olish
- `release()` — token qaytarish

**Limitlar:**
- Gemini: `GEMINI_RPM_PER_KEY` (default 300)
- Groq: `GROQ_RPM` (default 30)
- OpenAI: `OPENAI_RPM` (default 60)

#### 2.9.4 app/services/ai_resource_manager.py

```python
# AI resurslarini boshqarish:
# - Kalitlar rotatsiyasi
# - Rate limit monitoring
# - Xatolarni qayta ishlash
```

**Funksiyalar:**
- `AIResourceManager` — asosiy klass
- `get_available_key()` — mavjud kalit olish
- `mark_key_exhausted()` — kalit limitini belgilash
- `reset_keys()` — kalitlarini tiklash

#### 2.9.5 app/services/report_service.py

```python
# Hisobot generatsiya:
# - Har bir javob uchun AI baholash
# - Umumiy ball hisoblash
# - Daraja aniqlash
```

**Funksiyalar:**
- `generate_report()` — hisobot yaratish
- `_evaluate_answer()` — javobni baholash
- `_calculate_grade()` — daraja aniqlash

**Baholash tizimi:**
- Grammar: 0-15 ball
- Vocabulary: 0-15 ball
- Pronunciation: 0-15 ball
- Sentence Structure: 0-15 ball
- Relevance: 0-15 ball
- **Jami: 75 ball**

**Dajarlar:**
- Below B1: 0-30 ball
- B1: 31-45 ball
- B2: 46-60 ball
- C1: 61-75 ball

#### 2.9.6 app/services/report_worker.py

```python
# Hisobot workerlari:
# - Parallel qayta ishlash
# - Navbat boshqaruvi
# - Xatolarni qayta ishlash
```

**Funksiyalar:**
- `ReportWorker` — worker klass
- `process_attempt()` — attempt ni qayta ishlash
- `start_workers()` — workerlarni ishga tushirish
- `stop_workers()` — workerlarni to'xtatish

**Sozlamalar:**
- `REPORT_WORKERS` — workerlar soni (default 8)
- `MAX_QUEUE_SIZE` — navbat hajmi (default 1000)

#### 2.9.7 app/services/telegram_rate_limiter.py

```python
# Telegram API rate limiting:
# - Xabar yuborish tezligini cheklash
# - Kutish vaqti
```

**Funksiyalar:**
- `TelegramRateLimiter` — asosiy klass
- `send_message()` — xabar yuborish (rate limit bilan)
- `edit_message()` — xabarni tahrirlash

**Limit:**
- `TELEGRAM_RATE_PER_SECOND` — default 30 msg/s

#### 2.9.8 app/services/docx_parser.py

```python
# DOCX fayldan savollarni parse qilish:
# - "N.soru:" bloklarini topish
# - Rasmlarni ajratish
# - Sub-savollarni topish
# - Ballarni aniqlash
```

**Funksiyalar:**
- `parse_docx_questions()` — savollarni parse qilish
- `_extract_sections()` — bo'limlarni ajratish
- `_extract_images()` — rasmlarni ajratish
- `_extract_scores()` — ballarni ajratish

#### 2.9.9 app/services/ai_docx_service.py

```python
# DOCX faylni AI orqali tahlil qilish:
# - Vision model ishlatish
# - Rasmlarni tahlil qilish
# - Savollarni aniqlash
```

**Funksiyalar:**
- `analyze_docx_with_ai()` — DOCX ni tahlil qilish
- `_build_questions()` — savollarni yaratish
- `_validate_response()` — javobni tekshirish

#### 2.9.10 app/services/question_service.py

```python
# Savol import:
# - DOCX dan savollarni o'qish
# - DB ga qo'shish
```

**Funksiyalar:**
- `extract_docx_lines()` — matn qatorlarini olish
- `extract_docx_images()` — rasmlarni olish
- `import_questions()` — savollarni import qilish

#### 2.9.11 app/services/archive_service.py

```python
# Audio fayllarni ZIP arxivga yig'ish:
# - Barcha javoblarning audio fayllarini yig'ish
# - ZIP arxiv yaratish
```

**Funksiyalar:**
- `create_audio_archive()` — ZIP arxiv yaratish

#### 2.9.12 app/services/base_wipe.py

```python
# Bazani to'liq tozalash:
# - Tablolarni tozalash
# - Audio fayllarni o'chirish
```

**Funksiyalar:**
- `count_rows()` — qatorlar sonini hisoblash
- `wipe_user_data()` — barcha ma'lumotlarni tozalash

#### 2.9.13 app/services/cleanup_service.py

```python
# Eski ma'lumotlarni tozalash:
# - Muallak qolgan attemptlarni qaytarish
# - Eski attemptlarni o'chirish
# - Yetim audio fayllarni o'chirish
```

**Funksiyalar:**
- `run_cleanup()` — tozalashni bajarish
- `_fix_stuck_attempts()` — muallak attemptlarni tuzatish
- `_delete_old_attempts()` — eski attemptlarni o'chirish
- `_delete_orphan_audios()` — yetim audio fayllarni o'chirish

#### 2.9.14 app/services/daily_export_wipe.py

```python
# Kunlik eksport va tozalash:
# - Har kuni 00:00 da bajariladi
# - Barcha ma'lumotlarni .docx ga eksport qilish
# - Adminlarga yuborish
# - Bazani tozalash
```

**Funksiyalar:**
- `daily_export_and_wipe()` — kunlik eksport va tozalash
- `_export_all_users()` — barcha foydalanuvchilarni eksport qilish
- `_send_to_admins()` — adminlarga yuborish
- `_wipe_data()` — bazani tozalash

**Xavfsizlik:**
- Admin ro'yxati bo'sh bo'lsa wipe bajarilmaydi
- Hech bir admin faylni olmasa wipe bajarilmaydi
- Race condition himoyasi: `_in_progress` flag va `asyncio.Lock`

#### 2.9.15 app/services/user_report_exporter.py

```python
# Foydalanuvchi hisobotini yaratish:
# - Barcha foydalanuvchilarni to'plash
# - Test topshirmaganlarni ham qayd etish
# - .docx jadval yaratish
```

**Funksiyalar:**
- `export_all_user_reports()` — barcha hisobotlarni eksport qilish
- `_collect_user_data()` — foydalanuvchi ma'lumotlarini yig'ish
- `create_docx_report()` — .docx fayl yaratish

**Jadval ustunlari:**
1. № — tartib raqami
2. Telegram ID
3. Ism
4. Username
5. Telefon
6. Sana
7. Holat (test topshirdi/topshirmadi)
8. Ball
9. Daraja

#### 2.9.16 app/services/user_scope.py

```python
# Foydalanuvchi tanlash mezonini aniqlaydi:
# - is_registered=True
# - is_admin=False
```

**Funksiyalar:**
- `get_user_scope()` — filtri qaytaradi

---

### 2.10 app/utils/ — Yordamchi funksiyalar

#### 2.10.1 app/utils/helpers.py

```python
# Umumiy yordamchi funksiyalar:
# - utcnow() — timezone-naive UTC vaqt
# - format_timedelta() — HH:MM:SS format
# - format_filename() — fayl nomlarini xavfsiz belgilarga filtrlaydi
```

#### 2.10.2 app/utils/constants.py

```python
# Loyiha konstantalari:
# - ALLOWED_AUDIO_EXTENSIONS — ruxsat etilgan audio kengaytmalar
# - MAX_AUDIO_SIZE_MB — maksimal audio hajm (50 MB)
# - CEFR_LEVELS — CEFR darajalar ro'yxati (A1-C2)
```

---

### 2.11 app/logging_config.py

```python
# Loggingni sozlaydi:
# - Console handler (stdout)
# - Format: %(asctime)s | %(levelname)s | %(name)s | %(message)s
# - Aiogram INFO, httpx/httpcore/uvicorn.access WARNING
```

---

## 3. Frontend (webapp/)

### 3.1 webapp/src/main.jsx

```jsx
// React ilovasining kirish nuqtasi:
// - App komponentini render qilish
// - StrictMode
```

### 3.2 webapp/src/App.jsx

```jsx
// Asosiy komponent:
// - Telegram WebApp avtorizatsiya
// - Savollar yuklash
// - Test boshlash/davom ettirish
// - Prep/record faza boshqaruvi
// - Timer
// - Audio yozish va yuklash
// - Natijalarni polling qilish
// - Finish logikasi
```

**Holatlar:**
- `idle` — test hali boshlanmagan
- `active` — test davom etmoqda
- `finished` — test yakunlangan

**Funksiyalar:**
- `initWebApp()` — WebApp ni ishga tushirish
- `startTest()` — testni boshlash
- `handleRecording()` — audio yozish
- `uploadAudio()` — audio yuklash
- `finishTest()` — testni yakunlash
- `fetchResults()` — natijalarni olish

### 3.3 webapp/src/api.js

```javascript
// API chaqiruvlari:
// - initWebApp() — /api/init
// - getQuestions() — /api/questions
// - createAttempt() — /api/attempts
// - uploadAnswer() — /api/answers
// - finishTest() — /api/finish
// - notifyTestClosed() — /api/notify-closed
// - getResults() — /api/results
```

**Xususiyatlar:**
- Har bir chaqiruv timeout bilan (AbortController)
- Xatolar uchun maxsus holat kodlari (401, 403, 413, 409, 422)
- O'zbekcha xabarlar

### 3.4 webapp/src/components/

#### 3.4.1 AudioRecorder.jsx

```jsx
// Audio yozish komponenti:
// - MediaRecorder API
// - Qulay MIME-tip tanlash
// - Retry bilan yuklash (max 2 marta)
// - Xatolarda avtomatik keyingi savolga skip
```

**Props:**
- `onRecordingComplete(audioBlob)` — yozish tugaganda
- `onError(error)` — xatolik yuz berganda
- `disabled` — o'chirilgan holat

#### 3.4.2 QuestionCard.jsx

```jsx
// Savol kartasi:
// - Savol raqami
// - Progress bar
// - Max ball
// - Savol matni
// - Rasmlar
// - Lehine/Aleyhine bahs-jadvali
```

**Props:**
- `question` — savol obyekti
- `currentIndex` — joriy indeks
- `total` — jami savollar soni

#### 3.4.3 Timer.jsx

```jsx
// Vaqt hisoblagich:
// - SVG aylana (dumaloq) timer
// - Tayyorlanish/yozib olish fazasi
// - Dashoffset animatsiyasi
// - "KAYIT" belgisi
// - Waveform-bar animatsiyasi
```

**Props:**
- `duration` — umumiy vaqt (soniya)
- `phase` — `prep` yoki `record`
- `onTimeUp()` — vaqt tugaganda

#### 3.4.4 Results.jsx

```jsx
// Natijalar sahifasi:
// - Umumiy ball
// - Daraja
// - Javoblar soni
// - Har bir savol uchun:
//   - Transcript
//   - Tuzatilgan matn
//   - Xatolar ro'yxati
//   - Ball panellari
//   - Kuchli tomonlar
//   - Fikr-mulohaza
// - Yopish tugmasi
```

**Props:**
- `results` — natijalar obyekti
- `onClose()` — yopish tugmasi bosilganda

---

## 4. Database migratsiyalar

### 4.1 002_open_attempt_partial_unique_index.sql

```sql
-- PARTIAL UNIQUE INDEX yaratadi:
-- Bitta foydalanuvchi uchun bitta "ochiq" attempt kafolatlanadi
-- DB darajasida race-condition himoyasi
CREATE UNIQUE INDEX idx_one_open_attempt_per_user
ON test_attempts (user_id)
WHERE status IN ('active', 'started', 'processing');
```

### 4.2 003_attempt_chat_id.sql

```sql
-- test_attempts jadvaliga chat_id ustunini qo'shadi
-- WebApp tugmasi yuborilgan chatni attempt bilan bog'lash uchun
ALTER TABLE test_attempts ADD COLUMN chat_id BIGINT;
```

---

## 5. Docker sozlamalari

### 5.1 docker-compose.yml

```yaml
# PostgreSQL + app container:
# - PostgreSQL 15
# - App (FastAPI + Bot)
# - Volume (DB ma'lumotlari)
# - Network
```

**Xizmatlar:**
- `db:` — PostgreSQL
  - `image: postgres:15`
  - `ports: 5432:5432`
  - `environment: POSTGRES_PASSWORD=123`
  - `volumes: pg_data:/var/lib/postgresql/data`
  - `max_connections: 200`

- `app:` — FastAPI + Bot
  - `build: .`
  - `ports: 8000:8000`
  - `depends_on: db`
  - `env_file: .env`

### 5.2 Dockerfile

```dockerfile
# Python 3.13 image
# Requirements o'rnatish
# WebApp build qilish
# App ishga tushirish
```

---

## 6. Xavfsizlik va optimallash

### 6.1 Race Condition himoyasi

- `PARTIAL UNIQUE INDEX` — bitta foydalanuvchi uchun bitta ochiq attempt
- `asyncio.Lock` — kunlik export/wide uchun

### 6.2 Rate Limiting

- Gemini: 300 RPM (paid tier)
- Groq: 30 RPM
- OpenAI: 60 RPM
- Telegram: 30 msg/s

### 6.3 Connection Pool

- PostgreSQL: 30 + 30 = 60 connection
- Pool recycle: 5 daqiqa
- Pool pre ping: zeroval connectionlarni tekshirish

### 6.4 Timeout

- Statement timeout: 300 soniya
- Idle in transaction timeout: 60 soniya
- TCP keepalive: 60 soniya

---

## 7. 100 Concurrent user uchun resurs talablari

| Resurs | Min | Tavsiya |
|--------|-----|---------|
| RAM | 2 GB | 4 GB |
| CPU | 2 yadro | 4 yadro |
| PostgreSQL connections | 60 | 200 |
| Gemini RPM | 300 | 600+ |
| Telegram msg/s | 30 | 30 |
| Disk | 10 GB | 50 GB |

---

## 8. Muammo hal qilish

### 8.1 Bot ishlamayapti

1. `.env` faylini tekshiring
2. PostgreSQL ishlashini tekshiring
3. `python run.py` ni ishga tushiring
4. Loglarni tekshiring

### 8.2 Audio yuklanmayapti

1. `UPLOAD_DIR` papkasi mavjudligini tekshiring
2. `MAX_AUDIO_SIZE_MB` ni tekshiring
3. Telegram rate limitni tekshiring

### 8.3 AI javob bermayapti

1. API kalitlarini tekshiring
2. Rate limitni tekshiring
3. Model nomini tekshiring

### 8.4 Database xatosi

1. PostgreSQL ishlashini tekshiring
2. `DATABASE_URL` ni tekshiring
3. Connection pool ni tekshiring

---

## 9. Qo'shimcha ma'lumotlar

### 9.1 API kalitlarini olish

- **Gemini**: https://aistudio.google.com/apikey
- **Groq**: https://console.groq.com/keys
- **OpenAI**: https://platform.openai.com/api-keys
- **Ngrok**: https://dashboard.ngrok.com/get-started/your-authtoken

### 9.2 Test rejimi

`.env` da `LOG_LEVEL=DEBUG` qo'ying — batafsil loglar chiqadi.

### 9.3 Production uchun

- `CORS_ORIGINS` ni domen bilan cheklang
- `LOG_LEVEL=WARNING` qo'ying
- SSL sertifikat o'rnating
- PostgreSQL xavfsizligini sozlang

---

## 10. Kontaktlar

Loyiha muallifi: MicroStar
GitHub: https://github.com/MicroStar
