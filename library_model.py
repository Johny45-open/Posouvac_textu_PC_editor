"""
Knihovna pisni na disku – nacteni slozky s .txt, sprava modelu pro PC editor.
Kazda pisen: {artist,title,filePath,content,duration,tempo,stopMarks}
"""
import os
import re
import pathlib

import playlist_backend
import song_parser


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
