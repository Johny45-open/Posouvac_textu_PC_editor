"""
Export setlistu do Wordu (.docx) – tabulka + detailní rozpis + tisková úprava.
Používá python-docx, izolováno od playlist_backend pro volitelnou závislost.
"""
from datetime import datetime
from pathlib import Path

try:
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor, Emu
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
    from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
    from docx.enum.section import WD_SECTION
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn, nsdecls
    HAS_DOCX = True
except Exception:
    HAS_DOCX = False
    Document = None  # type: ignore


def _check_docx():
    if not HAS_DOCX:
        return False, "Chybí knihovna python-docx. Nainstalujte: pip install python-docx"
    return True, ""


def _set_cell_shading(cell, color_hex: str):
    """Nastaví pozadí buňky (hex bez #)."""
    try:
        tblCell = cell._tc
        tblCellProperties = tblCell.get_or_add_tcPr()
        shd = OxmlElement('w:shd')
        shd.set(qn('w:val'), 'clear')
        shd.set(qn('w:color'), 'auto')
        shd.set(qn('w:fill'), color_hex)
        tblCellProperties.append(shd)
    except Exception:
        pass


def _set_cell_margins(cell, top=40, bottom=40, left=80, right=80):
    try:
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        tcMar = OxmlElement('w:tcMar')
        for m, v in [("top", top), ("bottom", bottom), ("left", left), ("right", right)]:
            el = OxmlElement(f'w:{m}')
            el.set(qn('w:w'), str(v))
            el.set(qn('w:type'), 'dxa')
            tcMar.append(el)
        tcPr.append(tcMar)
    except Exception:
        pass


def _set_repeat_header(row):
    """Hlavička tabulky se opakuje na každé straně (tblHeader)."""
    try:
        tr = row._tr
        trPr = tr.get_or_add_trPr()
        tblHeader = OxmlElement('w:tblHeader')
        tblHeader.set(qn('w:val'), 'true')
        trPr.append(tblHeader)
    except Exception:
        pass


def _add_page_number(paragraph):
    """Vloží field PAGE do paragraph (číslování stran)."""
    try:
        p = paragraph._p
        # begin
        fldChar1 = OxmlElement('w:fldChar')
        fldChar1.set(qn('w:fldCharType'), 'begin')
        instr = OxmlElement('w:instrText')
        instr.set(qn('xml:space'), 'preserve')
        instr.text = ' PAGE '
        fldChar2 = OxmlElement('w:fldChar')
        fldChar2.set(qn('w:fldCharType'), 'end')
        r1 = OxmlElement('w:r')
        r1.append(fldChar1)
        r2 = OxmlElement('w:r')
        r2.append(instr)
        r3 = OxmlElement('w:r')
        r3.append(fldChar2)
        p.append(r1)
        p.append(r2)
        p.append(r3)
    except Exception:
        pass


def _setup_section(doc, name: str):
    """A4, okraje 2cm, záhlaví + zápatí s číslováním."""
    try:
        section = doc.sections[0]
        section.page_height = Cm(29.7)
        section.page_width = Cm(21.0)
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.0)
        section.right_margin = Cm(2.0)
        section.header_distance = Cm(1.0)
        section.footer_distance = Cm(1.0)
        # záhlaví
        header = section.header
        hp = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
        hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        run = hp.add_run(name)
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
        run.font.italic = True
        # zápatí – číslování
        footer = section.footer
        fp = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run2 = fp.add_run("Strana ")
        run2.font.size = Pt(8)
        run2.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
        _add_page_number(fp)
        # zajistit, že záhlaví/zápatí jsou viditelné
        sectPr = section._sectPr
        titlePg = OxmlElement('w:titlePg')
        titlePg.set(qn('w:val'), '0')
    except Exception:
        pass


def _style_document(doc):
    """Základní styly."""
    try:
        style = doc.styles['Normal']
        style.font.name = 'Calibri'
        style.font.size = Pt(10)
        style.paragraph_format.space_after = Pt(4)
        style.paragraph_format.line_spacing = 1.05
        # nadpisy
        for i in (1, 2, 3):
            hs = doc.styles[f'Heading {i}']
            hs.font.color.rgb = RGBColor(0x1A, 0x1A, 0x1A)
            if i == 1:
                hs.font.size = Pt(20)
            elif i == 2:
                hs.font.size = Pt(13)
                hs.font.color.rgb = RGBColor(0x2E, 0x74, 0xB5)
            else:
                hs.font.size = Pt(11)
    except Exception:
        pass


def _format_duration_text(seconds):
    if seconds is None or seconds <= 0:
        return "?"
    try:
        sec = int(seconds)
        return f"{sec // 60}:{sec % 60:02d}"
    except Exception:
        return "?"


def _format_tempo_text(tempo):
    if tempo is None:
        return "—"
    try:
        v = float(tempo)
        if v <= 0:
            return "—"
        # bez desetinných když celé
        if abs(v - round(v)) < 0.01:
            return f"{int(round(v))} BPM"
        return f"{v:.1f} BPM"
    except Exception:
        return "—"


def _stop_summary(marks):
    if not marks:
        return "—"
    total_bars = sum(int(m.get("bars") or 0) for m in marks)
    return f"{len(marks)} ({total_bars} taktů)" if total_bars else f"{len(marks)}"


def build_word_document(name, songs, include_details=True, include_texts=False, highlight_stops=True):
    """
    Sestaví python-docx Document.
    songs = list[dict] {title,artist,duration,tempo,content,stopMarks}
    Vrací Document nebo (None, err) pokud chybí závislost.
    """
    ok, err = _check_docx()
    if not ok:
        return None, err

    # normalizace přes playlist_backend (aby seděla logika s HTML/JSON)
    try:
        import playlist_backend as pb
        norm = []
        for s in songs:
            n = pb._normalize_song_entry(s)
            if n and n.get("title"):
                # zachovat content/stopMarks z originálu (normalize je může ořezat)
                if s.get("content") and not n.get("content"):
                    n["content"] = s.get("content")
                if s.get("stopMarks") and not n.get("stopMarks"):
                    n["stopMarks"] = s.get("stopMarks")
                norm.append(n)
            elif s.get("title"):
                norm.append(s)
    except Exception:
        norm = [s for s in songs if s.get("title")]

    total = sum(int(s["duration"]) for s in norm if s.get("duration") and int(s["duration"]) > 0)
    unknown = sum(1 for s in norm if not s.get("duration") or int(s.get("duration") or 0) <= 0)

    doc = Document()
    _style_document(doc)
    _setup_section(doc, name)

    # --- Titul ---
    h = doc.add_heading(name, level=1)
    h.alignment = WD_ALIGN_PARAGRAPH.LEFT
    try:
        for run in h.runs:
            run.font.color.rgb = RGBColor(0x1A, 0x1A, 0x1A)
    except Exception:
        pass

    # meta
    meta = doc.add_paragraph()
    meta.paragraph_format.space_after = Pt(2)
    now_str = datetime.now().strftime("%d. %m. %Y %H:%M")
    total_min = total // 60
    total_sec = total % 60
    if unknown == 0:
        time_label = f"Celkový čas: {total_min}:{total_sec:02d} • {len(norm)} písní"
    else:
        time_label = f"Celkový čas: {total_min}:{total_sec:02d} + {unknown} bez času (odhad +{unknown*3} min) • {len(norm)} písní"
    r = meta.add_run(f"{time_label}  •  Export: {now_str}")
    r.font.size = Pt(9)
    r.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    if unknown > 0:
        hint = doc.add_paragraph()
        hint.paragraph_format.space_after = Pt(8)
        hr = hint.add_run("„?“ = délka neznámá, do součtu se nepočítá (odhad 3 min/píseň).")
        hr.font.size = Pt(8)
        hr.font.italic = True
        hr.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

    # --- Tabulka přehledu ---
    doc.add_heading("Přehled setlistu", level=2)

    cols = 6
    table = doc.add_table(rows=1, cols=cols)
    table.style = 'Light Grid Accent 1'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    try:
        table.allow_autofit = True
    except Exception:
        pass

    hdr_cells = table.rows[0].cells
    headers = ["#", "Interpret", "Název", "Délka", "Tempo", "Zarážky"]
    for i, txt in enumerate(headers):
        cell = hdr_cells[i]
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER if i in (0, 3, 4, 5) else WD_ALIGN_PARAGRAPH.LEFT
        run = p.add_run(txt)
        run.bold = True
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        _set_cell_shading(cell, "2E74B5")
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        _set_cell_margins(cell, top=60, bottom=60)
    _set_repeat_header(table.rows[0])

    # šířky sloupců (twips cca)
    widths = [Cm(1.0), Cm(4.5), Cm(5.5), Cm(1.6), Cm(2.0), Cm(2.2)]
    for row in table.rows:
        for idx, w in enumerate(widths):
            try:
                row.cells[idx].width = w
            except Exception:
                pass

    for i, s in enumerate(norm):
        row = table.add_row().cells
        # #
        c = row[0]
        c.text = ""
        p = c.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(str(i + 1))
        r.font.size = Pt(9)
        # Interpret
        c = row[1]
        c.text = ""
        p = c.paragraphs[0]
        r = p.add_run(s.get("artist") or "—")
        r.font.size = Pt(9)
        if not s.get("artist"):
            r.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
            r.font.italic = True
        # Název
        c = row[2]
        c.text = ""
        p = c.paragraphs[0]
        r = p.add_run(s.get("title") or "")
        r.font.size = Pt(9)
        r.bold = True
        # Délka
        c = row[3]
        c.text = ""
        p = c.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        dur_txt = _format_duration_text(s.get("duration"))
        r = p.add_run(dur_txt)
        r.font.size = Pt(9)
        if dur_txt == "?":
            r.font.color.rgb = RGBColor(0xC6, 0x28, 0x28)
            r.bold = True
        # Tempo
        c = row[4]
        c.text = ""
        p = c.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        tempo_txt = _format_tempo_text(s.get("tempo"))
        r = p.add_run(tempo_txt)
        r.font.size = Pt(9)
        if tempo_txt == "—":
            r.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
        # Zarážky
        c = row[5]
        c.text = ""
        p = c.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        marks = s.get("stopMarks") or []
        txt = _stop_summary(marks) if marks else "—"
        r = p.add_run(txt)
        r.font.size = Pt(9)
        if not marks:
            r.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
        else:
            r.bold = True
        # střídavé pruhy
        if i % 2 == 1:
            for cell in row:
                _set_cell_shading(cell, "F2F2F2")
        for cell in row:
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            _set_cell_margins(cell, top=40, bottom=40)

    # součtový řádek
    sum_row = table.add_row().cells
    c = sum_row[0]
    c.merge(sum_row[2])
    # po merge je potřeba znovu získat buňky
    # python-docx merge posune indexy – jednodušší: vyplnit první, zbytek prázdný
    try:
        p = c.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r = p.add_run("Celkem:")
        r.bold = True
        r.font.size = Pt(9)
        _set_cell_shading(c, "D9E1F2")
        for idx in (3, 4, 5):
            cell = sum_row[idx]
            _set_cell_shading(cell, "D9E1F2")
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        # hodnoty
        p = sum_row[3].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        rr = p.add_run(f"{total_min}:{total_sec:02d}" + (f" +{unknown}?" if unknown else ""))
        rr.bold = True
        rr.font.size = Pt(9)
        p = sum_row[4].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        rr = p.add_run(f"{len(norm)} písní")
        rr.bold = True
        rr.font.size = Pt(8)
        rr.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
        p = sum_row[5].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        tot_marks = sum(len(s.get("stopMarks") or []) for s in norm)
        rr = p.add_run(f"{tot_marks} zarážek" if tot_marks else "—")
        rr.bold = True
        rr.font.size = Pt(8)
    except Exception:
        pass

    # --- Detailní rozpis ---
    if include_details and norm:
        doc.add_page_break()
        doc.add_heading("Detailní rozpis", level=2)
        intro = doc.add_paragraph()
        intro.paragraph_format.space_after = Pt(6)
        ir = intro.add_run("Rozpis po písních – tempo, zarážky a volitelně texty. Slouží jako podklad pro zkoušku / zvukaře.")
        ir.font.size = Pt(8)
        ir.font.italic = True
        ir.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

        for idx, s in enumerate(norm):
            h2 = doc.add_heading(f"{idx+1}. {s.get('artist') + ' – ' if s.get('artist') else ''}{s.get('title')}", level=2)
            # meta řádek
            meta_p = doc.add_paragraph()
            meta_p.paragraph_format.space_after = Pt(2)
            parts = []
            dur_txt = _format_duration_text(s.get("duration"))
            tempo_txt = _format_tempo_text(s.get("tempo"))
            marks = s.get("stopMarks") or []
            parts.append(f"Délka: {dur_txt}")
            parts.append(f"Tempo: {tempo_txt}")
            if marks:
                parts.append(f"Zarážky: {len(marks)} ({sum(int(m.get('bars') or 0) for m in marks)} taktů)")
            else:
                parts.append("Zarážky: —")
            mr = meta_p.add_run("  •  ".join(parts))
            mr.font.size = Pt(9)
            mr.font.color.rgb = RGBColor(0x33, 0x33, 0x33)

            # seznam zarážek
            if marks:
                for m in marks:
                    line_text = (m.get("lineText") or "").strip()
                    bars = int(m.get("bars") or 2)
                    if line_text:
                        txt = f'před „{line_text}“ – {bars} {"takt" if bars==1 else "takty" if 2 <= bars <=4 else "taktů"}'
                    else:
                        li = m.get("lineIndex")
                        if li is not None:
                            txt = f'řádek #{int(li)+1} – {bars} taktů'
                        else:
                            txt = f'{bars} taktů'
                    pp = doc.add_paragraph(style='List Bullet')
                    pp.paragraph_format.left_indent = Cm(0.6)
                    pp.paragraph_format.space_after = Pt(1)
                    rr = pp.add_run(txt)
                    rr.font.size = Pt(9)
            else:
                pp = doc.add_paragraph()
                rr = pp.add_run("– bez zarážek –")
                rr.font.size = Pt(9)
                rr.font.italic = True
                rr.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

            # text písně
            if include_texts:
                content = (s.get("content") or "").strip()
                if content:
                    # nahradit {stop:N}/{pause:N} čitelně
                    if highlight_stops:
                        # vložit [Pauza N] a zvýraznit později runem
                        import re
                        def repl(m):
                            n = m.group(1) or m.group(2) or "2"
                            return f"[Pauza {n}]"
                        content_disp = re.sub(r'\{(?:stop|pause):\s*(\d+)\}', repl, content, flags=re.IGNORECASE)
                        # také {stop: N} bez dvojtečky? ne – držet se parseru
                    else:
                        import re
                        content_disp = re.sub(r'\{(?:stop|pause):\s*(\d+)\}', r'[Pauza \1]', content, flags=re.IGNORECASE)
                    # přidat nadpis Text
                    tp = doc.add_paragraph()
                    tp.paragraph_format.space_before = Pt(4)
                    tr = tp.add_run("Text:")
                    tr.bold = True
                    tr.font.size = Pt(9)
                    tr.font.color.rgb = RGBColor(0x2E, 0x74, 0xB5)
                    # text jako jeden paragraph s uchováním řádků (python-docx neumí snadno zachovat prázdné řádky, použijeme add_paragraph per line block)
                    # Rozdělit po řádcích, prázdný řádek = malý odstup
                    for line in content_disp.splitlines():
                        lp = doc.add_paragraph()
                        lp.paragraph_format.space_after = Pt(1)
                        lp.paragraph_format.space_before = Pt(0)
                        if not line.strip():
                            # prázdný řádek – malá mezera
                            lp.paragraph_format.space_after = Pt(6)
                            continue
                        # zvýraznit [Pauza N] pokud highlight
                        if highlight_stops and "[Pauza" in line:
                            import re
                            parts = re.split(r'(\[Pauza\s*\d+\])', line)
                            for part in parts:
                                if re.match(r'\[Pauza\s*\d+\]', part):
                                    rr = lp.add_run(part)
                                    rr.bold = True
                                    rr.font.color.rgb = RGBColor(0xC6, 0x28, 0x28)
                                    rr.font.size = Pt(9)
                                    try:
                                        shd = OxmlElement('w:shd')
                                        shd.set(qn('w:val'), 'clear')
                                        shd.set(qn('w:color'), 'auto')
                                        shd.set(qn('w:fill'), 'FFF2CC')
                                        rr._r.get_or_add_rPr().append(shd)
                                    except Exception:
                                        pass
                                else:
                                    if part:
                                        rr = lp.add_run(part)
                                        rr.font.size = Pt(9)
                                        rr.font.name = 'Consolas'
                        else:
                            rr = lp.add_run(line)
                            rr.font.size = Pt(9)
                            rr.font.name = 'Consolas'
                            if line.strip().startswith("{") and line.strip().endswith("}"):
                                rr.font.color.rgb = RGBColor(0x70, 0x70, 0x70)
                                rr.font.italic = True
                else:
                    pp = doc.add_paragraph()
                    rr = pp.add_run("(text písně není k dispozici – zaškrtněte „Včetně textů“ při ukládání)")
                    rr.font.size = Pt(8)
                    rr.font.italic = True
                    rr.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

    # --- Patička dokumentu (poznámka) ---
    doc.add_paragraph()  # spacer
    note = doc.add_paragraph()
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    note.paragraph_format.space_before = Pt(12)
    nr = note.add_run(f"Vygenerováno Posouvač textu – PC Editor  •  {now_str}  •  {len(norm)} písní")
    nr.font.size = Pt(7)
    nr.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
    nr.font.italic = True

    return doc, None


def build_library_word_document(title, songs, include_duration=True, include_tempo=True, include_stops=True):
    """
    Sestaví tisknutelný .docx se seznamem knihovny (abecedně).
    songs = list[dict] {title,artist,duration,tempo,stopMarks}
    Vrací (Document, None) nebo (None, err).
    """
    ok, err = _check_docx()
    if not ok:
        return None, err
    if not title or not str(title).strip():
        return None, "Název seznamu nesmí být prázdný."
    if not songs:
        return None, "Seznam neobsahuje žádné písně."

    # normalizace + abecední řazení
    try:
        import playlist_backend as pb
        norm = []
        for s in songs:
            n = pb._normalize_song_entry(s)
            if n and n.get("title"):
                if s.get("stopMarks") and not n.get("stopMarks"):
                    n["stopMarks"] = s.get("stopMarks")
                norm.append(n)
            elif s.get("title"):
                norm.append(s)
    except Exception:
        norm = [s for s in songs if s.get("title")]
    # abecedně dle interpretu + názvu (case-insensitive)
    try:
        norm.sort(key=lambda s: (((s.get("artist") or "").strip().lower(), (s.get("title") or "").strip().lower())))
    except Exception:
        pass

    total = sum(int(s["duration"]) for s in norm if s.get("duration") and int(s["duration"]) > 0)
    unknown = sum(1 for s in norm if not s.get("duration") or int(s.get("duration") or 0) <= 0)

    doc = Document()
    _style_document(doc)
    _setup_section(doc, title.strip())

    # --- Titul ---
    h = doc.add_heading(title.strip(), level=1)
    h.alignment = WD_ALIGN_PARAGRAPH.LEFT
    try:
        for run in h.runs:
            run.font.color.rgb = RGBColor(0x1A, 0x1A, 0x1A)
    except Exception:
        pass

    # meta
    meta = doc.add_paragraph()
    meta.paragraph_format.space_after = Pt(2)
    now_str = datetime.now().strftime("%d. %m. %Y %H:%M")
    total_min = total // 60
    total_sec = total % 60
    if unknown == 0:
        time_label = f"Celkový čas: {total_min}:{total_sec:02d} • {len(norm)} písní"
    else:
        time_label = f"Celkový čas: {total_min}:{total_sec:02d} + {unknown} bez času (odhad +{unknown*3} min) • {len(norm)} písní"
    r = meta.add_run(f"{time_label}  •  Export: {now_str}")
    r.font.size = Pt(9)
    r.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    if unknown > 0:
        hint = doc.add_paragraph()
        hint.paragraph_format.space_after = Pt(8)
        hr = hint.add_run("„?“ = délka neznámá, do součtu se nepočítá (odhad 3 min/píseň).")
        hr.font.size = Pt(8)
        hr.font.italic = True
        hr.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

    # --- Tabulka ---
    # dynamické sloupce
    headers = ["#", "Interpret", "Název"]
    col_keys = ["num", "artist", "title"]
    if include_duration:
        headers.append("Délka")
        col_keys.append("duration")
    if include_tempo:
        headers.append("Tempo")
        col_keys.append("tempo")
    if include_stops:
        headers.append("Zarážky")
        col_keys.append("stops")
    cols = len(headers)
    table = doc.add_table(rows=1, cols=cols)
    table.style = 'Light Grid Accent 1'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    try:
        table.allow_autofit = True
    except Exception:
        pass

    hdr_cells = table.rows[0].cells
    # indexy centrovaných sloupců (číslo + volitelné)
    center_cols = {0}
    if include_duration:
        center_cols.add(headers.index("Délka"))
    if include_tempo:
        center_cols.add(headers.index("Tempo"))
    if include_stops:
        center_cols.add(headers.index("Zarážky"))
    for i, txt in enumerate(headers):
        cell = hdr_cells[i]
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER if i in center_cols else WD_ALIGN_PARAGRAPH.LEFT
        run = p.add_run(txt)
        run.bold = True
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        _set_cell_shading(cell, "2E74B5")
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        _set_cell_margins(cell, top=60, bottom=60)
    _set_repeat_header(table.rows[0])

    # šířky – rozdělit podle počtu sloupců
    base_widths = {
        "#": Cm(0.9), "Interpret": Cm(4.8), "Název": Cm(5.8),
        "Délka": Cm(1.5), "Tempo": Cm(1.8), "Zarážky": Cm(2.0),
    }
    widths = [base_widths.get(h, Cm(2.0)) for h in headers]
    for row in table.rows:
        for idx, w in enumerate(widths):
            try:
                row.cells[idx].width = w
            except Exception:
                pass

    for i, s in enumerate(norm):
        row = table.add_row().cells
        for col_idx, key in enumerate(col_keys):
            c = row[col_idx]
            c.text = ""
            p = c.paragraphs[0]
            is_center = col_idx in center_cols
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if is_center else WD_ALIGN_PARAGRAPH.LEFT
            if key == "num":
                r = p.add_run(str(i + 1))
                r.font.size = Pt(9)
            elif key == "artist":
                txt = s.get("artist") or "—"
                r = p.add_run(txt)
                r.font.size = Pt(9)
                if not s.get("artist"):
                    r.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
                    r.font.italic = True
            elif key == "title":
                r = p.add_run(s.get("title") or "")
                r.font.size = Pt(9)
                r.bold = True
            elif key == "duration":
                dur_txt = _format_duration_text(s.get("duration"))
                r = p.add_run(dur_txt)
                r.font.size = Pt(9)
                if dur_txt == "?":
                    r.font.color.rgb = RGBColor(0xC6, 0x28, 0x28)
                    r.bold = True
            elif key == "tempo":
                tempo_txt = _format_tempo_text(s.get("tempo"))
                r = p.add_run(tempo_txt)
                r.font.size = Pt(9)
                if tempo_txt == "—":
                    r.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
            elif key == "stops":
                marks = s.get("stopMarks") or []
                txt = _stop_summary(marks) if marks else "—"
                r = p.add_run(txt)
                r.font.size = Pt(9)
                if not marks:
                    r.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
                else:
                    r.bold = True
            c.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            _set_cell_margins(c, top=40, bottom=40)
        if i % 2 == 1:
            for cell in row:
                _set_cell_shading(cell, "F2F2F2")

    # součtový řádek
    if norm:
        try:
            sum_row = table.add_row().cells
            # merge prvních 3 buněk (číslo+interpret+název) -> "Celkem:"
            first = sum_row[0]
            last_merge = sum_row[2] if cols >= 3 else sum_row[0]
            if cols >= 3:
                first.merge(last_merge)
            p = first.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            rr = p.add_run("Celkem:")
            rr.bold = True
            rr.font.size = Pt(9)
            _set_cell_shading(first, "D9E1F2")
            # obarvit zbytek sum_row
            for idx in range(1, len(sum_row)):
                try:
                    _set_cell_shading(sum_row[idx], "D9E1F2")
                    sum_row[idx].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                except Exception:
                    pass
            # hodnoty – mapovat dle col_keys
            for col_idx, key in enumerate(col_keys):
                if key in ("num", "artist", "title"):
                    continue
                cell = sum_row[col_idx] if col_idx < len(sum_row) else None
                if cell is None:
                    continue
                p = cell.paragraphs[0]
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                if key == "duration":
                    txt = f"{total_min}:{total_sec:02d}" + (f" +{unknown}?" if unknown else "")
                elif key == "tempo":
                    txt = f"{len(norm)} písní"
                elif key == "stops":
                    tot_marks = sum(len(s.get("stopMarks") or []) for s in norm)
                    txt = f"{tot_marks} zarážek" if tot_marks else "—"
                else:
                    txt = ""
                if txt:
                    rr = p.add_run(txt)
                    rr.bold = True
                    rr.font.size = Pt(8 if key != "duration" else 9)
                    if key == "tempo":
                        rr.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
        except Exception:
            pass

    # patička
    doc.add_paragraph()
    note = doc.add_paragraph()
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    note.paragraph_format.space_before = Pt(12)
    nr = note.add_run(f"Vygenerováno Posouvač textu – PC Editor  •  {now_str}  •  {len(norm)} písní")
    nr.font.size = Pt(7)
    nr.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
    nr.font.italic = True

    return doc, None


def save_library_docx(filename, title, songs, include_duration=True, include_tempo=True, include_stops=True):
    """Uloží seznam knihovny do .docx. Vrací (True, path) nebo (False, err)."""
    ok, err = _check_docx()
    if not ok:
        return False, err
    if not title or not str(title).strip():
        return False, "Název seznamu nesmí být prázdný."
    if not songs:
        return False, "Seznam neobsahuje žádné písně."
    doc, err2 = build_library_word_document(title, songs,
                                            include_duration=include_duration,
                                            include_tempo=include_tempo,
                                            include_stops=include_stops)
    if doc is None:
        return False, err2 or "Nepodařilo se sestavit dokument."
    try:
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(filename))
        return True, str(filename)
    except Exception as e:
        return False, str(e)


def save_playlist_docx(filename, name, songs, include_details=True, include_texts=False, highlight_stops=True):
    """Uloží .docx do filename. Vrací (True, path) nebo (False, err)."""
    ok, err = _check_docx()
    if not ok:
        return False, err
    if not name or not str(name).strip():
        return False, "Název setlistu nesmí být prázdný."
    if not songs:
        return False, "Setlist neobsahuje žádné písně."
    doc, err2 = build_word_document(name, songs, include_details=include_details, include_texts=include_texts, highlight_stops=highlight_stops)
    if doc is None:
        return False, err2 or "Nepodařilo se sestavit dokument."
    try:
        # zajistit adresář
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(filename))
        return True, str(filename)
    except Exception as e:
        return False, str(e)
