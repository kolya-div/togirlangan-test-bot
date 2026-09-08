-- ============================================================
-- Migratsiya: 003 — Attemptga chat_id qo'shish (UX: tugma o'chirish)
--
-- Maqsad: WebApp tugma yuborilgan chat'ni attempt bilan bog'lash.
--   Attempt finished bo'lganda bot shu chat_id ga yangi
--   "Test yakunlandi" xabarini yuboradi.
--
--   ⚠️ XAVFSIZLIK ESLATMACHASI (keyingi dasturchi uchun):
--   `chat_id`/start_param FAQAT UX (tugmani o'chirish/xabar yuborish)
--   uchun mo'ljallangan. U imzolanmagan va osongina soxtalashtirilishi
--   mumkin — user_id ni aniqlash yoki hohlagan xavfsizlik/avtorizatsiya
--   qaroriga ASLO ishlatmang. Barcha avtorizatsiya faqat
--   Telegram HMAC imzosi (init_data) orqali amalga oshiriladi.
--
-- Eslatma: telegram_message_id kerak emas — eski xabarni tahrirlash
--   o'rniga yangi xabar yuboriladi.
-- ============================================================

ALTER TABLE test_attempts ADD COLUMN IF NOT EXISTS chat_id BIGINT;
