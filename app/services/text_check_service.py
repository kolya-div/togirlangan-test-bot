"""
Turk tilidagi matnni imlo va grammatika jihatidan tekshirish servisi.
Avval Groq (tekin), keyin OpenAI (pullik) ishlatiladi.
"""

import json
import logging
from typing import Optional

from groq import AsyncGroq
from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Sen turk tili imlo va grammatika o'qituvchisisan. "
    "Faqat JSON formatida javob ber.\n\n"
    "## ÇOK ÖNEMLİ KURAL:\n"
    "Bir cümlede Şimdiki Zaman veya Geniş Zaman kullanılmış olması tek başına hata değildir.\n\n"
    "Şimdiki Zaman: -yor, -yorum, -yorsun, -yoruz, -yorsunuz, -yorlar, "
    "-ıyorum, -ıyorsun, -ıyor, -ıyoruz, -ıyorsunuz, -ıyorlar, "
    "-uyorum, -uyorsun, -uyor, -uyoruz, -uyorsunuz, -uyorlar, "
    "-üyorum, -üyorsun, -iyor, -iyoruz, -üyorsunuz, -iyorlar\n\n"
    "Geniş Zaman: -r, -ar, -er, -ır, -ir, -ur, -ür, "
    "-arım, -arsın, -ar, -arız, -arsınız, -arlar, "
    "-erim, -ersin, -er, -eriz, -ersiniz, -erler, "
    "-ırım, -ırsın, -ır, -ırız, -ırınız, -ırlar, "
    "-irim, -irsin, -ir, -iriz, -irsiniz, -irler, "
    "-urum, -ursun, -ur, -uruz, -ursunuz, -urlar, "
    "-ürüm, -ürsün, -ür, -ürüz, -ürsünüz, -ürler\n\n"
    "Kullanıcının cümlesi dilbilgisel olarak doğruysa, sadece beklenen cevapta farklı bir zaman "
    "kullanıldığı için cümleyi yanlış kabul etme.\n\n"
    "Örneğin:\n"
    "- 'Ben kitap okuyorum.' ve 'Ben kitap okurum.' ikisi de dilbilgisel olarak doğrudur.\n"
    "- 'Ben Türkçe öğreniyorum.' ve 'Ben Türkçe öğrenirim.' ikisi de dilbilgisel olarak doğrudur.\n\n"
    "Bu nedenle:\n"
    "1. Zaman farkını otomatik hata olarak işaretleme.\n"
    "2. Doğru kullanılan zamanı başka bir zamana dönüştürme.\n"
    "3. corrected_text içinde gereksiz zaman değişikliği yapma.\n"
    "4. mistakes listesine sadece gerçek gramer, yazım veya anlam hatalarını ekle.\n"
    "5. Kullanıcının söylediği cümleyi expected answer ile kelime kelime karşılaştırma.\n"
    "6. Önce cümlenin kendi başına gramer açısından doğru olup olmadığını değerlendir.\n\n"
    "## XATO KATEGORIYALARI:\n"
    "grammar — fe'l qo'shimchalari, shaxs qo'shimchalari, gap tuzilishi\n"
    "spelling — imlo xatolari\n"
    "suffix — kelimga noto'g'ri qo'shimcha qo'shish\n"
    "word_order — so'z tartibining noto'g'riligi\n"
    "word_choice — noto'g'ri so'z tanlash\n"
    "meaning — ma'no jihatidan noto'g'ri ishlatish\n\n"
    "AI xato topish uchun majburan xato qidirmasin. Agar gap to'g'ri bo'lsa, mistakes bo'sh bo'lsin.\n\n"
    "Faqat haqiqiy grammatik xatolarni belgila."
)


async def check_turkish_text(text: str) -> dict:
    """
    Turk tilidagi matnni tekshiradi:
    - qaysi so'zlar to'g'ri yozilgan
    - qaysi so'zlarda imlo/grammatika xatosi bor va to'g'ri variantini qaytaradi.

    Javob formati:
    {
      "corrected_text": "...",
      "mistakes": [
        {"original": "xato so'z", "correct": "to'g'ri variant",
         "type": "imlo", "explanation_uz": "..."}
      ],
      "feedback_uz": "umumiy fikr"
    }
    """

    if getattr(settings, "gemini_api_key", None):
        try:
            return await _check_with_gemini(text)
        except Exception as e:
            logger.warning(f"Gemini tekshiruvda xato: {e}. Keyingi provayderga o'tiladi.")

    if getattr(settings, "groq_api_key", None):
        try:
            return await _check_with_groq(text)
        except Exception as e:
            logger.warning(f"Groq tekshiruvda xato: {e}. OpenAI ga o'tiladi.")

    if getattr(settings, "openai_api_key", None):
        try:
            return await _check_with_openai(text)
        except Exception as e:
            logger.error(f"OpenAI tekshiruvda xato: {e}")
            raise RuntimeError("AI tekshiruv servisi vaqtinchalik ishlamayapti.")

    raise RuntimeError(
        "Hech qanday AI API kaliti sozlanmagan."
    )


async def _check_with_groq(text: str) -> dict:
    client = AsyncGroq(api_key=settings.groq_api_key)

    response = await client.chat.completions.create(
        model=getattr(settings, "groq_chat_model", "llama-3.3-70b-versatile"),
        temperature=0.1,
        messages=[
            {
                "role": "system",
                "content": _SYSTEM_PROMPT,
            },
            {"role": "user", "content": _build_prompt(text)},
        ],
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    return _parse_and_validate(content)


async def _check_with_openai(text: str) -> dict:
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    response = await client.chat.completions.create(
        model=getattr(settings, "openai_model", "gpt-4o-mini"),
        temperature=0.1,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": _SYSTEM_PROMPT,
            },
            {"role": "user", "content": _build_prompt(text)},
        ],
    )

    content = response.choices[0].message.content
    return _parse_and_validate(content)


async def _check_with_gemini(text: str) -> dict:
    """Gemini orqali imlo/grammatika tekshiruvi — bepul."""
    import asyncio
    import google.genai as genai_mod

    client = genai_mod.Client(api_key=settings.gemini_api_key)

    prompt = _build_prompt(text)
    model = getattr(settings, "gemini_stt_model", "gemini-3.6-flash")

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=model,
        contents=[{"parts": [{"text": _SYSTEM_PROMPT + "\n\n" + prompt}]}],
    )

    content = response.text if response.text else ""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        content = "\n".join(lines)

    return _parse_and_validate(content)


def _build_prompt(text: str) -> str:
    return f"""
Aşağıdaki metin, bir kişinin Türkçe konuşması sesli mesajdan yazıya çevrilmiş hali.
Metni Türkçe imla (yazım), ekler ve gramer açısından kontrol et.

## Metin:
{text}

## Talab:
1. Faqat haqiqiy xatolarni belgila (imlo, qo'shimcha, grammatika).
2. "original" maydonida matnda aynan qanday yozilgan bo'lsa, shunday ko'rinishda ber.
3. Xatolar yo'q bo'lsa, mistakes bo'sh ro'yxat bo'lsin. AI xato topish uchun majburan xato qidirmasin.
4. explanation_uz — o'zbek tilida qisqa izoh.
5. corrected_text — faqat haqiqiy xatolar tuzatilgan to'liq matn. Foydalanuvchining ishlatgan zamonini boshqa zamon bilan almashtirma!
6. corrected_text ichida zamon farqi tufayli o'zgartirish qilma.

Faqat quyidagi JSON formatda javob ber:

```json
{{
  "corrected_text": "to'g'irlangan to'liq matn (turk tilida)",
  "is_grammatically_correct": true,
  "mistakes": [
    {{
      "original": "xato so'z yoki ibora",
      "correct": "to'g'ri variant",
      "type": "grammar | spelling | suffix | word_order | word_choice | meaning",
      "explanation_uz": "nima uchun xato (o'zbek tilida)"
    }}
  ],
  "feedback_uz": "o'quvchining nutqi haqida umumiy fikr, 2-3 gap, o'zbek tilida"
}}
""".strip()


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

    if not isinstance(data.get("mistakes"), list):
        data["mistakes"] = []
        logger.warning("AI javobida 'mistakes' ro'yxati yo'q, bo'sh qo'yildi")

    data.setdefault("corrected_text", "")
    data.setdefault("feedback_uz", "")
    data.setdefault("is_grammatically_correct", len(data["mistakes"]) == 0)

    # Har bir xato maydonlarini normallashtirish
    normalized = []
    for mistake in data["mistakes"]:
        if not isinstance(mistake, dict):
            continue
        original = str(mistake.get("original") or "").strip()
        correct = str(mistake.get("correct") or "").strip()
        if not original:
            continue
        normalized.append(
            {
                "original": original,
                "correct": correct,
                "type": str(mistake.get("type") or "grammar").strip(),
                "explanation_uz": str(mistake.get("explanation_uz") or "").strip(),
            }
        )
    data["mistakes"] = normalized
    data["is_grammatically_correct"] = len(data["mistakes"]) == 0

    # Inconsistency validation
    data = _validate_consistency(data)

    return data


def _validate_consistency(data: dict) -> dict:
    """
    is_grammatically_correct va mistakes o'zaro mosligini tekshiradi.
    Inconsistent holatlarni xavfsiz normalize qiladi.
    """
    mistakes = data.get("mistakes", [])
    is_gram = data.get("is_grammatically_correct")
    grammar_mistakes = [m for m in mistakes if m.get("type") == "grammar"]

    # Holat B: grammatik xato bor deb aytilgan, lekin mistakes bo'sh — inconsistent
    if is_gram is False and len(grammar_mistakes) == 0:
        logger.warning(
            "Inconsistency: is_grammatically_correct=False but mistakes=[]. "
            "Fixing: setting is_grammatically_correct=True."
        )
        data["is_grammatically_correct"] = True

    # Holat D: grammatik xato yo'q, lekin grammar tipsli mistake bor — inconsistent
    elif is_gram is True and len(grammar_mistakes) > 0:
        logger.warning(
            "Inconsistency: is_grammatically_correct=True but grammar mistakes exist. "
            "Fixing: setting is_grammatically_correct=False."
        )
        data["is_grammatically_correct"] = False

    return data
