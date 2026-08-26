# USB přenos – krok za krokem (kabel, MTP)

## Telefon → PC (příprava)
1. Telefon: Posouvač textu → Knihovna → menu (tři tečky) → **Export CSV pro Generátor**. Vznikne `metadata_pisni.csv` v `Download`.
2. Připoj kabel USB k PC. Na telefonu v notifikaci zvol **Přenos souborů / File Transfer (MTP)** (případně zapni **USB ladění** v Možnosti pro vývojáře – není nutné pro MTP, ale pomůže při potížích).
3. V Průzkumníku otevři `Tento počítač → Název telefonu → Interní úložiště → Download`.
4. Zkopíruj `metadata_pisni.csv` na PC, např. do `C:\Honza\Texty-pisni\`.
5. Zkopíruj celou složku s `.txt` (např. `C:\Honza\Texty-pisni\` nebo složku z telefonu `Music/` pokud tam máš texty) – stačí mít jednu zdrojovou složku se všemi `.txt`.

## PC editor
1. Spusť `C:\Honza\Projekty\Posouvac_textu_PC_editor\main.py` (`py main.py`).
2. **Otevřít složku s písněmi** → vyber zdrojovou složku `.txt`.
3. **Načíst knihovnu CSV** → vyber `metadata_pisni.csv` (doplní délky/tempa).
4. Vlevo vyber píseň → v **Detail** uprav interpreta/název/délku (`m:ss`) / tempo (30–300) → **Uložit změny**.
5. **Upravit zarážky** → vyber řádek → **Přidat zarážku** (spin Takty 1–16, výchozí 2) → **Uložit**. Lze více zarážek na píseň.
6. Přidej písně do **Setlist** (Enter / tlačítko ← Přidat), změň pořadí **Výše/Níže** nebo přetažením, **Upravit** tempo v setlistu.
7. Nastav **Výstupní složku** (např. `C:\Honza\Texty-pisni_upraveno`). Zaškrtněte **Včetně textů**.
8. **Uložit vše** → zapíše upravené `.txt` (záloha `.bak`) s direktivami `{stop:N}` před řádky a `setlist_*.json` v3 s `stopMarks` + `setlist_*.html`.

## PC → Telefon (import)
1. V Průzkumníku zkopíruj obsah výstupní složky (`*.txt` + `*.json`) do `Tento počítač → Telefon → Download → Posouvac\` (složku vytvoř pokud neexistuje).
2. Odpoj kabel.
3. Telefon: **Knihovna → Vybrat složku / Vybrat soubory** → vyber zkopírované `.txt` z `Download/Posouvac` (nebo přes správce souborů přesuň do viditelné složky a pak import). Potvrď aktualizaci.
4. Telefon: **Setlisty → Import → Ze souboru** → vyber `setlist_*.json`. Aplikace přiřadí písně, nabídne doplnění chybějících časů/diakritiky, a **zapíše zarážky do DB** (`{stop:N}` z textu i `stopMarks` pole).
5. Otevři setlist → Spustit → zkontroluj pauzy (vibrace + hláška „Pauza na N taktů“).

## Tipy
- Direktiva `{stop:N}` je samostatný řádek před cílovým řádkem. `N` 1–16, doporučeno 2 pro rychlou, 4 pro pomalou.
- Pokud používáš „Balíček včetně textů“, nemusíš kopírovat `.txt` zvlášť – JSON už nese `content`.
- Zálohy `.bak` najdeš vedle původních `.txt` ve výstupní složce.
- QR a schránka fungují stejně, ale přes kabel je nejspolehlivější pro větší setlisty (>1500 znaků limit QR).
