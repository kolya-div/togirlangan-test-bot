-- ============================================================
-- Migratsiya: 002 — Bitta foydalanuvchiga bitta "ochiq" attempt
--
-- Maqsad: Registry (race-condition) himoyasi.
--   Bir foydalanuvchi bir vaqtning o'zida faqat bitta "ochiq"
--   (active/started/processing) attemptga ega bo'lishi kafolatlanadi.
--   Ikki parallel/simultane so'rov ikkinchi INSERT ni DB darajasida
--   rad etadi (oldindan tekshiruvdan qat'i nazar).
--
-- Nuqta: PARTIAL UNIQUE INDEX — faqat statusi faol bo'lgan
--   qatorlarni indekslaydi, shuning uchun finished qatorlari
--   bir-biriga xalaqit bermaydi (har bir urinish uchun bitta).
--
-- PostgreSQL sintaksis (asyncpg/AIOSQL uchun mos).
-- ============================================================

CREATE UNIQUE INDEX IF NOT EXISTS uq_test_attempts_one_open_per_user
    ON test_attempts (user_id)
    WHERE status IN ('active', 'started', 'processing');
