"""
AI Docx Service — docx faylni OpenAI vision modeli orqali tahlil qiladi.

Fayldan matn qatorlari va rasmlar ajratib olinib, GPT-4o-mini ga
yuboriladi. Model savollarni bo'limlarga ajratib, har bir savolga
o'z rasmini moslab, qat'iy JSON formatida qaytaradi.
"""

import base64
import json
import logging
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Sen turk tili speaking imtihoni hujjatlarini tuzilishli JSON ga "
    "aylantiruvchi aniq assistentsan. Faqat valid JSON qaytarasan, "
    "hech qanday izohsiz."
)

USER_PROMPT = """Aşağıda bir Türkçe konuşma sınavı DOCX dosyasından satır satır çıkarılmış içerik var. Resimler [IMAGE:<id>] şeklinde işaretlenmiştir ve resimlerin kendileri de mesaja eklenmiştir.

Görevin: içeriği sorulara ayırmak.

Kurallar:
1. Her soru hangi "Bölüm"e aitse o bölümde yazılmalıdır (örn: "1.1", "2").
2. Soru metinlerini AYNEN koru, çevirme veya değiştirme.
3. Tayyorlanish ve Javob değerleri saniye cinsinden preparation_seconds ve answer_seconds alanlarına yazılır (yoksa 10 / 30 kullan). "Ball: N" satırı varsa N değeri "points" alanına yazılır. DİKKAT: "Ball" bazen bölüm başlığının (örn. "Bölüm 1.1") hemen altında yazılır — bu durumda o bölümdeki HER soruya aynı points değerini ver. Sorunun kendisinde ayrı "Ball" yazılmışsa onu kullan.
4. Resimler ([IMAGE:id]) ait oldukları sorunun "images" dizisine id olarak eklenir. Bir soruda birden fazla resim olabilir. Resim sırası önemli değildir, sadece doğru soruya bağlanmalıdır.
5. "- " veya "•" ile başlayan alt maddeler sub_questions dizisine girer.
6. Numaralı sorusu olmayan bölümlerdeki görev metni de TEK soru olarak eklenir (örnek: Bölüm 2'deki madde listesi veya Bölüm 3'teki tartışma konusu).
7. Lehine/Aleyhine tablosu varsa sol sütun "pro_points", sağ sütun "con_points" dizilerine satır satır yazılır (başlık satırı hariç).
8. Başlık/giriş gibi soru olmayan satırları atla ("Yangi Savollar To'plami" gibi).

Sadece şu JSON şemasını döndür:
{"questions": [{"section": "1.1", "order": 1, "text": "...", "preparation_seconds": 10, "answer_seconds": 30, "images": ["rId9"], "sub_questions": ["...", "..."], "pro_points": ["..."], "con_points": ["..."], "points": 10}]}

=== HUJJAT SATIRLARI ===
{document}
"""


def _paragraph_image_rids(paragraph) -> list[str]:
    blips = paragraph._element.findall('.//' + qn('a:blip'))
    rids = []
    for blip in blips:
        rid = blip.get(qn('r:embed'))
        if rid:
            rids.append(rid)
    return rids


def _extract_content(doc: Document, images_dir: Path) -> tuple[list[dict], list[dict]]:
    """
    Document dan matn qatorlari va rasmlarni ajratib oladi.
    Qaytaradi: (lines, images)
      lines:  [{"type": "text", "value": "..."} | {"type": "image", "rid": "rId9"}]
      images: [{"rid": "rId9", "rel_path": "images/rId9.png", "data_url": "data:image/png;base64,..."}]
    """
    images_dir.mkdir(parents=True, exist_ok=True)

    saved: dict[str, dict] = {}
    for rel in doc.part.rels.values():
        if "image" not in rel.reltype:
            continue
        try:
            image_data = rel.target_part.blob
        except Exception:
            continue
        ext = rel.target_part.content_type.split('/')[-1]
        if ext == 'jpeg':
            ext = 'jpg'
        img_name = f"{rel.rId}.{ext}"
        img_path = images_dir / img_name
        img_path.write_bytes(image_data)

        b64 = base64.b64encode(image_data).decode()
        saved[rel.rId] = {
            "rid": rel.rId,
            "rel_path": f"images/{img_name}",
            "data_url": f"data:image/{'jpeg' if ext == 'jpg' else ext};base64,{b64}",
        }

    lines: list[dict] = []
    for paragraph in doc.paragraphs:
        for rid in _paragraph_image_rids(paragraph):
            if rid in saved:
                lines.append({"type": "image", "rid": rid})
        text = paragraph.text.strip()
        if text:
            lines.append({"type": "text", "value": text})

    return lines, list(saved.values())


async def parse_docx_with_ai(file_path: str | Path, upload_dir: str | None = None) -> list[dict]:
    """
    Docx ni AI orqali parse qiladi. Natija docx_parser.parse_docx_questions
    bilan bir xil dict shaklda qaytadi (moslik uchun kalit nomlari bir xil).
    Avval Groq vision, ishlamasa OpenAI vision ishlatiladi.
    """
    if upload_dir is None:
        upload_dir = settings.upload_dir

    doc = Document(file_path)
    lines, images = _extract_content(doc, Path(upload_dir) / "images")

    if not lines and not images:
        return []

    # Hujjat matnini yig'amiz
    doc_lines = []
    for item in lines:
        if item["type"] == "text":
            doc_lines.append(item["value"])
        else:
            doc_lines.append(f"[IMAGE:{item['rid']}]")
    document_text = "\n".join(doc_lines)

    # Xabar kontenti: prompt + rasmlar (har biri oldida id yorlig'i)
    content: list[dict] = [
        {"type": "text", "text": USER_PROMPT.replace("{document}", document_text)}
    ]
    for img in images:
        content.append({"type": "text", "text": f"Rasm id={img['rid']}:"})
        content.append({"type": "image_url", "image_url": {"url": img["data_url"]}})

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]

    rid_map = {img["rid"]: img["rel_path"] for img in images}

    errors: list[str] = []

    # 0) Gemini (bepul, birinchi)
    if getattr(settings, "gemini_api_key", None):
        try:
            raw = await _request_gemini(document_text, images)
            return _build_questions(raw, rid_map)
        except Exception as e:
            logger.warning(f"Gemini docx tahlilida xato: {e}")
            errors.append(f"gemini: {e}")

    # 1) Groq vision (tekin/tez)
    if getattr(settings, "groq_api_key", None):
        try:
            raw = await _request_groq(messages)
            return _build_questions(raw, rid_map)
        except Exception as e:
            logger.warning(f"Groq docx tahlilida xato: {e}")
            errors.append(f"groq: {e}")

    # 2) OpenAI vision (zaxira)
    if getattr(settings, "openai_api_key", None):
        try:
            raw = await _request_openai(messages)
            return _build_questions(raw, rid_map)
        except Exception as e:
            logger.error(f"OpenAI docx tahlilida xato: {e}")
            errors.append(f"openai: {e}")

    raise RuntimeError("AI xizmati ishlamadi: " + "; ".join(errors))


async def _request_groq(messages: list[dict]) -> str:
    from groq import AsyncGroq

    client = AsyncGroq(api_key=settings.groq_api_key)
    try:
        response = await client.chat.completions.create(
            model=getattr(settings, "groq_vision_model", "qwen/qwen3.6-27b"),
            temperature=0,
            messages=messages,
            response_format={"type": "json_object"},
        )
    except Exception:
        response = await client.chat.completions.create(
            model=getattr(settings, "groq_vision_model", "qwen/qwen3.6-27b"),
            temperature=0,
            messages=messages,
        )
    return response.choices[0].message.content or "{}"


async def _request_openai(messages: list[dict]) -> str:
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model=getattr(settings, "openai_model", "gpt-4o-mini"),
        temperature=0,
        messages=messages,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content or "{}"


async def _request_gemini(document_text: str, images: list[dict]) -> str:
    import asyncio
    import google.genai as genai_mod

    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY sozlanmagan")

    client = genai_mod.Client(api_key=settings.gemini_api_key)

    parts: list[dict] = [
        {"text": SYSTEM_PROMPT + "\n\n" + USER_PROMPT.replace("{document}", document_text)}
    ]

    for img in images:
        parts.append({"text": f"[IMAGE:{img['rid']}]"})
        parts.append({
            "inline_data": {
                "mime_type": "image/png",
                "data": img["data_url"].split(",", 1)[1]
                if "," in img["data_url"]
                else img["data_url"],
            }
        })

    model = getattr(settings, "gemini_stt_model", "gemini-3.6-flash")

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=model,
        contents=[{"parts": parts}],
    )

    return response.text if response.text else "{}"


def _build_questions(raw: str, rid_map: dict[str, str]) -> list[dict]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"AI JSON qaytarmadi: {e}")

    questions = []
    for idx, q in enumerate(data.get("questions", []), start=1):
        text = str(q.get("text") or "").strip()
        section = str(q.get("section") or "").strip() or "1"
        try:
            order = int(q.get("order") or idx)
        except (TypeError, ValueError):
            order = idx
        try:
            prep = max(1, min(600, int(q.get("preparation_seconds") or 10)))
        except (TypeError, ValueError):
            prep = 10
        try:
            answer = max(1, min(600, int(q.get("answer_seconds") or 30)))
        except (TypeError, ValueError):
            answer = 30

        points = None
        try:
            if q.get("points") is not None:
                points = max(1, min(75, int(q.get("points"))))
        except (TypeError, ValueError):
            points = None

        img_paths = []
        for rid in q.get("images") or []:
            rel_path = rid_map.get(str(rid).strip())
            if rel_path and rel_path not in img_paths:
                img_paths.append(rel_path)

        subs = [str(s).strip() for s in (q.get("sub_questions") or []) if str(s).strip()]
        pros = [str(s).strip() for s in (q.get("pro_points") or []) if str(s).strip()]
        cons = [str(s).strip() for s in (q.get("con_points") or []) if str(s).strip()]

        if not text and not img_paths:
            continue

        questions.append({
            "section": section,
            "order_num": order,
            "text": text,
            "prep_time": prep,
            "answer_time": answer,
            "sub_questions": subs if subs else None,
            "image_path": "|".join(img_paths) if img_paths else None,
            "pro_points": "\n".join(pros) if pros else None,
            "con_points": "\n".join(cons) if cons else None,
            "points": points,
        })

    # order_num bo'yicha qayta raqamlash (bo'lim ichida ketma-ket bo'lishi uchun)
    counters: dict[str, int] = {}
    for q in questions:
        sec = q["section"]
        counters[sec] = counters.get(sec, 0) + 1
        q["order_num"] = counters[sec]

    logger.info(f"AI docx parse: {len(questions)} ta savol ajratildi")
    return questions
