# exporthtml.py - VERSÃO FINAL E CORRIGIDA

import os
import re
import base64
from urllib.parse import unquote
from aqt import mw
from aqt.utils import showWarning

# --- FUNÇÕES AUXILIARES ---

def get_common_css(cards_per_row):
    """Gera o CSS unificado para a exportação."""
    return f"""
<style>
    * {{ box-sizing: border-box; }}
    body {{ background-color: #F0F0F0; font-family: sans-serif; margin: 15px; }}
    h1 {{ text-align: center; color: #333; margin-bottom: 25px; }}
    .card-grid {{ display: grid; grid-template-columns: repeat({cards_per_row}, 1fr); gap: 20px; align-items: stretch; }}
    .card-item {{ background-color: #fff; border: 1px solid #CCC; border-radius: 12px; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 4px 8px rgba(0,0,0,0.07); }}
    .card-content-wrapper {{ flex-grow: 1; padding: 15px; overflow-y: auto; min-height: 0; display: flex; flex-direction: column; }}
    .card-content-wrapper .card {{ flex-grow: 1; display: flex; flex-direction: column; }}
    @media print {{
        @page {{ size: A4; margin: 1cm; }}
        body {{ background-color: #FFF !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; margin: 0; }}
        h1 {{ margin: 0 0 5mm 0; page-break-after: avoid; }}
        .card-grid {{ gap: 5mm; align-items: start; }}
        .card-item {{ height: auto !important; page-break-inside: avoid !important; border: 1px solid #DDD; box-shadow: none; }}
        .card-content-wrapper {{ overflow: visible !important; height: auto !important; }}
        audio, .anki-controls {{ display: none !important; }}
    }}
    .card-content-wrapper img {{ max-width: 100%; height: auto; }}
    .separator {{ border-top: 1px solid #EEE; margin: 15px 0; }}
    .side-title {{ text-align: center; font-weight: bold; font-size: 0.9em; color: #999; margin: 10px 0; text-transform: uppercase; letter-spacing: 0.5px; }}
</style>
"""

def get_pure_back_content(card):
    """Extrai apenas o conteúdo do verso."""
    answer_html = card.render_output(True, False).answer_text
    parts = re.split(r'<hr id=[\'"]?answer[\'"]?>', answer_html, maxsplit=1)
    return parts[1] if len(parts) > 1 else answer_html

def media_to_data_url(filename):
    """Converte um arquivo de mídia local para um data URL Base64."""
    if not filename: return None
    decoded_filename = unquote(filename)
    media_dir = mw.col.media.dir()
    if not media_dir: return None
    file_path = os.path.join(media_dir, decoded_filename)
    if not os.path.exists(file_path): return None
    ext = os.path.splitext(decoded_filename)[1].lower()
    mime_type = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.gif': 'image/gif', '.svg': 'image/svg+xml'}.get(ext, 'application/octet-stream')
    try:
        with open(file_path, 'rb') as f:
            data = base64.b64encode(f.read()).decode('utf-8')
        return f"data:{mime_type};base64,{data}"
    except Exception:
        return None

def find_and_embed_media(content: str) -> str:
    """Encontra e embute todas as mídias (imagens e CSS) de forma robusta."""
    if not content: return ""
    media_references = re.findall(r'src\s*=\s*["\']([^"\']+)["\']|url\s*\(\s*["\']?([^"\')]+)["\']?\s*\)', content, re.IGNORECASE)
    filenames_to_process = {src or url for src, url in media_references if (src or url) and not (src or url).startswith(('http', 'data:'))}
    for original in filenames_to_process:
        data_url = media_to_data_url(original)
        if data_url:
            content = content.replace(f'"{original}"', f'"{data_url}"').replace(f"'{original}'", f"'{data_url}'").replace(f'({original})', f'({data_url})').replace(f"('{original}')", f"('{data_url}')")
    return content

def process_card_html_isolate_js(html_content):
    """ESTRATÉGIA 1: Isola o JavaScript para notas padrão (Cloze, etc.)."""
    if not html_content: return ""
    processed_html = re.sub(r"\[\[type:[^]]+\]\]", "", html_content)
    def scope_script_tag(match):
        original_script = match.group(1)
        scoped_script = original_script.replace('document.querySelectorAll', 'cardElement.querySelectorAll').replace('document.querySelector', 'cardElement.querySelector')
        scoped_script = re.sub(r"document\.getElementById\((['\"])([^'\"]+)\1\)", r"cardElement.querySelector('#\2')", scoped_script)
        scoped_script = re.sub(r"window\.(addEventListener|ankiDidShowQuestion|ankiDidShowAnswer)\s*=\s*function\(\)[\s\S]*?};?", "", scoped_script, flags=re.DOTALL)
        return f"""<script>(function(){{const cardElement=document.currentScript.closest('.card-item');if(!cardElement)return;try{{{scoped_script}}}catch(e){{console.error('Error in scoped script for card:',cardElement.id,e);}}}})();</script>"""
    return re.sub(r"<script>([\s\S]*?)</script>", scope_script_tag, processed_html, flags=re.DOTALL)

def process_card_html_remove_js(html_content):
    """ESTRATÉGIA 2: Remove completamente o JavaScript para Oclusão de Imagem."""
    if not html_content: return ""
    return re.sub(r"<script>.*?</script>", "", html_content, flags=re.DOTALL)

# --- FUNÇÃO PRINCIPAL DE EXPORTAÇÃO (COM LÓGICA HÍBRIDA E CORREÇÃO) ---

def generate_export_html(self, translator):
    _t = translator
    if not self.lista_notetypes.currentItem():
        showWarning(_t("Por favor, selecione um Tipo de Nota para exportar."))
        return None
    cards_text_lines = self.txt_entrada.toPlainText().strip().split('\n')
    if not any(line.strip() for line in cards_text_lines):
        showWarning(_t("Não há conteúdo para exportar."))
        return None

    model = mw.col.models.by_name(self.lista_notetypes.currentItem().text())
    deck_id = mw.col.decks.current()['id']
    cards_per_row = 3
    mathjax_script = '<script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>'
    
    buf = []
    buf.append(f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{_t('Cards Exportados')}</title>{get_common_css(cards_per_row)}{mathjax_script}</head><body>")
    buf.append(f'<h1>{_t("Cards Exportados")}</h1><div class="card-grid">')
    
    mw.progress.start(label=_t("Renderizando e processando cards..."), max=len(cards_text_lines))
    
    for i, line in enumerate(cards_text_lines):
        mw.progress.update(value=i)
        if not line.strip(): continue
        note = None
        try:
            note = mw.col.new_note(model)
            parts = self._get_split_parts(line)
            for idx, field_content in enumerate(parts):
                if idx < len(note.fields):
                    note.fields[idx] = field_content.strip()
            mw.col.add_note(note, deck_id)
            card = note.cards()[0]
            
            raw_css = model.get('css', '')
            front_raw = card.render_output(True, False).question_text
            back_raw = get_pure_back_content(card)

            # --- CORREÇÃO DEFINITIVA ---
            # Verifica de forma mais robusta se o modelo é de Oclusão de Imagem (inglês ou português).
            model_name_lower = model['name'].lower()
            is_image_occlusion = 'image occlusion' in model_name_lower or 'oclusão de imagem' in model_name_lower

            if is_image_occlusion:
                # Se for Oclusão de Imagem, usa a ESTRATÉGIA 2: REMOVER o script.
                front_processed = process_card_html_remove_js(front_raw)
                back_processed = process_card_html_remove_js(back_raw)
            else:
                # Para todos os outros tipos, usa a ESTRATÉGIA 1: ISOLAR o script.
                front_processed = process_card_html_isolate_js(front_raw)
                back_processed = process_card_html_isolate_js(back_raw)

            processed_css = find_and_embed_media(raw_css)
            front_final = find_and_embed_media(front_processed)
            back_final = find_and_embed_media(back_processed)

            final_html = (f'<div class="side-title">{_t("Frente")}</div>{front_final}'
                          f'<div class="separator"></div>'
                          f'<div class="side-title">{_t("Verso")}</div>{back_final}')
            
            card_content = (f'<div class="card-item card" id="card-item-{card.id}">'
                            f'<style>{processed_css}</style>'
                            f'<div class="card-content-wrapper">{final_html}</div>'
                            '</div>')
            buf.append(card_content)
        finally:
            if note and note.id:
                mw.col.remove_notes([note.id])

    mw.progress.finish()
    buf.append("</div></body></html>")
    return "".join(buf)