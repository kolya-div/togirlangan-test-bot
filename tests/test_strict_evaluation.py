"""
Qat'iy baholash: yomon gapirganlar yuqori ball olmasligi kerak.
- Ball = kategoriya ballari yig'indisi (AI "score" ni oshirib yozsa ham)
- Juda qisqa javob ball chegarasi
- Tushunarsiz joylar ko'p bo'lsa chegarasi
- suffix/word_order xatolari bo'lsa grammar balli 25 ga ko'tarilmaydi
- Gemini baholashga audio ham yuboriladi
- Transkripsiya prompti xatolarni tuzatmaslikni talab qiladi
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services import evaluation_service
from app.services.evaluation_service import _apply_strictness, _validate_consistency
from app.services.prompts import TRANSCRIPTION_SYSTEM_PROMPT

LONG_ANSWER = (
    "Benim adım Ali. Ben Taşkent'te yaşıyorum ve üniversitede ekonomi okuyorum. "
    "Boş zamanlarımda kitap okurum, arkadaşlarımla futbol oynarım ve bazen sinemaya giderim. "
    "Gelecekte Türkiye'de çalışmak istiyorum çünkü Türk kültürünü çok seviyorum."
)


def _ai(score, **scores):
    base = {"grammar": 25, "vocabulary": 25, "pronunciation": 20,
            "sentence_structure": 15, "relevance": 15}
    base.update(scores)
    return {"score": score, "level": "C1", "scores": base, "score_reasons": [], "mistakes": []}


def test_score_is_sum_of_category_scores():
    data = _ai(95, vocabulary=10, pronunciation=8, sentence_structure=5)
    result = _apply_strictness(data, LONG_ANSWER)
    assert result["score"] == 25 + 10 + 8 + 5 + 15
    assert result["level"] == "B1"  # 63 < 68


def test_category_scores_are_clamped_to_max():
    data = _ai(100, grammar=40)
    assert _apply_strictness(data, LONG_ANSWER)["score"] == 100


@pytest.mark.parametrize("transcript,cap", [
    ("eee merhaba", 10),
    ("eee ben ııı Ali ben öğrenci", 35),
    ("Ben Ali. Ben öğrenciyim. Ben futbol seviyorum. Okul güzel.", 55),
])
def test_short_answers_are_capped(transcript, cap):
    result = _apply_strictness(_ai(100), transcript)
    assert result["score"] == cap
    assert result["score_reasons"]


def test_unclear_speech_is_capped():
    transcript = LONG_ANSWER + " [anlaşılmıyor] ve [anlaşılmıyor] sonra [anlaşılmıyor]"
    assert _apply_strictness(_ai(100), transcript)["score"] == 50


def test_good_long_answer_keeps_high_score():
    assert _apply_strictness(_ai(92, vocabulary=22, pronunciation=17), LONG_ANSWER)["score"] == 94


def test_suffix_mistakes_do_not_restore_grammar_score():
    data = _ai(70, grammar=15)
    data["is_grammatically_correct"] = True
    data["mistakes"] = [{"original": "okula gidiyor", "correct": "okula gidiyorum", "type": "suffix"}]
    assert _validate_consistency(data)["scores"]["grammar"] == 15


def test_transcription_prompt_is_verbatim():
    prompt = TRANSCRIPTION_SYSTEM_PROMPT
    assert "TUZATMA" in prompt
    assert "[anlaşılmıyor]" in prompt
    assert "Punctuationlarni to'g'ri qo'y" not in prompt


@pytest.mark.anyio
async def test_gemini_evaluation_receives_audio(tmp_path, monkeypatch):
    audio = tmp_path / "answer.webm"
    audio.write_bytes(b"\x1aE\xdf\xa3fake-audio")
    captured = {}

    def fake_generate(**kw):
        captured.update(kw)
        return SimpleNamespace(text='{"score": 80, "level": "B2", "mistakes": [], "strengths": [], '
                                    '"feedback_uz": "", "feedback_tr": "", "scores": {"grammar": 20, '
                                    '"vocabulary": 20, "pronunciation": 15, "sentence_structure": 10, '
                                    '"relevance": 15}}')

    fake_client = SimpleNamespace(models=SimpleNamespace(generate_content=fake_generate))
    monkeypatch.setattr(evaluation_service.settings, "gemini_api_key", "key-A", raising=False)
    monkeypatch.setattr(evaluation_service, "_get_gemini_rotator",
                        lambda: SimpleNamespace(get_next_key=AsyncMock(return_value="key-A")))
    with patch("google.genai.Client", return_value=fake_client), \
            patch.object(evaluation_service, "wait_gemini", AsyncMock()):
        result = await evaluation_service._evaluate_with_gemini("Soru?", LONG_ANSWER, audio_path=audio)

    parts = captured["contents"][0]["parts"]
    assert any("inline_data" in p for p in parts)
    assert captured["config"] == {"temperature": 0}
    assert result["score"] == 80  # qat'iylik evaluate_answer da qo'llanadi


@pytest.mark.anyio
async def test_evaluate_answer_applies_strictness():
    raw = _ai(95)
    with patch.object(evaluation_service.settings, "gemini_api_key", "k", create=True), \
            patch.object(type(evaluation_service.settings), "gemini_keys_list",
                         property(lambda self: ["k"])), \
            patch.object(evaluation_service, "_evaluate_with_gemini", AsyncMock(return_value=raw)):
        result = await evaluation_service.evaluate_answer("Soru?", "eee merhaba", audio_path=Path("x"))
    assert result["score"] == 10
