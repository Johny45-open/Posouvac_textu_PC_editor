"""
Regression testy CSV importu knihovny (etapa opravy dle auditu).

Ověřovaná pravidla:
  1. `title` je jediný povinný sloupec; `artist`/`duration` jsou nepovinné.
  2. Chybějící sloupec se chová jako prázdná hodnota (nikdy se za něj
     nedosazuje jiný sloupec).
  3. Prázdné/krátké řádky se přeskočí s počítadlem a důvodem (číslo řádku).
  4. Celosouborové parsití: uvozovky, escapované uvozovky, řádkové zlomy,
     čárka i středník, libovolné pořadí sloupců.
  5. Kódování: utf-8-sig, cp1250; nesrozumitelný soubor -> jasná chyba.
  6. CSV NIKDY nepřepisuje ani nemazá existující metadata knihovny.
  7. Párování: priorita shoda artist+title; řádek bez interpreta jen při
     jednoznačném názvu; jinak spolehlivě nic (raději nic než chybně).
  8. Druhá úroveň bez diacritiky jen při jednoznačné shodě (bez kolize).
"""
import pathlib

import playlist_backend as pb
import library_model


def _write(path: pathlib.Path, text: str, encoding: str = "utf-8") -> pathlib.Path:
    path.write_bytes(text.encode(encoding))
    return path


def _lib(artist, title, duration=None):
    return {"artist": artist, "title": title, "duration": duration}


def _load(tmp_path, filename, text, encoding="utf-8"):
    p = _write(tmp_path / filename, text, encoding)
    res = pb.load_csv_library(str(p))
    assert len(res) == 3  # kontrakt: (ok, data|chyba, info) – všechny volající v main.py
    return res


# --- 1. Platný soubor v dokumentovaném formátu ---

def test_valid_full_csv(tmp_path):
    ok, data, info = _load(tmp_path, "ok.csv",
        'id,artist,title,duration,filePath\n'
        '1,Martin,Refrén,3:30,/a/1.txt\n'
        '2,Jana,Modra,210,/a/2.txt\n')
    assert ok is True
    assert info["imported"] == 2 and info["skipped"] == 0
    assert data[0]["artist"] == "Martin" and data[0]["title"] == "Refrén"
    assert data[0]["duration"] == 210 and data[1]["duration"] == 210
    # doplnění knihovny
    lib = [_lib("Martin", "Refrén")]
    library_model.enrich_with_csv(lib, data)
    assert lib[0]["duration"] == 210


# --- 2. CSV bez sloupce artist ---

def test_csv_without_artist_column(tmp_path):
    ok, data, info = _load(tmp_path, "noartist.csv",
        'title,duration\nRefrén,210\nNeco jine,95\n')
    assert ok is True and info["imported"] == 2
    assert all(r["artist"] == "" for r in data)
    assert data[0]["duration"] == 210
    # doplní se i při interpretní neznámosti, pokud je název v knihovně jednoznačný
    lib = [_lib("Neznamy interpret", "Refrén"), _lib("Druga", "Jina")]
    library_model.enrich_with_csv(lib, data)
    assert lib[0]["duration"] == 210          # doplněna
    assert lib[1]["duration"] is None         # nedotčena
    assert lib[0]["artist"] == "Neznamy interpret"  # interpret NIKDY přepsán


# --- 3. CSV bez sloupce duration ---

def test_csv_without_duration_column(tmp_path):
    ok, data, info = _load(tmp_path, "nodur.csv",
        'artist,title\nMartin,Refrén\n')
    assert ok is True and info["imported"] == 1
    assert data[0]["duration"] is None
    lib = [_lib("Martin", "Refrén")]
    library_model.enrich_with_csv(lib, data)
    assert lib[0]["duration"] is None  # CSV neumí doplnit, nic se nesejde


# --- 4. Prázdná buňka artist – metadatum knihovny se nemění ---

def test_empty_artist_cell_preserves_library(tmp_path):
    ok, data, _ = _load(tmp_path, "emptyartist.csv",
        'id,artist,title,duration,filePath\n1,,Refrén,210,/a/1.txt\n')
    assert ok is True and data[0]["artist"] == ""
    assert data[0]["title"] == "Refrén"
    lib = [_lib("Martin", "Refrén")]
    library_model.enrich_with_csv(lib, data)
    assert lib[0]["artist"] == "Martin"  # prázdné buňka = ne mazání
    assert lib[0]["duration"] == 210     # doplnění funkční


# --- 5. Již vyplněná duration se nepřepíše ---

def test_existing_duration_not_overwritten(tmp_path):
    ok, data, _ = _load(tmp_path, "keep.csv",
        'artist,title,duration\nMartin,Refrén,210\n')
    assert ok is True
    lib = [_lib("Martin", "Refrén", duration=180)]
    library_model.enrich_with_csv(lib, data)
    assert lib[0]["duration"] == 180  # CSV nemá právo přepsat
    # a prázdné duration v CSV nic nedoplní na nemy
    d2 = _load(tmp_path, "keep2.csv", 'artist,title,duration\nMartin,Refrén,\n')
    lib2 = [_lib("Martin", "Refrén", duration=180)]
    library_model.enrich_with_csv(lib2, d2[1])
    assert lib2[0]["duration"] == 180


# --- 6. Chybějící povinný sloupec title – jasná chyba ---

def test_missing_title_column_is_error(tmp_path):
    ok, err, info = _load(tmp_path, "notitle.csv", 'artist,duration\nMartin,210\n')
    assert ok is False
    assert 'title' in str(err).lower()
    assert info == {}  # s chybou se žádné data nepoužijí
    lib = [_lib("Martin", "Refrén")]
    # volající v UI při ok==False knihovnu nikdy neobohacuje – ověřujeme, že
    # ani náhodné použití by nic nezpůsobilo
    library_model.enrich_with_csv(lib, [])
    assert lib[0]["duration"] is None


def test_missing_file_and_empty_file_are_errors(tmp_path):
    res = pb.load_csv_library(str(tmp_path / "neznama.csv"))
    assert len(res) == 3 and res[0] is False
    _write(tmp_path / "empty.csv", "")
    res2 = pb.load_csv_library(str(tmp_path / "empty.csv"))
    assert res2[0] is False and res2[2] == {}


# --- 7. Prázdné a příliš krátké řádky – přeskočeny s důvodem ---

def test_blank_and_short_rows_counted(tmp_path):
    ok, data, info = _load(tmp_path, "shortrows.csv",
        'id,artist,title,duration\n'
        '1,Martin,Refrén,210\n'     # řádek 2 – platný
        '\n'                        # řádek 3 – prázdný
        '2,Jana,,95\n'              # řádek 4 – prázdné title
        'x\n')                      # řádek 5 – jen 1 sloupec
    assert ok is True
    assert info["imported"] == 1
    assert info["skipped"] == 3
    text = " ".join(info["errors"])
    assert "řádek 3" in text and "prázdný" in text
    assert "řádek 4" in text and "title" in text
    assert "řádek 5" in text
    assert data[0]["title"] == "Refrén"


# --- 8. Smíšené pořadí sloupců ---

def test_mixed_column_order(tmp_path):
    ok, data, info = _load(tmp_path, "order.csv",
        'duration,title,artist\n210,Refrén,Martin\n3:30,Modrá,Jana\n')
    assert ok is True and info["imported"] == 2
    assert data[0] == {"artist": "Martin", "title": "Refrén",
                       "duration": 210, "label": "Martin - Refrén"}
    assert data[1]["title"] == "Modrá" and data[1]["duration"] == 210
    # ignorují se neznámé sloupce (filePath, id apod.)
    ok2, data2, _ = _load(tmp_path, "extra.csv",
        'id,artist,title,duration,filePath,unknown\n7,Martin,Refrén,210,/x/1.txt,plic\n')
    assert ok2 is True and data2[0]["title"] == "Refrén" and data2[0]["duration"] == 210


# --- 9. Oddělovače: čárka i středník ---

def test_comma_delimiter(tmp_path):
    ok, data, _ = _load(tmp_path, "comma.csv", 'artist,title,duration\nMartin,Refrén,210\n')
    assert ok is True and data[0]["title"] == "Refrén"


def test_semicolon_delimiter(tmp_path):
    ok, data, _ = _load(tmp_path, "semi.csv",
        'artist;title;duration\nMartin;Refrén;210\n;Modrá;95\n')
    assert ok is True and len(data) == 2
    assert data[0]["artist"] == "Martin" and data[0]["title"] == "Refrén"
    assert data[1]["artist"] == "" and data[1]["title"] == "Modrá"


# --- 10. Uvozovky, escapované uvozovky, řádkové zlomy ---

def test_quotes_escaped_and_newline_in_field(tmp_path):
    ok, data, info = _load(tmp_path, "quotes.csv",
        'artist,title,duration\n'
        '"Zem, Martin","Refrén ""velký""",210\n'
        '"Jana","text\nna dva řádky",95\n')
    assert ok is True and info["imported"] == 2 and info["skipped"] == 0
    assert data[0]["artist"] == "Zem, Martin"
    assert data[0]["title"] == 'Refrén "velký"'
    assert data[0]["duration"] == 210
    # uvozované pole s řádkovým zlomem = JEDEN záznam
    assert data[1]["title"] == "text\nna dva řádky"
    assert data[1]["duration"] == 95


# --- 11. České znaky: UTF-8 a cp1250 ---

def test_czech_utf8(tmp_path):
    ok, data, _ = _load(tmp_path, "cs_utf8.csv",
        'artist,title,duration\nHavlíček,Kočičí tanc,210\n')
    assert ok is True
    assert data[0]["artist"] == "Havlíček" and data[0]["title"] == "Kočičí tanc"
    lib = [_lib("Havlíček", "Kočičí tanc")]
    library_model.enrich_with_csv(lib, data)
    assert lib[0]["duration"] == 210


def test_czech_cp1250(tmp_path):
    ok, data, info = _load(tmp_path, "cs_cp1250.csv",
        'artist,title,duration\nHavlíček,Kočičí tanc,210\n', encoding="cp1250")
    assert ok is True
    assert info["encoding"] == "cp1250"
    assert data[0]["artist"] == "Havlíček" and data[0]["title"] == "Kočičí tanc"
    assert data[0]["duration"] == 210


def test_undecodable_file_is_clear_error(tmp_path):
    # osamělý 0x81 – neplatné UTF-8 i cp1250 (0x81 je v cp1250 nedefinováno)
    p = tmp_path / "bad.csv"
    p.write_bytes(b'artist,title\n,\x81x\n')
    res = pb.load_csv_library(str(p))
    assert len(res) == 3
    ok, err = res[0], res[1]
    assert ok is False
    assert "dekódovat" in str(err) or "decode" in str(err).lower()


# --- 12. Dvě skladby se stejným názvem, různé interpreti ---

def test_same_title_different_artists_correct_mapping(tmp_path):
    ok, data, _ = _load(tmp_path, "dup.csv",
        'artist,title,duration\nA,X,200\nB,X,300\n')
    assert ok is True and len(data) == 2
    lib = [_lib("A", "X"), _lib("B", "X")]
    library_model.enrich_with_csv(lib, data)
    assert lib[0]["duration"] == 200
    assert lib[1]["duration"] == 300


def test_same_title_unknown_csv_artist_not_assigned(tmp_path):
    # CSV zmiňuje interpreta D – knihovna X má A a B -> nic nepřiřadit
    ok, data, _ = _load(tmp_path, "dup2.csv", 'artist,title,duration\nD,X,500\n')
    lib = [_lib("A", "X"), _lib("B", "X")]
    library_model.enrich_with_csv(lib, data)
    assert lib[0]["duration"] is None and lib[1]["duration"] is None


# --- 13. CSV bez interpreta + jednoznačný název v knihovně ---

def test_no_artist_unique_title_assigned(tmp_path):
    ok, data, _ = _load(tmp_path, "unique.csv", 'title,duration\nX,400\n')
    lib = [_lib("A", "X"), _lib("Y", "K")]
    library_model.enrich_with_csv(lib, data)
    assert lib[0]["duration"] == 400
    assert lib[1]["duration"] is None


# --- 14. Nejednoznačný název – bezpečně nic ---

def test_no_artist_ambiguous_title_not_assigned(tmp_path):
    ok, data, _ = _load(tmp_path, "amb.csv", 'title,duration\nX,400\n')
    lib = [_lib("A", "X"), _lib("B", "X")]
    library_model.enrich_with_csv(lib, data)
    assert lib[0]["duration"] is None and lib[1]["duration"] is None


# --- 15. Párování ignorující diacritiku + kolize ---

def test_diacritic_insensitive_match(tmp_path):
    ok, data, _ = _load(tmp_path, "na.csv",
        'artist,title,duration\nHavlíček,Refrén,210\n')
    # v knihovně chybí diacritiky -> přesná shoda nevyjde, bez-diacritika vyjde
    lib = [_lib("Havlicek", "Refren")]
    library_model.enrich_with_csv(lib, data)
    assert lib[0]["duration"] == 210


def test_diacritic_collision_not_assigned(tmp_path):
    # "Puda" a "Puda" se po normalizaci (bez diacritiky) rovnají -> kolize
    ok, data, _ = _load(tmp_path, "col.csv", 'artist,title,duration\nA,Púda,500\n')
    lib = [_lib("A", "Puda"), _lib("B", "Puda")]
    library_model.enrich_with_csv(lib, data)
    # přesná shoda nevyjde (Puda != Puda), diacritická úroveň je
    # v knihovně nejednoznačná (2 skladby) -> bezpečně nic
    assert lib[0]["duration"] is None and lib[1]["duration"] is None


def test_exact_level_artist_disambiguation(tmp_path):
    # přesná úroveň s rozlišením podle interpreta
    ok, data, _ = _load(tmp_path, "mix.csv", 'artist,title,duration\nB,Puda,700\n')
    lib = [_lib("A", "Puda"), _lib("B", "Puda")]
    library_model.enrich_with_csv(lib, data)
    assert lib[1]["duration"] == 700
    assert lib[0]["duration"] is None


# --- 16. Obnova stavu: kontrakt návratové тройки (všech 3 volajících v main.py) ---

def test_return_contract_for_all_paths(tmp_path):
    # OK cesta
    p1 = _write(tmp_path / "a.csv", 'artist,title,duration\nA,X,210\n')
    r1 = pb.load_csv_library(str(p1))
    assert len(r1) == 3 and r1[0] is True
    assert set(r1[2]) >= {"imported", "skipped", "errors"}
    # chyba hlavičky
    p2 = _write(tmp_path / "b.csv", 'artist,duration\nA,210\n')
    r2 = pb.load_csv_library(str(p2))
    assert len(r2) == 3 and r2[0] is False and r2[2] == {}
    # chybějící soubor
    r3 = pb.load_csv_library(str(tmp_path / "ztracena.csv"))
    assert len(r3) == 3 and r3[0] is False and r3[2] == {}


# --- 17. Souhrnné počty (pro ohlášení výsledku) ---

def test_summary_counts_for_announcement(tmp_path):
    ok, data, info = _load(tmp_path, "summary.csv",
        'artist,title,duration\n'
        'A,X,210\n'
        '\n'
        'B,,95\n'
        'C,Y,2\n')
    assert ok is True
    assert info["imported"] == 2
    assert info["skipped"] == 2
    assert len(info["errors"]) == 2
    # ohlášení v UI je postaveno přesně na této struktuře – zkontroluj
    # konzistentní složení (počty + důvody s číslem řádku)
    assert any("řádek 3" in e for e in info["errors"])
    assert any("řádek 4" in e for e in info["errors"])
