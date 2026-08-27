import os
import sys
import json
import html
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QMessageBox, QFileDialog, QDialog,
    QDialogButtonBox, QFormLayout, QSpinBox, QGroupBox, QSplitter, QTabWidget,
    QTextEdit, QCheckBox
)
from PyQt6.QtCore import Qt, QUrl, QStringListModel, QSettings
from PyQt6.QtGui import QDesktopServices

import playlist_backend
import library_model
import song_parser
import diacritic
import tts
from stop_marks_editor import StopMarksDialog

try:
    import qrcode
    HAS_QRCODE = True
except Exception:
    HAS_QRCODE = False


class EditSetlistSongDialog(QDialog):
    def __init__(self, song_dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Upravit píseň v setlistu")
        self.song = dict(song_dict)
        layout = QFormLayout(self)

        self.song_label = QLabel(f"{song_dict.get('artist')} – {song_dict.get('title')}")
        self.song_label.setAccessibleName("Píseň")
        layout.addRow("Píseň:", self.song_label)

        self.dur_input = QLineEdit(playlist_backend.format_duration(song_dict.get('duration')) if song_dict.get('duration') else "")
        self.dur_input.setAccessibleName("Délka písně")
        self.dur_input.setPlaceholderText("m:ss nebo sekundy, např. 3:30, prázdné = neznámá")
        layout.addRow("Délka:", self.dur_input)

        self.tempo_input = QLineEdit(str(int(song_dict.get('tempo'))) if song_dict.get('tempo') else "")
        self.tempo_input.setAccessibleName("Tempo v BPM")
        self.tempo_input.setPlaceholderText("30–300 BPM, prázdné = bez tempa")
        layout.addRow("Tempo:", self.tempo_input)

        marks = song_dict.get("stopMarks") or []
        self.marks_info = QLabel(f"{len(marks)} zarážek" if marks else "Žádné zarážky")
        self.marks_info.setAccessibleName("Počet zarážek")
        layout.addRow("Zarážky:", self.marks_info)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_result(self):
        dur_text = self.dur_input.text().strip()
        tempo_text = self.tempo_input.text().strip()
        duration = None
        tempo = None
        if dur_text:
            duration = playlist_backend.parse_duration(dur_text)
            if duration is None:
                return None, "Neplatný formát délky. Použijte m:ss (např. 3:30) nebo sekundy."
        if tempo_text:
            tempo = playlist_backend.parse_tempo(tempo_text)
            if tempo is None:
                return None, "Tempo musí být 30 až 300 BPM."
        res = dict(self.song)
        res["duration"] = duration
        res["tempo"] = tempo
        return res, None


class QRDialog(QDialog):
    def __init__(self, payload, parent=None):
        super().__init__(parent)
        self.setWindowTitle("QR kód setlistu")
        self.setMinimumSize(420, 520)
        layout = QVBoxLayout(self)
        lab = QLabel("Naskenujte QR kód v telefonu: Posouvač textu → Knihovna → Skenovat QR nebo Setlisty → Import → QR.")
        lab.setWordWrap(True)
        layout.addWidget(lab)
        if HAS_QRCODE and payload:
            try:
                qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=6, border=2)
                qr.add_data(payload)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                try:
                    from PIL import ImageQt  # type: ignore
                    qimg = ImageQt.ImageQt(img)
                    from PyQt6.QtGui import QPixmap
                    pix = QPixmap.fromImage(qimg)
                except Exception:
                    import io
                    b = io.BytesIO()
                    img.save(b, format='PNG')
                    from PyQt6.QtGui import QImage, QPixmap
                    qimg = QImage.fromData(b.getvalue(), 'PNG')
                    pix = QPixmap.fromImage(qimg)
                pix = pix.scaled(320, 320, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                img_label = QLabel()
                img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                img_label.setPixmap(pix)
                img_label.setAccessibleName("QR kód setlistu")
                layout.addWidget(img_label)
            except Exception as e:
                layout.addWidget(QLabel(f"Chyba QR: {e}"))
        else:
            layout.addWidget(QLabel("QR knihovna není dostupná. Nainstalujte: pip install qrcode[pil]"))
            txt = QLabel(payload or "")
            txt.setWordWrap(True)
            txt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(txt)
        info = QLabel(f"Délka dat: {len(payload) if payload else 0} / {playlist_backend.MAX_QR_LENGTH} znaků")
        layout.addWidget(info)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        layout.addWidget(btns)


class PCEditorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Posouvač textu – PC Editor (příprava zarážek, tempa, setlistu)")
        self.resize(1100, 750)
        self.library: list[dict] = []
        self.library_file_map: dict[str, dict] = {}
        self.csv_library: list[dict] = []
        self.setlist: list[dict] = []
        self.current_library_index: int = -1
        self.output_folder: str = ""
        self.source_folder: str = ""
        self.diacritic_map: dict = {}
        self.diacritic_info: dict = {}
        self.diacritic_path: str = ""
        self.live_label = QLabel("")
        self.live_label.setAccessibleName("")
        self.live_label.setProperty("accessibleLiveRegion", "polite")
        # hlas
        self.settings = QSettings("Posouvac", "PCEditor")
        voice_enabled = self.settings.value("voiceConfirm", True)
        # QSettings vrací string na některých platformách
        if isinstance(voice_enabled, str):
            voice_enabled = voice_enabled.lower() in ("true", "1", "yes")
        tts.set_enabled(bool(voice_enabled))
        self.init_ui()

    def announce(self, msg):
        self.statusBar().showMessage(msg, 4000)
        self.live_label.setText(msg)
        self.live_label.setAccessibleName(msg)
        try:
            tts.speak(msg)
        except Exception:
            pass

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # --- Horní lišta: načtení ---
        top_row = QHBoxLayout()
        self.open_folder_btn = QPushButton("Otevřít složku s písněmi (&S)")
        self.open_folder_btn.setAccessibleName("Otevřít složku s písněmi")
        self.open_folder_btn.setAccessibleDescription("Vyberte složku obsahující .txt soubory s texty písní. Lze i rekurzivně.")
        self.open_folder_btn.clicked.connect(self.open_folder)
        top_row.addWidget(self.open_folder_btn)

        self.import_gen_btn = QPushButton("Import z Generátoru (&G)")
        self.import_gen_btn.setAccessibleName("Importovat setlist z Generátoru")
        self.import_gen_btn.setAccessibleDescription("Importuje JSON playlist z programu Generátor playlistu.")
        self.import_gen_btn.clicked.connect(self.import_from_generator)
        top_row.addWidget(self.import_gen_btn)

        self.merge_check = QCheckBox("Přidat k setlistu")
        self.merge_check.setAccessibleName("Přidat importované písně k aktuálnímu setlistu místo nahrazení")
        self.merge_check.setChecked(True)
        top_row.addWidget(self.merge_check)

        self.load_csv_btn = QPushButton("Načíst knihovnu CSV (&C)")
        self.load_csv_btn.setAccessibleName("Načíst knihovnu CSV")
        self.load_csv_btn.setAccessibleDescription("Vyberte metadata_pisni.csv exportovaný z telefonu pro doplnění délek a temp.")
        self.load_csv_btn.setToolTip("Telefon: Knihovna → menu → Export CSV pro Generátor → soubor v Download, zkopírujte přes USB na PC.")
        self.load_csv_btn.clicked.connect(self.load_csv)
        top_row.addWidget(self.load_csv_btn)

        self.output_btn = QPushButton("Výstupní složka (&V)")
        self.output_btn.setAccessibleName("Nastavit výstupní složku")
        self.output_btn.setAccessibleDescription("Složka kam se uloží upravené .txt a setlist JSON. Doporučeno např. C:\\Honza\\Texty-pisni_upraveno.")
        self.output_btn.clicked.connect(self.choose_output_folder)
        top_row.addWidget(self.output_btn)

        top_row.addStretch()
        main_layout.addLayout(top_row)

        # --- Druhá lišta: slovník + hlas ---
        dia_row = QHBoxLayout()
        self.load_diacritic_btn = QPushButton("Načíst slovník (&K)")
        self.load_diacritic_btn.setAccessibleName("Načíst slovník diakritiky")
        self.load_diacritic_btn.setAccessibleDescription("Vyberte CSV slovník bezDiakritiky,sDiakritikou exportovaný z telefonu. Libovolný název souboru.")
        self.load_diacritic_btn.setToolTip("Telefon: Nastavení → Slovník diakritiky → Exportovat slovník. Na PC vyberte libovolný *.csv.")
        self.load_diacritic_btn.clicked.connect(self.load_diacritic_csv)
        dia_row.addWidget(self.load_diacritic_btn)

        self.repair_diacritic_btn = QPushButton("Opravit diakritiku – náhled… (&D)")
        self.repair_diacritic_btn.setAccessibleName("Opravit diakritiku – náhled")
        self.repair_diacritic_btn.setAccessibleDescription("Zobrazí náhled oprav podle slovníku, umožní potvrdit a přejmenovat soubory.")
        self.repair_diacritic_btn.clicked.connect(self.show_diacritic_preview)
        self.repair_diacritic_btn.setEnabled(False)
        dia_row.addWidget(self.repair_diacritic_btn)

        self.diacritic_status = QLabel("Slovník: nenačten")
        self.diacritic_status.setAccessibleName("Stav slovníku diakritiky")
        self.diacritic_status.setWordWrap(True)
        dia_row.addWidget(self.diacritic_status, 1)

        self.voice_check = QCheckBox("Hlasové potvrzení")
        self.voice_check.setAccessibleName("Hlasové potvrzení")
        self.voice_check.setAccessibleDescription("Když zapnuto, aplikace hlásí akce přes čtečku obrazovky (NVDA/JAWS) nebo SAPI, pomocí accessible_output2 Auto().")
        # sync s QSettings – reuse voice_enabled z __init__
        try:
            ve = self.settings.value("voiceConfirm", True)
            if isinstance(ve, str):
                ve = ve.lower() in ("true", "1", "yes")
            self.voice_check.setChecked(bool(ve))
        except Exception:
            self.voice_check.setChecked(True)
        self.voice_check.toggled.connect(self.on_voice_toggled)
        dia_row.addWidget(self.voice_check)

        self.voice_test_btn = QPushButton("Zkouška hlasu")
        self.voice_test_btn.setAccessibleName("Zkouška hlasového výstupu")
        self.voice_test_btn.clicked.connect(lambda: tts.speak("Zkouška hlasového výstupu. Slovník obsahuje {} záznamů.".format(len(self.diacritic_map)) if self.diacritic_map else "Zkouška hlasového výstupu."))
        dia_row.addWidget(self.voice_test_btn)

        dia_row.addStretch()
        main_layout.addLayout(dia_row)

        self.status_label = QLabel("Začněte: Otevřít složku s písněmi nebo Načíst CSV.")
        self.status_label.setAccessibleName("Stav")
        self.status_label.setWordWrap(True)
        main_layout.addWidget(self.status_label)
        main_layout.addWidget(self.live_label)

        # --- Splitter: knihovna vlevo, pravý panel ---
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Levá: Knihovna
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        filter_row = QHBoxLayout()
        self.filter_label = QLabel("Hledat:")
        self.filter_input = QLineEdit()
        self.filter_label.setBuddy(self.filter_input)
        self.filter_input.setAccessibleName("Hledat v knihovně")
        self.filter_input.setAccessibleDescription("Filtruje podle interpreta nebo názvu. Psaní ihned filtruje seznam.")
        self.filter_input.setPlaceholderText("Filtr: interpret nebo název")
        self.filter_input.textChanged.connect(self.refresh_library_list)
        filter_row.addWidget(self.filter_label)
        filter_row.addWidget(self.filter_input)
        left_layout.addLayout(filter_row)

        self.library_label = QLabel("Knihovna:")
        self.library_list = QListWidget()
        self.library_list.setAccessibleName("Seznam písní v knihovně")
        self.library_list.setAccessibleDescription("Šipkami vyberte píseň, Enter přidá do setlistu, dvojklik otevře detail. Počet a filtry hlásí stavový řádek.")
        self.library_label.setBuddy(self.library_list)
        self.library_list.itemSelectionChanged.connect(self.on_library_selection)
        self.library_list.itemDoubleClicked.connect(lambda _: self.add_to_setlist())
        left_layout.addWidget(self.library_label)
        left_layout.addWidget(self.library_list)

        self.lib_count_label = QLabel("0 písní")
        self.lib_count_label.setAccessibleName("Počet písní v knihovně")
        left_layout.addWidget(self.lib_count_label)

        splitter.addWidget(left_widget)

        # Pravý: TabWidget Detail + Setlist
        self.tabs = QTabWidget()
        self.tabs.setAccessibleName("Panely editoru")
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)

        # --- Tab Detail ---
        detail_tab = QWidget()
        detail_layout = QVBoxLayout(detail_tab)

        self.detail_title = QLabel("Detail písně: –")
        self.detail_title.setAccessibleName("Detail vybrané písně")
        self.detail_title.setStyleSheet("font-weight: bold;")
        detail_layout.addWidget(self.detail_title)

        form = QFormLayout()
        self.artist_input = QLineEdit()
        self.artist_input.setAccessibleName("Interpret")
        self.artist_input.setPlaceholderText("Interpret")
        form.addRow("Interpret:", self.artist_input)

        self.title_input = QLineEdit()
        self.title_input.setAccessibleName("Název písně")
        self.title_input.setPlaceholderText("Název")
        form.addRow("Název:", self.title_input)

        dur_row = QHBoxLayout()
        self.dur_input = QLineEdit()
        self.dur_input.setAccessibleName("Délka písně")
        self.dur_input.setPlaceholderText("m:ss např. 3:30")
        self.dur_input.setToolTip("Prázdné = neznámá (odhad 3 min v setlistu).")
        dur_row.addWidget(self.dur_input, 1)
        self.tempo_input = QLineEdit()
        self.tempo_input.setAccessibleName("Tempo BPM")
        self.tempo_input.setPlaceholderText("BPM 30–300")
        dur_row.addWidget(QLabel("Tempo:"), 0)
        dur_row.addWidget(self.tempo_input, 1)
        dur_row_widget = QWidget()
        dur_row_widget.setLayout(dur_row)
        form.addRow("Délka:", dur_row_widget)

        detail_layout.addLayout(form)

        self.save_detail_btn = QPushButton("Uložit změny písně (&U)")
        self.save_detail_btn.setAccessibleName("Uložit změny písně")
        self.save_detail_btn.setAccessibleDescription("Uloží interpreta, název, délku, tempo a zarážky. Textový soubor se přepíše (záloha .bak) s direktivami {stop:N}.")
        self.save_detail_btn.clicked.connect(self.save_detail)
        detail_layout.addWidget(self.save_detail_btn)

        self.stops_btn = QPushButton("Upravit zarážky… (&Z)")
        self.stops_btn.setAccessibleName("Upravit zarážky")
        self.stops_btn.setAccessibleDescription("Otevře dialog se seznamem řádků a zarážek. Přidat před vybraný řádek, odebrat, nastavit takty.")
        self.stops_btn.clicked.connect(self.open_stops_dialog)
        detail_layout.addWidget(self.stops_btn)

        self.preview_label = QLabel("Náhled textu:")
        self.preview_text = QTextEdit()
        self.preview_text.setAccessibleName("Náhled textu písně")
        self.preview_text.setAccessibleDescription("Pouze ke čtení. Zarážky se vkládají přes tlačítko Upravit zarážky.")
        self.preview_text.setReadOnly(True)
        self.preview_label.setBuddy(self.preview_text)
        detail_layout.addWidget(self.preview_label)
        detail_layout.addWidget(self.preview_text)

        self.tabs.addTab(detail_tab, "Detail písně")

        # --- Tab Setlist ---
        setlist_tab = QWidget()
        setlist_layout = QVBoxLayout(setlist_tab)

        name_row = QHBoxLayout()
        self.setlist_name_label = QLabel("Název setlistu:")
        self.setlist_name_input = QLineEdit()
        self.setlist_name_label.setBuddy(self.setlist_name_input)
        self.setlist_name_input.setAccessibleName("Název setlistu")
        self.setlist_name_input.setPlaceholderText("Např. Oslava, Letní kino")
        name_row.addWidget(self.setlist_name_label)
        name_row.addWidget(self.setlist_name_input)
        setlist_layout.addLayout(name_row)

        self.setlist_label = QLabel("Písně v setlistu:")
        self.setlist_list = QListWidget()
        self.setlist_list.setAccessibleName("Seznam písní v setlistu")
        self.setlist_list.setAccessibleDescription("Pořadí měníte tlačítky Výše/Níže nebo přetažením. Dvojklik upraví tempo/délku.")
        self.setlist_label.setBuddy(self.setlist_list)
        self.setlist_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setlist_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setlist_list.itemDoubleClicked.connect(lambda _: self.edit_setlist_song())
        self.setlist_list.model().rowsMoved.connect(self.on_setlist_reordered)
        setlist_layout.addWidget(self.setlist_label)
        setlist_layout.addWidget(self.setlist_list)

        # Ovládání setlistu
        order_row = QHBoxLayout()
        self.add_to_setlist_btn = QPushButton("← Přidat z knihovny")
        self.add_to_setlist_btn.setAccessibleName("Přidat vybranou píseň z knihovny do setlistu")
        self.add_to_setlist_btn.clicked.connect(self.add_to_setlist)
        order_row.addWidget(self.add_to_setlist_btn)

        self.up_btn = QPushButton("↑ Výše")
        self.up_btn.setAccessibleName("Posunout píseň v setlistu výše")
        self.up_btn.clicked.connect(lambda: self.move_setlist(-1))
        order_row.addWidget(self.up_btn)

        self.down_btn = QPushButton("↓ Níže")
        self.down_btn.setAccessibleName("Posunout píseň v setlistu níže")
        self.down_btn.clicked.connect(lambda: self.move_setlist(1))
        order_row.addWidget(self.down_btn)

        self.remove_btn = QPushButton("Odebrat")
        self.remove_btn.setAccessibleName("Odebrat vybranou píseň ze setlistu")
        self.remove_btn.clicked.connect(self.remove_from_setlist)
        order_row.addWidget(self.remove_btn)

        self.edit_btn = QPushButton("Upravit…")
        self.edit_btn.setAccessibleName("Upravit tempo a délku vybrané písně v setlistu")
        self.edit_btn.clicked.connect(self.edit_setlist_song)
        order_row.addWidget(self.edit_btn)

        order_row.addStretch()
        setlist_layout.addLayout(order_row)

        self.summary_label = QLabel("Setlist prázdný.")
        self.summary_label.setAccessibleName("Souhrn setlistu")
        setlist_layout.addWidget(self.summary_label)

        # Exporty
        export_group = QGroupBox("Export / Uložení")
        export_layout = QVBoxLayout(export_group)

        row1 = QHBoxLayout()
        self.save_playlist_btn = QPushButton("Uložit setlist JSON (&J)")
        self.save_playlist_btn.setAccessibleName("Uložit setlist jako JSON")
        self.save_playlist_btn.setAccessibleDescription("Uloží setlist včetně zarážek, tempa a délky. Volitelně včetně textů – telefon pak nemusí mít písně.")
        self.save_playlist_btn.clicked.connect(self.save_playlist_json)
        row1.addWidget(self.save_playlist_btn)

        self.save_with_texts_check = QCheckBox("Včetně textů (pro příjemce bez knihovny)")
        self.save_with_texts_check.setAccessibleName("Uložit včetně textů písní")
        self.save_with_texts_check.setChecked(True)
        row1.addWidget(self.save_with_texts_check)
        export_layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.save_all_btn = QPushButton("Uložit vše: přepsat .txt + JSON (&A)")
        self.save_all_btn.setAccessibleName("Uložit vše – přepsat texty a uložit setlist")
        self.save_all_btn.setAccessibleDescription("Zapíše všechny upravené písně (včetně {stop:N} direktiv) do výstupní složky a uloží JSON. Připraveno ke kopírování přes USB do telefonu.")
        self.save_all_btn.clicked.connect(self.save_all)
        row2.addWidget(self.save_all_btn)
        export_layout.addLayout(row2)

        row3 = QHBoxLayout()
        self.html_btn = QPushButton("Export HTML (&H)")
        self.html_btn.setAccessibleName("Exportovat HTML přehled setlistu")
        self.html_btn.clicked.connect(self.export_html)
        row3.addWidget(self.html_btn)

        self.qr_btn = QPushButton("Zobrazit QR (&Q)")
        self.qr_btn.setAccessibleName("Zobrazit QR kód setlistu")
        self.qr_btn.clicked.connect(self.show_qr)
        row3.addWidget(self.qr_btn)

        self.clipboard_btn = QPushButton("Kopírovat do schránky")
        self.clipboard_btn.setAccessibleName("Kopírovat setlist do schránky jako JSON")
        self.clipboard_btn.clicked.connect(self.copy_to_clipboard)
        row3.addWidget(self.clipboard_btn)
        row3.addStretch()
        export_layout.addLayout(row3)

        # Nápověda USB
        usb_help = QLabel(
            "USB: Zkopírujte výsledné .txt a .json z výstupní složky přes Průzkumník do "
            "Telefon\\Download\\Posouvac\\, v telefonu pak Knihovna → Vybrat soubory a Setlisty → Import ze souboru."
        )
        usb_help.setWordWrap(True)
        usb_help.setAccessibleName("Nápověda USB přenos")
        export_layout.addWidget(usb_help)

        setlist_layout.addWidget(export_group)

        self.tabs.addTab(setlist_tab, "Setlist")

        splitter.addWidget(self.tabs)
        splitter.setSizes([380, 720])
        main_layout.addWidget(splitter, 1)

        # StatusBar
        self.statusBar().showMessage("Připraven. Otevřete složku s písněmi.")

        # Tab order
        self.setTabOrder(self.open_folder_btn, self.import_gen_btn)
        self.setTabOrder(self.import_gen_btn, self.load_csv_btn)
        self.setTabOrder(self.load_csv_btn, self.output_btn)
        self.setTabOrder(self.output_btn, self.filter_input)
        self.setTabOrder(self.filter_input, self.library_list)
        self.setTabOrder(self.library_list, self.artist_input)
        self.setTabOrder(self.artist_input, self.title_input)
        self.setTabOrder(self.title_input, self.dur_input)
        self.setTabOrder(self.dur_input, self.tempo_input)
        self.setTabOrder(self.tempo_input, self.save_detail_btn)
        self.setTabOrder(self.save_detail_btn, self.stops_btn)
        self.setTabOrder(self.stops_btn, self.preview_text)

    # --- Knihovna ---
    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Vyberte složku s písněmi (.txt)")
        if not folder:
            return
        self.source_folder = folder
        if not self.output_folder:
            self.output_folder = folder.rstrip("\\/") + "_upraveno"
        ok, data = library_model.load_library_from_folder(folder)
        if not ok:
            QMessageBox.critical(self, "Chyba", str(data))
            return
        self.library = data
        if self.csv_library:
            library_model.enrich_with_csv(self.library, self.csv_library)
        self.refresh_library_list()
        self.announce(f"Načteno {len(self.library)} písní z {folder}.")
        self.status_label.setText(f"Zdroj: {folder}  →  Výstup: {self.output_folder}  |  {len(self.library)} písní  |  {len(self.setlist)} v setlistu")
        self.save_detail_btn.setEnabled(bool(self.library))
        # povolit náhled diakritiky pokud je slovník
        try:
            self.repair_diacritic_btn.setEnabled(bool(self.library) and bool(self.diacritic_map))
        except Exception:
            pass

    def import_from_generator(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Import setlistu z Generátoru", 
            "C:/Honza/Projekty/Generator_playlistu_pro_Posouvac_textu", "JSON (*.json)")
        if not fn:
            return
        ok, data = playlist_backend.load_playlist(fn)
        if not ok:
            QMessageBox.critical(self, "Chyba", f"Nepodařilo se načíst playlist: {data}")
            return
        
        raw_songs = data.get("_normSongs") or data.get("songs") or []
        enriched, missing = library_model.enrich_imported_songs(raw_songs, self.library)
        
        if self.merge_check.isChecked():
            self.setlist.extend(enriched)
        else:
            self.setlist = enriched
            self.setlist_name_input.setText(data.get("name") or Path(fn).stem)
        
        self.refresh_setlist()
        self.announce(f"Importováno {len(enriched)} písní z {data.get('name')}. Chybějících v knihovně: {len(missing)}.")
        if missing:
            msg = "\n".join([f"{m.get('artist')} - {m.get('title')}" for m in missing[:10]])
            if len(missing) > 10: msg += "\n..."
            QMessageBox.information(self, "Chybějící v knihovně", f"Písně nebyly nalezeny v knihovně (budou přidány bez filePath/zarážek):\n{msg}")

    def load_csv(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Načíst metadata_pisni.csv", "", "CSV (*.csv);;Vše (*)")
        if not fn:
            return
        ok, data = playlist_backend.load_csv_library(fn)
        if not ok:
            QMessageBox.critical(self, "Chyba", f"CSV se nepodařilo načíst: {data}")
            return
        self.csv_library = data
        if self.library:
            library_model.enrich_with_csv(self.library, self.csv_library)
            self.refresh_library_list()
        self.announce(f"Knihovna načtena: {len(data)} písní.")
        self.status_label.setText(f"CSV: {len(data)} písní. " + self.status_label.text())

    def on_voice_toggled(self, checked: bool):
        tts.set_enabled(bool(checked))
        try:
            self.settings.setValue("voiceConfirm", bool(checked))
        except Exception:
            pass
        self.announce("Hlasové potvrzení zapnuto." if checked else "Hlasové potvrzení vypnuto.")

    def load_diacritic_csv(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Načíst slovník diakritiky", "", "CSV (*.csv);;Vše (*)")
        if not fn:
            return
        ok, dmap, info = diacritic.load_diacritic_csv(fn)
        if not ok:
            QMessageBox.critical(self, "Chyba", f"Slovník se nepodařilo načíst: {dmap}")
            self.announce(f"Chyba načtení slovníku: {dmap}")
            return
        self.diacritic_map = dmap
        self.diacritic_info = info
        self.diacritic_path = fn
        imp = info.get("imported", 0)
        skip = info.get("skipped", 0)
        self.diacritic_status.setText(f"Slovník: {Path(fn).name} – {len(dmap)} záznamů (import {imp}, přeskočeno {skip})")
        self.repair_diacritic_btn.setEnabled(bool(self.library) and bool(self.diacritic_map))
        msg = f"Slovník načten: {len(dmap)} záznamů z {Path(fn).name}. Import {imp}, přeskočeno {skip}."
        if info.get("errors"):
            # stručně
            msg += f" Chyby: {len(info['errors'])}"
        self.announce(msg)
        self.status_label.setText(msg + " | " + self.status_label.text())

    def show_diacritic_preview(self):
        if not self.library:
            QMessageBox.warning(self, "Varování", "Nejprve otevřete složku s písněmi.")
            self.announce("Nejprve otevřete složku s písněmi.")
            return
        if not self.diacritic_map:
            QMessageBox.warning(self, "Varování", "Nejprve načtěte slovník diakritiky (libovolný *.csv).")
            self.announce("Nejprve načtěte slovník diakritiky.")
            return
        candidates, unrepaired = library_model.find_diacritic_repairs(self.library, self.diacritic_map)
        total = len(self.library)
        c_count = len(candidates)
        u_count = len(unrepaired)
        if c_count == 0:
            # i tak zobrazit výpis jako v telefonu settings_page.dart:381
            self.announce(f"Žádné názvy k opravě nebyly nalezeny. V knihovně {total} písní.")
        else:
            self.announce(f"Nalezeno {c_count} návrhů na opravu z {total}. Bez návrhu {u_count}. Zkontrolujte seznam.")
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Kontrola změn ({total} písní)")
        dlg.resize(780, 520)
        layout = QVBoxLayout(dlg)

        info_lab = QLabel(f"K opravě: {c_count}  •  Bez návrhu: {u_count}  •  Celkem: {total}  •  Slovník: {Path(self.diacritic_path).name if self.diacritic_path else ''} ({len(self.diacritic_map)} záznamů)")
        info_lab.setWordWrap(True)
        info_lab.setAccessibleName("Souhrn náhledu oprav")
        layout.addWidget(info_lab)

        # seznam kandidátů
        if candidates:
            lab = QLabel(f"K opravě ({c_count}):")
            lab.setStyleSheet("font-weight: bold;")
            layout.addWidget(lab)
            cand_list = QListWidget()
            cand_list.setAccessibleName("Seznam návrhů k opravě")
            for c in candidates:
                cand_list.addItem(f"{c['currentArtist']} – {c['currentTitle']}  →  {c['newArtist']} – {c['newTitle']}")
            layout.addWidget(cand_list, 1)
        if unrepaired:
            lab2 = QLabel(f"Bez návrhu ({u_count}):")
            lab2.setStyleSheet("font-weight: bold; color: #555;")
            layout.addWidget(lab2)
            unrep_list = QListWidget()
            unrep_list.setAccessibleName("Seznam bez návrhu")
            for u in unrepaired[:200]:
                reason_map = {"alreadyCorrect": "už správně", "missingInMap": "chybí ve slovníku", "compositeNoMatch": "kompozit bez shody"}
                reason = reason_map.get(u.get("reason"), u.get("reason"))
                unrep_list.addItem(f"{u.get('artist')} – {u.get('title')}  [{reason}]")
            if len(unrepaired) > 200:
                unrep_list.addItem(f"… a dalších {len(unrepaired)-200}")
            layout.addWidget(unrep_list, 1)
            hint = QLabel(f"Celkem {total} písní v knihovně, k opravě {c_count}, bez návrhu {u_count}.")
            hint.setStyleSheet("color: #666; font-size: 11px;")
            layout.addWidget(hint)

        chk = QCheckBox("Přejmenovat i soubory na disku")
        chk.setAccessibleName("Přejmenovat i soubory na disku")
        chk.setAccessibleDescription("Přejmenuje .txt soubory podle opraveného interpreta a názvu. Na Windows může selhat, pokud je soubor otevřen.")
        try:
            chk.setChecked(bool(self.settings.value("diacriticRenameFiles", True) if not isinstance(self.settings.value("diacriticRenameFiles", True), str) else self.settings.value("diacriticRenameFiles", True).lower() in ("true","1")))
        except Exception:
            chk.setChecked(True)
        layout.addWidget(chk)

        btn_row = QHBoxLayout()
        export_btn = QPushButton("Exportovat náhled do CSV…")
        export_btn.setAccessibleName("Exportovat náhled oprav do CSV")
        def do_export():
            out, _ = QFileDialog.getSaveFileName(dlg, "Uložit náhled oprav", f"nahled_oprav_{Path(self.diacritic_path).stem if self.diacritic_path else 'slovnik'}.csv", "CSV (*.csv)")
            if not out:
                return
            ok2, res = library_model.export_diacritic_preview_csv(candidates, unrepaired, out)
            if ok2:
                QMessageBox.information(dlg, "Export", f"Náhled uložen do:\n{res}")
                self.announce(f"Náhled exportován do {res}")
                try:
                    QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(res)))
                except Exception:
                    pass
            else:
                QMessageBox.critical(dlg, "Chyba", res)
        export_btn.clicked.connect(do_export)
        btn_row.addWidget(export_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText(f"Potvrdit ({c_count})" if c_count else "Zavřít")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("Zrušit")
        if c_count == 0:
            btns.button(QDialogButtonBox.StandardButton.Cancel).setVisible(False)
            btns.accepted.connect(dlg.accept)
            btns.rejected.connect(dlg.reject)
            layout.addWidget(btns)
            # umožnit i zavření přes Ok
            btns.accepted.connect(lambda: None)
        else:
            btns.accepted.connect(dlg.accept)
            btns.rejected.connect(dlg.reject)
            layout.addWidget(btns)

        # tts ohlásit otevření
        tts.speak(info_lab.text())

        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.announce("Oprava zrušena.")
            return
        if c_count == 0:
            return
        rename = chk.isChecked()
        try:
            self.settings.setValue("diacriticRenameFiles", bool(rename))
        except Exception:
            pass
        # uložit staré cesty před přejmenováním
        old_paths = {c.get("index"): c.get("filePath") for c in candidates}
        res = library_model.apply_diacritic_repairs(self.library, candidates, rename_files=rename)
        # aktualizovat filePath i artist/title v setlistu pokud došlo k rename
        if rename and res.get("filesRenamed", 0) > 0:
            for c in candidates:
                idx = c.get("index")
                old = old_paths.get(idx)
                if not old:
                    continue
                new = self.library[idx].get("filePath") if idx is not None and 0 <= idx < len(self.library) else None
                if new and new != old:
                    for s in self.setlist:
                        if s.get("filePath") == old:
                            s["filePath"] = new
                            s["artist"] = c.get("newArtist") or s.get("artist")
                            s["title"] = c.get("newTitle") or s.get("title")
                else:
                    # i když rename selhalo, aktualizuj aspoň metadata
                    for s in self.setlist:
                        if s.get("filePath") == old:
                            s["artist"] = c.get("newArtist") or s.get("artist")
                            s["title"] = c.get("newTitle") or s.get("title")
        else:
            # bez rename – aktualizuj jen metadata podle filePath shody nebo title/artist
            for c in candidates:
                for s in self.setlist:
                    if s.get("filePath") and s.get("filePath") == c.get("filePath"):
                        s["artist"] = c.get("newArtist") or s.get("artist")
                        s["title"] = c.get("newTitle") or s.get("title")
        self.refresh_library_list()
        self.refresh_setlist()
        self._mark_dirty()
        msg2 = f"Opraveno {res['dbUpdated']} názvů."
        if rename:
            if res['filesFailed'] > 0:
                msg2 += f" Přejmenováno {res['filesRenamed']}, selhalo {res['filesFailed']} (soubor otevřen nebo chráněn)."
            elif res['filesRenamed'] > 0:
                msg2 += f" Přejmenováno {res['filesRenamed']} souborů."
        QMessageBox.information(self, "Hotovo", msg2)
        self.announce(msg2)
        self.status_label.setText(msg2 + " | " + self.status_label.text())
        if res['filesFailed'] > 0:
            detail = "\n".join(res['failedPaths'][:3])
            QMessageBox.warning(self, "Selhání přejmenování", f"Některé soubory se nepodařilo přejmenovat (otevřeny):\n{detail}")

    def choose_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Vyberte výstupní složku")
        if folder:
            self.output_folder = folder
            self.announce(f"Výstupní složka: {folder}")
            self.status_label.setText(f"Výstup: {folder}")

    def refresh_library_list(self):
        filt = self.filter_input.text().strip().lower()
        self.library_list.clear()
        count = 0
        for idx, entry in enumerate(self.library):
            label = f"{entry.get('artist')} – {entry.get('title')}"
            if filt and filt not in label.lower():
                continue
            dur = playlist_backend.format_duration(entry.get('duration'))
            tempo = f"{int(entry['tempo'])} BPM" if entry.get('tempo') else "—"
            marks = len(entry.get('stopMarks') or [])
            marks_txt = f", {marks} zarážek" if marks else ""
            item = QListWidgetItem(f"{label}  [{dur}, {tempo}{marks_txt}]")
            item.setData(Qt.ItemDataRole.UserRole, idx)
            self.library_list.addItem(item)
            count += 1
        self.lib_count_label.setText(f"Zobrazeno {count} / {len(self.library)} písní")

    def on_library_selection(self):
        items = self.library_list.selectedItems()
        if not items:
            return
        idx = items[0].data(Qt.ItemDataRole.UserRole)
        if idx is None or idx < 0 or idx >= len(self.library):
            return
        self.current_library_index = idx
        entry = self.library[idx]
        self.detail_title.setText(f"Detail: {entry.get('artist')} – {entry.get('title')}")
        self.artist_input.setText(entry.get('artist') or "")
        self.title_input.setText(entry.get('title') or "")
        self.dur_input.setText(playlist_backend.format_duration(entry['duration']) if entry.get('duration') else "")
        self.tempo_input.setText(str(int(entry['tempo'])) if entry.get('tempo') else "")
        content = entry.get('content') or ""
        self.preview_text.setPlainText(content[:4000])
        self.tabs.setCurrentIndex(0)
        self.statusBar().showMessage(f"Vybrána: {entry.get('artist')} – {entry.get('title')} – {len(entry.get('stopMarks') or [])} zarážek")

    def save_detail(self):
        if self.current_library_index < 0 or self.current_library_index >= len(self.library):
            QMessageBox.warning(self, "Varování", "Nejprve vyberte píseň v knihovně.")
            return
        entry = self.library[self.current_library_index]
        new_artist = self.artist_input.text().strip() or "Neznámý interpret"
        new_title = self.title_input.text().strip()
        if not new_title:
            QMessageBox.warning(self, "Varování", "Název nesmí být prázdný.")
            return
        dur_raw = self.dur_input.text().strip()
        tempo_raw = self.tempo_input.text().strip()
        duration = None
        tempo = None
        if dur_raw and dur_raw != "?":
            duration = playlist_backend.parse_duration(dur_raw)
            if duration is None:
                QMessageBox.warning(self, "Varování", "Neplatná délka.")
                return
        if tempo_raw:
            tempo = playlist_backend.parse_tempo(tempo_raw)
            if tempo is None:
                QMessageBox.warning(self, "Varování", "Tempo musí být 30–300 BPM.")
                return
        entry["artist"] = new_artist
        entry["title"] = new_title
        entry["duration"] = duration
        entry["tempo"] = tempo
        entry["content"] = playlist_backend.file_content_with_stop_marks_applied(entry.get("content") or "", entry.get("stopMarks") or [])
        self.preview_text.setPlainText(entry["content"][:4000])
        self.refresh_library_list()
        self.refresh_setlist()
        self.announce(f"Uloženo v paměti: {new_artist} – {new_title}. Pro zápis na disk použijte Uložit vše.")
        self._mark_dirty()

    def open_stops_dialog(self):
        if self.current_library_index < 0:
            QMessageBox.warning(self, "Varování", "Nejprve vyberte píseň v knihovně.")
            return
        entry = self.library[self.current_library_index]
        dlg = StopMarksDialog(entry, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            entry["content"] = playlist_backend.file_content_with_stop_marks_applied(entry.get("content") or "", entry.get("stopMarks") or [])
            self.preview_text.setPlainText(entry["content"][:4000])
            self.refresh_library_list()
            for s in self.setlist:
                if s.get("filePath") == entry.get("filePath") or (s.get("title") == entry.get("title") and s.get("artist") == entry.get("artist")):
                    s["stopMarks"] = list(entry.get("stopMarks") or [])
                    s["content"] = entry["content"]
            self.refresh_setlist()
            self._mark_dirty()
            self.announce(f"Zarážky uloženy v paměti ({len(entry.get('stopMarks') or [])} zarážek).")

    def _mark_dirty(self):
        self.save_all_btn.setStyleSheet("font-weight: bold;")

    # --- Setlist ---
    def add_to_setlist(self):
        if self.current_library_index < 0:
            items = self.library_list.selectedItems()
            if not items:
                QMessageBox.warning(self, "Varování", "Vyberte píseň v knihovně vlevo.")
                return
            idx = items[0].data(Qt.ItemDataRole.UserRole)
            self.current_library_index = idx
        entry = self.library[self.current_library_index] if 0 <= self.current_library_index < len(self.library) else None
        if not entry:
            return
        copy = {
            "title": entry["title"],
            "artist": entry["artist"],
            "duration": entry.get("duration"),
            "tempo": entry.get("tempo"),
            "content": entry.get("content"),
            "stopMarks": list(entry.get("stopMarks") or []),
            "filePath": entry.get("filePath"),
        }
        self.setlist.append(copy)
        self.refresh_setlist()
        self.announce(f"Přidána do setlistu: {copy['artist']} – {copy['title']}")

    def remove_from_setlist(self):
        row = self.setlist_list.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Varování", "Vyberte píseň v setlistu k odebrání.")
            return
        removed = self.setlist.pop(row)
        self.refresh_setlist()
        self.announce(f"Odebrána: {removed.get('title')}")

    def move_setlist(self, delta: int):
        row = self.setlist_list.currentRow()
        if row < 0:
            return
        new_row = row + delta
        if 0 <= new_row < len(self.setlist):
            self.setlist.insert(new_row, self.setlist.pop(row))
            self.refresh_setlist()
            self.setlist_list.setCurrentRow(new_row)
            self.announce(f"Přesunuta na {new_row+1}. místo")

    def on_setlist_reordered(self, *args):
        new_order = []
        for i in range(self.setlist_list.count()):
            it = self.setlist_list.item(i)
            data = it.data(Qt.ItemDataRole.UserRole)
            if data is not None and isinstance(data, dict):
                new_order.append(dict(data))
        if len(new_order) == len(self.setlist):
            self.setlist = new_order
            self.refresh_setlist()

    def edit_setlist_song(self):
        row = self.setlist_list.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Varování", "Vyberte píseň v setlistu k úpravě.")
            return
        dlg = EditSetlistSongDialog(self.setlist[row], self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            res, err = dlg.get_result()
            if err:
                QMessageBox.warning(self, "Varování", err)
                return
            self.setlist[row] = res
            self.refresh_setlist()
            self.announce(f"Upravena: {res.get('title')}")

    def refresh_setlist(self):
        self.setlist_list.clear()
        total = 0
        unknown = 0
        for i, s in enumerate(self.setlist):
            dur = s.get("duration")
            tempo = s.get("tempo")
            dur_txt = playlist_backend.format_duration(dur)
            tempo_txt = f"{int(tempo)} BPM" if tempo else "—"
            marks = len(s.get("stopMarks") or [])
            marks_txt = f", {marks} zarážek" if marks else ""
            label = f"{i+1}. {s.get('artist')} – {s.get('title')}  [{dur_txt}, {tempo_txt}{marks_txt}]"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, dict(s))
            self.setlist_list.addItem(item)
            if dur and int(dur) > 0:
                total += int(dur)
            else:
                unknown += 1
        if not self.setlist:
            self.summary_label.setText("Setlist prázdný. Přidejte písně z knihovny vlevo.")
        else:
            m = total // 60; sec = total % 60
            if unknown == 0:
                txt = f"{len(self.setlist)} písní • Celkový čas: {m}:{sec:02d}"
            else:
                txt = f"{len(self.setlist)} písní • Celkový čas: {m}:{sec:02d} + {unknown} bez času (odhad +{unknown*3} min)"
            self.summary_label.setText(txt)
        self.refresh_library_list()

    # --- Exporty ---
    def _require_setlist(self) -> bool:
        if not self.setlist_name_input.text().strip():
            QMessageBox.critical(self, "Chyba", "Název setlistu nesmí být prázdný.")
            return False
        if not self.setlist:
            QMessageBox.warning(self, "Varování", "Setlist neobsahuje žádné písně.")
            return False
        return True

    def _ensure_output_folder(self) -> str | None:
        if self.output_folder and os.path.isdir(self.output_folder):
            return self.output_folder
        folder = QFileDialog.getExistingDirectory(self, "Vyberte výstupní složku pro uložení")
        if not folder:
            return None
        self.output_folder = folder
        return folder

    def save_all(self):
        if not self._require_setlist():
            return
        folder = self._ensure_output_folder()
        if not folder:
            return
        ok_count = 0
        fail = []
        for entry in self.library:
            if not entry.get("filePath"):
                continue
            src = entry["filePath"]
            if os.path.abspath(folder) != os.path.abspath(os.path.dirname(src)):
                safe_a = "".join(c if c not in r'\/:*?"<>|' else "_" for c in (entry.get("artist") or "")).strip()
                safe_t = "".join(c if c not in r'\/:*?"<>|' else "_" for c in (entry.get("title") or "")).strip()
                fname = f"{safe_a} - {safe_t}.txt" if safe_a else f"{safe_t}.txt"
                dst = os.path.join(folder, fname)
                content = playlist_backend.file_content_with_stop_marks_applied(entry.get("content") or "", entry.get("stopMarks") or [])
                try:
                    os.makedirs(folder, exist_ok=True)
                    with open(dst, 'w', encoding='utf-8') as f:
                        f.write(content)
                    ok_count += 1
                except Exception as e:
                    fail.append(f"{fname}: {e}")
            else:
                ok, msg = library_model.save_entry_to_file(entry)
                if ok:
                    ok_count += 1
                else:
                    fail.append(msg)
        name = self.setlist_name_input.text().strip()
        include_texts = self.save_with_texts_check.isChecked()
        json_path = os.path.join(folder, f"{name.replace(' ', '_')}.json")
        export_songs = []
        for s in self.setlist:
            e = dict(s)
            if include_texts and not e.get("content"):
                for lib in self.library:
                    if lib.get("filePath") == e.get("filePath"):
                        e["content"] = lib.get("content")
                        break
            if not include_texts:
                e.pop("content", None)
            export_songs.append(e)
        success, result = playlist_backend.save_playlist_to(json_path, name, export_songs)
        if not success:
            QMessageBox.critical(self, "Chyba", f"JSON se nepodařilo uložit: {result}")
            return
        msg = f"Uloženo {ok_count} textů a setlist {result}."
        if fail:
            msg += f"\nChyby: {', '.join(fail[:3])}"
        QMessageBox.information(self, "Uloženo", msg + "\n\nZkopírujte do telefonu.")
        self.announce(msg)
        self.save_all_btn.setStyleSheet("")
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        except Exception:
            pass

    def save_playlist_json(self):
        if not self._require_setlist():
            return
        name = self.setlist_name_input.text().strip()
        folder = self._ensure_output_folder()
        if not folder:
            return
        include_texts = self.save_with_texts_check.isChecked()
        export_songs = []
        for s in self.setlist:
            e = dict(s)
            if include_texts and not e.get("content"):
                for lib in self.library:
                    if lib.get("filePath") == e.get("filePath"):
                        e["content"] = lib.get("content")
                        break
            if not include_texts:
                e.pop("content", None)
            export_songs.append(e)
        json_path = os.path.join(folder, f"{name.replace(' ', '_')}.json")
        success, result = playlist_backend.save_playlist_to(json_path, name, export_songs)
        if success:
            QMessageBox.information(self, "Uloženo", f"Setlist uložen do:\n{result}\n\nZkopírujte přes USB.")
            self.announce(f"Setlist uložen: {result}")
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        else:
            QMessageBox.critical(self, "Chyba", result)

    def export_html(self):
        if not self._require_setlist():
            return
        name = self.setlist_name_input.text().strip()
        folder = self._ensure_output_folder()
        if not folder:
            return
        html_path = os.path.join(folder, f"{name.replace(' ', '_')}.html")
        ok, res = playlist_backend.save_playlist_html(html_path, name, self.setlist)
        if ok:
            QMessageBox.information(self, "HTML", f"HTML přehled uložen do:\n{res}")
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        else:
            QMessageBox.critical(self, "Chyba", res)

    def show_qr(self):
        if not self._require_setlist():
            return
        name = self.setlist_name_input.text().strip()
        payload, err = playlist_backend.get_qr_payload(name, self.setlist)
        if err:
            QMessageBox.warning(self, "QR příliš velký", f"{err}\n\nPoužijte soubor JSON.")
            return
        if not HAS_QRCODE:
            QMessageBox.warning(self, "Chybí qrcode", "Nainstalujte pip install qrcode[pil].")
            QApplication.clipboard().setText(payload)
            return
        dlg = QRDialog(payload, self)
        dlg.exec()

    def copy_to_clipboard(self):
        if not self._require_setlist():
            return
        name = self.setlist_name_input.text().strip()
        text = playlist_backend.playlist_to_text(name, self.setlist)
        if not text:
            QMessageBox.critical(self, "Chyba", "Nepodařilo se sestavit JSON.")
            return
        QApplication.clipboard().setText(text)
        self.announce("Setlist zkopírován do schránky.")
        QMessageBox.information(self, "Zkopírováno", "Setlist zkopírován jako JSON do schránky.")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = PCEditorApp()
    win.show()
    sys.exit(app.exec())
