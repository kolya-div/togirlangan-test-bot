import re
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.config import settings


def _paragraph_image_rids(paragraph) -> list[str]:
    """Paragraph ichidagi inline rasmlarning rId ro'yxatini qaytaradi."""
    blips = paragraph._element.findall('.//' + qn('a:blip'))
    rids = []
    for blip in blips:
        rid = blip.get(qn('r:embed'))
        if rid:
            rids.append(rid)
    return rids


async def parse_docx_questions(file_path: str | Path, upload_dir: str | None = None):
    """
    Docx fayldan savollarni parse qiladi.
    Qaytaradi: list[dict] — har bir savol dict ko'rinishida.

    Qoidalar:
    - "N.soru:" bloki ichidagi rasm va matnlar (rasm ustida/tagida) SHU
      savolga yopishadi.
    - Soru raqami yo'q bo'limlar (masalan Bölüm 2/3) ham bitta savol
      sifatida olinadi.
    - Savoldan tashqarida turgan rasm keyingi eng yaqin savolga yopishadi.
    - Bir savolda bir nechta rasm "|" bilan bog'lanadi.
    """
    if upload_dir is None:
        # Statik fayllar /audios orqali settings.upload_dir dan beriladi
        upload_dir = settings.upload_dir

    doc = Document(file_path)

    # Rasm saqlash uchun papka
    images_dir = Path(upload_dir) / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # Docx dan rasmlarni ajratib olish
    image_map = {}
    for rel in doc.part.rels.values():
        if "image" in rel.reltype:
            try:
                image_data = rel.target_part.blob
            except Exception:
                continue
            ext = rel.target_part.content_type.split('/')[-1]
            if ext == 'jpeg':
                ext = 'jpg'
            img_name = f"{rel.rId}.{ext}"
            img_path = images_dir / img_name
            with open(img_path, 'wb') as f:
                f.write(image_data)
            # /audios statik papkasiga nisbatan yo'l
            image_map[rel.rId] = f"images/{img_name}"

    def _paths(rids: list[str]) -> list[str]:
        return [image_map[r] for r in rids if r in image_map]

    # Jadvallar tanadagi o'rnini aniqlash: paragraph indeksi -> jadvallar
    # (kalit k — jadval k-indeksli paragrafdan KEYIN turadi)
    tables_after: dict[int, list[Table]] = {}
    _p_idx = 0
    for child in doc.element.body.iterchildren():
        if child.tag == qn('w:p'):
            _p_idx += 1
        elif child.tag == qn('w:tbl'):
            tables_after.setdefault(_p_idx, []).append(Table(child, doc))

    def _extract_table_points(table: Table) -> tuple[list[str], list[str]]:
        """2 ustunli jadvaldan (Lehine | Aleyhine) juftliklarni oladi."""
        pros: list[str] = []
        cons: list[str] = []
        try:
            rows = table.rows
        except Exception:
            return pros, cons
        for row in rows:
            try:
                cells = [c.text.strip() for c in row.cells]
            except Exception:
                continue
            if len(cells) < 2:
                continue
            left, right = cells[0], cells[1]
            if not left and not right:
                continue
            # Sarlavha qatori
            if 'lehine' in left.lower() and 'aleyhine' in right.lower():
                continue
            pros.append(left)
            cons.append(right)
        return pros, cons

    def _tables_in_range(start: int, end: int) -> tuple[list[str], list[str]]:
        """[start, end) orasidagi barcha jadvallarning pro/con larini yig'adi."""
        all_pros: list[str] = []
        all_cons: list[str] = []
        for pos in range(start, end):
            for tbl in tables_after.get(pos, []):
                pros, cons = _extract_table_points(tbl)
                all_pros.extend(pros)
                all_cons.extend(cons)
        return all_pros, all_cons

    paragraphs = doc.paragraphs
    questions = []
    current_section = None
    order_counter = 1
    # Bo'lim sarlavhasi ostidagi "ball: N" — shu bo'limdagi barcha
    # savollarga tegishli (savol ostidagi ball ustun turadi)
    section_points = None

    last_prep = 10
    last_answer = 30

    # Hali hech qaysi savolga tegmagan rasmlar — keyingi savolga yopishadi
    orphan_paths: list[str] = []

    def _scan_block(start_i: int, initial_text: str):
        """Soru bloki ichidagi qatorlarni skanerlaydi.
        Qaytaradi: (tugash_indeksi, matn, sub_savollar, prep, javob, rasmlar)"""
        nonlocal last_prep, last_answer

        question_text = initial_text
        sub_questions: list[str] = []
        images: list[str] = []
        prep = None
        answer = None
        points = None

        i = start_i
        while i < len(paragraphs):
            para_rids = _paragraph_image_rids(paragraphs[i])
            t = paragraphs[i].text.strip()

            if not t and not para_rids:
                i += 1
                continue

            # Yangi savol yoki yangi bo'lim — blok tugadi
            if re.search(r'^\d+\.soru:', t, re.IGNORECASE) or \
               re.search(r'Bölüm\s+\d+', t, re.IGNORECASE):
                break

            # Tayyorgarlik vaqti
            m = re.search(r'Tayyorlanish:\s*(\d+)', t, re.IGNORECASE)
            if m:
                prep = int(m.group(1))
                last_prep = prep
                i += 1
                continue

            # Javob vaqti
            m = re.search(r'Javob:\s*(\d+)', t, re.IGNORECASE)
            if m:
                answer = int(m.group(1))
                last_answer = answer
                i += 1
                continue

            # Ball (savolning maksimal balli): alohida qator
            # "Ball: 10", "Bal: 10", "ball 10", "10 ball"
            m = re.match(r'^ba[ll]+\s*:?\s*(\d+)$', t, re.IGNORECASE) or \
                re.match(r'^(\d+)\s+ball$', t, re.IGNORECASE)
            if m:
                points = max(1, min(75, int(m.group(1))))
                i += 1
                continue

            # Rasm topildi — shu blokka bog'lanadi
            if para_rids:
                images.extend(_paths(para_rids))
                i += 1
                continue

            # "Lehine Aleyhine" sarlavha qatori
            if re.match(r'^Lehine\s*Aleyhine$', t, re.IGNORECASE):
                i += 1
                continue

            # Sub-savollar (bullet)
            if t.startswith('•') or t.startswith('-'):
                sub_questions.append(t.lstrip('•- ').strip())
                i += 1
                continue

            # Blok davomi — matnga qo'shiladi (rasm tagidagi/ustidagi matn ham)
            if not question_text.endswith('?') and len(question_text) < 500:
                question_text = (question_text + " " + t).strip()

            i += 1

        return i, question_text, sub_questions, prep, answer, images, points

    def _add_question(section, order_num, text, subs, prep, answer, images,
                      pro_points=None, con_points=None, points=None):
        """Savolni ro'yxatga qo'shadi (bo'sh bloklarni tashlab)."""
        final_images = orphan_paths + images
        orphan_paths.clear()

        if not text and subs:
            # Faqat bullet lar bo'lsa — matn ko'rinishida beriladi
            text = "\n".join(subs)

        if not text and not final_images:
            return False

        # Savol o'z balliga ega bo'lmasa — bo'lim balli qo'llanadi
        if points is None:
            points = section_points

        questions.append({
            "section": section,
            "order_num": order_num,
            "text": text,
            "prep_time": prep if prep is not None else last_prep,
            "answer_time": answer if answer is not None else last_answer,
            "sub_questions": "; ".join(subs) if subs else None,
            "image_path": "|".join(final_images) if final_images else None,
            "pro_points": "\n".join(pro_points) if pro_points else None,
            "con_points": "\n".join(con_points) if con_points else None,
            "points": points,
        })
        return True

    i = 0
    while i < len(paragraphs):
        text = paragraphs[i].text.strip()

        # Paragraph ichida rasm bormi? (soru tashqarisida — keyingi savolga)
        para_rids = _paragraph_image_rids(paragraphs[i])
        if para_rids:
            orphan_paths.extend(_paths(para_rids))

        # Bo'limni aniqlash: "Bölüm 1.1", "Bölüm 1.2", "Bölüm 2", "Bölüm 3"
        section_match = re.search(r'Bölüm\s+(\d+(?:\.\d+)?)', text, re.IGNORECASE)
        if section_match:
            current_section = section_match.group(1)
            order_counter = 1
            section_points = None

            # Sarlavha ostidagi bo'sh qatorlar va "ball: N" ni yutamiz.
            # Bu ball shu bo'limdagi HAMMA savolga beriladi.
            j = i + 1
            while j < len(paragraphs):
                nt = paragraphs[j].text.strip()
                if not nt:
                    j += 1
                    continue
                m_ball = re.match(r'^ba[ll]+\s*:?\s*(\d+)$', nt, re.IGNORECASE) or \
                         re.match(r'^(\d+)\s+ball$', nt, re.IGNORECASE)
                if m_ball:
                    section_points = max(1, min(75, int(m_ball.group(1))))
                    j += 1
                    continue
                break

            next_text = paragraphs[j].text.strip() if j < len(paragraphs) else ""

            # Agar keyingi qator raqamlangan soru bo'lmasa — bo'limning o'zi
            # bitta savol hisoblanadi (masalan Bölüm 2, Bölüm 3)
            if j < len(paragraphs) and \
               not re.search(r'^\d+\.soru:', next_text, re.IGNORECASE) and \
               not re.search(r'Bölüm\s+\d+', next_text, re.IGNORECASE):
                end_i, qtext, subs, prep, answer, imgs, pts = _scan_block(j, "")
                pros, cons = _tables_in_range(j, end_i)
                if _add_question(current_section, order_counter, qtext, subs,
                                 prep, answer, imgs, pros, cons, pts):
                    order_counter += 1
                i = end_i
                continue

            i += 1
            continue

        # Savolni aniqlash: "1.soru:", "2.soru:" va h.k.
        question_match = re.search(r'^(\d+)\.soru:?', text, re.IGNORECASE)
        if question_match and current_section:
            initial_text = text.split(':', 1)[-1].strip() if ':' in text else ""

            block_start = i + 1
            end_i, qtext, subs, prep, answer, imgs, pts = _scan_block(block_start, initial_text)

            pros, cons = _tables_in_range(block_start, end_i)
            if _add_question(current_section, order_counter, qtext, subs,
                             prep, answer, imgs, pros, cons, pts):
                order_counter += 1
            i = end_i
            continue

        i += 1

    # Oxirida qolgan yetim rasmlar — alohida savol sifatida qo'shiladi
    if orphan_paths and current_section:
        _add_question(
            current_section, order_counter, "", [], None, None, [],
        )

    return questions
