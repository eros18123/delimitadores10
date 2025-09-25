# visualizar.py - CORREÇÃO DEFINITIVA COM SCROLL FORÇADO

import os
import re
import base64
import html
import json
from aqt import mw, gui_hooks
from aqt.qt import *
from aqt.utils import showWarning
from aqt.webview import AnkiWebView
from aqt.theme import theme_manager
from anki.utils import pointVersion

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

class VisualizarCards(QDialog):
    def __init__(self, parent, translator):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowCloseButtonHint | Qt.WindowType.WindowMaximizeButtonHint)
        self.parent = parent
        self._t = translator
        self.cards_data = []
        self.cards_visible = True
        self.setup_ui()
        self.load_and_display_cards()

    def setup_ui(self):
        self.setWindowTitle(self._t("Visualizar Todos os Cards"))
        self.resize(800, 600)
        
        main_layout = QVBoxLayout()
        
        top_controls_layout = QHBoxLayout()
        self.toggle_cards_button = QPushButton(self._t("Ocultar Lista"), self)
        self.toggle_cards_button.clicked.connect(self.toggle_cards_visibility)
        top_controls_layout.addWidget(self.toggle_cards_button)
        top_controls_layout.addStretch()
        
        zoom_in_button = ForceLabelButton("+", parent=self)
        zoom_in_button.setFixedSize(30, 30)
        zoom_in_button.setToolTip(self._t("Aumentar Zoom"))
        zoom_in_button.clicked.connect(self.zoom_in)
        top_controls_layout.addWidget(zoom_in_button)
        
        zoom_out_button = ForceLabelButton("-", parent=self)
        zoom_out_button.setFixedSize(30, 30)
        zoom_out_button.setToolTip(self._t("Diminuir Zoom"))
        zoom_out_button.clicked.connect(self.zoom_out)
        top_controls_layout.addWidget(zoom_out_button)
        
        main_layout.addLayout(top_controls_layout)
        
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        
        self.card_list_widget = QListWidget()
        self.card_list_widget.currentItemChanged.connect(self.update_card_preview)
        self.card_list_widget.setMaximumWidth(200)
        self.card_list_widget.setMinimumWidth(100)
        self.splitter.addWidget(self.card_list_widget)
        
        self.card_preview_webview = AnkiWebView(self)
        self.card_preview_webview.setMinimumWidth(300)
        self.splitter.addWidget(self.card_preview_webview)
        
        self.splitter.setSizes([200, 600])
        main_layout.addWidget(self.splitter)
        self.setLayout(main_layout)

    def _get_reviewer_scripts(self):
        pv = pointVersion()
        if pv >= 231210:
            return ["js/mathjax.js", "js/vendor/mathjax/tex-chtml-full.js", "js/reviewer.js"]
        elif pv >= 45:
            return ["js/mathjax.js", "js/vendor/mathjax/tex-chtml.js", "js/reviewer.js"]
        else:
            return ["js/vendor/jquery.min.js", "js/vendor/css_browser_selector.min.js", "js/mathjax.js", "js/vendor/mathjax/tex-chtml.js", "js/reviewer.js"]

    def zoom_in(self):
        self.card_preview_webview.setZoomFactor(self.card_preview_webview.zoomFactor() + 0.1)

    def zoom_out(self):
        self.card_preview_webview.setZoomFactor(max(0.1, self.card_preview_webview.zoomFactor() - 0.1))

    def generate_card_data(self):
        self.cards_data.clear()
        
        linhas = self.parent.txt_entrada.toPlainText().strip().split('\n')
        model = mw.col.models.by_name(self.parent.lista_notetypes.currentItem().text())
        field_mappings = self.parent.field_mappings

        mw.progress.start(label=self._t("Preparando pré-visualização dos cards..."), max=len(linhas))

        for i, linha in enumerate(linhas):
            mw.progress.update(value=i + 1)
            linha = linha.strip()
            if not linha:
                continue
            
            try:
                note = mw.col.new_note(model)
                parts = self.parent._get_split_parts(linha)
                
                if not field_mappings:
                    for idx, field_content in enumerate(parts):
                        if idx < len(note.fields):
                            note.fields[idx] = field_content.strip()
                else:
                    field_names = [f['name'] for f in model['flds']]
                    for part_idx, field_content in enumerate(parts):
                        target_field_name = field_mappings.get(str(part_idx))
                        if target_field_name and target_field_name in field_names:
                            field_idx = field_names.index(target_field_name)
                            note.fields[field_idx] = field_content.strip()

                card = note.ephemeral_card()
                if not card: continue

                question_html = mw.prepare_card_text_for_display(card.question())
                answer_html = mw.prepare_card_text_for_display(card.answer())

                script_pattern = re.compile(r"<script[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)
                style_pattern = re.compile(r"<style[^>]*>(.*?)</style>", re.DOTALL | re.IGNORECASE)
                
                unique_scripts = set(script_pattern.findall(question_html) + script_pattern.findall(answer_html))
                unique_styles = set(style_pattern.findall(question_html) + style_pattern.findall(answer_html))

                question_html = script_pattern.sub("", style_pattern.sub("", question_html))
                answer_html = script_pattern.sub("", style_pattern.sub("", answer_html))

                question_html = gui_hooks.card_will_show(question_html, card, "clayoutQuestion")
                answer_html = gui_hooks.card_will_show(answer_html, card, "clayoutAnswer")

                body_class = theme_manager.body_classes_for_card_ord(card.ord, theme_manager.night_mode)

                # --- INÍCIO DA CORREÇÃO DEFINITIVA ---
                # Injetamos um estilo com '!important' para forçar a barra de rolagem,
                # sobrescrevendo o 'overflow: hidden' do arquivo reviewer.css do Anki.
                override_style = """
                <style>
                    html, body {
                        overflow-y: auto !important;
                        height: auto !important;
                    }
                </style>
                """

                final_html = f"""
                {override_style}
                <div class="preview-section" style="border: 1px solid #4a4a4a; border-radius: 8px; margin: 10px; overflow: hidden;">
                    <div class="preview-header" style="background-color: #3a3a3a; padding: 5px 15px; font-weight: bold; border-bottom: 1px solid #4a4a4a;">{self._t("Frente do Cartão (Preview)")}</div>
                    <div id="preview-front" class="preview-content" style="padding: 15px;">{question_html}</div>
                </div>
                <div class="preview-section" style="border: 1px solid #4a4a4a; border-radius: 8px; margin: 10px; overflow: hidden;">
                    <div class="preview-header" style="background-color: #3a3a3a; padding: 5px 15px; font-weight: bold; border-bottom: 1px solid #4a4a4a;">{self._t("Verso do Cartão (Preview)")}</div>
                    <div id="preview-back" class="preview-content" style="padding: 15px;">{answer_html}</div>
                </div>
                """
                # --- FIM DA CORREÇÃO ---
                
                self.cards_data.append({
                    "html": f'<div id="qa">{final_html}</div>',
                    "body_class": body_class,
                    "scripts": unique_scripts,
                    "styles": unique_styles,
                })

            except Exception as e:
                self.cards_data.append({"error": f"Erro ao renderizar card {i+1}:<br><pre>{html.escape(str(e))}</pre>"})
        
        mw.progress.finish()

    def load_and_display_cards(self):
        if not self.parent.txt_entrada.toPlainText().strip():
            showWarning(self._t("Digite conteúdo para visualizar!"))
            self.close()
            return
        if not self.parent.lista_notetypes.currentItem():
            showWarning(self._t("Selecione um tipo de nota para visualizar!"))
            self.close()
            return
            
        self.generate_card_data()
        
        if not self.cards_data:
            showWarning(self._t("Nenhum card válido para visualizar!"))
            self.close()
            return
            
        self.card_list_widget.clear()
        self.card_list_widget.addItems([f"Card {i+1}" for i in range(len(self.cards_data))])
        if self.cards_data:
            self.card_list_widget.setCurrentRow(0)

    def update_card_preview(self, current, previous):
        if not current:
            self.card_preview_webview.setHtml("")
            return

        index = self.card_list_widget.row(current)
        if not (0 <= index < len(self.cards_data)):
            return

        data = self.cards_data[index]

        if "error" in data:
            self.card_preview_webview.setHtml(f"<html><body>{data['error']}</body></html>")
            return

        try:
            self.card_preview_webview.loadFinished.disconnect()
        except TypeError:
            pass

        def on_load_finished(ok):
            if not ok: return
            self.card_preview_webview.eval(f"document.body.className = '{data['body_class']}';")
            for style_content in data['styles']:
                escaped_style = json.dumps(style_content)
                self.card_preview_webview.eval(f"var style = document.createElement('style'); style.type = 'text/css'; style.innerHTML = {escaped_style}; document.head.appendChild(style);")
            for script in data['scripts']:
                if script.strip():
                    self.card_preview_webview.eval(script)
            self.card_preview_webview.eval("if (typeof MathJax !== 'undefined') MathJax.typesetPromise();")

        self.card_preview_webview.loadFinished.connect(on_load_finished)

        self.card_preview_webview.stdHtml(
            data['html'],
            css=["css/reviewer.css"],
            js=self._get_reviewer_scripts(),
            context=self
        )

    def toggle_cards_visibility(self):
        self.cards_visible = not self.cards_visible
        self.toggle_cards_button.setText(self._t("Mostrar Lista") if not self.cards_visible else self._t("Ocultar Lista"))
        self.card_list_widget.setVisible(self.cards_visible)