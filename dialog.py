
# dialog.py

import json
import os
import html
import shutil
import re
import urllib.parse
import base64
import logging
import random
from datetime import datetime
from PyQt6.QtCore import QTimer
from aqt import mw, gui_hooks
from aqt.qt import *
from aqt.utils import showInfo, showWarning
from aqt.webview import AnkiWebView
from anki.utils import strip_html, pointVersion
from aqt.theme import theme_manager
from .highlighter import HtmlTagHighlighter
from .media_manager import MediaManagerDialog
from .visualizar import VisualizarCards
from .utils import CONFIG_FILE
from .exporthtml import *
# <<< INÍCIO: Importação de todos os idiomas >>>
from .english import TRANSLATIONS
from .japanese import TRANSLATIONS as JP_TRANSLATIONS
from .spanish import TRANSLATIONS as ES_TRANSLATIONS
from .italian import TRANSLATIONS as IT_TRANSLATIONS
from .hindi import TRANSLATIONS as HI_TRANSLATIONS
from .french import TRANSLATIONS as FR_TRANSLATIONS
from .german import TRANSLATIONS as DE_TRANSLATIONS
from .chinese import TRANSLATIONS as ZH_TRANSLATIONS
from .russian import TRANSLATIONS as RU_TRANSLATIONS
from .arabic import TRANSLATIONS as AR_TRANSLATIONS
from .indonesian import TRANSLATIONS as ID_TRANSLATIONS
# <<< FIM: Importação de todos os idiomas >>>

import webbrowser

# Configuração de logging
logging.basicConfig(filename="delimitadores.log", level=logging.DEBUG)

# Caminho para a pasta de ícones
addon_path = os.path.dirname(__file__)
icons_path = os.path.join(addon_path, 'icons')

PT_TRANSLATIONS = {
    "instructions_button": "Instruções",
    "instructions_title": "Instruções (Modo Iniciante)",
    "beginner_instructions_line1": "<b>1. Um card por linha.</b>",
    "beginner_instructions_line2": "<b>2. Separe a frente do verso com ponto e vírgula ( ; ).</b>",
    "beginner_instructions_example_title": "Exemplo:",
    "beginner_instructions_example_text": "capital do Brasil ; Brasília",
    # Novas traduções para as abas e labels
    "Cards e Mídia": "Cards e Mídia",
    "Formatação": "Formatação",
    "Organizar e Ações": "Organizar e Ações",
    "Busca e Visualização": "Busca e Visualização",
    "Cor Texto:": "Cor Texto:",
    "Cor Fundo:": "Cor Fundo:",
    "Zoom Texto:": "Zoom Texto:",
}


# =============================================================================
# BOTÃO CUSTOMIZADO QUE FORÇA O DESENHO DO TEXTO
# =============================================================================
class ForceLabelButton(QPushButton):
    def __init__(self, text, text_color=Qt.GlobalColor.black, parent=None):
        super().__init__("", parent)
        self.forced_text = text
        self.text_color = text_color

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(self.text_color)
        font = self.font()
        font.setPixelSize(14)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.forced_text)


class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.line_numbers = []
        self.setStyleSheet("background-color: #ffffff; color: #555;")

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor("#ffffff"))
        document = self.editor.document()
        font_metrics = self.editor.fontMetrics()
        line_height = font_metrics.height()
        cursor = self.editor.cursorForPosition(QPoint(0, 0))
        first_visible_block = cursor.block()
        first_visible_block_number = first_visible_block.blockNumber()
        rect = self.editor.cursorRect(cursor)
        top = rect.top()
        block = first_visible_block
        block_number = first_visible_block_number
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible():
                if block_number < len(self.line_numbers) and self.line_numbers[block_number]:
                    painter.setPen(QColor("#555"))
                    painter.drawText(
                        0, int(top), self.width() - 5, line_height,
                        Qt.AlignmentFlag.AlignRight, self.line_numbers[block_number]
                    )
            block = block.next()
            cursor.movePosition(QTextCursor.MoveOperation.NextBlock)
            rect = self.editor.cursorRect(cursor)
            top = rect.top()
            block_number += 1


class CustomDialog(QDialog):
    def __init__(self, parent=None):
        if not mw:
            showWarning("A janela principal do Anki não está disponível!")
            return
        logging.debug("Inicializando CustomDialog")
        super().__init__(mw, Qt.WindowType.Window | Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowCloseButtonHint | Qt.WindowType.WindowMaximizeButtonHint)
        
        self.current_language = 'pt'  # Padrão
        
        self.media_dialog = None
        self.visualizar_dialog = None
        self.last_search_query = ""
        self.last_search_position = 0
        self.zoom_factor = 1.0
        self.cloze_2_count = 1
        self.initial_tags_set = False
        self.initial_numbering_set = False
        self.media_files = []
        self.current_line = 0
        self.previous_text = ""
        self.pre_show_state_file = os.path.join(os.path.dirname(CONFIG_FILE), "pre_show_state.json")
        self.last_edited_line = -1
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self._save_in_real_time)
        self.is_dark_theme = False
        self.field_mappings = {}
        self.field_images = {}
        self.card_notetypes = []
        self.real_text = ""
        self.last_preview_html = ""
        self.card_creation_info = [] # Para armazenar info dos cards mostrados (id, texto, tags)
        self.current_view_mode = 'simple' # 'simple', 'date', 'stats'
        self.is_beginner_mode = False 
        self.tags_visible_before_beginner_mode = False 
        self.is_first_show = True


        # --- ATRIBUTOS PARA EDIÇÃO EM TEMPO REAL ---
        self.edit_mode = False
        self.shown_note_ids = []
        self.edit_timer = QTimer(self)
        self.edit_timer.setSingleShot(True)
        self.edit_timer.timeout.connect(self._apply_real_time_edit)
        
        self.setup_ui()
        self.load_settings()
        self.retranslate_ui() # Aplica o idioma carregado
        self.setWindowState(Qt.WindowState.WindowMaximized)

    def _t(self, key):
        """Função auxiliar para obter a tradução."""
        lang_map = {
            'en': TRANSLATIONS,
            'jp': JP_TRANSLATIONS,
            'es': ES_TRANSLATIONS,
            'it': IT_TRANSLATIONS,
            'hi': HI_TRANSLATIONS,
            'fr': FR_TRANSLATIONS,
            'de': DE_TRANSLATIONS,
            'zh': ZH_TRANSLATIONS,
            'ru': RU_TRANSLATIONS,
            'ar': AR_TRANSLATIONS,
            'id': ID_TRANSLATIONS,
            'pt': PT_TRANSLATIONS,
        }
        return lang_map.get(self.current_language, PT_TRANSLATIONS).get(key, key)

    def _get_reviewer_scripts(self):
        """Retorna a lista de scripts JS do revisor com base na versão do Anki."""
        pv = pointVersion()
        if pv >= 231210:
            return ["js/mathjax.js", "js/vendor/mathjax/tex-chtml-full.js", "js/reviewer.js"]
        elif pv >= 45:
            return ["js/mathjax.js", "js/vendor/mathjax/tex-chtml.js", "js/reviewer.js"]
        else:
            return ["js/vendor/jquery.min.js", "js/vendor/css_browser_selector.min.js", "js/mathjax.js", "js/vendor/mathjax/tex-chtml.js", "js/reviewer.js"]

    def setup_ui(self):
        self.setWindowTitle(self._t("Adicionar Cards com Delimitadores"))
        self.resize(1000, 600)
        main_layout = QVBoxLayout()
        
        # --- SELETOR DE IDIOMA COM BANDEIRAS ---
        top_bar_layout = QHBoxLayout()
        self.lang_label = QLabel(self._t("Idioma:"))
        top_bar_layout.addWidget(self.lang_label)
        self.lang_combo = QComboBox()

        languages = [
            ('br', "Português"), ('us', "English"), ('es', "Español"),
            ('it', "Italiano"), ('in', "हिन्दी (Hindi)"), ('fr', "Français"),
            ('de', "Deutsch"), ('cn', "中文 (Chinese)"), ('ru', "Русский (Russian)"),
            ('sa', "العربية (Arabic)"), ('id', "Bahasa Indonesia"), ('jp', "日本語 (Japanese)"),
        ]

        for code, name in languages:
            icon_path = os.path.join(icons_path, f'{code}.jpg')
            icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
            self.lang_combo.addItem(icon, name)

        self.lang_combo.currentIndexChanged.connect(self.switch_language)
        top_bar_layout.addWidget(self.lang_combo)

        self.btn_beginner_mode = QPushButton(self._t("Modo Iniciante"))
        self.btn_beginner_mode.setToolTip(self._t("Simplifica a interface para mostrar apenas as funções essenciais."))
        self.btn_beginner_mode.clicked.connect(self.toggle_beginner_mode)
        top_bar_layout.addWidget(self.btn_beginner_mode)

        self.btn_instructions = QPushButton(self._t("instructions_button"))
        self.btn_instructions.clicked.connect(self.show_instructions_dialog)
        self.btn_instructions.setVisible(False)
        top_bar_layout.addWidget(self.btn_instructions)

        top_bar_layout.addStretch()
        main_layout.addLayout(top_bar_layout)
        # --- FIM DO SELETOR ---

        self.vertical_splitter = QSplitter(Qt.Orientation.Vertical)
        
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        
        status_layout = QHBoxLayout()
        self.save_status_label = QLabel(self._t("Pronto"), self)
        self.save_status_label.setStyleSheet("color: gray;")
        status_layout.addWidget(self.save_status_label)
        
        self.separator_label = QLabel(" / ", self) 
        self.separator_label.setStyleSheet("color: gray;")
        status_layout.addWidget(self.separator_label)
        
        self.card_count_label = QLabel(self._t("Cards: {}").format(0), self)
        self.card_count_label.setStyleSheet("color: gray;")
        status_layout.addWidget(self.card_count_label)
        status_layout.addStretch()
        top_layout.addLayout(status_layout)
        
        self.fields_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        self.cards_tags_widget = QWidget()
        cards_tags_layout = QHBoxLayout(self.cards_tags_widget)
        
        self.cards_group = QWidget()
        cards_layout = QVBoxLayout(self.cards_group)
        
        cards_header_layout = QHBoxLayout()
        self.cards_label = QLabel(self._t("Digite seus cards:"))
        cards_header_layout.addWidget(self.cards_label)
        cards_header_layout.addStretch()
        cards_layout.addLayout(cards_header_layout)
        
        self.stacked_editor = QStackedWidget()

        self.txt_entrada = QTextEdit()
        self.txt_entrada.setUndoRedoEnabled(True)
        self.txt_entrada.setPlaceholderText(self._t("Digite seus cards aqui..."))
        
        self.highlighter = HtmlTagHighlighter(self.txt_entrada.document())
        
        self.txt_entrada.line_number_area = LineNumberArea(self.txt_entrada)
        self.txt_entrada.line_number_area_width = self.line_number_area_width
        self.txt_entrada.textChanged.connect(self.update_line_number_area_width)
        self.txt_entrada.verticalScrollBar().valueChanged.connect(lambda: self.txt_entrada.line_number_area.update())
        self.txt_entrada.cursorPositionChanged.connect(self.highlight_current_line)
        self.txt_entrada.resizeEvent = lambda event: self.custom_resize_event(event)
        self.txt_entrada.textChanged.connect(self.schedule_save)
        self.txt_entrada.textChanged.connect(self.update_tags_lines)
        self.txt_entrada.textChanged.connect(self.update_preview)
        self.txt_entrada.textChanged.connect(self.update_card_count)
        self.txt_entrada.textChanged.connect(self.update_line_numbers)
        self.txt_entrada.textChanged.connect(self.clear_creation_info_on_edit)
        self.txt_entrada.cursorPositionChanged.connect(self.check_line_change)
        self.txt_entrada.installEventFilter(self)
        self.txt_entrada.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.txt_entrada.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.txt_entrada.setAcceptDrops(True)
        self.txt_entrada.dropEvent = self.drop_event

        self.txt_entrada.textChanged.connect(self.schedule_real_time_edit)
        self.txt_entrada.textChanged.connect(self._check_for_state_reset)
        # <<< INÍCIO DA MODIFICAÇÃO PRINCIPAL >>>
        self.txt_entrada.textChanged.connect(self._force_semicolon_on_cloze_lines)
        # <<< FIM DA MODIFICAÇÃO PRINCIPAL >>>
       
        self.stacked_editor.addWidget(self.txt_entrada)

        self.table_widget = QTableWidget()
        self.table_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_widget.customContextMenuRequested.connect(self.show_table_context_menu)
        self.stacked_editor.addWidget(self.table_widget)

        cards_layout.addWidget(self.stacked_editor)
        
        cards_tags_layout.addWidget(self.cards_group, stretch=2)
        
        self.etiquetas_group = QWidget()
        etiquetas_layout = QVBoxLayout(self.etiquetas_group)
        etiquetas_header_layout = QHBoxLayout()
        self.tags_label = QLabel(self._t("Etiquetas:"))
        etiquetas_header_layout.addWidget(self.tags_label)
        etiquetas_header_layout.addStretch()
        etiquetas_layout.addLayout(etiquetas_header_layout)
        self.txt_tags = QTextEdit()
        self.txt_tags.setUndoRedoEnabled(True)
        self.txt_tags.setPlaceholderText(self._t("Digite as etiquetas aqui (uma linha por card)..."))
        self.txt_tags.setMaximumWidth(200)
        self.txt_tags.textChanged.connect(self.schedule_save)
        self.txt_tags.textChanged.connect(self.update_preview)
        self.txt_tags.installEventFilter(self)
        self.txt_tags.textChanged.connect(self.schedule_real_time_edit) 

        etiquetas_layout.addWidget(self.txt_tags)
        self.etiquetas_group.setVisible(False)
        cards_tags_layout.addWidget(self.etiquetas_group, stretch=1)
        
        self.fields_splitter.addWidget(self.cards_tags_widget)
        
        self.preview_group = QWidget()
        preview_layout = QVBoxLayout(self.preview_group)
        
        preview_header_layout = QHBoxLayout()
        self.preview_label = QLabel(self._t("Preview:"))
        preview_header_layout.addWidget(self.preview_label)
        preview_header_layout.addStretch()
        
        self.zoom_in_preview_button = ForceLabelButton("+", parent=self)
        self.zoom_in_preview_button.clicked.connect(self.zoom_in_preview)
        self.zoom_in_preview_button.setFixedSize(30, 30)
        preview_header_layout.addWidget(self.zoom_in_preview_button)
        
        self.zoom_out_preview_button = ForceLabelButton("-", parent=self)
        self.zoom_out_preview_button.clicked.connect(self.zoom_out_preview)
        self.zoom_out_preview_button.setFixedSize(30, 30)
        preview_header_layout.addWidget(self.zoom_out_preview_button)
        
        preview_layout.addLayout(preview_header_layout)
        
        self.preview_widget = AnkiWebView(self)
        
        settings = self.preview_widget.settings()
        for attr in [QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
                     QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
                     QWebEngineSettings.WebAttribute.AllowRunningInsecureContent]:
            settings.setAttribute(attr, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        self.preview_widget.setMinimumWidth(0)
        preview_layout.addWidget(self.preview_widget)
        
        self.fields_splitter.addWidget(self.preview_group)
        self.fields_splitter.setSizes([700, 300])
        self.fields_splitter.setChildrenCollapsible(True)
        self.fields_splitter.setStretchFactor(0, 1)
        self.fields_splitter.setStretchFactor(1, 0)
        
        top_layout.addWidget(self.fields_splitter, 1)
        
        options_layout = QHBoxLayout()
        options_layout.addStretch()
        self.chk_num_tags = QCheckBox(self._t("Numerar Tags"))
        self.chk_repetir_tags = QCheckBox(self._t("Repetir Tags"))
        self.chk_num_tags.stateChanged.connect(self.update_tag_numbers)
        self.chk_num_tags.stateChanged.connect(self.schedule_save)
        self.chk_repetir_tags.stateChanged.connect(self.update_repeated_tags)
        self.chk_repetir_tags.stateChanged.connect(self.schedule_save)
        options_layout.addWidget(self.chk_num_tags)
        options_layout.addWidget(self.chk_repetir_tags)
        
        self.toggle_tags_button = QPushButton(self._t("Mostrar Etiquetas"), self)
        self.toggle_tags_button.clicked.connect(self.toggle_tags)
        options_layout.addWidget(self.toggle_tags_button)
        
        self.theme_button = QPushButton(self._t("Mudar Tema"), self)
        self.theme_button.clicked.connect(self.toggle_theme)
        options_layout.addWidget(self.theme_button)
        
        top_layout.addLayout(options_layout)
        self.vertical_splitter.addWidget(top_widget)
        
        self.main_scroll = QScrollArea()
        self.main_scroll.setWidgetResizable(True)
        self.main_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        
        bottom_scroll = QScrollArea()
        bottom_scroll.setWidgetResizable(True)
        bottom_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        
        # --- INÍCIO DA MODIFICAÇÃO: ABAS DE FERRAMENTAS ---
        self.tool_tabs = QTabWidget()
        self.tool_tabs.currentChanged.connect(self.schedule_save) # Salva a aba selecionada

        # --- Aba 1: Cards e Mídia ---
        cards_media_tab = QWidget()
        cards_media_layout = QVBoxLayout(cards_media_tab)
        cards_media_layout.setContentsMargins(5, 10, 5, 10)

        cards_media_row1_layout = QHBoxLayout()
        self.show_button = QPushButton(self._t("Mostrar"), self)
        self.show_button.clicked.connect(self.show_all_cards)
        self.show_button.setToolTip(self._t("Mostra todos os cards do deck em 'Digite seus cards'"))
        cards_media_row1_layout.addWidget(self.show_button)

        self.edit_button = QPushButton(self._t("Editar"), self)
        self.edit_button.clicked.connect(self.toggle_edit_mode)
        self.edit_button.setToolTip(self._t("Ativa/desativa a edição em tempo real dos cards mostrados."))
        cards_media_row1_layout.addWidget(self.edit_button)

        self.view_cards_button = QPushButton(self._t("Visualizar Cards"), self)
        self.view_cards_button.clicked.connect(self.view_cards_dialog)
        cards_media_row1_layout.addWidget(self.view_cards_button)
        cards_media_layout.addLayout(cards_media_row1_layout)

        cards_media_row2_layout = QHBoxLayout()
        self.image_button = QPushButton(self._t("Adicionar Imagem, Som ou Vídeo"), self)
        self.image_button.clicked.connect(self.add_image)
        cards_media_row2_layout.addWidget(self.image_button)

        self.manage_media_button = QPushButton(self._t("Gerenciar Mídia"), self)
        self.manage_media_button.clicked.connect(self.manage_media)
        cards_media_row2_layout.addWidget(self.manage_media_button)

        self.export_html_button = QPushButton(self._t("Exportar para HTML"), self)
        self.export_html_button.clicked.connect(self.export_to_html)
        self.export_html_button.setToolTip(self._t("Exportar cards para arquivo HTML"))
        cards_media_row2_layout.addWidget(self.export_html_button)
        cards_media_layout.addLayout(cards_media_row2_layout)
        self.tool_tabs.addTab(cards_media_tab, self._t("Cards e Mídia"))

        # --- Aba 2: Formatação ---
        formatting_tab = QWidget()
        formatting_layout = QVBoxLayout(formatting_tab)
        formatting_layout.setContentsMargins(5, 10, 5, 10)

        text_format_layout = QHBoxLayout()
        self.botoes_formatacao_widgets = {} 
        
        btn_bold = QPushButton(self._t("B"))
        btn_bold.clicked.connect(self.apply_bold)
        btn_bold.setToolTip(self._t("Negrito (Ctrl+B)"))
        text_format_layout.addWidget(btn_bold)
        self.botoes_formatacao_widgets["B"] = btn_bold

        btn_italic = QPushButton(self._t("I"))
        btn_italic.clicked.connect(self.apply_italic)
        btn_italic.setToolTip(self._t("Itálico (Ctrl+I)"))
        text_format_layout.addWidget(btn_italic)
        self.botoes_formatacao_widgets["I"] = btn_italic

        btn_underline = QPushButton(self._t("U"))
        btn_underline.clicked.connect(self.apply_underline)
        btn_underline.setToolTip(self._t("Sublinhado (Ctrl+U)"))
        text_format_layout.addWidget(btn_underline)
        self.botoes_formatacao_widgets["U"] = btn_underline

        btn_destaque = QPushButton(self._t("Destaque"))
        btn_destaque.clicked.connect(self.destaque_texto)
        btn_destaque.setToolTip(self._t("Destacar texto (Ctrl+M)"))
        text_format_layout.addWidget(btn_destaque)
        self.botoes_formatacao_widgets["Destaque"] = btn_destaque
        formatting_layout.addLayout(text_format_layout)

        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel(self._t("Cor Texto:")))
        self.color_buttons = []
        for color in ["red", "blue", "green", "yellow"]:
            btn = ForceLabelButton("A", text_color=QColor(color))
            btn.setStyleSheet("background-color: black;")
            btn.setFixedSize(30, 30)
            btn.clicked.connect(lambda checked, c=color: self.apply_text_color(c))
            btn.setToolTip(self._t("Aplicar cor ao texto"))
            color_layout.addWidget(btn)
            self.color_buttons.append(btn)
        color_layout.addStretch()
        color_layout.addWidget(QLabel(self._t("Cor Fundo:")))
        self.bg_color_buttons = []
        for color in ["red", "blue", "green", "yellow"]:
            btn = ForceLabelButton("Af", text_color=Qt.GlobalColor.black)
            btn.setStyleSheet(f"background-color: {color};")
            btn.setFixedSize(30, 30)
            btn.clicked.connect(lambda checked, c=color: self.apply_background_color(c))
            btn.setToolTip(self._t("Aplicar cor de fundo ao texto"))
            color_layout.addWidget(btn)
            self.bg_color_buttons.append(btn)
        formatting_layout.addLayout(color_layout)

        cloze_layout = QHBoxLayout()
        self.cloze_buttons_defs = [
            ("Cloze 1 (Ctrl+Shift+D)", self.add_cloze_1, "Adicionar Cloze 1 (Ctrl+Shift+D)"),
            ("Cloze 2 (Ctrl+Shift+F)", self.add_cloze_2, "Adicionar Cloze 2 (Ctrl+Shift+F)"),
            ("Remover Cloze", self.remove_cloze, "Remover Cloze (sem atalho)")
        ]
        self.cloze_buttons_widgets = []
        for text, func, tooltip in self.cloze_buttons_defs:
            btn = QPushButton(self._t(text), self)
            btn.clicked.connect(func)
            btn.setToolTip(self._t(tooltip))
            cloze_layout.addWidget(btn)
            self.cloze_buttons_widgets.append(btn)
        formatting_layout.addLayout(cloze_layout)
        self.tool_tabs.addTab(formatting_tab, self._t("Formatação"))

        # --- Aba 3: Organizar e Ações ---
        organize_actions_tab = QWidget()
        organize_actions_layout = QVBoxLayout(organize_actions_tab)
        organize_actions_layout.setContentsMargins(5, 10, 5, 10)

        sort_layout = QHBoxLayout()
        self.botoes_organizacao_widgets = {}
        botoes_organizacao_defs = [
            ("Juntar Linhas", self.join_lines, "Juntar todas as linhas"),
            ("Ordem Alfabética", self.sort_cards_alphabetically, "Organizar cards em ordem alfabética (A-Z / Z-A)"),
            ("Ordem de Criação", self.sort_cards_by_creation_date, "Organizar por data de criação e mostrar/ocultar data"),
            ("Ordem Aleatória", self.sort_cards_randomly, "Organizar cards em ordem aleatória"),
            ("Mais Errados", self.sort_cards_by_lapses, "Organizar por cards mais errados (com mais lapsos)"),
        ]
        for texto, funcao, tooltip in botoes_organizacao_defs:
            btn = QPushButton(self._t(texto))
            btn.clicked.connect(funcao)
            btn.setToolTip(self._t(tooltip))
            sort_layout.addWidget(btn)
            self.botoes_organizacao_widgets[texto] = btn
            if texto == "Mais Errados": self.mais_errados_button = btn
        organize_actions_layout.addLayout(sort_layout)

        general_actions_layout = QHBoxLayout()
        self.botoes_acoes_widgets = {}
        botoes_acoes_defs = [
            ("Concatenar", self.concatenate_text, "Concatenar texto"),
            ("Limpar Tudo", self.clear_all, "Limpar todos os campos e configurações"),
            ("Desfazer", self.restore_pre_show_state, "Desfazer (Ctrl+Z)"),
            ("Refazer", self.txt_entrada.redo, "Refazer (Ctrl+Y)"),
        ]
        for texto, funcao, tooltip in botoes_acoes_defs:
            btn = QPushButton(self._t(texto))
            btn.clicked.connect(funcao)
            btn.setToolTip(self._t(tooltip))
            general_actions_layout.addWidget(btn)
            self.botoes_acoes_widgets[texto] = btn
        organize_actions_layout.addLayout(general_actions_layout)
        self.tool_tabs.addTab(organize_actions_tab, self._t("Organizar e Ações"))

        # --- Aba 4: Busca e Visualização ---
        search_view_tab = QWidget()
        search_view_layout = QVBoxLayout(search_view_tab)
        search_view_layout.setContentsMargins(5, 10, 5, 10)

        search_layout = QHBoxLayout()
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText(self._t("Pesquisar... Ctrl+P"))
        search_layout.addWidget(self.search_input)
        self.search_button = QPushButton(self._t("Pesquisar"), self)
        self.search_button.clicked.connect(self.search_text)
        search_layout.addWidget(self.search_button)
        self.replace_input = QLineEdit(self)
        self.replace_input.setPlaceholderText(self._t("Substituir tudo por... Ctrl+Shift+R"))
        search_layout.addWidget(self.replace_input)
        self.replace_button = QPushButton(self._t("Substituir Tudo"), self)
        self.replace_button.clicked.connect(self.replace_text)
        search_layout.addWidget(self.replace_button)
        search_view_layout.addLayout(search_layout)

        view_mode_layout = QHBoxLayout()
        view_mode_layout.addWidget(QLabel(self._t("Zoom Texto:")))
        self.zoom_in_button = QPushButton("+", self)
        self.zoom_in_button.clicked.connect(self.zoom_in)
        view_mode_layout.addWidget(self.zoom_in_button)
        self.zoom_out_button = QPushButton("-", self)
        self.zoom_out_button.clicked.connect(self.zoom_out)
        view_mode_layout.addWidget(self.zoom_out_button)
        view_mode_layout.addStretch()
        self.toggle_view_button = QPushButton(self._t("📝 Editar em Grade"))
        self.toggle_view_button.setToolTip(self._t("Alterna entre a edição de texto livre e uma grade estilo planilha."))
        self.toggle_view_button.clicked.connect(self.toggle_editor_view)
        view_mode_layout.addWidget(self.toggle_view_button)
        search_view_layout.addLayout(view_mode_layout)
        self.tool_tabs.addTab(search_view_tab, self._t("Busca e Visualização"))

        bottom_layout.addWidget(self.tool_tabs)
        # --- FIM DA MODIFICAÇÃO: ABAS DE FERRAMENTAS ---

        self.group_widget = QWidget()
        group_layout = QVBoxLayout(self.group_widget)
        self.group_splitter = QSplitter(Qt.Orientation.Vertical)
        decks_modelos_widget = QWidget()
        decks_modelos_layout = QVBoxLayout(decks_modelos_widget)
        self.decks_modelos_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        deck_count = len(mw.col.decks.all_names_and_ids())
        self.decks_group = QGroupBox(self._t("Decks: {}").format(deck_count))
        decks_layout = QVBoxLayout(self.decks_group)
        self.lista_decks = self.criar_lista_rolavel([d.name for d in mw.col.decks.all_names_and_ids()], 100)
        self.lista_decks.currentItemChanged.connect(self.schedule_save)
        decks_layout.addWidget(self.lista_decks)

        deck_controls_layout = QHBoxLayout()
        self.decks_search_input = QLineEdit(self)
        self.decks_search_input.setPlaceholderText(self._t("Pesquisar decks..."))
        self.decks_search_input.textChanged.connect(self.filter_decks)
        deck_controls_layout.addWidget(self.decks_search_input)
        self.deck_name_input = QLineEdit(self)
        self.deck_name_input.setPlaceholderText(self._t("Digite o nome do novo deck..."))
        deck_controls_layout.addWidget(self.deck_name_input)
        self.create_deck_button = QPushButton(self._t("Criar Deck"), self)
        self.create_deck_button.clicked.connect(self.create_deck)
        deck_controls_layout.addWidget(self.create_deck_button)
        self.delete_deck_button = QPushButton(self._t("Excluir Deck"), self)
        self.delete_deck_button.clicked.connect(self.delete_deck)
        deck_controls_layout.addWidget(self.delete_deck_button)
        decks_layout.addLayout(deck_controls_layout)

        self.decks_modelos_splitter.addWidget(self.decks_group)
        notetype_count = len(mw.col.models.all_names())
        self.modelos_group = QGroupBox(self._t("Modelos ou Tipos de Notas: {}").format(notetype_count))
        modelos_layout = QVBoxLayout(self.modelos_group)
        self.lista_notetypes = self.criar_lista_rolavel(mw.col.models.all_names(), 100)
        self.lista_notetypes.currentItemChanged.connect(self.update_field_mappings)
        self.lista_notetypes.currentItemChanged.connect(self.update_preview)
        self.lista_notetypes.currentItemChanged.connect(self.schedule_save)
        modelos_layout.addWidget(self.lista_notetypes)
        self.notetypes_search_input = QLineEdit(self)
        self.notetypes_search_input.setPlaceholderText(self._t("Pesquisar tipos de notas..."))
        self.notetypes_search_input.textChanged.connect(self.filter_notetypes)
        modelos_layout.addWidget(self.notetypes_search_input)
        self.decks_modelos_splitter.addWidget(self.modelos_group)
        self.decks_modelos_splitter.setSizes([200, 150])
        decks_modelos_layout.addWidget(self.decks_modelos_splitter)
        self.group_splitter.addWidget(decks_modelos_widget)
        self.fields_group = QGroupBox(self._t("Mapeamento de Campos"))
        fields_layout = QVBoxLayout(self.fields_group)
        self.fields_map_label = QLabel(self._t("Associe cada parte a um campo:"))
        fields_layout.addWidget(self.fields_map_label)
        self.fields_container = QWidget()
        self.fields_container_layout = QVBoxLayout(self.fields_container)
        self.field_combo_boxes = []
        self.field_image_buttons = {}
        fields_layout.addWidget(self.fields_container)
        self.group_splitter.addWidget(self.fields_group)
        self.delimitadores_widget = QWidget() 
        delimitadores_layout = QVBoxLayout(self.delimitadores_widget)
        self.delimitadores_label = QLabel(self._t("Delimitadores:"))
        delimitadores_layout.addWidget(self.delimitadores_label)
        delimitadores = [("Tab", "\t"), ("Vírgula", ","), ("Ponto e Vírgula", ";"), ("Dois Pontos", ":"),
                         ("Interrogação", "?"), ("Barra", "/"), ("Exclamação", "!"), ("Pipe", "|")]
        grid = QGridLayout()
        self.chk_delimitadores = {}
        for i, (nome, simbolo) in enumerate(delimitadores):
            chk = QCheckBox(self._t(nome))
            chk.simbolo = simbolo
            chk.stateChanged.connect(self.update_preview)
            chk.stateChanged.connect(self.schedule_save)
            grid.addWidget(chk, i // 4, i % 4)
            self.chk_delimitadores[nome] = chk
        delimitadores_layout.addLayout(grid)
        self.group_splitter.addWidget(self.delimitadores_widget)
        self.group_splitter.setSizes([150, 150, 100])
        group_layout.addWidget(self.group_splitter)
        bottom_layout.addWidget(self.group_widget)
        
        bottom_buttons_layout = QHBoxLayout()
        
        self.btn_toggle_formatting = QPushButton(self._t("Ocultar Ferramentas"))
        self.btn_toggle_formatting.clicked.connect(self.toggle_formatting_tools)
        bottom_buttons_layout.addWidget(self.btn_toggle_formatting)

        self.btn_toggle = QPushButton(self._t("Ocultar Decks/Modelos/Delimitadores"))
        self.btn_toggle.clicked.connect(self.toggle_group)
        bottom_buttons_layout.addWidget(self.btn_toggle)
        
        self.btn_add = QPushButton(self._t("Adicionar Cards (Ctrl+R)"))
        self.btn_add.clicked.connect(self.add_cards)
        self.btn_add.setToolTip(self._t("Adicionar Cards (Ctrl+R)"))
        bottom_buttons_layout.addWidget(self.btn_add)
        
        bottom_layout.addLayout(bottom_buttons_layout)
        bottom_layout.addStretch()
        
        bottom_scroll.setWidget(bottom_widget)
        scroll_layout.addWidget(bottom_scroll)
        self.main_scroll.setWidget(scroll_content)
        self.vertical_splitter.addWidget(self.main_scroll)
        self.vertical_splitter.setSizes([300, 300])
        self.vertical_splitter.setChildrenCollapsible(False)
        
        main_layout.addWidget(self.vertical_splitter)
        self.setLayout(main_layout)
        
        self.txt_entrada.setMinimumHeight(100)
        self.vertical_splitter.setMinimumSize(800, 600)
        self.fields_splitter.setMinimumSize(400, 200)
        
        self.vertical_splitter.splitterMoved.connect(self.handle_splitter_move)
        self.fields_splitter.splitterMoved.connect(self.handle_splitter_move)
        self.resizeEvent = self.handle_resize
        self.vertical_splitter.splitterMoved.connect(self.schedule_save)
        self.fields_splitter.splitterMoved.connect(self.schedule_save)
        
        for key, func in [
            ("Ctrl+B", "apply_bold"), ("Ctrl+I", "apply_italic"), ("Ctrl+U", "apply_underline"),
            ("Ctrl+M", "destaque_texto"), ("Ctrl+P", "search_text"), ("Ctrl+Shift+R", "replace_text"),
            ("Ctrl+=", "zoom_in"), ("Ctrl+-", "zoom_out"), ("Ctrl+Shift+D", "add_cloze_1"),
            ("Ctrl+Shift+F", "add_cloze_2"), ("Ctrl+R", "add_cards"), ("Ctrl+Z", "restore_pre_show_state"), ("Ctrl+Y", "redo")
        ]:
            QShortcut(QKeySequence(key), self).activated.connect(lambda f=func: self.log_shortcut(f))
        
        self.txt_entrada.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.txt_entrada.customContextMenuRequested.connect(self.show_context_menu)
        self.txt_entrada.setAcceptDrops(True)
        self.txt_entrada.focusInEvent = self.create_focus_handler(self.txt_entrada, "cards")
        self.txt_tags.focusInEvent = self.create_focus_handler(self.txt_tags, "tags")
        self.txt_entrada.textChanged.connect(self.update_line_numbers)
        
        # Aplica o tema inicial
        self.toggle_theme()
        self.toggle_theme()

    # <<< INÍCIO DA NOVA FUNÇÃO >>>
    def _force_semicolon_on_cloze_lines(self):
        """
        Verifica o texto em tempo real e força a adição de um ponto e vírgula
        no final das linhas que contêm a sintaxe de cloze.
        """
        # Armazena a posição original do cursor para restaurá-la depois
        cursor = self.txt_entrada.textCursor()
        original_pos = cursor.position()

        full_text = self.txt_entrada.toPlainText()
        lines = full_text.split('\n')
        new_lines = []
        text_was_modified = False

        for line in lines:
            # Verifica se a linha contém um padrão cloze
            if re.search(r'{{c\d+::.*?}}', line):
                # Verifica se a linha (ignorando espaços em branco no final) já termina com ;
                if not line.rstrip().endswith(';'):
                    new_lines.append(line + ';')
                    text_was_modified = True
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)

        # Apenas atualiza o texto se uma alteração foi realmente feita
        # Isso evita um loop infinito de sinais textChanged
        if text_was_modified:
            updated_text = '\n'.join(new_lines)
            
            # Bloqueia os sinais para evitar que esta função seja chamada novamente ao definir o texto
            self.txt_entrada.blockSignals(True)
            self.txt_entrada.setPlainText(updated_text)
            self.txt_entrada.blockSignals(False)
            
            # Restaura a posição do cursor para não interromper a digitação do usuário
            cursor.setPosition(original_pos)
            self.txt_entrada.setTextCursor(cursor)
    # <<< FIM DA NOVA FUNÇÃO >>>

    def toggle_beginner_mode(self):
        """Alterna a visibilidade da interface entre o modo completo e o iniciante."""
        self.is_beginner_mode = not self.is_beginner_mode
        
        is_advanced_visible = not self.is_beginner_mode

        if self.is_beginner_mode:
            self.btn_beginner_mode.setText(self._t("Modo Completo"))
            self.btn_beginner_mode.setToolTip(self._t("Mostra todas as ferramentas avançadas."))
        else:
            self.btn_beginner_mode.setText(self._t("Modo Iniciante"))
            self.btn_beginner_mode.setToolTip(self._t("Simplifica a interface para mostrar apenas as funções essenciais."))

        self.btn_instructions.setVisible(self.is_beginner_mode)

        widgets_to_hide = [
            self.save_status_label, self.separator_label, self.card_count_label,
            self.cards_label,
            self.chk_num_tags, self.chk_repetir_tags, self.toggle_tags_button, self.theme_button,
            self.tool_tabs, # Oculta o widget de abas inteiro
            self.fields_group, self.delimitadores_widget,
            self.decks_search_input, self.deck_name_input, self.create_deck_button, self.delete_deck_button,
            self.notetypes_search_input,
            self.btn_toggle_formatting, self.btn_toggle,
            self.zoom_in_preview_button, self.zoom_out_preview_button, self.preview_label
        ]
        
        for widget in widgets_to_hide:
            widget.setVisible(is_advanced_visible)

        if self.is_beginner_mode:
            self.tags_visible_before_beginner_mode = self.etiquetas_group.isVisible()
            self.etiquetas_group.setVisible(False)
        else:
            self.etiquetas_group.setVisible(self.tags_visible_before_beginner_mode)

    def show_instructions_dialog(self):
        """Mostra uma caixa de mensagem com as instruções do modo iniciante."""
        title = self._t("instructions_title")
        text = (
            f"<p>{self._t('beginner_instructions_line1')}</p>"
            f"<p>{self._t('beginner_instructions_line2')}</p>"
            f"<p><b>{self._t('beginner_instructions_example_title')}</b><br>"
            f"<em>{self._t('beginner_instructions_example_text')}</em></p>"
        )
        QMessageBox.information(self, title, text)

    def switch_language(self, index):
        lang_map = {
            0: 'pt', 1: 'en', 2: 'es', 3: 'it', 4: 'hi', 
            5: 'fr', 6: 'de', 7: 'zh', 8: 'ru', 9: 'ar',
            10: 'id', 11: 'jp'
        }
        new_lang = lang_map.get(index)
        if new_lang and new_lang != self.current_language:
            self.current_language = new_lang
            self.retranslate_ui()
            self.schedule_save()

    def load_settings(self):
        logging.debug("Carregando configurações do arquivo")
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    dados = json.load(f)
                    self.current_language = dados.get('language', 'pt')
                    lang_index_map = {
                        'pt': 0, 'en': 1, 'es': 2, 'it': 3, 'hi': 4, 
                        'fr': 5, 'de': 6, 'zh': 7, 'ru': 8, 'ar': 9,
                        'id': 10, 'jp': 11
                    }
                    self.lang_combo.setCurrentIndex(lang_index_map.get(self.current_language, 0))

                    # Carrega a última aba selecionada
                    last_tab_index = dados.get('last_tab_index', 0)
                    if last_tab_index < self.tool_tabs.count():
                        self.tool_tabs.setCurrentIndex(last_tab_index)

                    conteudo = dados.get('conteudo', '')
                    logging.debug(f"Conteúdo carregado do CONFIG_FILE: '{conteudo}'")
                    self.real_text = conteudo
                    self.txt_entrada.setPlainText(conteudo)
                    self.previous_text = conteudo
                    self.txt_tags.setPlainText(dados.get('tags', ''))
                    for nome, estado in dados.get('delimitadores', {}).items():
                        if nome in self.chk_delimitadores:
                            self.chk_delimitadores[nome].setChecked(estado)
                    if 'window_geometry' in dados:
                        geo = dados['window_geometry']
                        self.resize(*geo.get('size', (1000, 600)))
                        self.move(*geo.get('pos', (100, 100)))
                        self.vertical_splitter.setSizes(geo.get('vertical_splitter', [300, 300]))
                        self.fields_splitter.setSizes(geo.get('fields_splitter', [700, 300]))
                    for key, lista in [('deck_selecionado', self.lista_decks), ('modelo_selecionado', self.lista_notetypes)]:
                        if dados.get(key):
                            items = lista.findItems(dados[key], Qt.MatchFlag.MatchExactly)
                            if items:
                                lista.setCurrentItem(items[0])
                    self.field_mappings = dados.get('field_mappings', {})
                    self.field_images = dados.get('field_images', {})
                    self.last_preview_html = dados.get('last_preview_html', '')
                    if self.last_preview_html:
                        self.preview_widget.setHtml(self.last_preview_html)
                    self.update_field_mappings()
                    self.update_line_numbers()
                    self.update_card_count()
                    logging.debug(f"Configurações carregadas: {dados}")
            except Exception as e:
                logging.error(f"Erro ao carregar configurações: {str(e)}")
                showWarning(self._t("Erro ao carregar configurações: {}").format(str(e)))
        else:
            logging.debug("Arquivo CONFIG_FILE não encontrado")
            self.real_text = ""
            self.last_preview_html = ""
            self.update_line_numbers()
            self.update_card_count()

    def retranslate_ui(self):
        """Atualiza todo o texto da UI para o idioma atual."""
        self.setWindowTitle(self._t("Adicionar Cards com Delimitadores"))
        self.lang_label.setText(self._t("Idioma:"))
        self.save_status_label.setText(self._t("Pronto"))
        self.update_card_count()
        
        # Aba 1: Cards e Mídia
        self.tool_tabs.setTabText(0, self._t("Cards e Mídia"))
        self.image_button.setText(self._t("Adicionar Imagem, Som ou Vídeo"))
        self.manage_media_button.setText(self._t("Gerenciar Mídia"))
        self.export_html_button.setText(self._t("Exportar para HTML"))
        self.export_html_button.setToolTip(self._t("Exportar cards para arquivo HTML"))
        self.view_cards_button.setText(self._t("Visualizar Cards"))
        self.show_button.setText(self._t("Mostrar"))
        self.show_button.setToolTip(self._t("Mostra todos os cards do deck em 'Digite seus cards'"))
        if self.edit_mode:
            self.edit_button.setText(self._t("Parar Edição"))
        else:
            self.edit_button.setText(self._t("Editar"))
        self.edit_button.setToolTip(self._t("Ativa/desativa a edição em tempo real dos cards mostrados."))

        # Aba 2: Formatação
        self.tool_tabs.setTabText(1, self._t("Formatação"))
        self.botoes_formatacao_widgets["B"].setToolTip(self._t("Negrito (Ctrl+B)"))
        self.botoes_formatacao_widgets["I"].setToolTip(self._t("Itálico (Ctrl+I)"))
        self.botoes_formatacao_widgets["U"].setToolTip(self._t("Sublinhado (Ctrl+U)"))
        self.botoes_formatacao_widgets["Destaque"].setText(self._t("Destaque"))
        self.botoes_formatacao_widgets["Destaque"].setToolTip(self._t("Destacar texto (Ctrl+M)"))
        for btn in self.color_buttons: btn.setToolTip(self._t("Aplicar cor ao texto"))
        for btn in self.bg_color_buttons: btn.setToolTip(self._t("Aplicar cor de fundo ao texto"))
        for i, btn in enumerate(self.cloze_buttons_widgets):
            text, _, tooltip = self.cloze_buttons_defs[i]
            btn.setText(self._t(text))
            btn.setToolTip(self._t(tooltip))

        # Aba 3: Organizar e Ações
        self.tool_tabs.setTabText(2, self._t("Organizar e Ações"))
        for texto, btn in self.botoes_organizacao_widgets.items():
            if texto == "Mais Errados": continue
            btn.setText(self._t(texto))
        for texto, btn in self.botoes_acoes_widgets.items():
            btn.setText(self._t(texto))
        if hasattr(self, 'lapses_sort_descending') and not self.lapses_sort_descending:
            self.mais_errados_button.setText(self._t("Mais Certos"))
            self.mais_errados_button.setToolTip(self._t("Organizar por cards mais certos (com menos lapsos)"))
        else:
            self.mais_errados_button.setText(self._t("Mais Errados"))
            self.mais_errados_button.setToolTip(self._t("Organizar por cards mais errados (com mais lapsos)"))

        # Aba 4: Busca e Visualização
        self.tool_tabs.setTabText(3, self._t("Busca e Visualização"))
        self.search_input.setPlaceholderText(self._t("Pesquisar... Ctrl+P"))
        self.search_button.setText(self._t("Pesquisar"))
        self.replace_input.setPlaceholderText(self._t("Substituir tudo por... Ctrl+Shift+R"))
        self.replace_button.setText(self._t("Substituir Tudo"))
        self.toggle_view_button.setText(self._t("📝 Editar em Grade") if self.stacked_editor.currentIndex() == 0 else self._t("📄 Editar como Texto"))
        self.toggle_view_button.setToolTip(self._t("Alterna entre a edição de texto livre e uma grade estilo planilha."))

        # Outros elementos da UI
        self.cards_label.setText(self._t("Digite seus cards:"))
        self.txt_entrada.setPlaceholderText(self._t("Digite seus cards aqui..."))
        self.tags_label.setText(self._t("Etiquetas:"))
        self.txt_tags.setPlaceholderText(self._t("Digite as etiquetas aqui (uma linha por card)..."))
        self.preview_label.setText(self._t("Preview:"))
        self.chk_num_tags.setText(self._t("Numerar Tags"))
        self.chk_repetir_tags.setText(self._t("Repetir Tags"))
        is_visible = self.etiquetas_group.isVisible()
        self.toggle_tags_button.setText(self._t("Ocultar Etiquetas") if is_visible else self._t("Mostrar Etiquetas"))
        self.theme_button.setText(self._t("Mudar Tema"))
        
        deck_count = len(mw.col.decks.all_names_and_ids())
        self.decks_group.setTitle(self._t("Decks: {}").format(deck_count))
        self.decks_search_input.setPlaceholderText(self._t("Pesquisar decks..."))
        self.deck_name_input.setPlaceholderText(self._t("Digite o nome do novo deck..."))
        self.create_deck_button.setText(self._t("Criar Deck"))
        self.delete_deck_button.setText(self._t("Excluir Deck"))
        
        notetype_count = len(mw.col.models.all_names())
        self.modelos_group.setTitle(self._t("Modelos ou Tipos de Notas: {}").format(notetype_count))
        self.notetypes_search_input.setPlaceholderText(self._t("Pesquisar tipos de notas..."))
        
        self.fields_group.setTitle(self._t("Mapeamento de Campos"))
        self.fields_map_label.setText(self._t("Associe cada parte a um campo:"))
        
        self.delimitadores_label.setText(self._t("Delimitadores:"))
        for nome, chk in self.chk_delimitadores.items():
            chk.setText(self._t(nome))

        is_group_visible = self.group_widget.isVisible()
        self.btn_toggle.setText(self._t("Ocultar Decks/Modelos/Delimitadores") if is_group_visible else self._t("Mostrar Decks/Modelos/Delimitadores"))
        
        is_formatting_visible = self.tool_tabs.isVisible()
        self.btn_toggle_formatting.setText(self._t("Ocultar Ferramentas") if is_formatting_visible else self._t("Mostrar Ferramentas"))

        if self.is_beginner_mode:
            self.btn_beginner_mode.setText(self._t("Modo Completo"))
            self.btn_beginner_mode.setToolTip(self._t("Mostra todas as ferramentas avançadas."))
        else:
            self.btn_beginner_mode.setText(self._t("Modo Iniciante"))
            self.btn_beginner_mode.setToolTip(self._t("Simplifica a interface para mostrar apenas as funções essenciais."))

        self.btn_instructions.setText(self._t("instructions_button"))
        self.btn_add.setText(self._t("Adicionar Cards (Ctrl+R)"))
        self.btn_add.setToolTip(self._t("Adicionar Cards (Ctrl+R)"))

        self.update_preview()
        self.update_field_mappings()


    def zoom_in_preview(self):
        current_zoom = self.preview_widget.zoomFactor()
        self.preview_widget.setZoomFactor(current_zoom + 0.1)
    
    def zoom_out_preview(self):
        current_zoom = self.preview_widget.zoomFactor()
        self.preview_widget.setZoomFactor(max(0.1, current_zoom - 0.1))

    def handle_splitter_move(self, pos, index):
        self.txt_entrada.updateGeometry()
        self.txt_entrada.line_number_area.update()

    def handle_resize(self, event):
        QDialog.resizeEvent(self, event)
        self.schedule_save()

    def log_shortcut(self, func_name):
        logging.debug(f"Atalho acionado: {func_name}")
        if func_name in ["undo", "redo"]:
            getattr(self.txt_entrada, func_name)()
        else:
            getattr(self, func_name)()

    def schedule_save(self):
        self.save_status_label.setText(self._t("Salvando..."))
        self.save_status_label.setStyleSheet("color: orange;")
        self.save_timer.start(500)

    def update_card_count(self):
        text = self.txt_entrada.toPlainText()
        lines = text.splitlines()
        
        active_delimiters = [chk.simbolo for chk in self.chk_delimitadores.values() if chk.isChecked()]
        if not active_delimiters:
            active_delimiters = [';']
        
        card_count = 0
        for line in lines:
            line = line.strip()
            if line and any(d in line for d in active_delimiters):
                card_count += 1
        
        self.card_count_label.setText(self._t("Cards: {}").format(card_count))

    def clear_creation_info_on_edit(self):
        if self.card_creation_info:
            self.card_creation_info = []
            self.current_view_mode = 'simple'

    def update_line_numbers(self):
        if self.card_creation_info:
            return

        document = self.txt_entrada.document()
        block = document.firstBlock()
        line_numbers = []
        valid_line_count = 0
        
        active_delimiters = [chk.simbolo for chk in self.chk_delimitadores.values() if chk.isChecked()]
        if not active_delimiters:
            active_delimiters = [';']

        while block.isValid():
            text = block.text().strip()
            if text and any(d in text for d in active_delimiters):
                valid_line_count += 1
                line_numbers.append(str(valid_line_count))
            else:
                line_numbers.append("")
            block = block.next()
            
        self.txt_entrada.line_number_area.line_numbers = line_numbers
        self.txt_entrada.line_number_area.update()
        self.update_line_number_area_width()

    def line_number_area_width(self):
        if self.card_creation_info:
            if self.current_view_mode == 'date':
                return self.txt_entrada.fontMetrics().horizontalAdvance('999 (9999-99-99)') + 10
            elif self.current_view_mode == 'stats':
                return self.txt_entrada.fontMetrics().horizontalAdvance('999 (E:99 R:999)') + 10

        max_num = 0
        for num_str in self.txt_entrada.line_number_area.line_numbers:
            if num_str and num_str.isdigit():
                max_num = max(max_num, int(num_str))
        digits = len(str(max_num)) if max_num > 0 else 1
        space = 3 + self.txt_entrada.fontMetrics().horizontalAdvance('9') * digits
        return space + 10
    
    def update_line_number_area_width(self):
        self.txt_entrada.setViewportMargins(self.line_number_area_width(), 0, 0, 0)
        self.txt_entrada.line_number_area.update()
    
    def custom_resize_event(self, event):
        QTextEdit.resizeEvent(self.txt_entrada, event)
        cr = self.txt_entrada.contentsRect()
        if cr.height() < 100:
            cr.setHeight(100)
        self.txt_entrada.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))
        self.txt_entrada.line_number_area.update()
        self.txt_entrada.updateGeometry()

    def highlight_current_line(self):
        extra_selections = []
        if not self.txt_entrada.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            line_color = QColor("#3b3b3b") if self.is_dark_theme else QColor("#e0e0e0")
            selection.format.setBackground(line_color)
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.cursor = self.txt_entrada.textCursor()
            selection.cursor.clearSelection()
            extra_selections.append(selection)
        self.txt_entrada.setExtraSelections(extra_selections)

    def _save_in_real_time(self):
        try:
            if os.path.exists(CONFIG_FILE):
                shutil.copy2(CONFIG_FILE, CONFIG_FILE + ".bak")
            window_geometry = {'size': (self.width(), self.height()), 'pos': (self.x(), self.y()), 'vertical_splitter': self.vertical_splitter.sizes(), 'fields_splitter': self.fields_splitter.sizes()}
            dados = {
                'conteudo': self.txt_entrada.toPlainText(), 
                'tags': self.txt_tags.toPlainText(), 
                'delimitadores': {nome: chk.isChecked() for nome, chk in self.chk_delimitadores.items()}, 
                'deck_selecionado': self.lista_decks.currentItem().text() if self.lista_decks.currentItem() else '', 
                'modelo_selecionado': self.lista_notetypes.currentItem().text() if self.lista_notetypes.currentItem() else '', 
                'field_mappings': self.field_mappings, 
                'field_images': self.field_images, 
                'window_geometry': window_geometry, 
                'last_preview_html': getattr(self, 'last_preview_html', ''),
                'language': self.current_language,
                'last_tab_index': self.tool_tabs.currentIndex() # Salva o índice da aba
            }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(dados, f, ensure_ascii=False, indent=2)
            self.save_status_label.setText(self._t("Salvo"))
            self.save_status_label.setStyleSheet("color: green;")
            QTimer.singleShot(2000, lambda: self.save_status_label.setText(self._t("Pronto")) or self.save_status_label.setStyleSheet("color: gray;"))
        except Exception as e:
            logging.error(f"Erro ao salvar em tempo real: {str(e)}")
            self.save_status_label.setText(self._t("Erro ao salvar"))
            self.save_status_label.setStyleSheet("color: red;")

    def toggle_tags(self):
        novo_estado = not self.etiquetas_group.isVisible()
        self.etiquetas_group.setVisible(novo_estado)
        self.toggle_tags_button.setText(self._t("Ocultar Etiquetas") if novo_estado else self._t("Mostrar Etiquetas"))
        if novo_estado:
            self.txt_tags.setFocus()
            cursor = self.txt_tags.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.txt_tags.setTextCursor(cursor)
            self.adjust_scroll_position()
    
    def adjust_scroll_position(self):
        self.txt_tags.verticalScrollBar().setValue(0)

    def showEvent(self, event):
        super().showEvent(event)
        if self.etiquetas_group.isVisible():
            self.txt_tags.setFocus()
            cursor = self.txt_tags.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.txt_tags.setTextCursor(cursor)
        
        if self.is_first_show:
            self.update_preview()
            self.is_first_show = False

    def update_tags_lines(self):
        linhas_cards = self.txt_entrada.toPlainText().strip().split('\n')
        linhas_tags = self.txt_tags.toPlainText().strip().split('\n')
        if len(linhas_tags) < len(linhas_cards):
            self.txt_tags.setPlainText(self.txt_tags.toPlainText() + '\n' * (len(linhas_cards) - len(linhas_tags)))
        elif len(linhas_tags) > len(linhas_cards):
            self.txt_tags.setPlainText('\n'.join(linhas_tags[:len(linhas_cards)]))
        self.update_preview()

    def check_line_change(self):
        cursor = self.txt_entrada.textCursor()
        current_line = cursor.blockNumber()
        if current_line != self.current_line:
            self.process_media_rename()
            self.current_line = current_line
            self.last_edited_line = current_line
        self.update_preview()

    def focus_out_event(self, event):
        self.process_media_rename()
        QTextEdit.focusOutEvent(self.txt_entrada, event)

    def process_media_rename(self):
        current_text = self.txt_entrada.toPlainText()
        if self.previous_text != current_text:
            patterns = [r'<img src="([^"]+)"', r'<source src="([^"]+)"', r'<video src="([^"]+)"']
            previous_media = set()
            current_media = set()
            for pattern in patterns:
                previous_media.update(re.findall(pattern, self.previous_text))
                current_media.update(re.findall(pattern, current_text))
            media_dir = mw.col.media.dir()
            for old_name in previous_media:
                if old_name in self.media_files and old_name not in current_media:
                    for new_name in current_media:
                        if new_name not in previous_media and new_name not in self.media_files:
                            if os.path.exists(os.path.join(media_dir, new_name)):
                                logging.warning(f"O nome '{new_name}' já existe na pasta de mídia!")
                                showWarning(f"O nome '{new_name}' já existe na pasta de mídia!")
                                continue
                            try:
                                src_path = os.path.join(media_dir, old_name)
                                dst_path = os.path.join(media_dir, new_name)
                                if not os.path.exists(src_path):
                                    logging.error(f"Arquivo de origem '{src_path}' não encontrado!")
                                    continue
                                os.rename(src_path, dst_path)
                                self.media_files[self.media_files.index(old_name)] = new_name
                                logging.info(f"Arquivo renomeado de '{old_name}' para '{new_name}' na pasta de mídia.")
                                showInfo(f"Arquivo renomeado de '{old_name}' para '{new_name}' na pasta de mídia.")
                            except Exception as e:
                                logging.error(f"Erro ao renomear o arquivo de '{old_name}' para '{new_name}': {str(e)}")
                                showWarning(f"Erro ao renomear o arquivo: {str(e)}")
                            break
            self.previous_text = current_text

    def update_field_mappings(self):
        while self.fields_container_layout.count():
            child = self.fields_container_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
            elif child.layout():
                while child.layout().count():
                    item = child.layout().takeAt(0)
                    if item.widget():
                        item.widget().deleteLater()
                child.layout().deleteLater()

        self.field_combo_boxes.clear()
        self.field_image_buttons.clear()

        if not self.lista_notetypes.currentItem():
            return
        modelo = mw.col.models.by_name(self.lista_notetypes.currentItem().text())
        campos = [fld['name'] for fld in modelo['flds']]
        num_campos = len(campos)
        for i in range(num_campos):
            field_layout = QHBoxLayout()
            combo = QComboBox()
            combo.addItem(self._t("Parte {} -> Ignorar").format(i + 1))
            for campo in campos:
                combo.addItem(self._t("Parte {} -> {}").format(i + 1, campo))
            
            if str(i) in self.field_mappings and self.field_mappings[str(i)] in campos:
                combo.setCurrentText(self._t("Parte {} -> {}").format(i + 1, self.field_mappings[str(i)]))
            else:
                combo.setCurrentIndex(0)
            
            combo.currentIndexChanged.connect(self.update_field_mapping)
            self.field_combo_boxes.append(combo)
            field_layout.addWidget(combo)
            
            btn = QPushButton(self._t("Midia {}").format(campos[i]))
            btn.clicked.connect(lambda checked, idx=i, campo=campos[i]: self.add_media_to_field(idx, campo))
            self.field_image_buttons[campos[i]] = btn
            field_layout.addWidget(btn)
            self.fields_container_layout.addLayout(field_layout)
        self.update_preview()

    def add_media_to_field(self, idx, campo):
        arquivos, _ = QFileDialog.getOpenFileNames(self, self._t("Selecionar Mídia para {}").format(campo), "", "Mídia (*.png *.jpg *.jpeg *.gif *.mp3 *.wav *.ogg *.mp4 *.webm)")
        if not arquivos:
            return
        media_dir = mw.col.media.dir()
        current_line = self.txt_entrada.textCursor().blockNumber()
        linhas = self.txt_entrada.toPlainText().strip().split('\n')
        for caminho in arquivos:
            nome = os.path.basename(caminho)
            destino = os.path.join(media_dir, nome)
            if os.path.exists(destino):
                base, ext = os.path.splitext(nome)
                counter = 1
                while os.path.exists(destino):
                    nome = f"{base}_{counter}{ext}"
                    destino = os.path.join(media_dir, nome)
                    counter += 1
            shutil.copy2(caminho, destino)
            if campo not in self.field_images:
                self.field_images[campo] = []
            while len(self.field_images[campo]) <= current_line:
                self.field_images[campo].append("")
            self.field_images[campo][current_line] = nome
            if current_line < len(linhas):
                partes = self._get_split_parts(linhas[current_line])
                partes = [p.strip() for p in partes]
                if all(str(i) not in self.field_mappings for i in range(len(partes))):
                    if idx < len(partes):
                        partes[idx] += f' <img src="{nome}">' if partes[idx] else f'<img src="{nome}">'
                else:
                    for i, parte in enumerate(partes):
                        if str(i) in self.field_mappings and self.field_mappings[str(i)] == campo:
                            partes[i] += f' <img src="{nome}">' if parte else f'<img src="{nome}">'
                active_delimiter = next((chk.simbolo for chk in self.chk_delimitadores.values() if chk.isChecked()), ';')
                linhas[current_line] = active_delimiter.join(partes)
                self.txt_entrada.setPlainText('\n'.join(linhas))
        self.schedule_save()
        self.update_preview()

    def update_field_mapping(self):
        self.field_mappings = {}
        if not self.lista_notetypes.currentItem(): return

        modelo = mw.col.models.by_name(self.lista_notetypes.currentItem().text())
        campos = [fld['name'] for fld in modelo['flds']]

        for i, combo in enumerate(self.field_combo_boxes):
            text = combo.currentText()
            if " -> " in text:
                parts = text.split(" -> ")
                if len(parts) > 1:
                    campo_display = parts[1]
                    if campo_display != self._t("Ignorar"):
                        for original_campo in campos:
                            if self._t(original_campo) == campo_display or original_campo == campo_display:
                                self.field_mappings[str(i)] = original_campo
                                break
        self.schedule_save()
        self.update_preview()

    def clean_input_text(self):
        try:
            current_text = self.txt_entrada.toPlainText()
            if not current_text:
                return

            def clean_attributes(match):
                tag, attrs, content = match.groups()
                attrs_cleaned = re.sub(r'"(.*?);(.*?)"', r'"\1 \2"', attrs)
                return f"<{tag}{attrs_cleaned}>{content}</span>"

            new_text = re.sub(r'<(span)([^>]*)>(.*?)<\/span>', clean_attributes, current_text, flags=re.DOTALL)

            if new_text != current_text:
                cursor = self.txt_entrada.textCursor()
                pos = cursor.position()
                self.txt_entrada.blockSignals(True)
                self.txt_entrada.setPlainText(new_text)
                self.txt_entrada.blockSignals(False)
                cursor.setPosition(pos)
                self.txt_entrada.setTextCursor(cursor)
        except Exception as e:
            logging.error(f"ERRO ao limpar ; em <span>: {str(e)}")

    def clean_non_breaking_spaces(self, text):
        if '\u00A0' in text:
            cleaned_text = text.replace('\u00A0', ' ')
            logging.debug(f"\u00A0 encontrado e substituído: {repr(text)} -> {repr(cleaned_text)}")
            return cleaned_text
        return text

    def _get_split_parts(self, line_text: str) -> list[str]:
        active_delimiters = [chk.simbolo for chk in self.chk_delimitadores.values() if chk.isChecked()]
        delimiter = active_delimiters[0] if active_delimiters else ';'

        if delimiter not in line_text:
            return [line_text]

        parts = []
        current_part = ""
        tag_level = 0
        
        for char in line_text:
            if char == '<':
                tag_level += 1
            
            if char == delimiter and tag_level == 0:
                parts.append(current_part.strip())
                current_part = ""
            else:
                current_part += char

            if char == '>':
                tag_level = max(0, tag_level - 1)
        
        parts.append(current_part.strip())
        
        return parts

    def _check_for_state_reset(self):
        if self.shown_note_ids and not self.txt_entrada.toPlainText():
            self.shown_note_ids.clear()
            
            if self.edit_mode:
                self.toggle_edit_mode()
            
            self.update_preview()

    def update_preview(self):
        try:
            cursor = self.txt_entrada.textCursor()
            current_line = cursor.blockNumber()
            all_lines = self.txt_entrada.toPlainText().split('\n')

            if not (0 <= current_line < len(all_lines)):
                self.preview_widget.setHtml("")
                return
            
            line_text = all_lines[current_line]

            if not self.lista_notetypes.currentItem():
                self.preview_widget.setHtml(f"<div style='padding:10px;'>{self._t('Selecione um modelo para ver a pré-visualização.')}</div>")
                return

            note = None
            
            if self.shown_note_ids and 0 <= current_line < len(self.shown_note_ids):
                nid = self.shown_note_ids[current_line]
                note = mw.col.get_note(nid)
            else:
                modelo_nome = self.lista_notetypes.currentItem().text()
                model = mw.col.models.by_name(modelo_nome)
                if not model:
                    self.preview_widget.setHtml(f"<div style='color:red'><b>{self._t('Erro:')}</b><br>{self._t('Modelo não encontrado.')}</div>")
                    return

                note = mw.col.new_note(model)
                parts = self._get_split_parts(line_text)
                
                if not self.field_mappings:
                    for idx, field_content in enumerate(parts):
                        if idx < len(note.fields):
                            note.fields[idx] = field_content.strip()
                else:
                    field_names = [f['name'] for f in model['flds']]
                    for part_idx, field_content in enumerate(parts):
                        target_field_name = self.field_mappings.get(str(part_idx))
                        if target_field_name and target_field_name in field_names:
                            field_idx = field_names.index(target_field_name)
                            note.fields[field_idx] = field_content.strip()

            if not note:
                self.preview_widget.setHtml("")
                return

            card = note.ephemeral_card()

            question_html = mw.prepare_card_text_for_display(card.question())
            answer_html = mw.prepare_card_text_for_display(card.answer())

            script_pattern = re.compile(r"<script[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)
            style_pattern = re.compile(r"<style[^>]*>(.*?)</style>", re.DOTALL | re.IGNORECASE)
            
            unique_scripts = set()
            unique_styles = set()

            for style in style_pattern.findall(question_html): unique_styles.add(style)
            for style in style_pattern.findall(answer_html): unique_styles.add(style)
            for script in script_pattern.findall(question_html): unique_scripts.add(script)
            for script in script_pattern.findall(answer_html): unique_scripts.add(script)

            question_html = style_pattern.sub("", question_html)
            answer_html = style_pattern.sub("", answer_html)
            question_html = script_pattern.sub("", question_html)
            answer_html = script_pattern.sub("", answer_html)

            question_html = gui_hooks.card_will_show(question_html, card, "clayoutQuestion")
            answer_html = gui_hooks.card_will_show(answer_html, card, "clayoutAnswer")

            body_class = theme_manager.body_classes_for_card_ord(card.ord, self.is_dark_theme)

            # Define styles based on the current theme
            if self.is_dark_theme:
                section_style = "border: 1px solid #4a4a4a; border-radius: 8px; margin: 10px 0; overflow: hidden; background-color: #2d2d2d;"
                header_style = "background-color: #3a3a3a; color: #eee; padding: 5px 15px; font-weight: bold; border-bottom: 1px solid #4a4a4a;"
                content_style = "padding: 15px;"
            else:
                # Styles for the light theme
                section_style = "border: 1px solid #ccc; border-radius: 8px; margin: 10px 0; overflow: hidden; background-color: #ffffff;"
                header_style = "background-color: #f0f0f0; color: #000; padding: 5px 15px; font-weight: bold; border-bottom: 1px solid #ccc;"
                content_style = "padding: 15px;"

            # Construct the HTML with labeled sections
            final_html = f"""
            <div class="preview-section" style="{section_style}">
                <div class="preview-header" style="{header_style}">{self._t("Frente do Cartão (Preview)")}</div>
                <div id="preview-front" class="preview-content" style="{content_style}">{question_html}</div>
            </div>
            <div class="preview-section" style="{section_style}">
                <div class="preview-header" style="{header_style}">{self._t("Verso do Cartão (Preview)")}</div>
                <div id="preview-back" class="preview-content" style="{content_style}">{answer_html}</div>
            </div>
            """
            
            try:
                self.preview_widget.loadFinished.disconnect()
            except TypeError:
                pass

            def on_load_finished(ok):
                if not ok: return
                self.preview_widget.eval(f"document.body.className = '{body_class}';")
                
                # Set the background of the entire page to match the dialog theme
                bg_color = "#333" if self.is_dark_theme else "#f0f0f0"
                self.preview_widget.eval(f"document.documentElement.style.backgroundColor = '{bg_color}';")
                
                # Ensure the main document is scrollable
                self.preview_widget.eval("document.documentElement.style.overflowY = 'auto';")

                # Force text color to ensure theme change is applied correctly.
                if not self.is_dark_theme:
                    self.preview_widget.eval("document.body.style.color = 'black';")

                for style_content in unique_styles:
                    escaped_style = json.dumps(style_content)
                    self.preview_widget.eval(f"var style = document.createElement('style'); style.type = 'text/css'; style.innerHTML = {escaped_style}; document.head.appendChild(style);")

                for script in unique_scripts:
                    if script.strip():
                        self.preview_widget.eval(script)
                
                self.preview_widget.eval("if (typeof MathJax !== 'undefined') MathJax.typesetPromise();")

            self.preview_widget.loadFinished.connect(on_load_finished)

            self.preview_widget.stdHtml(
                f'<div id="qa" style="padding: 0 10px;">{final_html}</div>',
                css=["css/reviewer.css"],
                js=self._get_reviewer_scripts(),
                context=self
            )

        except Exception as e:
            logging.error(f"Erro na pré-visualização: {e}")
            self.preview_widget.setHtml(f"<div style='color:red'><b>{self._t('Erro na pré-visualização:')}</b><br>{e}</div>")

    def apply_text_color(self, color):
        cursor = self.txt_entrada.textCursor()
        if cursor.hasSelection():
            texto = cursor.selectedText()
            cursor.insertText(f'<span style="color:{color}">{texto}</span>')
        else:
            cursor.insertText(f'<span style="color:{color}"></span>')
            cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, 7)
            self.txt_entrada.setTextCursor(cursor)
        self.previous_text = self.txt_entrada.toPlainText()
        self.update_preview()

    def apply_background_color(self, color):
        cursor = self.txt_entrada.textCursor()
        if cursor.hasSelection():
            texto = cursor.selectedText()
            cursor.insertText(f'<span style="background-color:{color}">{texto}</span>')
        else:
            cursor.insertText(f'<span style="background-color:{color}"></span>')
            cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, 7)
            self.txt_entrada.setTextCursor(cursor)
        self.previous_text = self.txt_entrada.toPlainText()
        self.update_preview()

    def clear_all(self):
        reply = QMessageBox.question(self, self._t("Confirmação"), self._t("Tem certeza de que deseja limpar tudo? Isso não pode ser desfeito."), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.txt_entrada.clear()
            self.txt_tags.clear()
            self.search_input.clear()
            self.replace_input.clear()
            self.deck_name_input.clear()
            self.decks_search_input.clear()
            self.notetypes_search_input.clear()
            for chk in self.chk_delimitadores.values():
                chk.setChecked(False)
            self.chk_num_tags.setChecked(False)
            self.chk_repetir_tags.setChecked(False)
            self.cloze_2_count = 1
            self.zoom_factor = 1.0
            self.txt_entrada.zoomOut(int((self.zoom_factor - 1.0) * 10))
            self.initial_tags_set = False
            self.initial_numbering_set = False
            self.current_line = 0
            self.previous_text = ""
            self.last_edited_line = -1
            self.last_search_query = ""
            self.last_search_position = 0
            self.field_mappings.clear()
            self.field_images.clear()
            self.media_files.clear()
            self.card_creation_info = []
            self.update_field_mappings()
            self.update_preview()
            self.schedule_save()
            showInfo(self._t("Todos os campos e configurações foram limpos!"))

    def add_cards(self):
        if self.stacked_editor.currentIndex() == 1:
            self.switch_to_text_view()
            self.toggle_view_button.setText(self._t("📝 Editar em Grade"))

        deck_item = self.lista_decks.currentItem()
        notetype_item = self.lista_notetypes.currentItem()
        if not deck_item or not notetype_item:
            showWarning(self._t("Selecione um deck e um modelo!"))
            return
        
        # O texto já foi corrigido em tempo real pelo sinal textChanged,
        # então podemos prosseguir diretamente.
        linhas_texto = self.txt_entrada.toPlainText().strip()
        if not linhas_texto:
            showWarning(self._t("Digite algum conteúdo!"))
            return
        
        linhas = linhas_texto.split('\n')
        deck_name = deck_item.text()
        deck_id = mw.col.decks.id_for_name(deck_name)
        
        default_model = mw.col.models.by_name(notetype_item.text())
        cloze_model = mw.col.models.by_name("Cloze")
        if not cloze_model:
            logging.warning("Modelo 'Cloze' não encontrado. Cards com padrão cloze usarão o modelo selecionado.")

        contador = 0
        linhas_tags = self.txt_tags.toPlainText().strip().split('\n')

        mw.progress.start(label="Adicionando cards...", max=len(linhas))

        for i, linha in enumerate(linhas):
            mw.progress.update(value=i + 1)
            linha = linha.strip()
            
            active_delimiters = [chk.simbolo for chk in self.chk_delimitadores.values() if chk.isChecked()]
            if not active_delimiters:
                active_delimiters = [';']
            
            if not linha or not any(d in linha for d in active_delimiters):
                continue

            is_cloze = cloze_model and re.search(r'{{c\d+::.*?}}', linha)
            
            nota = None
            if is_cloze:
                nota = mw.col.new_note(cloze_model)
                parts = self._get_split_parts(linha)
                nota.fields[0] = parts[0] # Texto com o cloze
                if len(parts) > 1 and parts[1]:
                    nota.fields[1] = parts[1] # Campo "Extra"
            else:
                nota = mw.col.new_note(default_model)
                parts = self._get_split_parts(linha)
                
                if not self.field_mappings:
                    for idx, field_content in enumerate(parts):
                        if idx < len(nota.fields):
                            nota.fields[idx] = field_content.strip()
                else:
                    field_names = [f['name'] for f in default_model['flds']]
                    for part_idx, field_content in enumerate(parts):
                        target_field_name = self.field_mappings.get(str(part_idx))
                        if target_field_name and target_field_name in field_names:
                            field_idx = field_names.index(target_field_name)
                            nota.fields[field_idx] = field_content.strip()
            
            if i < len(linhas_tags):
                tags_for_card = [tag.strip() for tag in linhas_tags[i].split(',') if tag.strip()]
                if tags_for_card:
                    if self.chk_num_tags.isChecked():
                        nota.tags.extend([f"{tag}{i + 1}" for tag in tags_for_card])
                    else:
                        nota.tags.extend(tags_for_card)
            
            try:
                mw.col.add_note(nota, deck_id)
                contador += 1
            except Exception as e:
                logging.error(f"Erro ao adicionar card da linha {i+1}: {str(e)}")

        mw.progress.finish()
        showInfo(self._t("{} cards adicionados com sucesso!").format(contador))
        mw.reset()

    def show_all_cards(self):
        if self.edit_mode:
            self.toggle_edit_mode()

        def clean_html_tags(text):
            text = re.sub(r'(<img[^>]*)alt="[^"]*"([^>]*>)', r'\1\2', text)
            return text

        if not self.lista_decks.currentItem():
            showWarning(self._t("Selecione um deck primeiro!"))
            return
        deck_name = self.lista_decks.currentItem().text()
        deck_id = mw.col.decks.id_for_name(deck_name)
        if not deck_id:
            showWarning(self._t("Deck '{}' não encontrado!").format(deck_name))
            return
        note_ids = mw.col.find_notes(f"deck:\"{deck_name}\"")
        if not note_ids:
            showWarning(self._t("Nenhum card encontrado no deck '{}'!").format(deck_name))
            return
        current_text = self.txt_entrada.toPlainText()
        try:
            with open(self.pre_show_state_file, 'w', encoding='utf-8') as f:
                json.dump({'pre_show_text': current_text}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Erro ao salvar estado antes de 'Mostrar': {str(e)}")
            showWarning(self._t("Erro ao salvar estado antes de 'Mostrar': {}").format(str(e)))
        
        self.card_notetypes = []
        self.shown_note_ids.clear()
        self.card_creation_info.clear()

        for nid in note_ids:
            note = mw.col.get_note(nid)
            
            note_model = mw.col.models.get(note.mid)
            note_type_name = note_model['name']
            campos = [fld['name'] for fld in note_model['flds']]
            field_values = []
            for campo in campos:
                if campo in note:
                    field_value = html.unescape(note[campo])
                    field_value = re.sub(r'\[sound:([^\]]+)\]', r'<audio controls=""><source src="\1" type="audio/mpeg"></audio>', field_value)
                    field_value = clean_html_tags(field_value)
                    field_value = field_value.replace('\n', ' ').replace('\u00A0', ' ')
                    field_value = re.sub(r'\s+', ' ', field_value).strip()
                    field_values.append(field_value)
                else:
                    field_values.append("")
            
            active_delimiter = next((chk.simbolo for chk in self.chk_delimitadores.values() if chk.isChecked()), ';')
            card_line = f" {active_delimiter} ".join(field_values)
            
            if card_line.strip():
                tags = note.string_tags().strip()
                self.card_creation_info.append([nid, card_line, tags])
                self.shown_note_ids.append(nid)
                self.card_notetypes.append(note_type_name)

        if self.card_creation_info:
            self.current_view_mode = 'simple'
            self._repopulate_ui_from_creation_info()
        else:
            self.txt_entrada.clear()
            self.txt_tags.clear()
            self.update_line_numbers()

        self.previous_text = self.txt_entrada.toPlainText()
        self.update_card_count()
        self.update_preview()
        self._save_in_real_time()

    def toggle_edit_mode(self):
        if not self.shown_note_ids:
            showWarning(self._t("Use a função 'Mostrar' para carregar os cards de um deck antes de editar."))
            return

        self.edit_mode = not self.edit_mode

        if self.edit_mode:
            self.edit_button.setText(self._t("Parar Edição"))
            self.edit_button.setStyleSheet("background-color: #ffdddd; color: black;")
            self.show_button.setEnabled(False)
            self.save_status_label.setText(self._t("Modo de edição ativado."))
            self.save_status_label.setStyleSheet("color: blue; font-weight: bold;")
            QTimer.singleShot(2500, lambda: self.save_status_label.setText(self._t("Pronto")) or self.save_status_label.setStyleSheet("color: gray; font-weight: normal;"))
        else:
            self.edit_button.setText(self._t("Editar"))
            self.edit_button.setStyleSheet("")
            self.show_button.setEnabled(True)
            self.save_status_label.setText(self._t("Modo de edição desativado."))
            self.save_status_label.setStyleSheet("color: gray; font-weight: normal;")
            QTimer.singleShot(2500, lambda: self.save_status_label.setText(self._t("Pronto")))

    def schedule_real_time_edit(self):
        if not self.edit_mode:
            return

        current_line_count = len(self.txt_entrada.toPlainText().split('\n'))
        if current_line_count != len(self.shown_note_ids):
            showWarning(self._t("O número de linhas foi alterado. Modo de edição desativado para evitar erros."))
            self.toggle_edit_mode()
            return

        self.save_status_label.setText(self._t("Atualizando card..."))
        self.save_status_label.setStyleSheet("color: orange;")
        self.edit_timer.start(750)

    def _apply_real_time_edit(self):
        if not self.edit_mode:
            return

        try:
            line_number = self.txt_entrada.textCursor().blockNumber()

            if not (0 <= line_number < len(self.shown_note_ids)):
                logging.warning(f"Edição em tempo real: número de linha inválido ({line_number}).")
                return

            note_id = self.shown_note_ids[line_number]
            note = mw.col.get_note(note_id)
            if not note:
                logging.error(f"Edição em tempo real: Nota com ID {note_id} não encontrada.")
                return

            all_lines = self.txt_entrada.toPlainText().split('\n')
            edited_line_text = all_lines[line_number]
            
            parts = self._get_split_parts(edited_line_text)
            model = note.model()

            for fld in model['flds']:
                note[fld['name']] = ""

            if not self.field_mappings:
                for idx, field_content in enumerate(parts):
                    if idx < len(note.fields):
                        note.fields[idx] = field_content.strip()
            else:
                field_names = [f['name'] for f in model['flds']]
                for part_idx, field_content in enumerate(parts):
                    target_field_name = self.field_mappings.get(str(part_idx))
                    if target_field_name and target_field_name in field_names:
                        note[target_field_name] = field_content.strip()
            
            all_tags_lines = self.txt_tags.toPlainText().split('\n')
            if line_number < len(all_tags_lines):
                tags_for_card_str = all_tags_lines[line_number].strip()
                note.tags = mw.col.tags.split(tags_for_card_str)

            note.flush()
            
            if mw.state == "review" and mw.reviewer.card and mw.reviewer.card.nid == note_id:
                mw.reviewer.card.load()
                if mw.reviewer.state == "question":
                    mw.reviewer._showQuestion()
                elif mw.reviewer.state == "answer":
                    mw.reviewer._showAnswer()

            self.save_status_label.setText(self._t("Card {} atualizado!").format(line_number + 1))
            self.save_status_label.setStyleSheet("color: green;")
            QTimer.singleShot(2000, lambda: self.save_status_label.setText(self._t("Pronto")) or self.save_status_label.setStyleSheet("color: gray;"))

        except Exception as e:
            logging.error(f"Erro na edição em tempo real: {e}")
            self.save_status_label.setText(self._t("Erro ao atualizar"))
            self.save_status_label.setStyleSheet("color: red;")

    def restore_pre_show_state(self):
        if os.path.exists(self.pre_show_state_file):
            try:
                with open(self.pre_show_state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    pre_show_text = data.get('pre_show_text', '')
                    self.txt_entrada.blockSignals(True)
                    self.txt_entrada.setPlainText(pre_show_text)
                    self.txt_entrada.blockSignals(False)
                    self.previous_text = pre_show_text
                    self.update_line_numbers()
                    self.update_card_count()
                    self.update_preview()
                    logging.debug("Estado anterior restaurado com sucesso.")
            except Exception as e:
                logging.error(f"Erro ao restaurar estado anterior: {str(e)}")
                showWarning(f"Erro ao restaurar estado anterior: {str(e)}")
        else:
            showWarning(self._t("Nenhum estado anterior salvo encontrado!"))

    def add_image(self):
        if self.stacked_editor.currentIndex() == 1:
            if not self.table_widget.currentItem():
                showWarning(self._t("Por favor, selecione uma célula na grade primeiro."))
                return

        arquivos, _ = QFileDialog.getOpenFileNames(self, self._t("Selecionar Mídia"), "", "Mídia (*.png *.jpg *.jpeg *.gif *.mp3 *.wav *.ogg *.mp4 *.webm)")
        if not arquivos:
            return

        media_dir = mw.col.media.dir()
        html_tags_to_add = []
        for caminho in arquivos:
            nome = os.path.basename(caminho)
            destino = os.path.join(media_dir, nome)
            if os.path.exists(destino):
                base, ext = os.path.splitext(nome)
                counter = 1
                while os.path.exists(destino):
                    nome = f"{base}_{counter}{ext}"
                    destino = os.path.join(media_dir, nome)
                    counter += 1
            shutil.copy2(caminho, destino)
            self.media_files.append(nome)
            
            ext = os.path.splitext(nome)[1].lower()
            if ext in ('.png', '.jpg', '.jpeg', '.gif'):
                html_tags_to_add.append(f'<img src="{nome}">')
            elif ext in ('.mp3', '.wav', '.ogg'):
                html_tags_to_add.append(f'[sound:{nome}]')
            elif ext in ('.mp4', '.webm'):
                html_tags_to_add.append(f'<video src="{nome}" controls></video>')

        if not html_tags_to_add:
            return

        tags_str = " ".join(html_tags_to_add)
        
        if self.stacked_editor.currentIndex() == 0:
            cursor = self.txt_entrada.textCursor()
            cursor.insertText(tags_str)
        else:
            item = self.table_widget.currentItem()
            current_text = item.text()
            new_text = f"{current_text} {tags_str}".strip()
            item.setText(new_text)
            self.switch_to_text_view()
            self.toggle_view_button.setText(self._t("📝 Editar em Grade"))

    def show_table_context_menu(self, pos):
        item = self.table_widget.itemAt(pos)
        if not item:
            return

        menu = QMenu()
        add_image_action = menu.addAction(self._t("🖼️ Adicionar Imagem/Mídia..."))
        add_image_action.triggered.connect(self.add_image)
        
        menu.exec(self.table_widget.mapToGlobal(pos))

    def drag_enter_event(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def drop_event(self, event):
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            file_paths = [url.toLocalFile() for url in mime_data.urls()]
            for file_path in file_paths:
                file_name = os.path.basename(file_path)
                media_dir = mw.col.media.dir()
                dest_path = os.path.join(media_dir, file_name)
                if os.path.exists(dest_path):
                    base, ext = os.path.splitext(file_name)
                    counter = 1
                    while os.path.exists(dest_path):
                        file_name = f"{base}_{counter}{ext}"
                        dest_path = os.path.join(media_dir, file_name)
                        counter += 1
                shutil.copy2(file_path, dest_path)
                self.media_files.append(file_name)
                ext = os.path.splitext(file_name)[1].lower()
                if ext in ('.png', '.jpg', '.jpeg', '.gif'):
                    html_tag = f'<img src="{file_name}">'
                elif ext in ('.mp3', '.wav', '.ogg'):
                    html_tag = f'<audio controls><source src="{file_name}"></audio>'
                elif ext in ('.mp4', '.webm'):
                    html_tag = f'<video src="{file_name}" controls width="320" height="240"></video>'
                else:
                    continue
                cursor = self.txt_entrada.textCursor()
                cursor.insertText(html_tag)
            self.update_line_numbers()
            self.previous_text = self.txt_entrada.toPlainText()
            self.update_preview()
            self.txt_entrada.setFocus()
            QApplication.processEvents()
        event.accept()

    def process_files(self, file_paths):
        media_folder = mw.col.media.dir()
        for file_path in file_paths:
            file_name = os.path.basename(file_path)
            new_path = os.path.join(media_folder, file_name)
            if os.path.exists(new_path):
                base_name, ext = os.path.splitext(file_name)
                counter = 1
                while os.path.exists(new_path):
                    file_name = f"{base_name}{counter}{ext}"
                    new_path = os.path.join(media_folder, file_name)
                    counter += 1
            shutil.copy(file_path, new_path)
            self.media_files.append(file_name)
            ext = file_name.lower()
            if ext.endswith(('.png', '.xpm', '.jpg', '.jpeg', '.bmp', '.gif')):
                self.txt_entrada.insertPlainText(f'<img src="{file_name}">\n')
            elif ext.endswith(('.mp3', '.wav', '.ogg')):
                self.txt_entrada.insertPlainText(f'<audio controls=""><source src="{file_name}" type="audio/mpeg"></audio>\n')
            elif ext.endswith(('.mp4', '.webm', '.avi', '.mkv', '.mov')):
                self.txt_entrada.insertPlainText(f'<video src="{file_name}" controls width="320" height="240"></video>\n')

    def show_context_menu(self, pos):
        menu = self.txt_entrada.createStandardContextMenu()
        paste_action = QAction(self._t("Colar HTML sem Tag e sem Formatação"), self)
        paste_action.triggered.connect(self.paste_html)
        menu.addAction(paste_action)
        paste_raw_action = QAction(self._t("Colar com Tags HTML"), self)
        paste_raw_action.triggered.connect(self.paste_raw_html)
        menu.addAction(paste_raw_action)
        paste_excel_action = QAction(self._t("Colar do Excel com Ponto e Vírgula"), self)
        paste_excel_action.triggered.connect(self.paste_excel)
        menu.addAction(paste_excel_action)
        paste_word_action = QAction(self._t("Colar do Word"), self)
        paste_word_action.triggered.connect(self.paste_word)
        menu.addAction(paste_word_action)
        menu.exec(self.txt_entrada.mapToGlobal(pos))

    def convert_markdown_to_html(self, text):
        lines = text.split('\n')
        table_html = ""
        in_table = False
        headers = []
        rows = []
        table_start_idx = -1
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            if line.startswith('|') and line.endswith('|') and '|' in line[1:-1]:
                cells = [cell.strip() for cell in line[1:-1].split('|')]
                if not in_table and i + 1 < len(lines) and re.match(r'^\|(?:\s*[-:]+(?:\s*\|)?)+$', lines[i + 1]):
                    in_table = True
                    table_start_idx = i
                    headers = cells
                    continue
                elif in_table:
                    rows.append(cells)
            elif in_table:
                if headers and rows:
                    table_html += "<table>\n<thead>\n<tr>"
                    for header in headers:
                        table_html += f"<th>{header}</th>"
                    table_html += "</tr>\n</thead>\n<tbody>\n"
                    for row in rows:
                        while len(row) < len(headers):
                            row.append("")
                        table_html += "<tr>"
                        for cell in row[:len(headers)]:
                            table_html += f"<td>{cell}</td>"
                        table_html += "</tr>\n"
                    table_html += "</tbody>\n</table>"
                in_table = False
                headers = []
                rows = []
        if in_table and headers and rows:
            table_html += "<table>\n<thead>\n<tr>"
            for header in headers:
                table_html += f"<th>{header}</th>"
            table_html += "</tr>\n</thead>\n<tbody>\n"
            for row in rows:
                while len(row) < len(headers):
                    row.append("")
                table_html += "<tr>"
                for cell in row[:len(headers)]:
                    table_html += f"<td>{cell}</td>"
                table_html += "</tr>\n"
            table_html += "</tbody>\n</table>"
        if table_html:
            new_lines = []
            in_table = False
            for i, line in enumerate(lines):
                if i == table_start_idx:
                    in_table = True
                    continue
                elif in_table and (line.strip().startswith('|') and line.strip().endswith('|') and '|' in line.strip()[1:-1] or re.match(r'^\|(?:\s*[-:]+(?:\s*\|)?)+$', line)):
                    continue
                else:
                    in_table = False
                    if line.strip():
                        new_lines.append(line.rstrip())
            remaining_text = '\n'.join(new_lines).rstrip()
            if remaining_text:
                text = remaining_text + '\n' + table_html.rstrip()
            else:
                text = table_html.rstrip()
        else:
            text = '\n'.join(line.rstrip() for line in lines if line.strip()).rstrip()
        return text

    def paste_html(self):
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        if mime_data.hasHtml():
            html_content = mime_data.html()
            cleaned_text = strip_html(html_content)
            cleaned_text = self.convert_markdown_to_html(cleaned_text)
            self.txt_entrada.insertPlainText(cleaned_text)
        elif mime_data.hasImage():
            image = clipboard.image()
            if not image.isNull():
                media_folder = mw.col.media.dir()
                base_name, ext, counter = "img", ".png", 1
                file_name = f"{base_name}{counter}{ext}"
                new_path = os.path.join(media_folder, file_name)
                while os.path.exists(new_path):
                    counter += 1
                    file_name = f"{base_name}{counter}{ext}"
                    new_path = os.path.join(media_folder, file_name)
                image.save(new_path)
                self.media_files.append(file_name)
                self.txt_entrada.insertPlainText(f'<img src="{file_name}">\n')
        elif mime_data.hasText():
            text = clipboard.text()
            text = self.convert_markdown_to_html(text)
            self.txt_entrada.insertPlainText(text)
        else:
            showWarning(self._t("Nenhuma imagem, texto ou HTML encontrado na área de transferência."))
        self.previous_text = self.txt_entrada.toPlainText()
        self.update_preview()

    def paste_excel(self):
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        if mime_data.hasText():
            text = clipboard.text()
            lines = text.strip().split('\n')
            formatted_lines = []
            for line in lines:
                columns = line.split('\t')
                columns = [col.strip() for col in columns]
                formatted_line = ' ; '.join(columns)
                formatted_lines.append(formatted_line)
            formatted_text = '\n'.join(formatted_lines)
            self.txt_entrada.insertPlainText(formatted_text)
            self.previous_text = self.txt_entrada.toPlainText()
            self.update_preview()
        else:
            showWarning(self._t("Nenhum texto encontrado na área de transferência para colar como Excel."))

    def paste_word(self):
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        if mime_data.hasHtml():
            html_content = mime_data.html()
            fragment_match = re.search(r'<!--StartFragment-->(.*?)<!--EndFragment-->', html_content, re.DOTALL)
            if fragment_match:
                html_content = fragment_match.group(1)
            def clean_style_attr(match):
                style_content = match.group(1)
                style_content = re.sub(r'mso-highlight:([\w-]+)', r'background-color:\1', style_content, flags=re.IGNORECASE)
                cleaned_style = re.sub(r'mso-[^;:]*:[^;]*;?', '', style_content)
                cleaned_style = re.sub(r'background:([^;]*)', r'background-color:\1', cleaned_style)
                styles = cleaned_style.split(';')
                style_dict = {}
                for style in styles:
                    if style.strip():
                        key, value = style.split(':')
                        style_dict[key.strip()] = value.strip()
                cleaned_style = ', '.join(f'{key}:{value}' for key, value in style_dict.items() if key in ['color', 'background-color'])
                return f"style='{cleaned_style}'" if cleaned_style else ''
            html_content = re.sub(r"style=['\"]([^'\"]*)['\"]", clean_style_attr, html_content)
            def preserve_colored_spans(match):
                full_span = match.group(0)
                content = match.group(1)
                style = ''
                color_match = re.search(r'color:([#\w]+)', full_span, re.IGNORECASE)
                if color_match and color_match.group(1).lower() != '#000000':
                    style += f'color:{color_match.group(1)}'
                bg_match = re.search(r'background-color:([#\w]+)', full_span, re.IGNORECASE)
                if bg_match and bg_match.group(1).lower() != 'transparent':
                    if style:
                        style += ', '
                    style += f'background-color:{bg_match.group(1)}'
                if style:
                    return f'<span style="{style}">{content}</span>'
                return content
            previous_html = None
            while html_content != previous_html:
                previous_html = html_content
                html_content = re.sub(r'<span[^>]*>(.*?)</span>', preserve_colored_spans, html_content, flags=re.DOTALL)
            html_content = html_content.replace(';', ',')
            html_content = re.sub(r'\s+', ' ', html_content).strip()
            self.txt_entrada.insertPlainText(html_content)
            self.previous_text = self.txt_entrada.toPlainText()
            self.update_preview()
        elif mime_data.hasText():
            text = clipboard.text()
            lines = text.strip().split('\n')
            lines = [line.strip() for line in lines if line.strip()]
            formatted_text = ' '.join(lines)
            self.txt_entrada.insertPlainText(formatted_text)
            self.previous_text = self.txt_entrada.toPlainText()
            self.update_preview()
        else:
            showWarning(self._t("Nenhum texto encontrado na área de transferência para colar como Word."))

    def paste_raw_html(self):
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        if mime_data.hasHtml():
            html_content = mime_data.html()
            tags_to_remove = ['html', 'body', 'head', 'meta', 'link', 'script', 'style', 'title', 'doctype', '!DOCTYPE', 'br', 'hr', 'div', 'p', 'form', 'input', 'button', 'a']
            pattern = r'</?(?:' + '|'.join(tags_to_remove) + r')(?:\s+[^>])?>'
            cleaned_html = re.sub(pattern, '', html_content, flags=re.IGNORECASE)
            cleaned_html = self.convert_markdown_to_html(cleaned_html)
            def protect_structures(match):
                return match.group(0).replace('\n', ' PROTECTED_NEWLINE ')
            cleaned_html = re.sub(r'<ul>.?</ul>|<ol>.?</ol>|<li>.?</li>|<table>.?</table>', protect_structures, cleaned_html, flags=re.DOTALL)
            lines = cleaned_html.split('\n')
            cleaned_lines = [line.strip() for line in lines if line.strip()]
            cleaned_html = '\n'.join(cleaned_lines)
            cleaned_html = cleaned_html.replace(' PROTECTED_NEWLINE ', '\n')
            cleaned_html = re.sub(r'\s+(?![^<]>)', ' ', cleaned_html).strip()
            self.txt_entrada.insertPlainText(cleaned_html)
        elif mime_data.hasText():
            text = clipboard.text()
            text = self.convert_markdown_to_html(text)
            self.txt_entrada.insertPlainText(text)
        else:
            showWarning(self._t("Nenhum texto ou HTML encontrado na área de transferência."))
        self.previous_text = self.txt_entrada.toPlainText()
        self.update_preview()

    def eventFilter(self, obj, event):
        if obj == self.txt_entrada:
            if event.type() == QEvent.Type.KeyPress and event.matches(QKeySequence.StandardKey.Paste):
                self.paste_html()
                return True
            elif event.type() == QEvent.Type.FocusOut:
                self.focus_out_event(event)
                return True
            elif event.type() == QEvent.Type.DragEnter:
                self.drag_enter_event(event)
                return True
            elif event.type() == QEvent.Type.Drop:
                self.drop_event(event)
                return True
        return super().eventFilter(obj, event)

    def criar_lista_rolavel(self, itens, altura_min=100):
        lista = QListWidget()
        lista.addItems(itens)
        lista.setMinimumHeight(altura_min)
        lista.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return lista

    def toggle_group(self):
        novo_estado = not self.group_widget.isVisible()
        self.group_widget.setVisible(novo_estado)
        self.btn_toggle.setText(self._t("Ocultar Decks/Modelos/Delimitadores") if novo_estado else self._t("Mostrar Decks/Modelos/Delimitadores"))
        if hasattr(self, 'main_scroll') and self.main_scroll:
            QTimer.singleShot(100, lambda: self.main_scroll.ensureVisible(0, self.main_scroll.verticalScrollBar().maximum()))

    def toggle_formatting_tools(self):
        is_visible = self.tool_tabs.isVisible()
        self.tool_tabs.setVisible(not is_visible)
        if is_visible:
            self.btn_toggle_formatting.setText(self._t("Mostrar Ferramentas"))
        else:
            self.btn_toggle_formatting.setText(self._t("Ocultar Ferramentas"))

    def ajustar_tamanho_scroll(self):
        self.lista_decks.adjustSize()
        self.lista_notetypes.adjustSize()
        self.lista_decks.updateGeometry()
        self.lista_notetypes.updateGeometry()

    def scan_media_files_from_text(self):
        patterns = [r'<img src="([^"]+)"', r'<source src="([^"]+)"', r'<video src="([^"]+)"']
        current_text = self.txt_entrada.toPlainText()
        media_dir = mw.col.media.dir()
        found_media = set()
        for pattern in patterns:
            matches = re.findall(pattern, current_text)
            for file_name in matches:
                file_path = os.path.join(media_dir, file_name)
                if os.path.exists(file_path) and file_name not in self.media_files:
                    found_media.add(file_name)
        self.media_files.extend(found_media)
        self.media_files = list(dict.fromkeys(self.media_files))

    def toggle_theme(self):
        self.is_dark_theme = not self.is_dark_theme
        theme_manager.set_night_mode(self.is_dark_theme)

        if self.is_dark_theme:
            self.setStyleSheet("""
                QWidget { background-color: #333; color: #eee; }
                QGroupBox { border: 1px solid #555; margin-top: 10px; padding-top: 15px; }
                QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
                QTextEdit, QLineEdit, QListWidget { 
                    background-color: #2d2d2d; 
                    color: #eee; 
                    border: 1px solid #555; 
                    selection-background-color: #4a90d9; 
                    selection-color: #fff;
                }
                QListWidget::item:selected { background-color: #4a90d9; color: #000; }
                QPushButton { 
                    background-color: #555; color: #eee; border: 1px solid #666; 
                    padding: 5px; border-radius: 5px;
                }
                QPushButton:hover { background-color: #6a6a6a; }
                QTabWidget::pane { border-top: 1px solid #666; }
                QTabBar::tab { background: #555; color: #eee; padding: 8px; border: 1px solid #666; border-bottom: none; }
                QTabBar::tab:selected { background: #333; color: #eee; border-bottom: 1px solid #333; }
            """)
            self.txt_entrada.line_number_area.setStyleSheet("background-color: #333; color: #aaa;")
            self.theme_button.setText(self._t("Tema Claro"))
        else:
            self.setStyleSheet("""
                QWidget { background-color: #f0f0f0; color: #000; }
                QGroupBox { border: 1px solid #ccc; margin-top: 10px; padding-top: 15px; }
                QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
                QTextEdit, QLineEdit, QListWidget { 
                    background-color: #fff; 
                    color: #000; 
                    border: 1px solid #ccc; 
                    selection-background-color: #4a90d9; 
                    selection-color: #fff;
                }
                QListWidget::item:selected { background-color: #4a90d9; color: #fff; }
                QPushButton { 
                    background-color: #f0f0f0; color: #000; border: 1px solid #ccc; 
                    padding: 5px; border-radius: 5px;
                }
                QPushButton:hover { background-color: #e0e0e0; }
                QTabWidget::pane { border-top: 1px solid #ccc; }
                QTabBar::tab { background: #e0e0e0; color: #000; padding: 8px; border: 1px solid #ccc; border-bottom: none; }
                QTabBar::tab:selected { background: #f0f0f0; color: #000; }
            """)
            self.txt_entrada.line_number_area.setStyleSheet("background-color: #f0f0f0; color: #555;")
            self.theme_button.setText(self._t("Tema Escuro"))

        # Estilos especiais que sobrescrevem o tema
        self.botoes_formatacao_widgets["Destaque"].setStyleSheet("background-color: yellow; color: black;")
        if self.edit_mode:
            self.edit_button.setStyleSheet("background-color: #ffdddd; color: black;")

        self.highlight_current_line()
        self.update_preview()

    def copy_media_files(self, dest_folder):
        media_files = set()
        text = self.txt_entrada.toPlainText()
        for pattern in [r'src="([^"]+)"', r'<source src="([^"]+)"', r'<video src="([^"]+)"']:
            media_files.update(re.findall(pattern, text))
        media_dir = mw.col.media.dir()
        for file_name in media_files:
            src = os.path.join(media_dir, file_name)
            dst = os.path.join(dest_folder, file_name)
            if os.path.exists(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)

    def export_to_html(self):
        try:
            html_content = generate_export_html(self, self._t)
            if not html_content:
                return
            desktop_path = os.path.join(os.path.expanduser("~/Desktop"), "delimit.html")
            with open(desktop_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            webbrowser.open(f"file://{os.path.abspath(desktop_path)}")
        except Exception as e:
            QMessageBox.critical(self, self._t("Erro na Exportação"), self._t("Ocorreu um erro durante a exportação: {}").format(str(e)))

    def update_tag_numbers(self):
        linhas_tags = self.txt_tags.toPlainText().strip().split('\n')
        num_linhas_cards = len(self.txt_entrada.toPlainText().strip().splitlines())
        if not any(linhas_tags) and num_linhas_cards > 0:
            self.txt_tags.setPlainText('\n'.join(f"{i + 1}" for i in range(num_linhas_cards)))
            self.initial_numbering_set = True
            self.update_preview()
            return
        if self.chk_num_tags.isChecked() and not self.initial_numbering_set:
            updated_tags = []
            for i in range(num_linhas_cards):
                if i < len(linhas_tags) and linhas_tags[i].strip():
                    tags_for_card = [tag.rstrip('0123456789') for tag in linhas_tags[i].split(',') if tag.strip()]
                    numbered_tags = [f"{tag}{i + 1}" for tag in tags_for_card]
                    updated_tags.append(", ".join(numbered_tags))
                else:
                    updated_tags.append("")
            self.txt_tags.setPlainText('\n'.join(updated_tags))
            self.initial_numbering_set = True
        elif not self.chk_num_tags.isChecked():
            updated_tags = []
            for i in range(num_linhas_cards):
                if i < len(linhas_tags) and linhas_tags[i].strip():
                    tags_for_card = [tag.rstrip('0123456789') for tag in linhas_tags[i].split(',') if tag.strip()]
                    updated_tags.append(", ".join(tags_for_card))
                else:
                    updated_tags.append("")
            self.txt_tags.setPlainText('\n'.join(updated_tags))
            self.initial_numbering_set = False
        self.update_preview()

    def update_repeated_tags(self):
        if self.chk_repetir_tags.isChecked() and not self.initial_tags_set:
            linhas_tags = self.txt_tags.toPlainText().strip().split('\n')
            num_cards = len(self.txt_entrada.toPlainText().strip().splitlines())
            if not any(linhas_tags):
                self.txt_tags.setPlainText('\n' * (num_cards - 1))
                self.initial_tags_set = True
                self.update_preview()
                return
            first_non_empty = next((tags for tags in linhas_tags if tags.strip()), None)
            if not first_non_empty:
                self.txt_tags.setPlainText('\n' * (num_cards - 1))
                self.initial_tags_set = True
                self.update_preview()
                return
            tags = list(dict.fromkeys([tag.strip() for tag in first_non_empty.split(',') if tag.strip()]))
            if not tags:
                self.txt_tags.setPlainText('\n' * (num_cards - 1))
                self.initial_tags_set = True
                self.update_preview()
                return
            self.txt_tags.setPlainText('\n'.join([", ".join(tags)] * num_cards))
            self.initial_tags_set = True
        elif not self.chk_repetir_tags.isChecked():
            self.initial_tags_set = False
            self.update_tag_numbers()
        self.update_preview()

    def search_text(self):
        search_query = self.search_input.text().strip()
        if not search_query:
            showWarning(self._t("Por favor, insira um texto para pesquisar."))
            return
        search_words = search_query.split()
        if search_query != self.last_search_query:
            self.last_search_query = search_query
            self.last_search_position = 0
        cursor = self.txt_entrada.textCursor()
        cursor.setPosition(self.last_search_position)
        self.txt_entrada.setTextCursor(cursor)
        found = False
        for word in search_words:
            if self.txt_entrada.find(word):
                self.last_search_position = self.txt_entrada.textCursor().position()
                found = True
                break
        if not found:
            self.txt_entrada.moveCursor(QTextCursor.MoveOperation.Start)
            for word in search_words:
                if self.txt_entrada.find(word):
                    self.last_search_position = self.txt_entrada.textCursor().position()
                    found = True
                    break
        if not found:
            showWarning(self._t("Texto '{}' não encontrado.").format(search_query))
        self.update_preview()

    def replace_text(self):
        search_query = self.search_input.text().strip()
        replace_text_str = self.replace_input.text()
        if not search_query:
            showWarning(self._t("Por favor, insira um texto para pesquisar."))
            return
        full_text = self.txt_entrada.toPlainText()
        replaced_text = re.sub(re.escape(search_query), replace_text_str, full_text, flags=re.IGNORECASE)
        self.txt_entrada.setPlainText(replaced_text)
        self.previous_text = replaced_text
        self.update_preview()
        if replace_text_str:
            showInfo(self._t("Todas as ocorrências de '{}' foram substituídas por '{}'.").format(search_query, replace_text_str))
        else:
            showInfo(self._t("Todas as ocorrências de '{}' foram removidas.").format(search_query))

    def zoom_in(self):
        self.txt_entrada.zoomIn(1)
        self.zoom_factor += 0.1

    def create_deck(self):
        deck_name = self.deck_name_input.text().strip()
        if not deck_name:
            showWarning(self._t("Por favor, insira um nome para o deck!"))
            return
        try:
            mw.col.decks.id(deck_name)
            self.lista_decks.clear()
            self.lista_decks.addItems([d.name for d in mw.col.decks.all_names_and_ids()])
            
            deck_count = len(mw.col.decks.all_names_and_ids())
            self.decks_group.setTitle(self._t("Decks: {}").format(deck_count))
            self.deck_name_input.clear()

            self.schedule_save()
        except Exception as e:
            showWarning(self._t("Erro ao criar o deck: {}").format(str(e)))

    def zoom_out(self):
        if self.zoom_factor > 0.2:
            self.txt_entrada.zoomOut(1)
            self.zoom_factor -= 0.1

    def filter_list(self, list_widget, search_input, full_list):
        search_text = search_input.text().strip().lower()
        filtered = [item for item in full_list if search_text in item.lower()]
        list_widget.clear()
        list_widget.addItems(filtered)
        if filtered and search_text:
            list_widget.setCurrentRow(0)

    def filter_decks(self):
        self.filter_list(self.lista_decks, self.decks_search_input, [d.name for d in mw.col.decks.all_names_and_ids()])

    def filter_notetypes(self):
        self.filter_list(self.lista_notetypes, self.notetypes_search_input, mw.col.models.all_names())

    def create_focus_handler(self, widget, field_type):
        def focus_in_event(event):
            self.txt_entrada.setStyleSheet("")
            self.txt_tags.setStyleSheet("")
            widget.setStyleSheet(f"border: 2px solid {'blue' if field_type == 'cards' else 'green'};")
            self.tags_label.setText(self._t("Etiquetas:") if field_type == "cards" else self._t("Etiquetas (Selecionado)"))
            if isinstance(widget, QTextEdit):
                QTextEdit.focusInEvent(widget, event)
        return focus_in_event

    def concatenate_text(self):
        clipboard = QApplication.clipboard()
        copied_text = clipboard.text().strip().split("\n")
        current_widget = self.txt_entrada if self.txt_entrada.styleSheet() else self.txt_tags if self.txt_tags.styleSheet() else self.txt_entrada
        current_text = current_widget.toPlainText().strip().split("\n")
        result_lines = [f"{current_text[i] if i < len(current_text) else ''}{copied_text[i] if i < len(copied_text) else ''}".strip() for i in range(max(len(current_text), len(copied_text)))]
        current_widget.setPlainText("\n".join(result_lines))
        self.previous_text = self.txt_entrada.toPlainText()
        self.update_preview()

    def add_cloze_1(self):
        cursor = self.txt_entrada.textCursor()
        selected_text = cursor.selectedText().strip()
        if not selected_text:
            showWarning(self._t("Por favor, selecione uma palavra para adicionar o cloze."))
            return
        cursor.insertText(f"{{{{c1::{selected_text}}}}}")
        self.previous_text = self.txt_entrada.toPlainText()
        self.update_preview()

    def add_cloze_2(self):
        cursor = self.txt_entrada.textCursor()
        selected_text = cursor.selectedText().strip()
        if not selected_text:
            showWarning(self._t("Por favor, selecione uma palavra para adicionar o cloze."))
            return
        cursor.insertText(f"{{{{c{self.cloze_2_count}::{selected_text}}}}}")
        self.cloze_2_count += 1
        self.previous_text = self.txt_entrada.toPlainText()
        self.update_preview()

    def remove_cloze(self):
        self.txt_entrada.setPlainText(re.sub(r'{{c\d+::(.*?)}}', r'\1', self.txt_entrada.toPlainText()))
        self.previous_text = self.txt_entrada.toPlainText()
        self.update_preview()

    def join_lines(self):
        texto = self.txt_entrada.toPlainText()
        if '\n' not in texto:
            if hasattr(self, 'original_text'):
                self.txt_entrada.setPlainText(self.original_text)
                del self.original_text
        else:
            self.original_text = texto
            self.txt_entrada.setPlainText(texto.replace('\n', ' '))
        self.previous_text = self.txt_entrada.toPlainText()
        self.update_preview()

    def wrap_selected_text(self, tag):
        cursor = self.txt_entrada.textCursor()
        if cursor.hasSelection():
            texto = cursor.selectedText()
            cursor.insertText(f"{tag[0]}{texto}{tag[1]}")
        else:
            cursor.insertText(f"{tag[0]}{tag[1]}")
            cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, len(tag[1]))
            self.txt_entrada.setTextCursor(cursor)
        self.previous_text = self.txt_entrada.toPlainText()
        self.update_preview()

    def apply_bold(self): self.wrap_selected_text(('<b>', '</b>'))
    def apply_italic(self): self.wrap_selected_text(('<i>', '</i>'))
    def apply_underline(self): self.wrap_selected_text(('<u>', '</u>'))
    def destaque_texto(self): self.wrap_selected_text(('<mark>', '</mark>'))

    def manage_media(self):
        if hasattr(self, 'media_dialog') and self.media_dialog:
            self.media_dialog.showNormal()
            self.media_dialog.raise_()
            self.media_dialog.activateWindow()
            return
        self.scan_media_files_from_text()
        if not self.media_files:
            showWarning(self._t("Nenhum arquivo de mídia foi adicionado ou referenciado no texto!"))
            return
        self.media_dialog = MediaManagerDialog(self, self.media_files, self.txt_entrada, mw, self._t)
        self.media_dialog.show()

    def show_dialog():
        global custom_dialog_instance
        if not hasattr(mw, 'custom_dialog_instance') or not mw.custom_dialog_instance:
            mw.custom_dialog_instance = CustomDialog(mw)
        if mw.custom_dialog_instance.isVisible():
            mw.custom_dialog_instance.raise_()
            mw.custom_dialog_instance.activateWindow()
        else:
            mw.custom_dialog_instance.show()

    def closeEvent(self, event):
        self._save_in_real_time()
        if hasattr(mw, 'delimitadores_dialog'):
            mw.delimitadores_dialog = None
        if hasattr(self, 'media_dialog') and self.media_dialog:
            self.media_dialog.close()
            self.media_dialog = None
        if hasattr(mw, 'custom_dialog_instance'):
            mw.custom_dialog_instance = None
        super().closeEvent(event)

    def view_cards_dialog(self):
        if self.visualizar_dialog is None or not self.visualizar_dialog.isVisible():
            self.visualizar_dialog = VisualizarCards(self, self._t)
            self.visualizar_dialog.show()
        else:
            self.visualizar_dialog.raise_()
            self.visualizar_dialog.activateWindow()

    def toggle_editor_view(self):
        if self.stacked_editor.currentIndex() == 0:
            self.switch_to_grid_view()
            self.toggle_view_button.setText(self._t("📄 Editar como Texto"))
        else:
            self.switch_to_text_view()
            self.toggle_view_button.setText(self._t("📝 Editar em Grade"))

    def switch_to_grid_view(self):
        text = self.txt_entrada.toPlainText()
        lines = text.split('\n')
        
        self.table_widget.setRowCount(0)
        self.table_widget.setColumnCount(0)

        if not text.strip():
            self.stacked_editor.setCurrentIndex(1)
            return

        max_cols = 0
        all_parts = []
        for line in lines:
            parts = self._get_split_parts(line)
            all_parts.append(parts)
            if len(parts) > max_cols:
                max_cols = len(parts)
        
        self.table_widget.setColumnCount(max_cols)
        self.table_widget.setRowCount(len(lines))

        self.table_widget.setHorizontalHeaderLabels([self._t("Campo {}").format(i + 1) for i in range(max_cols)])

        for row, parts in enumerate(all_parts):
            for col, part_text in enumerate(parts):
                item = QTableWidgetItem(part_text.strip())
                self.table_widget.setItem(row, col, item)
        
        self.table_widget.resizeColumnsToContents()
        self.stacked_editor.setCurrentIndex(1)

    def switch_to_text_view(self):
        active_delimiter = next((chk.simbolo for chk in self.chk_delimitadores.values() if chk.isChecked()), ';')
        
        lines = []
        for row in range(self.table_widget.rowCount()):
            row_data = []
            for col in range(self.table_widget.columnCount()):
                item = self.table_widget.item(row, col)
                row_data.append(item.text() if item else "")
            lines.append(active_delimiter.join(row_data))
        
        self.txt_entrada.setPlainText("\n".join(lines))
        self.stacked_editor.setCurrentIndex(0)

    def add_media_to_cell(self, item):
        arquivos, _ = QFileDialog.getOpenFileNames(self, self._t("Selecionar Mídia"), "", "Mídia (*.png *.jpg *.jpeg *.gif *.mp3 *.wav *.ogg *.mp4 *.webm)")
        if not arquivos:
            return

        media_dir = mw.col.media.dir()
        html_to_add = []

        for caminho in arquivos:
            nome = os.path.basename(caminho)
            destino = os.path.join(media_dir, nome)
            if os.path.exists(destino):
                base, ext = os.path.splitext(nome)
                counter = 1
                while os.path.exists(destino):
                    nome = f"{base}_{counter}{ext}"
                    destino = os.path.join(media_dir, nome)
                    counter += 1
            shutil.copy2(caminho, destino)
            
            ext = os.path.splitext(nome)[1].lower()
            if ext in ('.png', '.jpg', '.jpeg', '.gif'):
                html_to_add.append(f'<img src="{nome}">')
            elif ext in ('.mp3', '.wav', '.ogg'):
                html_to_add.append(f'[sound:{nome}]')
            else:
                continue
        
        current_text = item.text()
        new_text = current_text + " " + " ".join(html_to_add)
        item.setText(new_text.strip())
        
        self.switch_to_text_view()
        self.toggle_view_button.setText(self._t("📝 Editar em Grade"))

    def natural_sort_key(self, s):
        def convert(text):
            try:
                return int(text)
            except ValueError:
                return text.lower()
        return [convert(c) for c in re.split('([0-9]+)', s)]

    def sort_cards_alphabetically(self):
        if self.card_creation_info:
            current_lines = [info[1] for info in self.card_creation_info]
            sorted_lines = sorted(current_lines, key=self.natural_sort_key)
            
            reverse_sort = (current_lines == sorted_lines)
            
            self.card_creation_info.sort(key=lambda x: self.natural_sort_key(x[1]), reverse=reverse_sort)
            self.current_view_mode = 'simple'
            self._repopulate_ui_from_creation_info()
            return

        if not self.txt_entrada.toPlainText().strip():
            return

        card_lines = self.txt_entrada.toPlainText().split('\n')
        tag_lines = self.txt_tags.toPlainText().split('\n')

        sorted_card_lines_check = sorted(card_lines, key=self.natural_sort_key)
        reverse_sort = (card_lines == sorted_card_lines_check)

        while len(tag_lines) < len(card_lines):
            tag_lines.append('')

        combined_lines = list(zip(card_lines, tag_lines))
        combined_lines.sort(key=lambda x: self.natural_sort_key(x[0]), reverse=reverse_sort)

        if not combined_lines:
            return

        sorted_card_lines, sorted_tag_lines = zip(*combined_lines)

        self.txt_entrada.setPlainText('\n'.join(sorted_card_lines))
        self.txt_tags.setPlainText('\n'.join(sorted_tag_lines))

    def sort_cards_randomly(self):
        if self.card_creation_info:
            random.shuffle(self.card_creation_info)
            self.current_view_mode = 'simple'
            self._repopulate_ui_from_creation_info()
            return

        if not self.txt_entrada.toPlainText().strip():
            return

        card_lines = self.txt_entrada.toPlainText().split('\n')
        tag_lines = self.txt_tags.toPlainText().split('\n')
        while len(tag_lines) < len(card_lines):
            tag_lines.append('')
        
        combined = list(zip(card_lines, tag_lines))
        random.shuffle(combined)
        
        if not combined:
            return
            
        shuffled_cards, shuffled_tags = zip(*combined)
        self.txt_entrada.setPlainText('\n'.join(shuffled_cards))
        self.txt_tags.setPlainText('\n'.join(shuffled_tags))

    def sort_cards_by_creation_date(self):
        if not self.card_creation_info:
            return

        if self.current_view_mode == 'date':
            self.card_creation_info.reverse()
        else:
            self.card_creation_info.sort(key=lambda x: x[0])
        
        self.current_view_mode = 'date'
        self._repopulate_ui_from_creation_info()

    def sort_cards_by_lapses(self):
        if not self.card_creation_info:
            return

        if len(self.card_creation_info[0]) < 5:
            for info in self.card_creation_info:
                nid = info[0]
                card_ids = mw.col.card_ids_of_note(nid)
                
                total_lapses = 0
                total_reps = 0

                if card_ids:
                    for cid in card_ids:
                        lapses_for_card = mw.col.db.scalar(
                            "SELECT count() FROM revlog WHERE cid = ? AND ease = 1", cid
                        )
                        reps_for_card = mw.col.db.scalar(
                            "SELECT count() FROM revlog WHERE cid = ?", cid
                        )
                        total_lapses += lapses_for_card if lapses_for_card else 0
                        total_reps += reps_for_card if reps_for_card else 0
                
                info.extend([total_lapses, total_reps])

        current_lapses = [info[3] for info in self.card_creation_info]
        sorted_lapses_desc = sorted(current_lapses, reverse=True)
        
        reverse_sort = not (current_lapses == sorted_lapses_desc)

        if reverse_sort:
            self.mais_errados_button.setText(self._t("Mais Errados"))
            self.mais_errados_button.setToolTip(self._t("Organizar por cards mais errados (com mais lapsos)"))
            self.lapses_sort_descending = True
        else:
            self.mais_errados_button.setText(self._t("Mais Certos"))
            self.mais_errados_button.setToolTip(self._t("Organizar por cards mais certos (com menos lapsos)"))
            self.lapses_sort_descending = False

        self.card_creation_info.sort(key=lambda x: x[3], reverse=reverse_sort)
        self.current_view_mode = 'stats'
        self._repopulate_ui_from_creation_info()

    def _repopulate_ui_from_creation_info(self):
        if not self.card_creation_info:
            return

        unpacked = [list(item) for item in self.card_creation_info]
        nids = [item[0] for item in unpacked]
        card_lines = [item[1] for item in unpacked]
        tag_lines = [item[2] for item in unpacked]

        self.txt_entrada.blockSignals(True)
        self.txt_tags.blockSignals(True)

        self.txt_entrada.setPlainText('\n'.join(card_lines))
        self.txt_tags.setPlainText('\n'.join(tag_lines))

        self.txt_entrada.blockSignals(False)
        self.txt_tags.blockSignals(False)

        if self.current_view_mode == 'date':
            dates = [datetime.fromtimestamp(nid / 1000).strftime('%Y-%m-%d') for nid in nids]
            numbers_with_dates = [f"{i+1} ({date_str})" for i, date_str in enumerate(dates)]
            self.txt_entrada.line_number_area.line_numbers = numbers_with_dates
        elif self.current_view_mode == 'stats':
            stats_lines = [f"{i+1} (E:{item[3]} R:{item[4]})" for i, item in enumerate(unpacked)]
            self.txt_entrada.line_number_area.line_numbers = stats_lines
        else: # 'simple'
            line_count = len(self.card_creation_info)
            self.txt_entrada.line_number_area.line_numbers = [str(i + 1) for i in range(line_count)]
        
        self.txt_entrada.line_number_area.update()
        self.update_line_number_area_width()

        self.shown_note_ids = list(nids)

    def delete_deck(self):
        deck_item = self.lista_decks.currentItem()
        if not deck_item:
            showWarning(self._t("Por favor, selecione um deck para excluir."))
            return
        deck_name = deck_item.text()

        nids_to_delete = mw.col.find_notes(f'deck:"{deck_name}"')
        msg = self._t("Você tem certeza que deseja excluir o deck '{}'?\n\n"
                      "Isso excluirá permanentemente {} card(s) e suas mídias associadas (se não forem usadas em outros decks).\n\n"
                      "ESTA AÇÃO NÃO PODE SER DESFEITA.").format(deck_name, len(nids_to_delete))
        
        reply = QMessageBox.question(self, self._t("Confirmar Exclusão de Deck"), msg,
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            mw.progress.start(label=self._t("Excluindo deck..."), max=3)

            media_to_check = set()
            for nid in nids_to_delete:
                note = mw.col.get_note(nid)
                if not note: continue
                text_content = "".join(note.fields)
                media_to_check.update(mw.col.media.files_in_str(note.mid, text_content))
            
            other_nids = mw.col.find_notes(f'-deck:"{deck_name}"')
            media_in_use_elsewhere = set()
            for nid in other_nids:
                note = mw.col.get_note(nid)
                if not note: continue
                text_content = "".join(note.fields)
                media_in_use_elsewhere.update(mw.col.media.files_in_str(note.mid, text_content))

            files_to_delete = media_to_check - media_in_use_elsewhere
            media_dir = mw.col.media.dir()
            for fname in files_to_delete:
                try:
                    os.remove(os.path.join(media_dir, fname))
                except Exception as e:
                    logging.warning(f"Não foi possível excluir o arquivo de mídia '{fname}': {e}")
            
            mw.progress.update(value=1, label=self._t("Mídia verificada..."))

            if nids_to_delete:
                mw.col.remove_notes(nids_to_delete)
            
            mw.progress.update(value=2, label=self._t("Cards excluídos..."))

            deck_id = mw.col.decks.id(deck_name)
            mw.col.decks.remove([deck_id])

            mw.progress.update(value=3, label=self._t("Atualizando interface..."))

            self.lista_decks.clear()
            self.lista_decks.addItems([d.name for d in mw.col.decks.all_names_and_ids()])
            deck_count = len(mw.col.decks.all_names_and_ids())
            self.decks_group.setTitle(self._t("Decks: {}").format(deck_count))

            mw.progress.finish()
            mw.reset()

        except Exception as e:
            mw.progress.finish()
            showWarning(self._t("Ocorreu um erro ao excluir o deck: {}").format(str(e)))
            logging.error(f"Erro ao excluir deck: {e}")
