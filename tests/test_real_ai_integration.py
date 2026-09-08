"""
Real AI integration tests — mock yo'q, haqiqiy API call.
"""
import asyncio
import json
import sys
sys.path.insert(0, ".")

from app.services.text_check_service import check_turkish_text
from app.services.evaluation_service import evaluate_answer


async def run_text_check_tests():
    print("=" * 60)
    print("TEXT CHECK SERVICE — REAL AI TESTS")
    print("=" * 60)

    tests = [
        {
            "name": "Test 1: Şimdiki Zaman (okuyorum)",
            "input": "Ben kitap okuyorum.",
            "expect_mistakes_empty": True,
        },
        {
            "name": "Test 2: Geniş Zaman (okurum)",
            "input": "Ben kitap okurum.",
            "expect_mistakes_empty": True,
        },
        {
            "name": "Test 3: Haqiqiy xato (okuyur)",
            "input": "Ben kitap okuyur.",
            "expect_mistakes_empty": False,
        },
    ]

    results = []
    for t in tests:
        print(f"\n--- {t['name']} ---")
        print(f"Input: {t['input']}")
        try:
            r = await check_turkish_text(t["input"])
            mistakes = r.get("mistakes", [])
            corrected = r.get("corrected_text", "")
            is_gram = r.get("is_grammatically_correct", None)
            print(f"Mistakes: {json.dumps(mistakes, ensure_ascii=False)}")
            print(f"Corrected: {corrected}")
            print(f"Is gram correct: {is_gram}")

            if t["expect_mistakes_empty"]:
                ok = len(mistakes) == 0
                print(f"PASS (mistakes empty): {ok}")
            else:
                ok = len(mistakes) > 0
                print(f"PASS (mistakes found): {ok}")
            results.append((t["name"], ok))
        except Exception as e:
            print(f"ERROR: {e}")
            results.append((t["name"], False))

    return results


async def run_eval_tests():
    print("\n" + "=" * 60)
    print("EVALUATION SERVICE — REAL AI TESTS")
    print("=" * 60)

    tests = [
        {
            "name": "Eval Test 1: Şimdiki Zaman (learniyorum)",
            "question": "Türkçe öğreniyor musun?",
            "transcript": "Evet, her gün Türkçe öğreniyorum.",
            "expect_mistakes_empty": True,
            "expect_grammar_correct": True,
        },
        {
            "name": "Eval Test 2: Geniş Zaman (öğrenirim)",
            "question": "Türkçe öğreniyor musun?",
            "transcript": "Evet, her gün Türkçe öğrenirim.",
            "expect_mistakes_empty": True,
            "expect_grammar_correct": True,
        },
        {
            "name": "Eval Test 3: Tense mismatch — Geniş kutilgan, Şimdiki ishlatilgan",
            "question": "Türkçe öğreniyor musun?",
            "transcript": "Evet, her gün Türkçe öğreniyorum.",
            "expect_mistakes_empty": True,
            "expect_grammar_correct": True,
        },
        {
            "name": "Eval Test 4: Haqiqiy xato (öğreniyor)",
            "question": "Türkçe öğreniyor musun?",
            "transcript": "Evet, her gün Türkçe öğreniyor.",
            "expect_mistakes_empty": False,
            "expect_grammar_correct": False,
        },
    ]

    results = []
    for t in tests:
        print(f"\n--- {t['name']} ---")
        print(f"Question: {t['question']}")
        print(f"Transcript: {t['transcript']}")
        try:
            r = await evaluate_answer(t["question"], t["transcript"])
            mistakes = r.get("mistakes", [])
            corrected = r.get("corrected_text", "")
            is_gram = r.get("is_grammatically_correct", None)
            score = r.get("score", 0)
            print(f"Mistakes: {json.dumps(mistakes, ensure_ascii=False)}")
            print(f"Corrected: {corrected}")
            print(f"Is gram correct: {is_gram}")
            print(f"Score: {score}")

            ok1 = (len(mistakes) == 0) == t["expect_mistakes_empty"]
            ok2 = is_gram == t["expect_grammar_correct"]
            ok = ok1 and ok2
            print(f"PASS: {ok}")
            results.append((t["name"], ok))
        except Exception as e:
            print(f"ERROR: {e}")
            results.append((t["name"], False))

    return results


async def run_false_positive_tests():
    print("\n" + "=" * 60)
    print("FALSE POSITIVE TESTS — 6 grammatically correct sentences")
    print("=" * 60)

    sentences = [
        "Her gün okula giderim.",
        "Şu anda okula gidiyorum.",
        "Türkçe konuşurum.",
        "Şimdi Türkçe konuşuyorum.",
        "Kitap okumayı severim.",
        "Şu anda kitap okuyorum.",
    ]

    results = []
    for s in sentences:
        print(f"\n--- Input: {s} ---")
        try:
            r = await check_turkish_text(s)
            mistakes = r.get("mistakes", [])
            corrected = r.get("corrected_text", "")
            is_gram = r.get("is_grammatically_correct", None)
            print(f"Mistakes count: {len(mistakes)}")
            if mistakes:
                print(f"Mistakes: {json.dumps(mistakes, ensure_ascii=False)}")
            print(f"Corrected: {corrected}")
            print(f"Is gram correct: {is_gram}")

            ok = len(mistakes) == 0
            print(f"PASS (no mistakes): {ok}")
            results.append((s, ok))
        except Exception as e:
            print(f"ERROR: {e}")
            results.append((s, False))

    return results


async def run_corrected_text_integrity():
    print("\n" + "=" * 60)
    print("CORRECTED TEXT INTEGRITY — correct sentences unchanged")
    print("=" * 60)

    sentences = [
        "Ben kitap okuyorum.",
        "Ben kitap okurum.",
        "Her gün okula giderim.",
        "Şu anda okula gidiyorum.",
        "Türkçe konuşurum.",
        "Şimdi Türkçe konuşuyorum.",
    ]

    results = []
    for s in sentences:
        print(f"\n--- Input: {s} ---")
        try:
            r = await check_turkish_text(s)
            corrected = r.get("corrected_text", "").strip()
            mistakes = r.get("mistakes", [])
            print(f"Transcript:   {s}")
            print(f"Corrected:    {corrected}")
            print(f"Mistakes:     {len(mistakes)}")

            if len(mistakes) == 0:
                ok = corrected == s.strip()
                print(f"PASS (corrected == transcript): {ok}")
            else:
                ok = True  # has mistakes, so corrected can differ
                print(f"SKIP (has mistakes, corrected may differ)")
            results.append((s, ok))
        except Exception as e:
            print(f"ERROR: {e}")
            results.append((s, False))

    return results


async def main():
    all_results = []

    r1 = await run_text_check_tests()
    all_results.extend(r1)

    r2 = await run_eval_tests()
    all_results.extend(r2)

    r3 = await run_false_positive_tests()
    all_results.extend(r3)

    r4 = await run_corrected_text_integrity()
    all_results.extend(r4)

    print("\n" + "=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, ok in all_results if ok)
    failed = sum(1 for _, ok in all_results if not ok)
    print(f"Total: {len(all_results)} | PASS: {passed} | FAIL: {failed}")
    for name, ok in all_results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")


if __name__ == "__main__":
    asyncio.run(main())
