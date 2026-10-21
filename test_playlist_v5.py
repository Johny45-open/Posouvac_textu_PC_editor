"""
Regresní testy identity a JSON kontraktu v5 (etapa A1.1).

Ověřovaná pravidla schválení A1.1:
  1. playlistUid je stabilní při opakovaném uložení a exportu.
  2. occurrenceId je stabilní po přesunu skladby a změně tempa.
  3. Dvě stejné skladby v jednom setlistu mají rozdílná occurrenceId.
  4. Kopie setlistu dostane nové playlistUid i nová occurrenceId.
  5. scrollSpeed, introDuration a fontSize se neztratí.
  6. Neznámá pole na úrovni setlistu i položky se zachovají; kanonická
     pole mají přednost před extras.
  7. Staré v3/v4 soubory se načtou bez ztráty údajů a ID se doplní jednou.
  8. Round-trip načtení → export nemění nepodporovaná pole.
  9. Zarážky a čisté indexy lineIndex (etapa B1) zůstávají beze změny.

Testy volají přímo produkční funkce:
  - playlist_backend.build_playlist_data / save_playlist_to / load_playlist
  - playlist_backend.ensure_song_ids / clone_setlist / legacy_export_warnings
  - playlist_backend.get_qr_payload / extract_stop_marks_from_content
  - library_model.enrich_imported_songs
"""
import json
import uuid

import playlist_backend as pb
import library_model


def _song(title="Píseň", artist="Interpret", **kw):
    e = {
        "title": title,
        "artist": artist,
        "duration": 210,
        "tempo": 120,
        "content": "A\nB\nC",
        "stopMarks": [{"lineText": "B", "lineIndex": 1, "bars": 2}],
    }
    e.update(kw)
    return e


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except Exception:
        return False


# --- 1. Stabilita playlistUid ---

def test_playlist_uid_stabilni_pri_opakovane_ulozeni_a_exportu(tmp_path):
    uid = pb.new_playlist_uid()
    assert _is_uuid(uid)
    songs = pb.ensure_song_ids([_song(), _song("Druhá")])
    ids_before = [s["occurrenceId"] for s in songs]

    f1 = tmp_path / "a.json"
    ok, _ = pb.save_playlist_to(str(f1), "Koncert", songs, playlist_uid=uid)
    assert ok

    # načtení zpět – identita i ID položek přežily
    ok, data = pb.load_playlist(str(f1))
    assert ok
    assert data["playlistUid"] == uid
    assert data["version"] == 5
    assert [s["occurrenceId"] for s in data["_normSongs"]] == ids_before

    # druhý export ze stejného stavu (jiný exportedAt, stejná identita)
    f2 = tmp_path / "b.json"
    ok, _ = pb.save_playlist_to(str(f2), "Koncert", data["_normSongs"],
                                playlist_uid=data["playlistUid"],
                                top_extras=data.get("_extras"))
    assert ok
    data2 = json.loads(f2.read_text(encoding="utf-8"))
    assert data2["playlistUid"] == uid
    assert [s["occurrenceId"] for s in data2["songs"]] == ids_before
    # UID se neodvozuje od názvu ani pořadí – je neprůhledné
    assert data2["playlistUid"] != data2["name"]


def test_id_se_negeneruji_pri_exportu():
    # pravidlo: ID vzniká při vytvoření výskytu, NE při každém exportu
    songs = [{"title": "A", "artist": "B"}]  # bez occurrenceId
    data = pb.build_playlist_data("K", songs, playlist_uid=pb.new_playlist_uid())
    assert "occurrenceId" not in data["songs"][0]


# --- 2. Stabilita occurrenceId po přesunu a změně tempa ---

def test_occurrence_id_stabilni_pri_presunu_a_zmene_tempa():
    songs = pb.ensure_song_ids([_song("První"), _song("Druhá")])
    id1, id2 = (s["occurrenceId"] for s in songs)
    first = songs[0]

    songs.append(songs.pop(0))   # přesun na konec – ID se nesmí změnit
    first["tempo"] = 90          # změna tempa – ID se nesmí změnit

    data = pb.build_playlist_data("Koncert", songs, playlist_uid=pb.new_playlist_uid())
    ids_after = [s["occurrenceId"] for s in data["songs"]]
    assert ids_after == [id2, id1]
    assert data["songs"][1]["tempo"] == 90.0


# --- 3. Dvě stejné skladby, odlišná ID ---

def test_dve_stejne_skladby_maji_odlisna_id():
    songs = pb.ensure_song_ids([_song(), _song()])  # shodné kromě ID
    ids = [s["occurrenceId"] for s in songs]
    assert len(set(ids)) == 2

    # po exportu zůstávají odlišné a shodné se vstupem
    data = pb.build_playlist_data("Koncert", songs, playlist_uid=pb.new_playlist_uid())
    exp = [s["occurrenceId"] for s in data["songs"]]
    assert len(set(exp)) == 2
    assert set(exp) == set(ids)


def test_ensure_song_ids_doplni_chybejici_a_nahradi_kolizi():
    a = {"title": "A", "artist": "B"}
    b = {"title": "A", "artist": "B", "occurrenceId": "pevne-id"}
    c = {"title": "A", "artist": "B", "occurrenceId": "pevne-id"}  # kolize
    out = pb.ensure_song_ids([a, b, c])
    ids = [x["occurrenceId"] for x in out]
    assert len(set(ids)) == 3
    # chybějící ID se doplní UUID; existující platné ID se nepřepočítává
    # (může pocházet z cizího souboru – nemusí být UUID, jen nesmí kolidovat)
    assert _is_uuid(a["occurrenceId"])
    assert out[1]["occurrenceId"] == "pevne-id"
    assert _is_uuid(c["occurrenceId"])
    assert c["occurrenceId"] != "pevne-id"
    # řetězce (ne-dict) se nechají být
    assert pb.ensure_song_ids(["Interpret - Název"])[0] == "Interpret - Název"


# --- 4. Kopie setlistu s novými ID ---

def test_kopie_setlistu_ma_nova_id():
    uid1 = pb.new_playlist_uid()
    songs = pb.ensure_song_ids([_song(), _song()])

    uid2, copy = pb.clone_setlist(songs)
    assert uid2 != uid1
    assert _is_uuid(uid2)
    # výskyty v kopii nemají shodná ID s originálem
    assert set(s["occurrenceId"] for s in copy).isdisjoint(
        s["occurrenceId"] for s in songs)
    # obsah zůstává shodný
    assert copy[0]["title"] == songs[0]["title"]
    assert copy[0]["stopMarks"] == songs[0]["stopMarks"]
    # hluboká kopie: zásah do kopie neovlivní originál
    copy[0]["stopMarks"][0]["bars"] = 4
    assert songs[0]["stopMarks"][0]["bars"] == 2


# --- 5. Zachování scrollSpeed / introDuration / fontSize ---

def test_zachovani_scrollspeed_introduration_fontsize():
    songs = [_song(scrollSpeed=1.25, fontSize=30, introDuration=4.5)]
    data = pb.build_playlist_data("Koncert", songs, playlist_uid=pb.new_playlist_uid())
    e = data["songs"][0]
    assert e["scrollSpeed"] == 1.25
    assert e["fontSize"] == 30
    assert e["introDuration"] == 4.5

    # číselný řetězec se převede, NEzahodí se
    s2 = [{"title": "A", "artist": "B", "scrollSpeed": "1,5", "introDuration": "6"}]
    e2 = pb.build_playlist_data("Koncert", s2)["songs"][0]
    assert e2["scrollSpeed"] == 1.5
    assert e2["introDuration"] == 6.0

    # nečíselná hodnota se zachová doslova (nesmí se ztratit)
    s3 = [{"title": "A", "artist": "B", "fontSize": "extra"}]
    assert pb.build_playlist_data("Koncert", s3)["songs"][0]["fontSize"] == "extra"


# --- 6. Neznámá pole (setlist i položka) ---

def test_neznama_pole_setlistu_i_polozky():
    songs = [_song(futureField={"x": 1}, stopMarksOverride=True)]
    top = {"futureTop": [1, 2], "generatedBy": "test"}
    data = pb.build_playlist_data("Koncert", songs,
                                  playlist_uid=pb.new_playlist_uid(),
                                  top_extras=top)
    assert data["futureTop"] == [1, 2]
    assert data["generatedBy"] == "test"
    e = data["songs"][0]
    assert e["futureField"] == {"x": 1}
    assert e["stopMarksOverride"] is True

    # kanonická pole mají PŘEDNOST před extras (žádné duplicitní klíče);
    # extras se při exportu rozplošťují na úroveň položky
    s2 = [{"title": "A", "artist": "B", "extras": {"title": "JINÝ", "future": "x"}}]
    e2 = pb.build_playlist_data("Koncert", s2)["songs"][0]
    assert e2["title"] == "A"
    assert "extras" not in e2
    assert e2["future"] == "x"

    # totéž pro horní úroveň
    data2 = pb.build_playlist_data("Koncert", s2, top_extras={"name": "JINÝ", "foo": 1})
    assert data2["name"] == "Koncert"
    assert data2["foo"] == 1


# --- 7. Staré v3/v4 soubory ---

def _write_json(tmp_path, name, payload):
    f = tmp_path / name
    f.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(f)


def test_nacteni_stareho_v3_souboru_bez_ztraty(tmp_path):
    old = {
        "type": "playlist",
        "version": 3,
        "name": "Starý setlist",
        "exportedAt": "2025-01-01T00:00:00+00:00",
        "totalDuration": 420,
        "unknownCount": 0,
        "songs": [
            {"title": "První", "artist": "Interpret", "duration": 210, "tempo": 120,
             "stopMarks": [{"lineText": "B", "lineIndex": 1, "bars": 2}]},
            {"title": "První", "artist": "Interpret", "duration": 210, "tempo": 95},
        ],
    }
    ok, data = pb.load_playlist(_write_json(tmp_path, "old_v3.json", old))
    assert ok
    norm = data["_normSongs"]
    assert len(norm) == 2
    # ID doplněna (v5) a validní
    ids = [s["occurrenceId"] for s in norm]
    assert all(_is_uuid(i) for i in ids) and len(set(ids)) == 2
    # žádný původní údaj se neztratil
    assert norm[0]["title"] == "První"
    assert norm[0]["artist"] == "Interpret"
    assert norm[0]["duration"] == 210
    assert norm[0]["tempo"] == 120
    assert norm[0]["stopMarks"] == [{"lineText": "B", "lineIndex": 1, "bars": 2}]
    assert norm[1]["tempo"] == 95
    # uložení → načtení: ID se doplnila jen jednou a přežila
    f2 = tmp_path / "resaved.json"
    ok, _ = pb.save_playlist_to(str(f2), "Starý setlist", norm,
                                playlist_uid=pb.new_playlist_uid())
    assert ok
    ok, data2 = pb.load_playlist(str(f2))
    assert ok
    assert [s["occurrenceId"] for s in data2["_normSongs"]] == ids
    assert data2["version"] == 5   # nový export je v5
    # starý soubor samotný zůstal nedotčen (v3) – přepisuje se jen nový
    assert json.loads((tmp_path / "old_v3.json").read_text(encoding="utf-8"))["version"] == 3
    out = json.loads(f2.read_text(encoding="utf-8"))
    assert out["version"] == 5


def test_nacteni_stareho_v4_souboru_s_telefonnimi_polimi(tmp_path):
    old = {
        "type": "playlist",
        "version": 4,
        "name": "Telefonní",
        "songs": [
            {"title": "Píseň", "artist": "Interpret", "duration": 180, "tempo": 100,
             "scrollSpeed": 1.5, "fontSize": 30, "introDuration": 5,
             "content": "A\nB", "stopMarks": [{"lineText": "B", "lineIndex": 1, "bars": 4}]},
        ],
        "neznámýTopLevel": {"a": 1},
    }
    ok, data = pb.load_playlist(_write_json(tmp_path, "old_v4.json", old))
    assert ok
    norm = data["_normSongs"][0]
    assert _is_uuid(norm["occurrenceId"])
    assert norm["scrollSpeed"] == 1.5
    assert norm["fontSize"] == 30
    assert norm["introDuration"] == 5
    assert norm["content"] == "A\nB"
    assert norm["stopMarks"] == [{"lineText": "B", "lineIndex": 1, "bars": 4}]
    # neznámé pole horní úrovně se zachovalo pro zpětný export
    assert data["_extras"] == {"neznámýTopLevel": {"a": 1}}

    out = pb.build_playlist_data("Telefonní", data["_normSongs"],
                                 playlist_uid=pb.new_playlist_uid(),
                                 top_extras=data.get("_extras"))
    assert out["version"] == 5
    assert out["neznámýTopLevel"] == {"a": 1}
    assert out["songs"][0]["scrollSpeed"] == 1.5
    assert out["songs"][0]["fontSize"] == 30
    assert out["songs"][0]["introDuration"] == 5


# --- 8. Round-trip bez změny nepodporovaných polí ---

def test_round_trip_nepodporovanych_poli(tmp_path):
    uid = pb.new_playlist_uid()
    songs = pb.ensure_song_ids([
        _song(scrollSpeed=1.2, introDuration=3, fontSize=32,
              stopMarksOverride=True, futureField="drž se"),
        _song("Druhá", futureField=42),
    ])
    top = {"futureTop": "hore"}
    f = tmp_path / "rt.json"
    ok, _ = pb.save_playlist_to(str(f), "Koncert", songs, playlist_uid=uid,
                                top_extras=top)
    assert ok

    ok, loaded = pb.load_playlist(str(f))
    assert ok
    rebuilt = pb.build_playlist_data("Koncert", loaded["_normSongs"],
                                     playlist_uid=loaded["playlistUid"],
                                     top_extras=loaded.get("_extras"))
    original = pb.build_playlist_data("Koncert", songs, playlist_uid=uid,
                                      top_extras=top)

    assert rebuilt["songs"] == original["songs"]     # žádná změna polí
    assert rebuilt["playlistUid"] == original["playlistUid"]
    assert rebuilt["futureTop"] == "hore"
    # filePath je interní – do JSONu se neexportuje (dokumentované)
    assert "filePath" not in rebuilt["songs"][0]


# --- 9. Zarážky a čisté indexy (B1) ---

def test_zarazky_a_ciste_indexy_zustavaji(tmp_path):
    content = "A\n{stop:2}\nB\nC"
    marks = pb.extract_stop_marks_from_content(content)
    assert marks == [{"lineText": "B", "lineIndex": 1, "bars": 2}]  # čistý index

    uid = pb.new_playlist_uid()
    songs = pb.ensure_song_ids([_song(content=content, stopMarks=marks)])
    data = pb.build_playlist_data("Koncert", songs, playlist_uid=uid)
    exported_marks = data["songs"][0]["stopMarks"]
    assert exported_marks == marks                     # export je nemění
    # aplikace po round-tripu je idempotentní (B1)
    applied = pb.file_content_with_stop_marks_applied(content, exported_marks)
    assert applied == content

    # QR payload obsahuje ID, nastavení i zarážky – nevynechávají se
    payload, err = pb.get_qr_payload("Koncert", songs, playlist_uid=uid)
    assert err is None
    pl = json.loads(payload)
    assert pl["playlistUid"] == uid
    assert pl["songs"][0]["occurrenceId"] == songs[0]["occurrenceId"]
    assert pl["songs"][0]["stopMarks"] == exported_marks
    assert "content" not in pl["songs"][0]             # jediné dokumentované vynechání


def test_qr_prilis_velky_zobrazuje_chybu_s_json_nebo_usb():
    songs = pb.ensure_song_ids([_song(f"Píseň {i}", "Interpret",
                                      content="x" * 50) for i in range(40)])
    payload, err = pb.get_qr_payload("Velký", songs, playlist_uid=pb.new_playlist_uid())
    assert payload is None
    assert err and "JSON" in err and "USB" in err


# --- Varování pro starší aplikace ---

def test_varovani_pri_exportu_opakovanych_skladeb():
    # bez duplicit žádné varování
    assert pb.legacy_export_warnings([_song("A"), _song("B")]) == []

    # duplicity bez odlišného nastavení → obecné varování
    w = pb.legacy_export_warnings([_song(), _song()])
    assert len(w) == 1 and "2×" in w[0] and "odlišným nastavením" not in w[0]

    # duplicity s odlišným tempem → varování o ztrátě nastavení
    w2 = pb.legacy_export_warnings([_song(), _song(tempo=95)])
    assert len(w2) == 1 and "odlišným nastavením" in w2[0]

    # odlišné zarážky dvou výskytů → také varování
    w3 = pb.legacy_export_warnings(
        [_song(), _song(stopMarks=[{"lineText": "C", "lineIndex": 2, "bars": 4}])])
    assert len(w3) == 1 and "odlišným nastavením" in w3[0]


# --- Obohacení importu nesmí ztratit ID ani nastavení ---

def test_enrich_imported_songs_zachovava_id_a_nastaveni():
    library = [{"title": "Píseň", "artist": "Interpret",
                "filePath": "C:/lib/pisen.txt", "content": "TEXT",
                "duration": 200, "tempo": 110, "stopMarks": []}]
    imported = [{"title": "Píseň", "artist": "Interpret",
                 "occurrenceId": "abc-123", "scrollSpeed": 1.2,
                 "introDuration": 3, "fontSize": 33, "futureField": "x",
                 "extras": {"keep": 1, "title": "NESMÍ PŘEPSAT"},
                 "duration": 210}]
    enriched, missing = library_model.enrich_imported_songs(imported, library)
    assert missing == []
    e = enriched[0]
    assert e["occurrenceId"] == "abc-123"
    assert e["scrollSpeed"] == 1.2
    assert e["introDuration"] == 3
    assert e["fontSize"] == 33
    assert e["futureField"] == "x"
    assert e["extras"] == {"keep": 1}   # kanonické pole z extras vypadlo
    assert e["filePath"] == "C:/lib/pisen.txt"
    assert e["duration"] == 210         # hodnota z importu má přednost
    assert e["content"] == "TEXT"       # doplněno z knihovny
