"""
Regresní testy indexace zarážek (etapa B1, nálezy F-01 / R-08).

lineIndex zarážky = index CÍLOVÉHO řádku v prostoru textu BEZ stop direktiv
{stop:N}/{pause:N}. Přítomnost direktiv v textu nesmí posouvat cílové indexy
žádné další operace (vkládání, opakované uložení, extrakce).

Testy volají přímo produkční funkce:
  - song_parser.insert_stop_directive / remove_stop_directive_at / split_physical_lines
  - playlist_backend.extract_stop_marks_from_content
  - playlist_backend.file_content_with_stop_marks_applied
"""
import pytest

import song_parser
import playlist_backend as pb


# --- T-1: existující zarážka nezpůsobí posun nové ---

def test_t1_existujici_zarazka_neposouva_novou():
    content = "A\n{stop:2}\nB\nC\nD\nE\nF\nG"
    marks = pb.extract_stop_marks_from_content(content)
    # existující zarážka míří na B = čistý index 1 (ne 2)
    assert marks == [{"lineText": "B", "lineIndex": 1, "bars": 2}]

    # nová zarážka na F = čistý index 5 (F je 6. textový řádek, index 5)
    marks.append({"lineText": "F", "lineIndex": 5, "bars": 4})
    result = pb.file_content_with_stop_marks_applied(content, marks)
    assert result == "A\n{stop:2}\nB\nC\nD\nE\n{stop:4}\nF\nG"


# --- T-2: opakované uložení je idempotentní ---

def test_t2_opakovane_ulozeni_idempotentni():
    content = "A\nB\nC\nD\nE\nF\nG"
    marks = [
        {"lineText": "B", "lineIndex": 1, "bars": 2},
        {"lineText": "F", "lineIndex": 5, "bars": 4},
    ]
    once = pb.file_content_with_stop_marks_applied(content, marks)
    assert once == "A\n{stop:2}\nB\nC\nD\nE\n{stop:4}\nF\nG"

    # aplikace téhož nad textem, který direktivy už obsahuje
    twice = pb.file_content_with_stop_marks_applied(once, marks)
    assert twice == once
    thrice = pb.file_content_with_stop_marks_applied(twice, marks)
    assert thrice == once

    # a extrakce z výsledku vrací tytéž čisté indexy
    assert pb.extract_stop_marks_from_content(once) == marks


# --- T-3: existující direktiva + nová zarážka ---

def test_t3_existujici_direktiva_a_nova_zarazka():
    content = "A\n{stop:3}\nB\nC\nD"
    marks = pb.extract_stop_marks_from_content(content)
    assert marks == [{"lineText": "B", "lineIndex": 1, "bars": 3}]

    marks.append({"lineText": "D", "lineIndex": 3, "bars": 1})
    result = pb.file_content_with_stop_marks_applied(content, marks)
    assert result == "A\n{stop:3}\nB\nC\n{stop:1}\nD"

    # obě zarážky zůstaly u zamýšlených řádků (round-trip)
    assert pb.extract_stop_marks_from_content(result) == [
        {"lineText": "B", "lineIndex": 1, "bars": 3},
        {"lineText": "D", "lineIndex": 3, "bars": 1},
    ]


# --- T-4: opakované stejné řádky ---

def test_t4_opakowane_stejne_radky():
    content = "Refrén\nA\nRefrén\nB"
    # cílem je DRUHÝ výskyt (čistý index 2), ne první
    result = pb.file_content_with_stop_marks_applied(
        content, [{"lineText": "Refrén", "lineIndex": 2, "bars": 2}]
    )
    assert result == "Refrén\nA\n{stop:2}\nRefrén\nB"

    # přímé vložení taktéž respektuje index, ne text
    assert song_parser.insert_stop_directive(content, 2, 2) == \
        "Refrén\nA\n{stop:2}\nRefrén\nB"
    # první výskyt je index 0
    assert song_parser.insert_stop_directive(content, 0, 2) == \
        "{stop:2}\nRefrén\nA\nRefrén\nB"

    # kontrola lineText jen potvrzuje cíl, nevybírá první shodu
    with pytest.raises(ValueError):
        song_parser.insert_stop_directive(content, 2, 2, expected_line_text="A")


# --- T-5: neplatný index / neshoda údajů ---

def test_t5_neplatny_index_insert():
    content = "A\nB\nC"
    with pytest.raises(ValueError):
        song_parser.insert_stop_directive(content, -1, 2)
    with pytest.raises(ValueError):
        song_parser.insert_stop_directive(content, 99, 2)
    # neshoda lineIndex/lineText
    with pytest.raises(ValueError):
        song_parser.insert_stop_directive(content, 1, 2, expected_line_text="C")
    # žádná direktiva nesmí být vložena – chyba zachová původní text
    assert content == "A\nB\nC"


def test_t5_neplatny_index_applied_vraci_puvodni_text():
    content = "A\n{stop:2}\nB\nC"
    errors: list[str] = []
    bad_marks = [{"lineText": "C", "lineIndex": 99, "bars": 2}]
    result = pb.file_content_with_stop_marks_applied(content, bad_marks, errors=errors)
    # původní text i existující zarážka beze změny, nic se nepřesunulo na konec
    assert result == content
    assert errors and "99" in errors[0]

    # neshoda lineIndex/lineText
    errors.clear()
    mismatch = [{"lineText": "C", "lineIndex": 0, "bars": 2}]  # index 0 = řádek A
    result = pb.file_content_with_stop_marks_applied(content, mismatch, errors=errors)
    assert result == content
    assert errors

    # záporný index
    errors.clear()
    result = pb.file_content_with_stop_marks_applied(
        content, [{"lineText": "B", "lineIndex": -1, "bars": 2}], errors=errors)
    assert result == content
    assert errors


def test_t5_stary_spinavy_index_se_neaplikuje_tiche_na_konec():
    # Starý (před B1) lineIndex = pozice direktivy v textu SE zarážkami.
    # U druhé direktivy se liší od čistého indexu → nesmí se tiše aplikovat.
    content = "A\n{stop:2}\nB\n{stop:4}\nC"
    stale = [{"lineText": "C", "lineIndex": 3, "bars": 4}]  # starý špinavý index
    errors: list[str] = []
    result = pb.file_content_with_stop_marks_applied(content, stale, errors=errors)
    assert result == content
    assert errors


def test_direktiva_na_konci_souboru_pretrvava():
    # Pauza za posledním řádkem (lineText je prázdný) – legální stav.
    content = "A\nB\n{stop:2}"
    marks = pb.extract_stop_marks_from_content(content)
    assert marks == [{"lineText": "", "lineIndex": 2, "bars": 2}]
    assert pb.file_content_with_stop_marks_applied(content, marks) == content


def test_t5_textovy_fallback_bez_indexu():
    content = "A\nB\nC"
    # jednoznačný text bez indexu → funguje
    ok = pb.file_content_with_stop_marks_applied(
        content, [{"lineText": "B", "bars": 2}])
    assert ok == "A\n{stop:2}\nB\nC"
    # nejednoznačný text bez indexu → chyba, žádný posun na konec
    dup = "Refrén\nA\nRefrén\nB"
    errors: list[str] = []
    result = pb.file_content_with_stop_marks_applied(
        dup, [{"lineText": "Refrén", "bars": 2}], errors=errors)
    assert result == dup
    assert errors


# --- T-6: zachování obsahu ---

def test_t6_zachovani_obsahu():
    content = (
        "{soc}\n"
        "Verse [C] one\n"
        "\n"
        "{c:poznámka}\n"
        "Refrén\n"
        "{eoc}\n"
        "\n"
        "Refrén\n"
        "Konec"
    )
    marks = [
        {"lineText": "Refrén", "lineIndex": 2, "bars": 2},  # první Refrén
        {"lineText": "Konec", "lineIndex": 4, "bars": 4},
    ]
    result = pb.file_content_with_stop_marks_applied(content, marks)
    expected = (
        "{soc}\n"
        "Verse [C] one\n"
        "\n"
        "{c:poznámka}\n"
        "{stop:2}\n"
        "Refrén\n"
        "{eoc}\n"
        "\n"
        "Refrén\n"
        "{stop:4}\n"
        "Konec"
    )
    assert result == expected

    # všechny původní řádky zůstaly, jen přibyly direktivy
    original_lines = content.split("\n")
    # prázdné řádky zachovány (přibyly jen 2 direktivní řádky)
    assert result.count("\n") == content.count("\n") + 2
    # žádný původní řádek nezmizel ani se nepřesunul (kromě vsunutých direktiv)
    filtered = [l for l in result.split("\n") if l not in ("{stop:2}", "{stop:4}")]
    assert filtered == original_lines
    # ostatní direktivy ({soc}, {c:}, {eoc}) zůstaly na místě
    assert "{soc}" in result and "{eoc}" in result and "{c:poznámka}" in result


# --- Doprovodné: extrakce a odstraňování v čistém prostoru ---

def test_extract_cisty_index():
    content = "{stop:2}\nA\nB\n{pause:4}\nC"
    marks = pb.extract_stop_marks_from_content(content)
    assert marks == [
        {"lineText": "A", "lineIndex": 0, "bars": 2},
        {"lineText": "C", "lineIndex": 2, "bars": 4},
    ]


def test_remove_stop_directive_cisty_index():
    content = "A\n{stop:2}\nB\n{stop:4}\nC"
    # direktiva s cílem B = čistý index 1
    out, removed = song_parser.remove_stop_directive_at(content, 1)
    assert removed is True
    assert out == "A\nB\n{stop:4}\nC"
    # neplatný cíl → beze změny
    out2, removed2 = song_parser.remove_stop_directive_at(out, 5)
    assert removed2 is False and out2 == out


def test_split_physical_lines_konzistence_s_parser():
    content = "A\n\n{c:x}\n{stop:2}\n{soc}\nB"
    kinds = [(i, k) for (i, k, _p) in song_parser.split_physical_lines(content)]
    assert kinds == [(0, "text"), (1, "empty"), (2, "comment"),
                     (3, "stop"), (4, "section"), (5, "text")]
    # čisté indexy = text + comment (bez stop, section, empty)
    assert song_parser.clean_line_indices(content) == [0, 2, 5]
    # ordered_lines má stejný počet čistých řádků + 1 stop řádek
    ordered = song_parser.ordered_lines(content)
    assert len([ln for ln in ordered
                if not any(e.type == song_parser.ElementType.stopMark for e in ln)]) == 3
