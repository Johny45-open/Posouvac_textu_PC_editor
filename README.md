# Posouvač textu – PC Editor

Přístupný PC editor pro přípravu zarážek, tempa, délky a setlistů doma na velkém PC s NVDA.
Na koncertě pak jen spustíte setlist v telefonu.

## Motivace
Uživatel chce na PC s NVDA v klidu připravit celý setlist (pořadí, tempo/BPM, délka, **zarážky/pauzy** na řádek) a v telefonu na pódiu jen hrát – bez ťukání na malém displeji.

## Co umí
- **Knihovna**: načíst složku s `.txt` a/nebo `metadata_pisni.csv` exportovaný z telefonu (`Knihovna → Export CSV`).
- **Detail písně**: náhled řádků, přidat/odebrat zarážku `{stop:N}` před libovolný řádek, nastavit tempo (30–300 BPM) a délku (m:ss).
- **Setlist**: přidat písně, měnit pořadí (šipky / drag&drop), hromadný souhrn času, uložit jako JSON v3.
- **Dvojí zápis zarážek** (pro maximální kompatibilitu):
  1. **Direktiva v textu** `{stop:2}` / `{pause:4}` – samostatný řádek před cílovým řádkem. Telefon ji přečte i bez změny appky (`lib/chord_pro_parser.dart:40`).
  2. **Pole `stopMarks` v JSON** `[{lineIndex, lineText, bars}]` – DB kotva (`lib/database.dart:StopMarks`). Telefon ji naimportuje do DB (`addStopMarkAtLine`).
  Sdílení „s texty“ přenese obojí, takže stačí jeden soubor.

## USB přenos (MTP)
1. **Telefon → PC**: v telefonu `Knihovna → Export CSV` → soubor `metadata_pisni.csv` v `Download`. Připojit kabel USB, v telefonu `Přenos souborů`, v Průzkumníku `Tento počítač\Telefon\Download\metadata_pisni.csv` zkopírovat na PC spolu se složkou `.txt` (např. `C:\Honza\Texty-pisni`).
2. **PC → Telefon**: v editoru `Uložit vše` → vybrat výstupní složku (např. `C:\Honza\Texty-pisni_upraveno`) – zapíše upravené `.txt` (záloha `.bak`) a `setlist_*.json` (+ volitelně `.html`). Zkopírovat do `Telefon\Download\Posouvac\`. V telefonu `Knihovna → Vybrat soubory` (nové `.txt`) a `Setlisty → Import → Ze souboru` (`.json`).

## Spuštění
```bat
pip install -r requirements.txt
python main.py
```

## Přístupnost (NVDA) + klávesové zkratky (zapamatovatelné pro neznalé)

Všechny ovládací prvky mají `setAccessibleName/Description` (včetně hlášení zkratky), `QLabel.setBuddy`, `setTabOrder`, `QMenuBar` pro objevitelnost a `QShortcut` s `WindowShortcut`. Dialogy po otevření fokusují první pole. Stavové hlášky přes `statusBar()` + `tts.speak()`. **Podrž `Alt` – uvidíš podtržená písmena. `F1` kdykoliv tahák.**

Heslo pro paměť: **S-G-K-V načti, F2-F3-F4 uprav, Ctrl+J/A ulož** + v seznamech `Enter/Delete/↑↓` jako v Průzkumníku.

| Akce | Zkratka | Alias | Kde | Mnemonika |
|---|---|---|---|---|
| Otevřít složku | `Ctrl+O` | `Alt+S` | Soubor | **S**ložka – `F2` knihovna |
| Import z Generátoru | `Ctrl+G` | `Alt+G` | Soubor | **G**enerátor |
| Načíst CSV | `Ctrl+Shift+C` | `Alt+C` | Knihovna | **C**SV |
| Výstupní složka | `Ctrl+Shift+V` | `Alt+V` | Soubor | **V**ýstup |
| Načíst slovník | `Ctrl+K` | `Alt+K` | Nástroje | slovní**K** |
| Opravit diakritiku | `Ctrl+D` | `Alt+D` | Nástroje | **D**iakritika |
| Hledat / filtr | `Ctrl+F` | `F6` | Knihovna | **F**iltr – `F2` pak `Ctrl+F` |
| Fokus Knihovna/Detail/Setlist | `F2` / `F3` / `F4` | — | Zobrazit | 1-2-3 krok |
| Uložit detail | `Ctrl+S` | `Ctrl+U` / `Alt+U` | Detail | **U**ložit – `F3` |
| Zarážky | `Ctrl+E` | `Alt+Z` | Detail | **E**dit / **Z**arážky – `F3` |
| Přidat do setlistu | `Enter` | dvojklik | Knihovna `F2` | — |
| Odebrat ze setlistu | `Delete` | — | Setlist `F4` | — |
| Setlist výše/níže | `Ctrl+↑/↓` | `Alt+↑/↓` | Setlist `F4` | — |
| Uložit JSON | `Ctrl+J` | `Alt+J` | Export | **J**SON |
| Uložit vše | `Ctrl+Shift+S` | `Alt+A` | Export | **A** vše |
| Export HTML/Word | `Ctrl+H/W` | `Alt+H/W` | Export | **H/W** |
| Zobrazit QR | `Ctrl+Shift+Q` | `Alt+Q` | Export | **Q**R (Ctrl+Q = ukončit) |
| Kopírovat do schránky | `Ctrl+Alt+C` | — | Export | schránka (Ctrl+Shift+C = CSV) |
| Zkouška hlasu | `Ctrl+T` | — | Nástroje | **T**est |
| Nápověda tahák | `F1` | `Ctrl+/` | Nápověda | **F1** = pomoc |
| Zarážky: přidat/odebrat/takty | `Ctrl+E` / `Delete` / `1-9` | `Alt+P/O` | Dialog zarážek | **E/O** + číslo |

Menu: `Soubor | Knihovna | Zobrazit (F2-F4) | Detail | Setlist | Export | Nástroje | Nápověda (F1)`. Tooltip + `AccessibleDescription` u každého tlačítka hlásí zkratku i alias.

## Formát JSON v3
Viz `playlist_backend.py:build_playlist_data` – shodný s `lib/song_export.dart:99` + volitelné `stopMarks` na každé písni.

## Test
```bat
python -m py_compile main.py song_parser.py playlist_backend.py stop_marks_editor.py library_model.py
python -m pytest -q
```
