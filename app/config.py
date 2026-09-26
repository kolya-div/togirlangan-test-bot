from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str
    admin_ids: str

    database_url: str = "postgresql+asyncpg://postgres:123@localhost:5432/turkish"
    webapp_url: str = "http://localhost:8000"

    # STT (Speech-to-Text) sozlamalari
    stt_provider: str = "gemini"  # "gemini", "groq" yoki "openai"
    gemini_api_key: str | None = None
    # Bir nechta Gemini kaliti (vergul bilan): "key1,key2,key3"
    gemini_api_keys: str | None = None

    # FIX: eski modellar (gemini-1.5-flash/2.0-flash/2.5-flash) yangi
    # kalitlarda yopilgan — Google API joriy kalit uchun gemini-3.6-flash
    # ni tavsiya qiladi.
    gemini_stt_model: str = "gemini-3.6-flash"

    groq_api_key: str | None = None
    groq_stt_model: str = "whisper-large-v3-turbo"

    # Vision (docx tahlili uchun)
    groq_vision_model: str = "qwen/qwen3.6-27b"

    # AI baholash sozlamalari
    ai_provider: str = "openai"  # "groq" yoki "openai"
    groq_chat_model: str = "openai/gpt-oss-120b"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    # Fayllar
    upload_dir: str = "data/audios"
    max_audio_size_mb: int = 50

    # CORS sozlamalari
    cors_origins: str = "*"

    # Kunlik hisobot/tozalash vaqti shu vaqt mintaqasida 00:00 da bajariladi
    report_timezone: str = "Asia/Tashkent"

    # Logging sozlamalari
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL

    # ── Paid (tier) konfiguratsiyasi ──
    # Gemini API RPM (requests per minute). Free tier: 15 per key.
    # Paid (Tier 1+): odatda 300+ — haqiqiy qiymatni AI Studio dan tekshiring.
    gemini_rpm_per_key: int = 300

    # Groq / OpenAI RPM — paid/tez-tez ishlatish darajasiga qarab sozlang
    groq_rpm_per_key: int = 30
    openai_rpm_per_key: int = 60

    # DB connection pool
    db_pool_size: int = 40
    db_max_overflow: int = 40

    # Report worker soni (50 user uchun 15, 100+ user uchun 20)
    report_workers: int = 15

    # Concurrent upload chegarasi (100 user uchun 100)
    upload_semaphore: int = 100

    # Telegram global yuborish tezligi (msg/s)
    telegram_rate_per_second: float = 30.0

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "Faqat PostgreSQL qo'llab-quvvatlanadi. "
                "DATABASE_URL quyidagi formatda bo'lishi kerak: "
                "postgresql+asyncpg://user:password@host:5432/dbname"
            )
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def admin_id_list(self) -> list[int]:
        return [
            int(item.strip())
            for item in self.admin_ids.split(",")
            if item.strip()
        ]

    @property
    def is_gemini_paid(self) -> bool:
        """Gemini paid (billing) rejimda ishlayotganini bildiradi.
        GEMINI_RPM_PER_KEY > 15 bo'lsa — paid rejim deb hisoblanadi.
        """
        return self.gemini_rpm_per_key > 15

    @property
    def gemini_keys_list(self) -> list[str]:
        """Barcha Gemini kalitlari ro'yxati.

        Avval `GEMINI_API_KEYS` (vergul bilan ajratilgan) olinadi,
        aks holda eski `GEMINI_API_KEY` ishlatiladi.
        """
        keys: list[str] = []
        if self.gemini_api_keys:
            keys = [k.strip() for k in self.gemini_api_keys.split(",") if k.strip()]
        if not keys and self.gemini_api_key:
            keys = [self.gemini_api_key.strip()]
        # Takrorlanuvchilarni olib tashlash
        seen: set[str] = set()
        unique: list[str] = []
        for k in keys:
            if k not in seen:
                seen.add(k)
                unique.append(k)
        return unique


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()