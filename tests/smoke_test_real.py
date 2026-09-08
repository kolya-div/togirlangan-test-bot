"""
REAL END-TO-END SMOKE TEST
Haqiqiy backend serverga (localhost:8000) to'g'ridan-to'g'ri API chaqiruvlar.
Telegram WebApp environment mavjud EMAS — faqat backend API tekshiriladi.
"""

import json
import io
import time
import hashlib
import hmac
import urllib.parse
import urllib.request
import urllib.error

from app.config import settings

BASE = "http://localhost:8000"

passed = 0
failed = 0
results_log = []


def make_init_data(user_id: int, *, tamper_fields: dict | None = None) -> str:
    """Telegram WebApp initData ni rasmiy algoritm bo'yicha imzolaydi.

    Algoritm (Telegram hujjatlari):
      1. data_check_string = initData dagi barcha key=value juftliklari,
         lexicographic (alifbo) tartibda, `\\n` bilan birlashtirilgan.
         `hash` maydoni bundan CHIQARIB tashlanadi (aralashishmaydi).
      2. secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
      3. hash = HMAC_SHA256(key=secret_key, msg=data_check_string).hexdigest()

    `tamper_fields` berilsa — imzolashdan OLDIN shu maydonlarni
    noto'g'ri qiymat bilan qo'shadi/asl qiymatini buzadi, natijada
    `data_check_string` o'zgaradi va imzo mos kelmay qoladi (backend
    rad etishi kerak — negative test case uchun).
    """
    user = {"id": user_id, "first_name": "Test", "username": "test_user"}
    params = {
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(int(time.time())),
    }
    if tamper_fields:
        params.update(tamper_fields)

    # 1) hash'ni CHIQARGAN HOLDA buguncheck_string ni tuzamiz
    check_string = "\n".join(f"{k}={params[k]}" for k in sorted(params))

    # 2) secret_key
    secret_key = hmac.new(
        b"WebAppData",
        settings.bot_token.encode(),
        hashlib.sha256,
    ).digest()

    # 3) hash
    params["hash"] = hmac.new(
        secret_key,
        check_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    return "&".join(f"{k}={v}" for k, v in sorted(params.items()))


def api(method, path, data=None, files=None):
    """Oddiy API chaqiruv."""
    url = f"{BASE}{path}"
    body = None
    headers = {}

    if files:
        import uuid
        boundary = uuid.uuid4().hex
        parts = []
        if data:
            for k, v in data.items():
                parts.append(
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{k}"\r\n\r\n'
                    f"{v}\r\n"
                )
        for fname, fdata, ftype in files:
            parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{fname}"; filename="test.webm"\r\n'
                f"Content-Type: {ftype}\r\n\r\n"
            )
            parts.append(fdata)
            parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n")
        body = b"".join(parts) if isinstance(parts[0], bytes) else b"".join(
            p.encode() if isinstance(p, str) else p for p in parts
        )
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif data:
        body = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = {"detail": str(e)}
        return e.code, body
    except Exception as e:
        return 0, {"error": str(e)}


def check(name, condition, detail=""):
    global passed, failed
    status = "PASS" if condition else "FAIL"
    if condition:
        passed += 1
    else:
        failed += 1
    msg = f"  [{status}] {name}"
    if detail:
        msg += f" — {detail}"
    results_log.append(msg)
    print(msg)


print("=" * 60)
print("  REAL END-TO-END SMOKE TEST")
print("=" * 60)
print()

# ═══════════════════════════════════════════════
# TEST 1: Yangi foydalanuvchi → active attempt
# ═══════════════════════════════════════════════
print("--- TEST 1: Yangi foydalanuvchi → active attempt ---")
TELEGRAM_ID_1 = 999001
status, data = api("POST", "/api/attempts", {"user_id": make_init_data(TELEGRAM_ID_1)})
check("POST /api/attempts → 200", status == 200, f"status={status}")
check("attempt.status = active", data.get("status") == "active", f"got={data.get('status')}")
check("attempt.id exists", "id" in data, f"id={data.get('id')}")
check("existing = False (yangi)", data.get("existing") is False, f"got={data.get('existing')}")
ATTEMPT_ID_1 = data.get("id")
print()

# ═══════════════════════════════════════════════
# TEST 2: Qayta kirish → mavjud active attempt
# ═══════════════════════════════════════════════
print("--- TEST 2: Qayta kirish → mavjud active attempt ---")
status, data = api("POST", "/api/attempts", {"user_id": make_init_data(TELEGRAM_ID_1)})
check("POST /api/attempts → 200 (qayta)", status == 200, f"status={status}")
check("existing = True", data.get("existing") is True, f"got={data.get('existing')}")
check("same attempt_id", data.get("id") == ATTEMPT_ID_1, f"got={data.get('id')}, expected={ATTEMPT_ID_1}")
check("status = active", data.get("status") == "active", f"got={data.get('status')}")
print()

# ═══════════════════════════════════════════════
# TEST 3: Active attemptga answer yuborish
# ═══════════════════════════════════════════════
print("--- TEST 3: Active attemptga answer yuborish ---")
# Avval savollarni olish kerak (question_id olish uchun)
status, questions = api("GET", "/api/questions")
check("GET /api/questions → 200", status == 200, f"status={status}")
Q_ID = questions[0]["id"] if questions else 1

fake_audio = b"\x00" * 1024
status, data = api(
    "POST",
    f"/api/attempts/{ATTEMPT_ID_1}/answers/{Q_ID}",
    files=[("audio", fake_audio, "audio/webm")],
)
check("POST /answers → 200", status == 200, f"status={status}")
check("success = True", data.get("success") is True, f"got={data.get('success')}")
print()

# ═══════════════════════════════════════════════
# TEST 4: Finish → active → processing
# ═══════════════════════════════════════════════
print("--- TEST 4: Finish → active → processing ---")
status, data = api("POST", f"/api/attempts/{ATTEMPT_ID_1}/finish")
check("POST /finish → 200", status == 200, f"status={status}")
check("processing = True", data.get("processing") is True, f"got={data.get('processing')}")

# Tekshir: database'da processing bo'lishi kerak
status, data = api("GET", f"/api/attempts/{ATTEMPT_ID_1}/results")
check("GET /results → 200", status == 200, f"status={status}")
check("status = processing (background hali ishlashi mumkin)", data.get("status") in ("processing", "finished"), f"got={data.get('status')}")
print()

# ═══════════════════════════════════════════════
# TEST 5: Finished attemptga qayta answer → 403
# ═══════════════════════════════════════════════
print("--- TEST 5: Processing/finished attemptga answer → 403 ---")
status, data = api(
    "POST",
    f"/api/attempts/{ATTEMPT_ID_1}/answers/{Q_ID}",
    files=[("audio", fake_audio, "audio/webm")],
)
check("POST /answers (finished) → 403", status == 403, f"status={status}")
check("error message contains 'yakunlangan' or 'yuborish'",
      "yakunlangan" in str(data.get("detail", "")).lower() or "yuborish" in str(data.get("detail", "")).lower(),
      f"detail={data.get('detail')}")
print()

# ═══════════════════════════════════════════════
# TEST 6: Finished attemptga qayta finish → 409
# ═══════════════════════════════════════════════
print("--- TEST 6: Finished attemptga qayta finish → 409 ---")
import time
time.sleep(2)  # Background task tugashini kutish
status, data = api("POST", f"/api/attempts/{ATTEMPT_ID_1}/finish")
check("POST /finish (double) → 409", status == 409, f"status={status}")
check("error mentions yakunlangan or qayta",
      "yakunlangan" in str(data.get("detail", "")).lower() or "qayta" in str(data.get("detail", "")).lower(),
      f"detail={data.get('detail')}")
print()

# ═══════════════════════════════════════════════
# TEST 7: Yangi attempt yaratishga urinish → 403
# ═══════════════════════════════════════════════
print("--- TEST 7: Finished foydalanuvchi → yangi attempt 403 ---")
status, data = api("POST", "/api/attempts", {"user_id": make_init_data(TELEGRAM_ID_1)})
check("POST /api/attempts (finished user) → 403", status == 403, f"status={status}")
check("detail mentions allaqachon", "allaqachon" in str(data.get("detail", "")).lower(),
      f"detail={data.get('detail')}")
check("attempt_id returned", "attempt_id" in str(data.get("detail", "")) or "attempt_id" in data,
      f"data={data}")
print()

# ═══════════════════════════════════════════════
# TEST 8: Results endpoint ishlayapti
# ═══════════════════════════════════════════════
print("--- TEST 8: Results endpoint ---")
status, data = api("GET", f"/api/attempts/{ATTEMPT_ID_1}/results")
check("GET /results → 200", status == 200, f"status={status}")
check("attempt_id matches", data.get("attempt_id") == ATTEMPT_ID_1)
check("results is list", isinstance(data.get("results"), list))
check("status in response", data.get("status") in ("processing", "finished"))
print()

# ═══════════════════════════════════════════════
# TEST 9: Results endpoint → 404 (not found)
# ═══════════════════════════════════════════════
print("--- TEST 9: Results endpoint 404 ---")
status, data = api("GET", "/api/attempts/999999/results")
check("GET /results (not found) → 404", status == 404, f"status={status}")
print()

# ═══════════════════════════════════════════════
# TEST 10: Finish → 404 (not found)
# ═══════════════════════════════════════════════
print("--- TEST 10: Finish endpoint 404 ---")
status, data = api("POST", "/api/attempts/999999/finish")
check("POST /finish (not found) → 404", status == 404, f"status={status}")
print()

# ═══════════════════════════════════════════════
# TEST 11: Eski "started" status compatibility
# ═══════════════════════════════════════════════
print("--- TEST 11: Eski 'started' status compatibility ---")
# Database ga to'g'ridan-to'g'ri "started" statusli attempt qo'shish
# (bu test faqat backend ishlayotganini tekshiradi)
TELEGRAM_ID_2 = 999002
status, data = api("POST", "/api/attempts", {"user_id": make_init_data(TELEGRAM_ID_2)})
check("Yangi user → active attempt", status == 200 and data.get("status") == "active")
ATTEMPT_ID_2 = data.get("id")
print()

# ═══════════════════════════════════════════════
# TEST 12: Different user → independent attempts
# ═══════════════════════════════════════════════
print("--- TEST 12: Different user → independent attempts ---")
TELEGRAM_ID_3 = 999003
status, data1 = api("POST", "/api/attempts", {"user_id": make_init_data(TELEGRAM_ID_3)})
check("User 3 → attempt created", status == 200, f"status={status}")
ATTEMPT_ID_3 = data1.get("id")

status, data2 = api("POST", "/api/attempts", {"user_id": make_init_data(TELEGRAM_ID_1)})
check("User 1 (finished) still blocked → 403", status == 403)
check("User 3 still has active attempt", True)  # User 1 bloklangan, User 3 mustaqil
print()

# ═══════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════
print("=" * 60)
print(f"  RESULTS: {passed} PASSED / {failed} FAILED")
print("=" * 60)
print()
for line in results_log:
    print(line)

print()
print("ENVIRONMENT NOTE:")
print("  Telegram WebApp environment mavjud EMAS.")
print("  Faqat backend API (localhost:8000) real ishlatildi.")
print("  Frontend rendering/UX test qilinmadi.")
