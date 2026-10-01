import asyncio
import json
import logging
import random
import threading
from pathlib import Path
from typing import Optional

from groq import AsyncGroq
from openai import AsyncOpenAI

from app.config import settings
from app.services.ai_provider_base import (
    AIProvider,
    MultiKeyRotator,
    ProviderChain,
    create_gemini_rotator
)
from app.services.prompts import (
    EVALUATION_SYSTEM_PROMPT,
    EVALUATION_USER_PROMPT_TEMPLATE
)
from app.services.rate_limiter import wait_gemini, wait_groq

logger = logging.getLogger(__name__)

EVAL_MAX_RETRIES = 3
EVAL_RATE_LIMIT_DELAY = 10.0
EVAL_TIMEOUT = 120.0

# Gemini key rotator - shared instance with thread safety
_gemini_rotator: Optional[MultiKeyRotator] = None
_gemini_rotator_lock = threading.Lock()


def _get_gemini_rotator() -> Optional[MultiKeyRotator]:
    """Get or create Gemini key rotator (thread-safe)."""
    global _gemini_rotator
    if _gemini_rotator is None:
        with _gemini_rotator_lock:
            if _gemini_rotator is None:
                _gemini_rotator = create_gemini_rotator()
    return _gemini_rotator

_SYSTEM_PROMPT = (
    "Sen aniq va xolis turk tili imtihon baholovchisisan.\n\n"
    "## ÖNEMLİ DEĞERLENDİRME KURALI:\n"
    "Öğrencinin cevabını yalnızca beklenen cevapla birebir karşılaştırma.\n"
    "Öğrencinin kullandığı cümle kendi başına dilbilgisel olarak doğruysa, farklı bir doğru "
    "zaman kullanımı nedeniyle puan düşürme.\n\n"
    "Özellikle:\n"
    "Şimdiki Zaman ve Geniş Zaman arasında yapılan doğru seçim farklılıkları gramer hatası değildir.\n\n"
    "Örnek:\n"
    "Beklenen: 'Ben Türkçe öğreniyorum.'\n"
    "Öğrenci: 'Ben Türkçe öğrenirim.'\n"
    "İki cümle anlam ve kullanım açısından farklı olabilir. Ancak öğrencinin cümlesi gramer "
    "açından doğruysa, sadece zaman farkı nedeniyle grammar_score düşürülmemelidir.\n\n"
    "Gramer doğruluğu ve soruya uygunluk ayrı değerlendirilmelidir.\n\n"
    "## ZAMON QOIDASI (ENG MUHIM — QAT'IY AMAL QIL):\n"
    "Turk tilidagi quyidagi ikki zamon bir xil to'g'ri hisoblanadi va farq qilinmaydi.\n"
    "Bu qoidani HICH QACHON buzma!\n\n"
    "Şimdiki Zaman (hozirgi zamon) — fe'l + -yor:\n"
    "- -yorum, -yorsun, -yor, -yoruz, -yorsunuz, -yorlar\n"
    "- -ıyorum, -ıyorsun, -ıyor, -ıyoruz, -ıyorsunuz, -ıyorlar\n"
    "- -uyorum, -uyorsun, -uyor, -uyoruz, -uyorsunuz, -uyorlar\n"
    "- -üyorum, -üyorsun, -iyor, -iyoruz, -üyorsunuz, -iyorlar\n"
    "Misol: okuyorum, gidiyorum, yapıyorum, bakıyorum, öğreniyorum, çalışıyorum\n\n"
    "Geniş zaman (keng zamon) — fe'l + -r/-ar/-er/-ır/-ir/-ur/-ür:\n"
    "- -arım, -arsın, -ar, -arız, -arsınız, -arlar\n"
    "- -erim, -ersin, -er, -eriz, -ersiniz, -erler\n"
    "- -ırım, -ırsın, -ır, -ırız, -ırınız, -ırlar\n"
    "- -irim, -irsin, -ir, -iriz, -irim, -irler\n"
    "- -urum, -ursun, -ur, -uruz, -ursunuz, -urlar\n"
    "- -ürüm, -ürsün, -ür, -ürüz, -ürsünüz, -ürler\n"
    "Misol: okurum, giderim, yaparım, bakarım, öğrenirim, çalışırım\n\n"
    "QOIDA: O'quvchi qaysi zamonda gapirsa ham, bu zamon NOTO'G'RI emas. "
    "Ikkalasi ham grammatik jihatdan to'g'ri. Zamon tanlashni XATO DEB BAHOLAMA!\n\n"
    "MISOLLAR (qat'iy amal qil):\n"
    "- 'Ben Türkçe öğreniyorum' vs 'Ben Türkçe öğrenirim' → ikkalasi ham TO'G'RI\n"
    "- 'Her gün kitap okuyorum' vs 'Her gün kitap okurum' → ikkalasi ham TO'G'RI\n"
    "- 'Ben çalışıyorum' vs 'Ben çalışırım' → ikkalasi ham TO'G'RI\n\n"
    "## Baholash mezonlari (alohida baholanadi):\n"
    "1. Grammatika (0-25): Fe'l shakllari, so'z tartibi, qo'shimchalar — FAQAT haqiqiy grammatik xatolar\n"
    "2. So'z boyligi (0-25): Ishlatilgan so'zlar xilma-xilligi\n"
    "3. Talaffuz (0-20): Transkript asosida tushunarliligi\n"
    "4. Gap tuzilishi (0-15): Murakkab gaplar qurish\n"
    "5. Moslik (0-15): Savolga to'g'ri javob — GRAMMAR VA RELEVANCE ALOHIDA!\n\n"
    "## MUHIM: Grammar va Savolga Moslik ALOHIDA!\n"
    "- Agar gap grammatik jihatdan to'g'ri bo'lsa, lekin savolga javob bo'lmasa — "
    "grammar xato emas, relevance past bo'ladi, lekin mistakes ga qo'shilmaydi.\n"
    "- Faqat haqiqiy grammatik, imlo yoki so'z tanlash xatolarini mistakes ga qo'sh.\n"
    "- Şimdiki Zaman o'rniga Geniş Zaman yoki aksincha ishlatilgani GRAMMATIK XATO EMAS.\n\n"
    "## XATO KATEGORIYALARI:\n"
    "grammar — fe'l qo'shimchalari, shaxs qo'shimchalari, gap tuzilishi\n"
    "spelling — imlo xatolari\n"
    "suffix — kelimga noto'g'ri qo'shimcha qo'shish\n"
    "word_order — so'z tartibining noto'g'riligi\n"
    "word_choice — noto'g'ri so'z tanlash\n"
    "meaning — ma'no jihatdan noto'g'ri ishlatish\n\n"
    "## SCOREReasons VA INCONSISTENCY QOIDASI:\n"
    "Har bir kategoriyada ball maksimaldan past bo'lsa, sababini score_reasons ga yoz.\n"
    "MISOL: vocabulary 20 emas 15 bo'lsa → score_reasons ga vocabulary sababini qo'sh.\n\n"
    "QAT'IY QOIDA — is_grammatically_correct va grammar_score va mistakes MOS BO'lishi kerak:\n"
    "- Agar is_grammatically_correct=true va mistakes=[] bo'lsa, grammar_score MUST be 25 (maksimal).\n"
    "- Agar grammar_score < 25 bo'lsa, DIQQAT bilan tekshir: faqat haqiqiy grammar xato tufayli kamaysin.\n"
    "- Faqat boshqa kategoriyalar (vocabulary, pronunciation, sentence_structure, relevance) tufayli "
    "umumiy ball kamayishi mumkin — bu normal holat.\n\n"
    "Faqat JSON formatida javob ber."
)


async def evaluate_answer(
    question: str,
    transcript: str,
) -> dict:
    """
    O'quvchining turk tilidagi javobini AI orqali baholaydi.
    Gemini (bepul) → Groq (tekin) → OpenAI (zaxira).
    Har bir provayder uchun rate limit bilan retry.
    """

    # Gemini (bepul, birinchi). gemini_keys_list — GEMINI_API_KEY yoki
    # GEMINI_API_KEYS (faqat ikkinchisi berilsa ham Gemini ishlatiladi).
    if settings.gemini_keys_list:
        try:
            return await _evaluate_with_retry("gemini", _evaluate_with_gemini, question, transcript)
        except Exception as e:
            logger.warning(f"Gemini baholashda xato: {e}. Keyingi provayderga o'tiladi.")

    # Groq bilan urinib ko'ramiz (tekin tier)
    if getattr(settings, "groq_api_key", None):
        try:
            return await _evaluate_with_retry("groq", _evaluate_with_groq, question, transcript)
        except Exception as e:
            logger.warning(f"Groq baholashda xato: {e}. OpenAI ga o'tiladi.")
    
    # OpenAI ga murojaat
    if getattr(settings, "openai_api_key", None):
        try:
            return await _evaluate_with_retry("openai", _evaluate_with_openai, question, transcript)
        except Exception as e:
            logger.error(f"OpenAI baholashda xato: {e}")
            raise RuntimeError("AI baholash servisi vaqtinchalik ishlamayapti.")
    
    raise RuntimeError(
        "Hech qanday AI API kaliti sozlanmagan."
    )


async def _evaluate_with_retry(name: str, fn, question: str, transcript: str) -> dict:
    """Rate limit va timeout uchun retry logikasi."""
    last_error = None
    for attempt in range(EVAL_MAX_RETRIES):
        try:
            return await fn(question, transcript)
        except Exception as e:
            last_error = e
            err_str = str(e).lower()

            # Rate limit — uzoqroq kutish
            if any(kw in err_str for kw in ["429", "rate limit", "quota", "too many requests"]):
                delay = EVAL_RATE_LIMIT_DELAY * (attempt + 1)
                logger.warning(
                    f"Rate limit ({name}), {delay}s kutilda, "
                    f"urinish {attempt + 1}/{EVAL_MAX_RETRIES}"
                )
                await asyncio.sleep(delay)
                continue

            # Qolgan xatolar — qisqa kutish
            if attempt < EVAL_MAX_RETRIES - 1:
                delay = 2.0 * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(f"Evaluation xatosi ({name}), urinish {attempt + 1}/{EVAL_MAX_RETRIES}: {e}")
                await asyncio.sleep(delay)

    raise last_error


async def _evaluate_with_groq(question: str, transcript: str) -> dict:
    """Groq orqali baholash."""
    await wait_groq()  # Rate limit — 2 soniya kutish
    client = AsyncGroq(api_key=settings.groq_api_key)
    
    prompt = EVALUATION_USER_PROMPT_TEMPLATE.format(
        question=question,
        transcript=transcript
    )
    
    response = await client.chat.completions.create(
        model=getattr(settings, "groq_chat_model", "llama-3.3-70b-versatile"),
        temperature=0.1,
        messages=[
            {
                "role": "system",
                "content": EVALUATION_SYSTEM_PROMPT,
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
    )
    
    content = response.choices[0].message.content
    return _parse_and_validate(content)


async def _evaluate_with_openai(question: str, transcript: str) -> dict:
    """OpenAI (GPT-4o-mini) orqali baholash — zaxira variant."""
    import asyncio as _aio
    await _aio.sleep(1)  # OpenAI uchun ham 1 soniya kutish
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    
    prompt = EVALUATION_USER_PROMPT_TEMPLATE.format(
        question=question,
        transcript=transcript
    )
    
    response = await client.chat.completions.create(
        model=getattr(settings, "openai_model", "gpt-4o-mini"),
        temperature=0.1,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": EVALUATION_SYSTEM_PROMPT,
            },
            {"role": "user", "content": prompt},
        ],
    )
    
    content = response.choices[0].message.content
    return _parse_and_validate(content)


async def _evaluate_with_gemini(question: str, transcript: str) -> dict:
    """Gemini orqali baholash — bepul. Bir nechta kalit bo'lsa navbat bilan."""
    import asyncio
    import google.genai as genai_mod

    await wait_gemini()  # Rate limit — 4 soniya kutish

    rotator = _get_gemini_rotator()
    api_key = await rotator.get_next_key() if rotator else None
    if not api_key:
        raise RuntimeError("Gemini API kaliti sozlanmagan.")

    client = genai_mod.Client(api_key=api_key)

    prompt = EVALUATION_USER_PROMPT_TEMPLATE.format(
        question=question,
        transcript=transcript
    )
    model = getattr(settings, "gemini_stt_model", "gemini-3.6-flash")

    # Timeout: osilib qolgan so'rov worker'ni cheksiz band qilmasin
    # (transkripsiyada ham xuddi shunday — TRANSCRIPTION_TIMEOUT).
    response = await asyncio.wait_for(
        asyncio.to_thread(
            client.models.generate_content,
            model=model,
            contents=[{"parts": [{"text": EVALUATION_SYSTEM_PROMPT + "\n\n" + prompt}]}],
        ),
        timeout=EVAL_TIMEOUT,
    )

    content = response.text if response.text else ""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        content = "\n".join(lines)

    return _parse_and_validate(content)


def _parse_and_validate(content: Optional[str]) -> dict:
    """JSON javobni parse qiladi va tekshiradi."""
    if not content:
        raise ValueError("AI bo'sh javob qaytardi")

    # Markdown code block dan tozalash
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        content = "\n".join(lines)

    # JSON dan oldingi ortiqcha matnni tozalash
    first_brace = content.find("{")
    first_bracket = content.find("[")
    if first_brace == -1 and first_bracket == -1:
        raise ValueError("AI noto'g'ri formatda javob qaytardi")
    elif first_brace == -1:
        content = content[first_bracket:]
    elif first_bracket == -1:
        content = content[first_brace:]
    else:
        content = content[min(first_brace, first_bracket):]

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse xatosi: {e}. Content: {content[:500]}")
        raise ValueError("AI noto'g'ri formatda javob qaytardi")

    # Majburiy maydonlarni tekshiramiz
    required_fields = ["score", "level", "mistakes", "strengths", "feedback_uz", "feedback_tr"]
    for field in required_fields:
        if field not in data:
            data[field] = [] if field in ("mistakes", "strengths") else "Noma'lum"
            logger.warning(f"AI javobida '{field}' maydoni yo'q, default qiymat qo'yildi")

    # Score ni butun songa aylantirish
    try:
        data["score"] = int(data["score"])
    except (ValueError, TypeError):
        data["score"] = 0

    # Level ni tekshirish — faqat B1/B2/C1
    valid_levels = ["B1", "B2", "C1", None]
    if data.get("level") not in valid_levels:
        data["level"] = None

    # Yangi maydonlar — default qiymatlar
    data["corrected_text"] = data.get("corrected_text") or ""

    if not data.get("mistakes"):
        data["mistakes"] = []
    data.setdefault("is_grammatically_correct", len(data["mistakes"]) == 0)

    data.setdefault("scores", {
        "grammar": 0,
        "vocabulary": 0,
        "pronunciation": 0,
        "sentence_structure": 0,
        "relevance": 0,
    })

    # Scores normallashtirish
    scores = data["scores"]
    if isinstance(scores, dict):
        for key in ["grammar", "vocabulary", "pronunciation", "sentence_structure", "relevance"]:
            try:
                scores[key] = max(0, int(scores.get(key, 0)))
            except (ValueError, TypeError):
                scores[key] = 0
    else:
        data["scores"] = {
            "grammar": 0, "vocabulary": 0, "pronunciation": 0,
            "sentence_structure": 0, "relevance": 0,
        }

    # Mistakes normallashtirish
    normalized = []
    for m in data.get("mistakes", []):
        if not isinstance(m, dict):
            continue
        original = str(m.get("original") or "").strip()
        correct = str(m.get("correct") or "").strip()
        if not original:
            continue
        normalized.append({
            "original": original,
            "correct": correct,
            "type": str(m.get("type") or "grammar").strip(),
            "explanation_uz": str(m.get("explanation_uz") or m.get("explanation") or "").strip(),
        })
    data["mistakes"] = normalized

    # score_reasons default
    if not isinstance(data.get("score_reasons"), list):
        data["score_reasons"] = []

    # Inconsistency validation — LLM deterministik emas
    data = _validate_consistency(data)

    return data


_MAX_GRAMMAR = 25


def _validate_consistency(data: dict) -> dict:
    """
    LLM javobidagi grammatika balli va xatolar o'zaro mosligini tekshiradi.
    Inconsistent holatlarni xavfsiz tarzda normalize qiladi.
    """
    mistakes = data.get("mistakes", [])
    is_gram = data.get("is_grammatically_correct")
    scores = data.get("scores", {})
    grammar_score = scores.get("grammar", _MAX_GRAMMAR)
    score_reasons = data.get("score_reasons", [])

    grammar_mistakes = [m for m in mistakes if m.get("type") == "grammar"]

    # Holat A: grammatik xato yo'q, lekin grammar_score past — noto'g'ri penalizatsiya
    if is_gram is True and len(grammar_mistakes) == 0:
        if grammar_score < _MAX_GRAMMAR:
            logger.warning(
                f"Inconsistency: is_grammatically_correct=True, mistakes=[], "
                f"but grammar_score={grammar_score}. Restoring to {_MAX_GRAMMAR}."
            )
            scores["grammar"] = _MAX_GRAMMAR
            # score_reasons dan grammar ga tegishli sabablarni olib tashlash
            score_reasons = [r for r in score_reasons if r.get("category") != "grammar"]

    # Holat B: grammatik xato bor deb aytilgan, lekin mistakes bo'sh — inconsistent
    elif is_gram is False and len(grammar_mistakes) == 0:
        logger.warning(
            "Inconsistency: is_grammatically_correct=False but mistakes=[]. "
            "Fixing: setting is_grammatically_correct=True, restoring grammar_score."
        )
        data["is_grammatically_correct"] = True
        if grammar_score < _MAX_GRAMMAR:
            scores["grammar"] = _MAX_GRAMMAR
            score_reasons = [r for r in score_reasons if r.get("category") != "grammar"]

    # Holat C: grammatik xato bor va mistakes bor — valid, qoldiramiz

    data["scores"] = scores
    data["score_reasons"] = score_reasons
    return data
