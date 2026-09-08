"""
EXTENDED SMOKE TEST — Edge cases
1. Old "started" status attempt behavior
2. Background processing completes → finished
3. Finished attempt → results have full data
4. OpenAPI schema (frontend contract)
"""
import json
import time
import os
import hashlib
import hmac
import asyncio
import urllib.parse
import urllib.request
import urllib.error

from app.config import settings


def make_init_data(user_id: int) -> str:
    """Telegram WebApp initData strukturasida valid imzo yaratadi (test uchun)."""
    user = {"id": user_id, "first_name": "Test", "username": "test_user"}
    params = {
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(int(time.time())),
    }
    check_string = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret_key = hmac.new(
        b"WebAppData",
        settings.bot_token.encode(),
        hashlib.sha256,
    ).digest()
    params["hash"] = hmac.new(
        secret_key,
        check_string.encode(),
        hashlib.sha256,
    ).hexdigest()
    return "&".join(f"{k}={v}" for k, v in params.items())

BASE = "http://localhost:8000"
passed = 0
failed = 0


def api_get(path):
    url = f"{BASE}{path}"
    req = urllib.request.Request(url, method="GET")
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


def api_post_form(path, data):
    url = f"{BASE}{path}"
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            b = json.loads(e.read())
        except Exception:
            b = {"detail": str(e)}
        return e.code, b
    except Exception as e:
        return 0, {"error": str(e)}


def api_post_multipart(path, data=None, file_bytes=b"\x00" * 1024, filename="audio", content_type="audio/webm"):
    import uuid
    boundary = uuid.uuid4().hex
    parts = []

    if data:
        for k, v in data.items():
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())

    file_header = (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"{filename}\"; filename=\"test.webm\"\r\n"
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode()
    parts.append(file_header)
    parts.append(file_bytes)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())

    body = b"".join(parts)
    url = f"{BASE}{path}"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            b = json.loads(e.read())
        except Exception:
            b = {"detail": str(e)}
        return e.code, b
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
    print(msg)


print("=" * 60)
print("  EXTENDED SMOKE TEST — Edge Cases")
print("=" * 60)

# ═══════════════════════════════════════════════
# E1: Old "started" status — force via DB
# ═══════════════════════════════════════════════
print("\n--- E1: Eski 'started' status compatibility ---")
TELEGRAM_ID = 888001
status, data = api_post_form("/api/attempts", {"init_data": make_init_data(TELEGRAM_ID)})
check("Create new user → active", status == 200 and data.get("status") == "active", f"status={data.get('status')}")
attempt_id = data.get("id")

# Force status to "started" in DB (simulating old data from before migration)
import asyncpg

DB_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/turkish_bot")
# asyncpg uses plain postgresql:// scheme
DB_SYNC_URL = DB_URL.replace("postgresql+asyncpg://", "postgresql://")

async def _force_status(attempt_id, new_status):
    conn = await asyncpg.connect(DB_SYNC_URL)
    await conn.execute("UPDATE test_attempts SET status=$1 WHERE id=$2", new_status, attempt_id)
    await conn.close()

asyncio.run(_force_status(attempt_id, "started"))

# Try answer — "started" is treated as "active" (backward compatibility)
status, data = api_post_multipart(
    f"/api/attempts/{attempt_id}/answers/1",
    file_bytes=b"\x00" * 1024,
)
check("Answer to 'started' attempt → 200 (accepted as active)",
      status == 200,
      f"status={status}")

# Try finish — "started" is treated as "active"
status, data = api_post_form(f"/api/attempts/{attempt_id}/finish", {})
check("Finish 'started' attempt → 200 (accepted as active)",
      status == 200,
      f"status={status}")
print()

# ═══════════════════════════════════════════════
# E2: Background processing completion
# ═══════════════════════════════════════════════
print("--- E2: Background processing → finished ---")
TELEGRAM_ID2 = 888002
status, data = api_post_form("/api/attempts", {"init_data": make_init_data(TELEGRAM_ID2)})
check("Create attempt", status == 200)
aid2 = data.get("id")

status, data = api_post_multipart(f"/api/attempts/{aid2}/answers/1")
check("Upload answer", status == 200)

status, data = api_post_form(f"/api/attempts/{aid2}/finish", {})
check("Finish → 200 + processing=True", status == 200 and data.get("processing") is True)

print("  Waiting for background processing...")
final_status = None
for i in range(60):
    time.sleep(1)
    status, data = api_get(f"/api/attempts/{aid2}/results")
    if status == 200:
        s = data.get("status")
        if s == "finished":
            final_status = s
            print(f"  [{i+1}s] status = finished ✓")
            break
        elif i % 5 == 0:
            print(f"  [{i+1}s] status = {s}...")
    else:
        print(f"  [{i+1}s] HTTP error: {status}")
        break

check("Background processing → finished", final_status == "finished", f"final={final_status}")
if final_status == "finished":
    check("results is list", isinstance(data.get("results"), list), f"len={len(data.get('results', []))}")
    check("total_score exists", data.get("total_score") is not None, f"score={data.get('total_score')}")
    check("level exists", data.get("level") is not None, f"level={data.get('level')}")
print()

# ═══════════════════════════════════════════════
# E3: OpenAPI schema check
# ═══════════════════════════════════════════════
print("--- E3: OpenAPI schema ---")
status, data = api_get("/openapi.json")
check("GET /openapi.json → 200", status == 200)
if status == 200:
    paths = list(data.get("paths", {}).keys())
    check("/api/attempts in paths", "/api/attempts" in paths)
    check("/api/questions in paths", "/api/questions" in paths)
    check("/api/attempts/{attempt_id}/finish in paths",
          "/api/attempts/{attempt_id}/finish" in paths)
print()

# ═══════════════════════════════════════════════
# E4: Race condition — simultaneous finish
# ═══════════════════════════════════════════════
print("--- E4: Simultaneous finish attempts ---")
TELEGRAM_ID3 = 888003
status, data = api_post_form("/api/attempts", {"init_data": make_init_data(TELEGRAM_ID3)})
aid3 = data.get("id")
status, data = api_post_form(f"/api/attempts/{aid3}/finish", {})
check("First finish → 200", status == 200)
status2, data2 = api_post_form(f"/api/attempts/{aid3}/finish", {})
check("Second finish → 409", status2 == 409, f"status={status2}")
print()

# ═══════════════════════════════════════════════
# E5: Finish with no answers
# ═══════════════════════════════════════════════
print("--- E5: Finish with 0 answers ---")
TELEGRAM_ID4 = 888004
status, data = api_post_form("/api/attempts", {"init_data": make_init_data(TELEGRAM_ID4)})
aid4 = data.get("id")
check("Create attempt (no answers)", status == 200)
status, data = api_post_form(f"/api/attempts/{aid4}/finish", {})
check("Finish with 0 answers → 200", status == 200)
check("total_answers = 0", data.get("total_answers") == 0, f"got={data.get('total_answers')}")
print()

# ═══════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════
print("=" * 60)
print(f"  RESULTS: {passed} PASSED / {failed} FAILED")
print("=" * 60)
