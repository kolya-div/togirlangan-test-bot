"""
Full integration test: evaluation -> feedback JSON -> report_service output.
No mocking — real AI calls through real service chain.
"""
import asyncio
import json
import html
import sys
sys.path.insert(0, ".")

from app.services.evaluation_service import evaluate_answer
from app.services.report_service import _annotate, _answer_text


class FakeQuestion:
    def __init__(self, text, section="A", order=1, max_points=10):
        self.text = text
        self.section = section
        self.order_number = order
        self.max_points = max_points


class FakeAnswer:
    def __init__(self, id, question_id, transcript, feedback, score):
        self.id = id
        self.question_id = question_id
        self.transcript = transcript
        self.feedback = feedback
        self.score = score
        self.audio_path = None


async def test_evaluation_chain():
    print("=" * 60)
    print("INTEGRATION: evaluation -> feedback JSON -> report")
    print("=" * 60)

    cases = [
        {
            "name": "Genis Zaman correct",
            "question": "Türkçe öğreniyor musun?",
            "transcript": "Evet, her gün Türkçe öğrenirim.",
            "expect_mistakes_empty": True,
            "expect_grammar_correct": True,
            "expect_corrected_equals_transcript": True,
        },
        {
            "name": "Simdiki Zaman correct",
            "question": "Türkçe öğreniyor musun?",
            "transcript": "Evet, her gün Türkçe öğreniyorum.",
            "expect_mistakes_empty": True,
            "expect_grammar_correct": True,
            "expect_corrected_equals_transcript": True,
        },
        {
            "name": "Real grammar error",
            "question": "Türkçe öğreniyor musun?",
            "transcript": "Evet, her gün Türkçe öğreniyor.",
            "expect_mistakes_empty": False,
            "expect_grammar_correct": False,
            "expect_corrected_equals_transcript": False,
        },
    ]

    results = []
    for c in cases:
        print(f"\n--- {c['name']} ---")
        print(f"Question: {c['question']}")
        print(f"Transcript: {c['transcript']}")

        try:
            # Step 1: Call evaluation service
            eval_result = await evaluate_answer(c["question"], c["transcript"])
            print(f"  [1] Evaluation: score={eval_result.get('score')}, mistakes={len(eval_result.get('mistakes', []))}")

            # Step 2: Build feedback JSON (same as report_service does)
            feedback_json = json.dumps({
                "transcript": c["transcript"],
                "corrected_text": eval_result.get("corrected_text", c["transcript"]),
                "is_grammatically_correct": eval_result.get("is_grammatically_correct", True),
                "mistakes": eval_result.get("mistakes", []),
                "scores": eval_result.get("scores", {}),
                "strengths": eval_result.get("strengths", []),
                "feedback_uz": eval_result.get("feedback_uz", ""),
                "feedback_tr": eval_result.get("feedback_tr", ""),
            }, ensure_ascii=False)
            print(f"  [2] Feedback JSON built ({len(feedback_json)} chars)")

            # Step 3: Parse back (simulates report_service reading from DB)
            feedback_data = json.loads(feedback_json)
            mistakes = feedback_data.get("mistakes", [])
            corrected = feedback_data.get("corrected_text", "")
            transcript = feedback_data.get("transcript", "")
            is_gram = feedback_data.get("is_grammatically_correct", True)
            print(f"  [3] Parsed: transcript='{transcript}', corrected='{corrected}', is_gram={is_gram}")

            # Step 4: Build answer object for report
            answer = FakeAnswer(
                id=1,
                question_id=1,
                transcript=c["transcript"],
                feedback=feedback_json,
                score=eval_result.get("score", 0),
            )
            question = FakeQuestion(c["question"])

            # Step 5: Generate Telegram-style report text
            report_text = _answer_text(1, 1, answer, question, {"pts": 10, "earned": 8})
            print(f"  [4] Report text ({len(report_text)} chars):")
            for line in report_text.split("\n"):
                print(f"      {line}")

            # Step 6: Verify invariant
            ok1 = (len(mistakes) == 0) == c["expect_mistakes_empty"]
            ok2 = is_gram == c["expect_grammar_correct"]
            ok3 = (corrected == transcript) == c["expect_corrected_equals_transcript"]

            if c["expect_corrected_equals_transcript"]:
                # KEY invariant: for correct sentences, corrected must equal transcript
                ok_invariant = corrected.strip() == c["transcript"].strip()
            else:
                ok_invariant = True  # errors allowed to differ

            all_ok = ok1 and ok2 and ok3 and ok_invariant
            print(f"  RESULT: {'PASS' if all_ok else 'FAIL'} (mistakes_ok={ok1}, grammar_ok={ok2}, corrected_ok={ok3}, invariant={ok_invariant})")
            results.append((c["name"], all_ok))

        except Exception as e:
            import traceback
            print(f"  ERROR: {e}")
            traceback.print_exc()
            results.append((c["name"], False))

    return results


async def test_feedback_json_edge_cases():
    print("\n" + "=" * 60)
    print("FEEDBACK JSON EDGE CASES — parsing safety")
    print("=" * 60)

    from app.services.text_check_service import _parse_and_validate as tc_parse
    from app.services.evaluation_service import _parse_and_validate as eval_parse

    cases = [
        ("Empty string", tc_parse, "", False),
        ("Invalid JSON", tc_parse, "not json", False),
        ("Missing mistakes", tc_parse, '{"corrected_text":"ok"}', True),
        ("Null corrected_text", tc_parse, '{"mistakes":[],"corrected_text":null}', True),
        ("Markdown wrapped", tc_parse, '```json\n{"corrected_text":"ok","mistakes":[]}\n```', True),
        ("Extra text before JSON", eval_parse, 'Here is the result:\n{"score":80,"level":"B1","mistakes":[],"strengths":[],"feedback_uz":"ok","feedback_tr":"ok"}', True),
        ("Only score field", eval_parse, '{"score":50}', True),
        ("Negative score", eval_parse, '{"score":-5,"level":"B1","mistakes":[],"strengths":[],"feedback_uz":"ok","feedback_tr":"ok"}', True),
    ]

    results = []
    for name, parser, input_data, expect_success in cases:
        print(f"\n--- {name} ---")
        try:
            r = parser(input_data)
            ok = expect_success
            print(f"  Result: parsed successfully. Keys: {list(r.keys())}")
            results.append((name, ok))
        except (ValueError, Exception) as e:
            ok = not expect_success
            print(f"  Result: raised {type(e).__name__}: {e}")
            results.append((name, ok))

    return results


async def test_report_annotate():
    print("\n" + "=" * 60)
    print("REPORT _annotate — XSS safety")
    print("=" * 60)

    cases = [
        ("Normal text", "Ben kitap okuyorum.", [], "Ben kitap okuyorum."),
        ("XSS attempt", '<script>alert("xss")</script>', [], "&lt;script&gt;"),
        ("Mistake with HTML in original", "kitab", [{"original": "kitab", "correct": "kitap", "type": "imlo", "explanation_uz": ""}], "<s>kitab</s>"),
    ]

    results = []
    for name, transcript, mistakes, expected_substring in cases:
        print(f"\n--- {name} ---")
        try:
            result = _annotate(transcript, mistakes)
            ok = expected_substring in result
            print(f"  Input: {transcript}")
            print(f"  Output: {result}")
            print(f"  Contains expected: {ok}")
            results.append((name, ok))
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append((name, False))

    return results


async def main():
    all_results = []

    r1 = await test_evaluation_chain()
    all_results.extend(r1)

    r2 = await test_feedback_json_edge_cases()
    all_results.extend(r2)

    r3 = await test_report_annotate()
    all_results.extend(r3)

    print("\n" + "=" * 60)
    print("FINAL INTEGRATION SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, ok in all_results if ok)
    failed = sum(1 for _, ok in all_results if not ok)
    print(f"Total: {len(all_results)} | PASS: {passed} | FAIL: {failed}")
    for name, ok in all_results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")


if __name__ == "__main__":
    asyncio.run(main())
