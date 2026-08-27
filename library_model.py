"""
Knihovna pisni na disku – nacteni slozky s .txt, sprava modelu pro PC editor.
Kazda pisen: {artist,title,filePath,content,duration,tempo,stopMarks}
"""
import os
import re
import pathlib

import playlist_backend
import song_parser
import diacritic as diacritic_mod


def _read_text_file(path: str) -> str:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                return f.read()
        except Exception:
            with open(path, 'r', encoding='latin-1') as f:
                return f.read()
    except Exception:
        return ""


def _parse_filename_artist_title(path: str) -> tuple[str, str]:
    base = pathlib.Path(path).stem.strip()
    m = re.search(r'\s+[-–—]\s+', base)
    if m is None:
        all_m = list(re.finditer(r'\s*[-–—]\s*', base))
        if all_m:
            m = all_m[-1]
    if m is None:
        return "", base
    artist = base[:m.start()].strip()
    title = base[m.end():].strip()
    if not artist or not title:
        return "", base
    return artist, title


def load_library_from_folder(folder: str) -> tuple[bool, list[dict] | str]:
    if not folder or not os.path.isdir(folder):
        return False, f"Slozka neexistuje: {folder}"
    files = []
    for root, _, filenames in os.walk(folder):
        for fn in filenames:
            if fn.lower().endswith('.txt'):
                files.append(os.path.join(root, fn))
    entries: list[dict] = []
    for fp in sorted(files):
        content = _read_text_file(fp)
        a_fn, t_fn = _parse_filename_artist_title(fp)
        title = t_fn
        artist = a_fn
        if not artist:
            artist = "Neznamy interpret" if not artist else artist
        stop_marks = playlist_backend.extract_stop_marks_from_content(content)
        entries.append({
            "artist": artist,
            "title": title,
            "filePath": fp,
            "content": content,
            "duration": None,
            "tempo": None,
            "stopMarks": stop_marks,
        })
    return True, entries


def enrich_with_csv(entries: list[dict], csv_entries: list[dict]) -> None:
    """Doplní duration podle CSV (match artist+title). Modifikuje in-place."""
    def norm(s): return re.sub(r'\s+', ' ', (s or "").strip().lower())
    csv_by_title = {}
    csv_by_full = {}
    for c in csv_entries:
        t = norm(c.get("title"))
        a = norm(c.get("artist"))
        full = f"{a}|{t}"
        if t and t not in csv_by_title:
            csv_by_title[t] = c
        if full and full not in csv_by_full:
            csv_by_full[full] = c
    for e in entries:
        t = norm(e.get("title"))
        a = norm(e.get("artist"))
        full = f"{a}|{t}"
        src = csv_by_full.get(full) or csv_by_title.get(t)
        if src and src.get("duration"):
            if not e.get("duration"):
                e["duration"] = src["duration"]
            if src.get("tempo") and not e.get("tempo"):
                e["tempo"] = src.get("tempo")


def enrich_imported_songs(imported: list[dict], library: list[dict]) -> tuple[list[dict], list[dict]]:
    """Obohatí importované písně z Generatoru o metadata z knihovny. Vrací (enriched, missing)."""
    def norm(s): return re.sub(r'\s+', ' ', (s or "").strip().lower())
    
    # map knihovny
    lib_map = {}
    for entry in library:
        t = norm(entry.get("title"))
        a = norm(entry.get("artist"))
        lib_map[f"{a}|{t}"] = entry
        lib_map[t] = entry # fallback

    enriched = []
    missing = []
    for imp in imported:
        t = norm(imp.get("title"))
        a = norm(imp.get("artist"))
        key = f"{a}|{t}"
        match = lib_map.get(key) or lib_map.get(t)
        
        if match:
            # Obohatit
            enriched.append({
                "title": imp.get("title"),
                "artist": imp.get("artist"),
                "duration": imp.get("duration") or match.get("duration"),
                "tempo": imp.get("tempo") or match.get("tempo"),
                "content": imp.get("content") or match.get("content"),
                "stopMarks": imp.get("stopMarks") or match.get("stopMarks") or [],
                "filePath": match.get("filePath")
            })
        else:
            missing.append(imp)
            # Přidat i tak, ale bez filePath/stopMarks
            enriched.append(imp)
            
    return enriched, missing


def save_entry_to_file(entry: dict) -> tuple[bool, str]:
    fp = entry.get("filePath")
    if not fp:
        return False, "Chybi filePath"
    content = entry.get("content") or ""
    marks = entry.get("stopMarks") or []
    new_content = playlist_backend.file_content_with_stop_marks_applied(content, marks)
    try:
        old = _read_text_file(fp)
        if old == new_content:
            return True, fp
        bak = fp + ".bak"
        if not os.path.exists(bak):
            try:
                with open(bak, 'w', encoding='utf-8') as f:
                    f.write(old)
            except Exception:
                pass
        with open(fp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        entry["content"] = new_content
        return True, fp
    except Exception as e:
        return False, str(e)


# --- Diakritika helpers (port database.dart) ---

def find_diacritic_repairs(entries: list[dict], dmap: dict) -> tuple[list[dict], list[dict]]:
    """Deleguje na diacritic.find_diacritic_repairs."""
    return diacritic_mod.find_diacritic_repairs(entries, dmap)


def apply_diacritic_repairs(entries: list[dict], candidates: list[dict], rename_files: bool = True) -> dict:
    """
    Aplikuje kandidáty na entries a volitelně přejmenuje soubory.
    candidates: z find_diacritic_repairs (obsahuje index, newArtist/newTitle)
    Vrací {dbUpdated, filesRenamed, filesFailed, failedPaths}
    """
    db_updated = 0
    renamed = 0
    failed = 0
    failed_paths: list[str] = []
    # mapa index->candidate
    cand_by_idx = {c["index"]: c for c in candidates}
    for idx, cand in cand_by_idx.items():
        if idx < 0 or idx >= len(entries):
            continue
        e = entries[idx]
        new_a = cand.get("newArtist") or e.get("artist")
        new_t = cand.get("newTitle") or e.get("title")
        if new_a == e.get("artist") and new_t == e.get("title"):
            continue
        e["artist"] = new_a
        e["title"] = new_t
        db_updated += 1

    if not rename_files:
        return {"dbUpdated": db_updated, "filesRenamed": 0, "filesFailed": 0, "failedPaths": []}

    for idx, cand in cand_by_idx.items():
        if idx < 0 or idx >= len(entries):
            continue
        e = entries[idx]
        old_path = cand.get("filePath") or e.get("filePath")
        if not old_path or not os.path.exists(old_path):
            continue
        # pokud se název nezměnil, přeskočit (už ošetřeno)
        if cand.get("newArtist") == cand.get("currentArtist") and cand.get("newTitle") == cand.get("currentTitle"):
            continue
        try:
            dir_name = os.path.dirname(old_path)
            safe_a = re.sub(r'[\\/:*?"<>|]', '_', e.get("artist") or "").strip()
            safe_t = re.sub(r'[\\/:*?"<>|]', '_', e.get("title") or "").strip()
            if not safe_t:
                continue
            new_name = f"{safe_a} - {safe_t}.txt" if safe_a else f"{safe_t}.txt"
            new_path = os.path.join(dir_name, new_name)
            # MAX_PATH ochrana ~240
            if len(new_path) > 240:
                ext = ".txt"
                max_base = 240 - len(dir_name) - len(ext) - 1
                if max_base > 10:
                    new_name = new_name[:max_base] + ext
                    new_path = os.path.join(dir_name, new_name)
            cnt = 1
            while new_path != old_path and os.path.exists(new_path):
                base = new_name.replace(".txt", "")
                new_path = os.path.join(dir_name, f"{base}_{cnt}.txt")
                cnt += 1
            if new_path == old_path:
                continue
            os.rename(old_path, new_path)
            # odstranit starý bak pokud existuje? ponechat
            e["filePath"] = new_path
            renamed += 1
        except Exception:
            failed += 1
            failed_paths.append(old_path)
    return {"dbUpdated": db_updated, "filesRenamed": renamed, "filesFailed": failed, "failedPaths": failed_paths}


def export_diacritic_preview_csv(candidates: list[dict], unrepaired: list[dict], out_path: str) -> tuple[bool, str]:
    """Zapíše náhled oprav do CSV pro kontrolu. Vrací (ok, path/msg)."""
    try:
        import csv as _csv
        with open(out_path, 'w', encoding='utf-8-sig', newline='') as f:
            w = _csv.writer(f, delimiter=',', quotechar='"', quoting=_csv.QUOTE_MINIMAL)
            w.writerow(["stav", "soubor", "puvodni_interpret", "puvodni_nazev", "novy_interpret", "novy_nazev", "duvod"])
            for c in candidates:
                w.writerow(["k_oprave", c.get("filePath") or "", c.get("currentArtist") or "", c.get("currentTitle") or "", c.get("newArtist") or "", c.get("newTitle") or "", ""])
            for u in unrepaired:
                w.writerow(["bez_navrhu", u.get("filePath") or "", u.get("artist") or "", u.get("title") or "", "", "", u.get("reason") or ""])
        return True, out_path
    except Exception as e:
        return False, str(e)


def create_file_for_new_entry(base_dir: str, entry: dict) -> str:
    safe_artist = re.sub(r'[\\/:*?"<>|]', '_', entry.get("artist") or "").strip()
    safe_title = re.sub(r'[\\/:*?"<>|]', '_', entry.get("title") or "").strip()
    if not safe_title:
        safe_title = "Nova_pisen"
    fname = f"{safe_artist} - {safe_title}.txt" if safe_artist else f"{safe_title}.txt"
    fp = os.path.join(base_dir, fname)
    cnt = 1
    while os.path.exists(fp):
        base = fname.replace(".txt", "")
        fp = os.path.join(base_dir, f"{base}_{cnt}.txt")
        cnt += 1
    content = entry.get("content") or f"{entry.get('title')}\n\nText pisne...\n"
    marks = entry.get("stopMarks") or []
    if marks:
        content = playlist_backend.file_content_with_stop_marks_applied(content, marks)
    os.makedirs(base_dir, exist_ok=True)
    with open(fp, 'w', encoding='utf-8') as f:
        f.write(content)
    entry["filePath"] = fp
    entry["content"] = content
    return fp
