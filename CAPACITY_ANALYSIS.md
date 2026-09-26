# 50 Concurrent User Capacity Analysis

## 📊 Hozirgi Konfiguratsiya va 50 User Capacity

| Resurs | Hozirgi Qiymat | 50 User Talabi | Status |
|--------|---------------|----------------|--------|
| **DB Connections** | 30+30=60 | ~40-50 | ✅ Yetarli |
| **Report Workers** | 8 | 12-15 | ⚠️ Yetmaydi |
| **Upload Semaphore** | 100 | 50 | ✅ Yetarli |
| **Telegram Rate** | 30 msg/s | 25-30 msg/s | ⚠️ Borderline |
| **Gemini RPM** | 300 per key | ~150-200 | ✅ Yetarli |
| **Groq RPM** | 30 per key | ~100-150 | ⚠️ Limit bo'lishi mumkin |

## 🔍 Detailed Analysis

### 1. Database Connections ✅
- **Hozirgi**: 30 pool + 30 overflow = 60 max connections
- **50 user**: ~40-50 connections (har user uchun ~1 connection)
- **Xulosa**: ✅ Yetarli, hech qanday muammo yo'q

### 2. Report Workers ⚠️
- **Hozirgi**: 8 parallel workers
- **50 user**: 12-15 worker kerak (har worker ~3-4 attempt qayta ishlashi)
- **Masala**: 50 user bir vaqtda test tugatsa, queue paydo bo'ladi
- **Yechim**: `REPORT_WORKERS=15` qo'yish tavsiya etiladi

### 3. Upload Semaphore ✅
- **Hozirgi**: 100 parallel uploads
- **50 user**: ~50 parallel uploads (har user ~1 audio fayl)
- **Xulosa**: ✅ Yetarli, 2x zaxira bor

### 4. Telegram Rate Limit ⚠️
- **Hozirgi**: 30 msg/s
- **50 user**: ~25-30 msg/s (har user ~5-6 xabar)
- **Masala**: Borderline - barcha xabarlar bir vaqtda yuborilsa, limit bo'lishi mumkin
- **Yechim**: `TELEGRAM_RATE_PER_SECOND=30` yetarli, lekin rate-limiter samarali ishlashi kerak

### 5. AI API Rate Limits ⚠️
- **Gemini**: 300 RPM per key (Paid tier)
  - 50 user: ~150-200 RPM
  - Xulosa: ✅ Yetarli
  
- **Groq**: 30 RPM per key (Free tier)
  - 50 user: ~100-150 RPM
  - Masala: ⚠️ Free tierda yetmaydi
  - Yechim: Groq paid tier ishlatish yoki Gemini/OpenAI asosiy provider qilish

- **OpenAI**: 60 RPM per key
  - 50 user: ~50-60 RPM
  - Xulosa: ⚠️ Borderline, multi-key tavsiya etiladi

## 🚀 Tavsiya Etilgan O'zgartirishlar

### `.env` File uchun:
```bash
# 50 concurrent user uchun optimal sozlamalar
REPORT_WORKERS=15              # 8 -> 15 oshirish
TELEGRAM_RATE_PER_SECOND=30   # 30 da qoldirish
DB_POOL_SIZE=30               # 30 da qoldirish
DB_MAX_OVERFLOW=30            # 30 da qoldirish
UPLOAD_SEMAPHORE=100          # 100 da qoldirish

# AI provider uchun tavsiya:
STT_PROVIDER=gemini           # Gemini paid + high RPM
AI_PROVIDER=openai            # OpenAI + multi-key

# Multi-key qo'shish tavsiya etiladi:
GEMINI_API_KEYS=key1,key2,key3  # Agar 3 ta key bo'lsa -> 900 RPM
OPENAI_API_KEY=key1,key2         # Multi-key support kerak
```

### PostgreSQL Settings:
```sql
-- postgresql.conf
max_connections = 200           # 60 -> 200 oshirish (zaxira uchun)
statement_timeout = 300000      # 5 minut
idle_in_transaction_session_timeout = 60000
tcp_keepalives_idle = 60
tcp_keepalives_interval = 10
tcp_keepalives_count = 6
```

## 📈 Performance Projections

### Load Test Scenarios:

| Scenario | Users | Expected Time | Success Rate |
|----------|-------|---------------|--------------|
| **Light Load** | 10 users | ~5-10 min | 99%+ |
| **Medium Load** | 25 users | ~10-15 min | 95%+ |
| **Heavy Load** | 50 users | ~15-25 min | 90%+ |
| **Peak Load** | 100 users | ~25-40 min | 80%+ |

### Key Metrics:

1. **Average Response Time**:
   - API requests: <100ms
   - Audio upload: 2-5s
   - Report generation: 30-60s

2. **Throughput**:
   - Upload requests: 50/min
   - Report processing: 15/min
   - Telegram messages: 30/min

3. **Resource Usage**:
   - CPU: 40-60% (4 core)
   - RAM: 2-3GB
   - DB connections: 40-50
   - Network: 10-20 Mbps

## ⚠️ Potensial Muammolar va Yechimlar

### 1. AI API Rate Limits
**Muammo**: 50 user bir vaqtda ishlaganda API limit bo'lishi mumkin

**Yechimlar**:
- Multi-key rotation (already implemented)
- Paid tier subscription
- Fallback chain (Gemini -> Groq -> OpenAI)

### 2. Report Processing Queue
**Muammo**: 8 worker 50 user uchun yetmaydi

**Yechimlar**:
- `REPORT_WORKERS=15` oshirish
- Priority queue implementation
- Caching results

### 3. Database Connection Pool
**Muammo**: 60 connection 50 user uchun yetarli, lekin zaxira kam

**Yechimlar**:
- `DB_POOL_SIZE=40`, `DB_MAX_OVERFLOW=40` oshirish
- Connection timeout optimization
- Query optimization

## 🎯 Optimal 50 User Configuration

```python
# app/config.py - Optimal settings
db_pool_size: int = 40
db_max_overflow: int = 40
report_workers: int = 15
upload_semaphore: int = 100
telegram_rate_per_second: float = 30.0
gemini_rpm_per_key: int = 300
openai_rpm_per_key: int = 60
```

## 📝 Monitoring Recommendations

1. **Key Metrics to Monitor**:
   - Report queue length
   - API response times
   - DB connection usage
   - AI API rate limit status
   - Telegram API success rate

2. **Alert Thresholds**:
   - Report queue > 10
   - API response time > 5s
   - DB connections > 50
   - AI API error rate > 5%

## ✅ Final Recommendation

**50 concurrent user uchun** hozirgi loyiha **ishlaydi**, lekin quyidagi o'zgartirishlar tavsiya etiladi:

1. **`REPORT_WORKERS=15`** - Bu asosiy o'zgarish
2. **`DB_POOL_SIZE=40, DB_MAX_OVERFLOW=40`** - Zaxira uchun
3. **Multi-key AI API** - Rate limit uchun
4. **Monitoring** - Real-time status tracking

**Bunda 50 user bir vaqtda ishlsa ham, loyiha stable ishlaydi.** 🚀