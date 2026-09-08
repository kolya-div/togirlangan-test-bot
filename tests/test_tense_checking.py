"""
Şimdiki Zaman va Geniş Zaman orasidagi farqni tekshirish testlari.

Bu testlar AI promptlarining to'g'ri ishlashini va
zamon tanlovini avtomatik xato deb belgilamasligini tekshiradi.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.text_check_service import (
    _build_prompt,
    _parse_and_validate,
    _SYSTEM_PROMPT,
)
from app.services.evaluation_service import (
    _build_prompt as _eval_build_prompt,
    _parse_and_validate as _eval_parse_and_validate,
    _SYSTEM_PROMPT as _EVAL_SYSTEM_PROMPT,
)


class TestTextCheckPromptContainsTenseRule:
    """text_check_service prompti zamon qoidasini o'z ichiga olishini tekshiradi."""

    def test_system_prompt_contains_simdiki_zaman_rule(self):
        """System prompt Şimdiki Zaman qoidasini o'z ichiga olishi kerak."""
        assert "Şimdiki Zaman" in _SYSTEM_PROMPT
        assert "Geniş Zaman" in _SYSTEM_PROMPT
        assert "-yor" in _SYSTEM_PROMPT

    def test_system_prompt_prohibits_tense_as_error(self):
        """System prompt zamon tanlovini xato deb belgilashni taqiqlashi kerak."""
        assert "XATO hisoblanmasin" in _SYSTEM_PROMPT or "XATO" in _SYSTEM_PROMPT

    def test_build_prompt_contains_tense_rule(self):
        """_build_prompt zamon qoidasini o'z ichiga olishi kerak."""
        prompt = _build_prompt("Ben kitap okuyorum.")
        assert "zamon" in prompt.lower()
        assert "xato" in prompt.lower()

    def test_build_prompt_contains_examples(self):
        """_build_prompt misollarni o'z ichiga olishi kerak."""
        prompt = _build_prompt("Ben kitap okuyorum.")
        assert "okuyorum" in prompt

    def test_build_prompt_prohibits_tense_change_in_corrected_text(self):
        """_build_prompt corrected_text da zamon o'zgartirishni taqiqlashi kerak."""
        prompt = _build_prompt("Ben kitap okuyorum.")
        assert "almashtirma" in prompt.lower() or "o'zgartirma" in prompt.lower()


class TestEvaluationPromptContainsTenseRule:
    """evaluation_service prompti zamon qoidasini o'z ichiga olishini tekshiradi."""

    def test_system_prompt_contains_simdiki_zaman_rule(self):
        """System prompt Şimdiki Zaman qoidasini o'z ichiga olishi kerak."""
        assert "Şimdiki Zaman" in _EVAL_SYSTEM_PROMPT
        assert "Geniş Zaman" in _EVAL_SYSTEM_PROMPT
        assert "-yor" in _EVAL_SYSTEM_PROMPT

    def test_system_prompt_prohibits_tense_as_error(self):
        """System prompt zamon tanlovini xato deb belgilashni taqiqlashi kerak."""
        assert "XATO DEB BAHOLAMA" in _EVAL_SYSTEM_PROMPT

    def test_system_prompt_has_examples(self):
        """System prompt misollarni o'z ichiga olishi kerak."""
        assert "okuyorum" in _EVAL_SYSTEM_PROMPT
        assert "okurum" in _EVAL_SYSTEM_PROMPT
        assert "öğreniyorum" in _EVAL_SYSTEM_PROMPT
        assert "öğrenirim" in _EVAL_SYSTEM_PROMPT

    def test_build_prompt_contains_tense_rule(self):
        """_build_prompt zamon qoidasini o'z ichiga olishi kerak."""
        prompt = _eval_build_prompt(
            "Türkçe öğreniyor musun?",
            "Evet, her gün Türkçe öğreniyorum."
        )
        assert "Şimdiki Zaman" in prompt
        assert "Geniş Zaman" in prompt

    def test_build_prompt_prohibits_tense_as_error(self):
        """_build_prompt zamon tanlovini xato deb belgilashni taqiqlashi kerak."""
        prompt = _eval_build_prompt(
            "Türkçe öğreniyor musun?",
            "Evet, her gün Türkçe öğreniyorum."
        )
        assert "XATO EMAS" in prompt or "XATO" in prompt

    def test_build_prompt_has_specific_examples(self):
        """_build_prompt aniq misollarni o'z ichiga olishi kerak."""
        prompt = _eval_build_prompt(
            "Türkçe öğreniyor musun?",
            "Evet, her gün Türkçe öğreniyorum."
        )
        assert "öğreniyorum" in prompt
        assert "öğrenirim" in prompt


class TestParseAndValidate:
    """JSON parse va validatsiya funksiyalarini tekshiradi."""

    def test_valid_json_with_no_mistakes(self):
        """Xatosiz matnni qabul qilish."""
        content = json.dumps({
            "corrected_text": "Ben kitap okuyorum.",
            "mistakes": [],
            "feedback_uz": "Gap to'g'ri."
        })
        result = _parse_and_validate(content)
        assert result["corrected_text"] == "Ben kitap okuyorum."
        assert result["mistakes"] == []

    def test_valid_json_with_mistakes(self):
        """Xatolikli matnni qabul qilish."""
        content = json.dumps({
            "corrected_text": "Ben kitap okuyorum.",
            "mistakes": [
                {
                    "original": "kitab",
                    "correct": "kitap",
                    "type": "imlo",
                    "explanation_uz": "Imlo xatosi"
                }
            ],
            "feedback_uz": "Bitta imlo xatosi bor."
        })
        result = _parse_and_validate(content)
        assert len(result["mistakes"]) == 1
        assert result["mistakes"][0]["original"] == "kitab"
        assert result["mistakes"][0]["correct"] == "kitap"

    def test_empty_content_raises_error(self):
        """Bo'sh content xato berishi kerak."""
        with pytest.raises(ValueError, match="bo'sh javob"):
            _parse_and_validate("")

    def test_invalid_json_raises_error(self):
        """Noto'g'ri JSON xato berishi kerak."""
        with pytest.raises(ValueError, match="noto'g'ri format"):
            _parse_and_validate("not json")

    def test_missing_mistakes_defaults_to_empty(self):
        """mistakes maydoni yo'q bo'lsa, bo'sh ro'yxat qaytarilishi kerak."""
        content = json.dumps({
            "corrected_text": "Test",
            "feedback_uz": "Test"
        })
        result = _parse_and_validate(content)
        assert result["mistakes"] == []

    def test_normalized_mistakes(self):
        """Xatolar normallashtirilishi kerak."""
        content = json.dumps({
            "corrected_text": "Test",
            "mistakes": [
                {
                    "original": "  kitab  ",
                    "correct": "  kitap  ",
                    "type": "  imlo  ",
                    "explanation_uz": "  Imlo xatosi  "
                }
            ],
            "feedback_uz": "Test"
        })
        result = _parse_and_validate(content)
        assert result["mistakes"][0]["original"] == "kitab"
        assert result["mistakes"][0]["correct"] == "kitap"
        assert result["mistakes"][0]["type"] == "imlo"


class TestEvalParseAndValidate:
    """evaluation_service JSON parse va validatsiya funksiyalarini tekshiradi."""

    def test_valid_evaluation_json(self):
        """To'g'ri baholash JSON ini qabul qilish."""
        content = json.dumps({
            "score": 85,
            "level": "B2",
            "corrected_text": "Ben Türkçe öğreniyorum.",
            "is_grammatically_correct": True,
            "mistakes": [],
            "scores": {
                "grammar": 23,
                "vocabulary": 20,
                "pronunciation": 15,
                "sentence_structure": 12,
                "relevance": 15
            },
            "strengths": ["Yaxshi grammatika"],
            "feedback_uz": "Juda yaxshi.",
            "feedback_tr": "Çok iyi."
        })
        result = _eval_parse_and_validate(content)
        assert result["score"] == 85
        assert result["level"] == "B2"
        assert result["mistakes"] == []

    def test_evaluation_with_mistakes(self):
        """Xatolikli baholash JSON ini qabul qilish."""
        content = json.dumps({
            "score": 70,
            "level": "B1",
            "corrected_text": "Ben her gün okuyorum.",
            "is_grammatically_correct": False,
            "mistakes": [
                {
                    "original": "hergün",
                    "correct": "her gün",
                    "type": "grammar",
                    "explanation_uz": "Ikki so'z bo'lishi kerak"
                }
            ],
            "scores": {
                "grammar": 18,
                "vocabulary": 18,
                "pronunciation": 14,
                "sentence_structure": 10,
                "relevance": 10
            },
            "strengths": ["Yaxshi talaffuz"],
            "feedback_uz": "Yaxshi, lekin bir xato bor.",
            "feedback_tr": "İyi, ama bir hata var."
        })
        result = _eval_parse_and_validate(content)
        assert result["score"] == 70
        assert len(result["mistakes"]) == 1

    def test_missing_required_fields_defaults(self):
        """Kerakli maydonlar yo'q bo'lsa, default qiymatlar qo'yilishi kerak."""
        content = json.dumps({
            "score": 50
        })
        result = _eval_parse_and_validate(content)
        assert result["level"] is None  # "Noma'lum" valid_levels da yo'q, shuning uchun None bo'ladi
        assert result["mistakes"] == []
        assert result["strengths"] == []

    def test_invalid_score_defaults_to_zero(self):
        """Noto'g'ri ball qiymati 0 ga o'zgartirilishi kerak."""
        content = json.dumps({
            "score": "invalid",
            "level": "B1",
            "mistakes": [],
            "strengths": [],
            "feedback_uz": "Test",
            "feedback_tr": "Test"
        })
        result = _eval_parse_and_validate(content)
        assert result["score"] == 0

    def test_invalid_level_defaults_to_none(self):
        """Noto'g'ri daraja None ga o'zgartirilishi kerak."""
        content = json.dumps({
            "score": 50,
            "level": "X",
            "mistakes": [],
            "strengths": [],
            "feedback_uz": "Test",
            "feedback_tr": "Test"
        })
        result = _eval_parse_and_validate(content)
        assert result["level"] is None

    def test_score_normalization(self):
        """Ballar 0 dan past bo'lmasligi kerak."""
        content = json.dumps({
            "score": -5,
            "level": "B1",
            "mistakes": [],
            "strengths": [],
            "feedback_uz": "Test",
            "feedback_tr": "Test",
            "scores": {
                "grammar": -10,
                "vocabulary": 30,
                "pronunciation": 15,
                "sentence_structure": 12,
                "relevance": 14
            }
        })
        result = _eval_parse_and_validate(content)
        # -10 -> clamped to 0, but consistency validator sees
        # is_grammatical=True + mistakes=[] + grammar=0 → restores to 25
        assert result["scores"]["grammar"] == 25
        assert result["scores"]["vocabulary"] == 30


class TestTenseNotMarkedAsError:
    """
    Zamon tanlovi avtomatik xato deb belgilanmasligini tekshiradi.
    Bu testlar AI mock bilan ishlaydi.
    """

    @pytest.mark.asyncio
    async def test_simdiki_zaman_not_marked_as_error(self):
        """Şimdiki Zaman ishlatilganda xato chiqmasligi kerak."""
        from app.services.text_check_service import check_turkish_text

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "corrected_text": "Ben kitap okuyorum.",
            "mistakes": [],
            "feedback_uz": "Gap grammatik jihatdan to'g'ri."
        })

        with patch("app.services.text_check_service.AsyncGroq") as MockGroq:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            MockGroq.return_value = mock_client

            with patch("app.services.text_check_service.settings") as mock_settings:
                mock_settings.gemini_api_key = None
                mock_settings.groq_api_key = "test-key"
                mock_settings.groq_chat_model = "llama-3.3-70b-versatile"

                result = await check_turkish_text("Ben kitap okuyorum.")

                assert result["mistakes"] == []
                assert result["corrected_text"] == "Ben kitap okuyorum."

    @pytest.mark.asyncio
    async def test_genis_zaman_not_marked_as_error(self):
        """Geniş Zaman ishlatilganda xato chiqmasligi kerak."""
        from app.services.text_check_service import check_turkish_text

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "corrected_text": "Ben kitap okurum.",
            "mistakes": [],
            "feedback_uz": "Gap grammatik jihatdan to'g'ri."
        })

        with patch("app.services.text_check_service.AsyncGroq") as MockGroq:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            MockGroq.return_value = mock_client

            with patch("app.services.text_check_service.settings") as mock_settings:
                mock_settings.gemini_api_key = None
                mock_settings.groq_api_key = "test-key"
                mock_settings.groq_chat_model = "llama-3.3-70b-versatile"

                result = await check_turkish_text("Ben kitap okurum.")

                assert result["mistakes"] == []
                assert result["corrected_text"] == "Ben kitap okurum."

    @pytest.mark.asyncio
    async def test_tense_difference_not_in_mistakes(self):
        """
        Şimdiki Zaman ishlatilgan, lekin expected answer Geniş Zaman bo'lsa,
        xato chiqmasligi kerak.
        """
        from app.services.text_check_service import check_turkish_text

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "corrected_text": "Ben Türkçe öğreniyorum.",
            "mistakes": [],
            "feedback_uz": "Gap to'g'ri."
        })

        with patch("app.services.text_check_service.AsyncGroq") as MockGroq:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            MockGroq.return_value = mock_client

            with patch("app.services.text_check_service.settings") as mock_settings:
                mock_settings.gemini_api_key = None
                mock_settings.groq_api_key = "test-key"
                mock_settings.groq_chat_model = "llama-3.3-70b-versatile"

                result = await check_turkish_text("Ben Türkçe öğreniyorum.")

                # Xatolar bo'lmasligi kerak
                assert len(result["mistakes"]) == 0

    @pytest.mark.asyncio
    async def test_real_grammar_error_still_detected(self):
        """Haqiqiy grammatik xato hali ham aniqlanishi kerak."""
        from app.services.text_check_service import check_turkish_text

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "corrected_text": "Ben kitap okuyorum.",
            "mistakes": [
                {
                    "original": "kitab",
                    "correct": "kitap",
                    "type": "imlo",
                    "explanation_uz": "Imlo xatosi: 'b' o'rniga 'p' bo'lishi kerak"
                }
            ],
            "feedback_uz": "Bitta imlo xatosi bor."
        })

        with patch("app.services.text_check_service.AsyncGroq") as MockGroq:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            MockGroq.return_value = mock_client

            with patch("app.services.text_check_service.settings") as mock_settings:
                mock_settings.gemini_api_key = None
                mock_settings.groq_api_key = "test-key"
                mock_settings.groq_chat_model = "llama-3.3-70b-versatile"

                result = await check_turkish_text("Ben kitab okuyorum.")

                # Haqiqiy xato aniqlanishi kerak
                assert len(result["mistakes"]) == 1
                assert result["mistakes"][0]["original"] == "kitab"
                assert result["mistakes"][0]["correct"] == "kitap"


class TestEvaluationTenseNotMarkedAsError:
    """
    Baholash xizmatida zamon tanlovi avtomatik xato deb belgilanmasligini tekshiradi.
    """

    @pytest.mark.asyncio
    async def test_evaluation_simdiki_zaman_correct(self):
        """Şimdiki Zaman ishlatilganda ball pasaytirilmasligi kerak."""
        from app.services.evaluation_service import evaluate_answer

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "score": 85,
            "level": "B2",
            "corrected_text": "Ben Türkçe öğreniyorum.",
            "is_grammatically_correct": True,
            "mistakes": [],
            "scores": {
                "grammar": 23,
                "vocabulary": 20,
                "pronunciation": 15,
                "sentence_structure": 12,
                "relevance": 15
            },
            "strengths": ["Yaxshi grammatika"],
            "feedback_uz": "Juda yaxshi.",
            "feedback_tr": "Çok iyi."
        })

        with patch("app.services.evaluation_service.AsyncGroq") as MockGroq:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            MockGroq.return_value = mock_client

            with patch("app.services.evaluation_service.settings") as mock_settings:
                mock_settings.gemini_api_key = None
                mock_settings.groq_api_key = "test-key"
                mock_settings.groq_chat_model = "llama-3.3-70b-versatile"

                result = await evaluate_answer(
                    "Türkçe öğreniyor musun?",
                    "Evet, her gün Türkçe öğreniyorum."
                )

                assert result["score"] == 85
                assert result["mistakes"] == []

    @pytest.mark.asyncio
    async def test_evaluation_genis_zaman_correct(self):
        """Geniş Zaman ishlatilganda ball pasaytirilmasligi kerak."""
        from app.services.evaluation_service import evaluate_answer

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "score": 85,
            "level": "B2",
            "corrected_text": "Ben Türkçe öğrenirim.",
            "is_grammatically_correct": True,
            "mistakes": [],
            "scores": {
                "grammar": 23,
                "vocabulary": 20,
                "pronunciation": 15,
                "sentence_structure": 12,
                "relevance": 15
            },
            "strengths": ["Yaxshi grammatika"],
            "feedback_uz": "Juda yaxshi.",
            "feedback_tr": "Çok iyi."
        })

        with patch("app.services.evaluation_service.AsyncGroq") as MockGroq:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            MockGroq.return_value = mock_client

            with patch("app.services.evaluation_service.settings") as mock_settings:
                mock_settings.gemini_api_key = None
                mock_settings.groq_api_key = "test-key"
                mock_settings.groq_chat_model = "llama-3.3-70b-versatile"

                result = await evaluate_answer(
                    "Türkçe öğreniyor musun?",
                    "Evet, her gün Türkçe öğrenirim."
                )

                assert result["score"] == 85
                assert result["mistakes"] == []

    @pytest.mark.asyncio
    async def test_evaluation_tense_difference_no_penalty(self):
        """
        Şimdiki Zaman o'rniga Geniş Zaman ishlatilganda ball kamaytirilmasligi kerak.
        """
        from app.services.evaluation_service import evaluate_answer

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "score": 80,
            "level": "B2",
            "corrected_text": "Ben her gün Türkçe çalışırım.",
            "is_grammatically_correct": True,
            "mistakes": [],
            "scores": {
                "grammar": 22,
                "vocabulary": 19,
                "pronunciation": 14,
                "sentence_structure": 11,
                "relevance": 14
            },
            "strengths": ["Yaxshi nutq"],
            "feedback_uz": "Yaxshi, lekin boshqa zamon ishlatildi.",
            "feedback_tr": "İyi, ama farklı zaman kullanıldı."
        })

        with patch("app.services.evaluation_service.AsyncGroq") as MockGroq:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            MockGroq.return_value = mock_client

            with patch("app.services.evaluation_service.settings") as mock_settings:
                mock_settings.gemini_api_key = None
                mock_settings.groq_api_key = "test-key"
                mock_settings.groq_chat_model = "llama-3.3-70b-versatile"

                result = await evaluate_answer(
                    "Her gün Türkçe çalışıyor musun?",
                    "Evet, her gün Türkçe çalışırım."
                )

                # Xatolar bo'lmasligi kerak
                assert len(result["mistakes"]) == 0
                # Ball yuqori bo'lishi kerak (grammatik xato deb hisoblanmasin)
                assert result["score"] >= 75


class TestTranscriptionPreservesOriginal:
    """
    Transkripsiya xizmati original matnni saqlab qolishini tekshiradi.
    Zamon o'zgartirilmaydi.
    """

    def test_normalize_text_preserves_tense(self):
        """normalize_text zamonni o'zgartirmaydi."""
        from app.services.transcription_service import _normalize_text

        assert _normalize_text("Ben kitap okuyorum.") == "Ben kitap okuyorum."
        assert _normalize_text("Ben kitap okurum.") == "Ben kitap okurum."
        assert _normalize_text("  Ben   kitap   okuyorum.  ") == "Ben kitap okuyorum."

    def test_is_valid_transcript_works(self):
        """is_valid_transcript to'g'ri ishlaydi."""
        from app.services.transcription_service import _is_valid_transcript

        assert _is_valid_transcript("Ben kitap okuyorum.") is True
        assert _is_valid_transcript("Ben kitap okurum.") is True
        assert _is_valid_transcript("") is False
        assert _is_valid_transcript("EMPTY") is False
        assert _is_valid_transcript("a") is False


class TestReportServicePreservesTranscript:
    """
    Hisobot xizmati original transcriptni saqlab qolishini tekshiradi.
    """

    def test_annotate_preserves_original_text(self):
        """_annotate original matnni saqlab qoladi."""
        from app.services.report_service import _annotate

        transcript = "Ben kitap okuyorum."
        mistakes = []
        result = _annotate(transcript, mistakes)
        assert "Ben kitap okuyorum." in result

    def test_annotate_with_mistakes(self):
        """_annotate xatolarni to'g'ri belgilaydi."""
        from app.services.report_service import _annotate

        transcript = "Ben kitab okuyorum."
        mistakes = [
            {
                "original": "kitab",
                "correct": "kitap",
                "type": "imlo",
                "explanation_uz": "Imlo xatosi"
            }
        ]
        result = _annotate(transcript, mistakes)
        assert "<s>kitab</s>" in result
        assert "<b>kitap</b>" in result


class TestSpecificScenarios:
    """
    Aniq ssenariylarni tekshiradi:
    Test A-E kabi specifik kirishlar uchun AI to'g'ri javob berishini ta'minlaydi.
    """

    def test_a_proper_simdiki_zaman_okuyorum(self):
        """Test A: 'okuyorum' — Şimdiki Zaman to'g'ri ishlatilgan, xato emas."""
        prompt = _build_prompt("Ben her gün kitap okuyorum.")
        # Prompt zamon qoidasini o'z ichiga olishi kerak
        assert "okuyorum" in prompt or "okurum" in prompt
        # Va xato deb belgilashni taqiqlashi kerak
        assert "xato" in prompt.lower() or "XATO" in prompt

    def test_b_proper_genis_zaman_okurum(self):
        """Test B: 'okurum' — Geniş Zaman to'g'ri ishlatilgan, xato emas."""
        prompt = _build_prompt("Ben her gün kitap okurum.")
        assert "okuyorum" in prompt or "okurum" in prompt
        assert "xato" in prompt.lower() or "XATO" in prompt

    def test_c_tense_mismatch_not_grammar_error_text_check(self):
        """Test C: Zamon mos kelmasligi grammatik xato emas — text_check."""
        content = json.dumps({
            "corrected_text": "Ben her gün Türkçe çalışıyorum.",
            "mistakes": [],
            "is_grammatically_correct": True,
            "feedback_uz": "Gap grammatik jihatdan to'g'ri."
        })
        result = _parse_and_validate(content)
        assert result["mistakes"] == []
        assert result["is_grammatically_correct"] is True

    def test_d_real_grammar_error_detected(self):
        """Test D: Haqiqiy grammatik xato aniqlanishi kerak — 'öğreniyor' (noto'g'ri shakl)."""
        content = json.dumps({
            "corrected_text": "Ben Türkçe öğreniyorum.",
            "mistakes": [
                {
                    "original": "öğreniyor",
                    "correct": "öğreniyorum",
                    "type": "grammar",
                    "explanation_uz": "Shaxs qo'shimchasi yo'q"
                }
            ],
            "is_grammatically_correct": False,
            "feedback_uz": "Grammatik xato bor."
        })
        result = _parse_and_validate(content)
        assert len(result["mistakes"]) == 1
        assert result["mistakes"][0]["original"] == "öğreniyor"
        assert result["is_grammatically_correct"] is False

    def test_e_irrelevant_answer_grammar_correct(self):
        """Test E: Savolga mos javob emas, lekin grammatik to'g'ri — text_check uchun xato emas."""
        content = json.dumps({
            "corrected_text": "Hava bugün çok güzel.",
            "mistakes": [],
            "is_grammatically_correct": True,
            "feedback_uz": "Gap grammatik jihatdan to'g'ri."
        })
        result = _parse_and_validate(content)
        assert result["mistakes"] == []
        assert result["is_grammatically_correct"] is True

    def test_c_tense_mismatch_not_grammar_error_eval(self):
        """Test C: Zamon mos kelmasligi grammatik xato emas — evaluation."""
        content = json.dumps({
            "score": 75,
            "level": "B1",
            "corrected_text": "Ben her gün Türkçe çalışıyorum.",
            "is_grammatically_correct": True,
            "mistakes": [],
            "scores": {
                "grammar": 22,
                "vocabulary": 18,
                "pronunciation": 14,
                "sentence_structure": 10,
                "relevance": 11
            },
            "strengths": ["Grammatik jihatdan to'g'ri"],
            "feedback_uz": "Yaxshi javob.",
            "feedback_tr": "İyi cevap."
        })
        result = _eval_parse_and_validate(content)
        assert result["mistakes"] == []
        assert result["is_grammatically_correct"] is True

    def test_e_irrelevant_answer_low_relevance(self):
        """Test E: Savolga mos javob emas — relevance past, lekin grammar to'g'ri."""
        content = json.dumps({
            "score": 40,
            "level": "B1",
            "corrected_text": "Hava bugün çok güzel.",
            "is_grammatically_correct": True,
            "mistakes": [],
            "scores": {
                "grammar": 22,
                "vocabulary": 15,
                "pronunciation": 12,
                "sentence_structure": 8,
                "relevance": 3
            },
            "strengths": [],
            "feedback_uz": "Savolga javob bermadi.",
            "feedback_tr": "Soruya cevap vermedi."
        })
        result = _eval_parse_and_validate(content)
        # Grammar to'g'ri — mistakes bo'sh bo'lishi kerak
        assert result["mistakes"] == []
        # Relevance past
        assert result["scores"]["relevance"] == 3

    def test_system_prompt_has_error_categories(self):
        """System prompt xato kategoriyalarini o'z ichiga olishi kerak."""
        assert "grammar" in _SYSTEM_PROMPT
        assert "spelling" in _SYSTEM_PROMPT
        assert "suffix" in _SYSTEM_PROMPT
        assert "word_order" in _SYSTEM_PROMPT
        assert "word_choice" in _SYSTEM_PROMPT

    def test_eval_system_prompt_has_error_categories(self):
        """Evaluation system prompt xato kategoriyalarini o'z ichiga olishi kerak."""
        assert "grammar" in _EVAL_SYSTEM_PROMPT
        assert "spelling" in _EVAL_SYSTEM_PROMPT
        assert "suffix" in _EVAL_SYSTEM_PROMPT
        assert "word_order" in _EVAL_SYSTEM_PROMPT

    def test_eval_prompt_no_aggressive_error_hunting(self):
        """Evaluation prompt AI ni faqat haqiqiy xatolarni belgilashga undashi kerak."""
        assert "faqat haqiqiy" in _EVAL_SYSTEM_PROMPT.lower()

    def test_text_check_prompt_no_aggressive_error_hunting(self):
        """Text check prompt AI ni agressiv xato qidirishdan ogoh etishi kerak."""
        assert "majburan" in _SYSTEM_PROMPT.lower() or "qidirmasin" in _SYSTEM_PROMPT.lower()


class TestConsistencyValidation:
    """
    Deterministic consistency validation — LLM javobidan keyin
    grammatika balli, xatolar va is_grammatically_correct o'zaro mosligini tekshiradi.
    """

    def test_eval_test1_grammatical_correct_no_mistakes_low_grammar_score(self):
        """Test 1: is_grammatically_correct=True, mistakes=[], grammar=15 → grammar restored to 25."""
        content = json.dumps({
            "score": 85,
            "level": "B2",
            "corrected_text": "Ben Türkçe öğreniyorum.",
            "is_grammatically_correct": True,
            "mistakes": [],
            "scores": {
                "grammar": 15,
                "vocabulary": 20,
                "pronunciation": 15,
                "sentence_structure": 12,
                "relevance": 14
            },
            "score_reasons": [
                {"category": "grammar", "explanation_uz": "Noto'g'ri penalizatsiya (inconsistent)"}
            ],
            "strengths": ["Yaxshi"],
            "feedback_uz": "Test",
            "feedback_tr": "Test"
        })
        result = _eval_parse_and_validate(content)
        assert result["is_grammatically_correct"] is True
        assert result["mistakes"] == []
        assert result["scores"]["grammar"] == 25
        # score_reasons dan grammar sababi olib tashlangan
        grammar_reasons = [r for r in result["score_reasons"] if r.get("category") == "grammar"]
        assert len(grammar_reasons) == 0

    def test_eval_test2_grammatical_incorrect_no_mistakes(self):
        """Test 2: is_grammatically_correct=False, mistakes=[] → inconsistent, fixed to True."""
        content = json.dumps({
            "score": 70,
            "level": "B1",
            "corrected_text": "Ben Türkçe öğreniyorum.",
            "is_grammatically_correct": False,
            "mistakes": [],
            "scores": {
                "grammar": 15,
                "vocabulary": 18,
                "pronunciation": 14,
                "sentence_structure": 10,
                "relevance": 13
            },
            "strengths": [],
            "feedback_uz": "Test",
            "feedback_tr": "Test"
        })
        result = _eval_parse_and_validate(content)
        # Inconsistent — fixed to True
        assert result["is_grammatically_correct"] is True
        assert result["mistakes"] == []
        assert result["scores"]["grammar"] == 25

    def test_eval_test3_grammatical_incorrect_with_mistakes(self):
        """Test 3: is_grammatically_correct=False, mistakes=[grammar] → valid response."""
        content = json.dumps({
            "score": 60,
            "level": "B1",
            "corrected_text": "Ben Türkçe öğreniyorum.",
            "is_grammatically_correct": False,
            "mistakes": [
                {
                    "original": "okuyur",
                    "correct": "okuyorum",
                    "type": "grammar",
                    "explanation_uz": "Fe'l qo'shimchasi noto'g'ri."
                }
            ],
            "scores": {
                "grammar": 15,
                "vocabulary": 18,
                "pronunciation": 14,
                "sentence_structure": 8,
                "relevance": 5
            },
            "strengths": [],
            "feedback_uz": "Test",
            "feedback_tr": "Test"
        })
        result = _eval_parse_and_validate(content)
        assert result["is_grammatically_correct"] is False
        assert len(result["mistakes"]) == 1
        assert result["mistakes"][0]["original"] == "okuyur"
        # Grammar penalty saqlanadi (haqiqiy xato sababli)
        assert result["scores"]["grammar"] == 15

    def test_eval_test4_simdiki_zaman_correct(self):
        """Test 4: 'Ben kitap okuyorum.' → is_grammatical=True, mistakes=[], grammar=25."""
        content = json.dumps({
            "score": 90,
            "level": "C1",
            "corrected_text": "Ben kitap okuyorum.",
            "is_grammatically_correct": True,
            "mistakes": [],
            "scores": {
                "grammar": 25,
                "vocabulary": 20,
                "pronunciation": 18,
                "sentence_structure": 13,
                "relevance": 14
            },
            "strengths": ["Yaxshi grammatika"],
            "feedback_uz": "Juda yaxshi.",
            "feedback_tr": "Çok iyi."
        })
        result = _eval_parse_and_validate(content)
        assert result["is_grammatically_correct"] is True
        assert result["mistakes"] == []
        assert result["scores"]["grammar"] == 25

    def test_eval_test5_genis_zaman_correct(self):
        """Test 5: 'Ben kitap okurum.' → is_grammatical=True, mistakes=[], grammar=25."""
        content = json.dumps({
            "score": 90,
            "level": "C1",
            "corrected_text": "Ben kitap okurum.",
            "is_grammatically_correct": True,
            "mistakes": [],
            "scores": {
                "grammar": 25,
                "vocabulary": 20,
                "pronunciation": 18,
                "sentence_structure": 13,
                "relevance": 14
            },
            "strengths": ["Yaxshi grammatika"],
            "feedback_uz": "Juda yaxshi.",
            "feedback_tr": "Çok iyi."
        })
        result = _eval_parse_and_validate(content)
        assert result["is_grammatically_correct"] is True
        assert result["mistakes"] == []
        assert result["scores"]["grammar"] == 25

    def test_eval_test_real_grammar_error_valid(self):
        """Haqiqiy grammar xato: is_grammatical=False, mistakes=[grammar], grammar<25 → valid."""
        content = json.dumps({
            "score": 55,
            "level": "B1",
            "corrected_text": "Ben kitap okuyorum.",
            "is_grammatically_correct": False,
            "mistakes": [
                {
                    "original": "okuyur",
                    "correct": "okuyorum",
                    "type": "grammar",
                    "explanation_uz": "Fe'l qo'shimchasi noto'g'ri."
                }
            ],
            "scores": {
                "grammar": 15,
                "vocabulary": 18,
                "pronunciation": 14,
                "sentence_structure": 8,
                "relevance": 0
            },
            "strengths": [],
            "feedback_uz": "Test",
            "feedback_tr": "Test"
        })
        result = _eval_parse_and_validate(content)
        assert result["is_grammatically_correct"] is False
        assert len(result["mistakes"]) == 1
        assert result["scores"]["grammar"] == 15

    def test_eval_inconsistent_grammar_mistakes_but_grammatical_true(self):
        """is_grammatical=True lekin grammar mistakes bor → text_check da False ga tuzatiladi."""
        content = json.dumps({
            "corrected_text": "Ben kitap okuyorum.",
            "is_grammatically_correct": True,
            "mistakes": [
                {
                    "original": "okuyur",
                    "correct": "okuyorum",
                    "type": "grammar",
                    "explanation_uz": "Fe'l qo'shimchasi noto'g'ri."
                }
            ],
            "feedback_uz": "Test"
        })
        result = _parse_and_validate(content)
        # Inconsistent — text_check fixes to False
        assert result["is_grammatically_correct"] is False
        assert len(result["mistakes"]) == 1

    def test_text_check_inconsistent_no_mistakes_but_incorrect(self):
        """text_check: is_grammatical=False, mistakes=[] → fixed to True."""
        content = json.dumps({
            "corrected_text": "Ben kitap okuyorum.",
            "is_grammatically_correct": False,
            "mistakes": [],
            "feedback_uz": "Test"
        })
        result = _parse_and_validate(content)
        assert result["is_grammatically_correct"] is True
        assert result["mistakes"] == []

    def test_eval_score_reasons_default(self):
        """score_reasons mavjud bo'lmasa, bo'sh ro'yxat qaytarilishi kerak."""
        content = json.dumps({
            "score": 85,
            "level": "B2",
            "corrected_text": "Test",
            "is_grammatically_correct": True,
            "mistakes": [],
            "scores": {
                "grammar": 25, "vocabulary": 20, "pronunciation": 15,
                "sentence_structure": 12, "relevance": 13
            },
            "strengths": [],
            "feedback_uz": "Test",
            "feedback_tr": "Test"
        })
        result = _eval_parse_and_validate(content)
        assert "score_reasons" in result
        assert isinstance(result["score_reasons"], list)

    def test_eval_score_reasons_non_grammar_preserved(self):
        """Grammar tashqari score_reasons saqlanishi kerak."""
        content = json.dumps({
            "score": 70,
            "level": "B1",
            "corrected_text": "Test",
            "is_grammatically_correct": True,
            "mistakes": [],
            "scores": {
                "grammar": 25, "vocabulary": 15, "pronunciation": 10,
                "sentence_structure": 10, "relevance": 10
            },
            "score_reasons": [
                {"category": "vocabulary", "explanation_uz": "So'z boyligi cheklangan."},
                {"category": "pronunciation", "explanation_uz": "Talaffuz tushunarli emas."}
            ],
            "strengths": [],
            "feedback_uz": "Test",
            "feedback_tr": "Test"
        })
        result = _eval_parse_and_validate(content)
        # vocabulary sababi saqlanadi
        vocab_reasons = [r for r in result["score_reasons"] if r.get("category") == "vocabulary"]
        assert len(vocab_reasons) == 1
        # pronunciation sababi saqlanadi
        pron_reasons = [r for r in result["score_reasons"] if r.get("category") == "pronunciation"]
        assert len(pron_reasons) == 1
