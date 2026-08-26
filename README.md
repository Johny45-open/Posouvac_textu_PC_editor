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

## Přístupnost (NVDA)
Všechny ovládací prvky mají `setAccessibleName/Description`, `QLabel.setBuddy`, `setTabOrder`. Dialogy po otevření fokusují první pole. Stavové hlášky přes `statusBar()`. Klávesy: `Alt+P přidat`, `Alt+O odebrat`, `Alt+T tempo`, `Alt+D délka`, `F6` sekce, `Ctrl+S uložit`.

## Formát JSON v3
Viz `playlist_backend.py:build_playlist_data` – shodný s `lib/song_export.dart:99` + volitelné `stopMarks` na každé písni.

## Test
```bat
python -m py_compile main.py song_parser.py playlist_backend.py stop_marks_editor.py library_model.py
python -m pytest -q
```
