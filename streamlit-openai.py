# streamlit-openai-II-Prototipo_leftmenu_chatbubbles_v6.py
import os, html
import streamlit as st
from datetime import datetime, timezone
from openai import AzureOpenAI
from azure.identity import ClientSecretCredential

# Optional: Document Intelligence
try:
    from azure.ai.formrecognizer import DocumentAnalysisClient
    from azure.core.credentials import AzureKeyCredential
    HAVE_FORMRECOGNIZER = True
except Exception:
    HAVE_FORMRECOGNIZER = False

st.set_page_config(page_title='EasyLook.DOC Chat', page_icon='💬', layout='wide')

TENANT_ID = os.getenv('AZURE_TENANT_ID')
CLIENT_ID = os.getenv('AZURE_CLIENT_ID')
CLIENT_SECRET = os.getenv('AZURE_CLIENT_SECRET')
AZURE_OPENAI_ENDPOINT = os.getenv('AZURE_OPENAI_ENDPOINT')
DEPLOYMENT_NAME = os.getenv('AZURE_OPENAI_DEPLOYMENT')
API_VERSION = os.getenv('AZURE_OPENAI_API_VERSION', '2024-05-01-preview')

AZURE_DOCINT_ENDPOINT = os.getenv('AZURE_DOCINT_ENDPOINT')
AZURE_DOCINT_KEY = os.getenv('AZURE_DOCINT_KEY')
AZURE_BLOB_CONTAINER_SAS_URL = os.getenv('AZURE_BLOB_CONTAINER_SAS_URL')

# Init Azure OpenAI
try:
    credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
    token = credential.get_token('https://cognitiveservices.azure.com/.default')
    client = AzureOpenAI(api_version=API_VERSION, azure_endpoint=AZURE_OPENAI_ENDPOINT, api_key=token.token)
except Exception as e:
    st.error(f'Errore inizializzazione Azure: {e}')
    st.stop()

def build_blob_sas_url(container_sas_url: str, blob_name: str) -> str:
    if not container_sas_url or '?' not in container_sas_url:
        return ''
    base, qs = container_sas_url.split('?', 1)
    base = base.rstrip('/')
    return f'{base}/{blob_name}?{qs}'

def now_local_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')

def human(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts).strftime('%d/%m %H:%M')
    except Exception:
        return ts

ss = st.session_state
ss.setdefault('document_text', '')
ss.setdefault('chat_history', [])

CSS = '''
<style>
:root{
  --yellow: #f5e663;
  --yellow-b: #e8d742;
  --blue:   #1f64c0;
  --blue-b: #1a4f98;
  --ink:    #1f2b3a;
  --muted:  #5b6b7e;
}
html, body, .stApp, [data-testid="stAppViewContainer"]{ background:#f2f2f2 !important; }
.block-container{ max-width:1200px; }
h1{ font-weight:900; letter-spacing:.2px; color:#132132; }
h2{ font-weight:800; color:#122033; margin: 0 0 10px 0; }
.section-caption{ color:var(--muted); font-size:13px; margin-top:-4px; }
.card{ background:#fff; border:1px solid #e6eaf0; border-radius:16px; box-shadow:0 2px 8px rgba(16,24,40,.05); padding:16px; }
.card + .card{ margin-top:16px; }
.btn-primary .stButton>button{ background:var(--yellow) !important; color:#222 !important; border:1px solid var(--yellow-b) !important; border-radius:12px !important; font-weight:700 !important; }
.btn-primary .stButton>button:hover{ filter:brightness(.97); }
.btn-secondary .stButton>button{ background:#fff !important; color:var(--blue) !important; border:2px solid var(--blue) !important; border-radius:12px !important; font-weight:700 !important; }
.btn-secondary .stButton>button:hover{ background:#f7fbff !important; border-color:var(--blue-b) !important; color:var(--blue-b) !important; }
.chat-card{ border:1px solid #e6eaf0; border-radius:16px; background:#fff; box-shadow:0 2px 8px rgba(16,24,40,.05); }
.chat-header{ padding:12px 16px; border-bottom:1px solid #eef2f7; font-weight:800; color:#1f2b3a; }
.chat-body{ padding:14px; height:520px; overflow:auto; background:#fff; border-radius:0 0 16px 16px; }
.msg-row{ display:flex; gap:10px; margin:8px 0; }
.msg{ padding:10px 14px; border-radius:16px; border:1px solid; max-width:78%; line-height:1.45; font-size:15px; }
.msg .meta{ font-size:11px; opacity:.7; margin-top:6px; }
.msg.ai{ background:#fff; border-color:#e8edf3; color:var(--ink); }
.msg.user{ background:var(--yellow); border-color:var(--yellow-b); color:#2b2b2b; margin-left:auto; }
.avatar{ width:28px; height:28px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:14px; }
.avatar.ai{ background:#d9e8ff; color:#123; }
.avatar.user{ background:#fff0a6; color:#5a4a00; }
.small{ font-size:12px; color:var(--muted); margin:6px 0 2px; }
.chat-footer{ padding-top:10px; }
</style>
'''
st.markdown(CSS, unsafe_allow_html=True)

from contextlib import contextmanager
@contextmanager
def btn_class(cls: str):
    st.markdown(f'<div class="{cls}">', unsafe_allow_html=True)
    try:
        yield
    finally:
        st.markdown('</div>', unsafe_allow_html=True)

left, right = st.columns([0.28, 0.72], gap='large')

with left:
    try:
        st.image('images/Nuovo_Logo.png', width=200)
    except Exception:
        st.markdown('### EasyLook.DOC')
    st.markdown('---')
    nav = st.radio('Navigazione', ['Estrazione documento', 'Chat'], index=0)

with right:
    st.title('EasyLook.DOC')

    if nav == 'Estrazione documento':
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.header('Document name')
        st.markdown('<div class="section-caption">Inserisci il nome del file nel container e avvia l\'estrazione.</div>', unsafe_allow_html=True)
        if not HAVE_FORMRECOGNIZER:
            st.warning('Installa azure-ai-formrecognizer>=3.3.0')
        else:
            file_name = st.text_input("Nome file nel container (es. 'contratto1.pdf')", key='file_name_input')
            col1, col2 = st.columns([1, 1])
            with col1, btn_class('btn-primary'):
                extract = st.button('Extract', use_container_width=True)
            with col2, btn_class('btn-secondary'):
                if st.button('Clear document', use_container_width=True):
                    ss['document_text'] = ''
                    ss['chat_history'] = []
                    st.rerun()

            if extract:
                if not (AZURE_DOCINT_ENDPOINT and (AZURE_DOCINT_KEY or (TENANT_ID and CLIENT_ID and CLIENT_SECRET)) and AZURE_BLOB_CONTAINER_SAS_URL and file_name):
                    st.error('Completa le variabili e inserisci il nome file.')
                else:
                    try:
                        blob_url = build_blob_sas_url(AZURE_BLOB_CONTAINER_SAS_URL, file_name)
                        if AZURE_DOCINT_KEY:
                            di_client = DocumentAnalysisClient(endpoint=AZURE_DOCINT_ENDPOINT, credential=AzureKeyCredential(AZURE_DOCINT_KEY))
                        else:
                            di_client = DocumentAnalysisClient(endpoint=AZURE_DOCINT_ENDPOINT, credential=ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET))
                        poller = di_client.begin_analyze_document_from_url(model_id='prebuilt-read', document_url=blob_url)
                        result = poller.result()
                        pages_text = []
                        for page in getattr(result, 'pages', []) or []:
                            if hasattr(page, 'content') and page.content:
                                pages_text.append(page.content)
                        full_text = '\n\n'.join(pages_text).strip()
                        if not full_text:
                            all_lines = []
                            for page in getattr(result, 'pages', []) or []:
                                for line in getattr(page, 'lines', []) or []:
                                    all_lines.append(line.content)
                            full_text = '\n'.join(all_lines).strip()
                        if full_text:
                            st.success('✅ Testo estratto correttamente!')
                            st.text_area('Anteprima testo (~4000 caratteri):', full_text[:4000], height=220)
                            ss['document_text'] = full_text
                            ss['chat_history'] = []
                        else:
                            st.warning('Nessun testo estratto. Verifica file o SAS.')
                    except Exception as e:
                        st.error(f"Errore durante l'analisi del documento: {e}")
        st.markdown('</div>', unsafe_allow_html=True)

    else:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.header('Chat')

        st.markdown('<div class="chat-card">', unsafe_allow_html=True)
        st.markdown('<div class="chat-header">Conversazione</div>', unsafe_allow_html=True)
        chat_container = st.container()
        with chat_container:
            st.markdown('<div class="chat-body" id="chat-body">', unsafe_allow_html=True)
            if not ss['chat_history']:
                st.markdown('<div class="small">Nessun messaggio. Scrivi sotto per iniziare.</div>', unsafe_allow_html=True)
            else:
                for m in ss['chat_history']:
                    role = m['role']
                    content = html.escape(m['content']).replace('\n', '<br>')
                    ts = human(m['ts'])
                    if role == 'user':
                        st.markdown(f'''<div class='msg-row' style='justify-content:flex-end;'>
                              <div class='msg user'>{content}<div class='meta'>{ts}</div></div>
                              <div class='avatar user'>U</div>
                            </div>''', unsafe_allow_html=True)
                    else:
                        st.markdown(f'''<div class='msg-row'>
                              <div class='avatar ai'>A</div>
                              <div class='msg ai'>{content}<div class='meta'>{ts}</div></div>
                            </div>''', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

            import streamlit.components.v1 as components
            components.html('''
                <script>
                const el = window.parent.document.getElementById('chat-body');
                if (el) { el.scrollTop = el.scrollHeight; }
                </script>
            ''', height=0)
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="chat-footer">', unsafe_allow_html=True)
        prompt = st.chat_input('Enter a message...')
        st.markdown('</div>', unsafe_allow_html=True)

        cols = st.columns([1,1,5])
        with cols[0], btn_class('btn-secondary'):
            if st.button('Reset chat', use_container_width=True):
                ss['chat_history'] = []
                st.rerun()

        if prompt:
            ss['chat_history'].append({'role': 'user', 'content': prompt, 'ts': now_local_iso()})
            try:
                doc_text = ss.get('document_text', '')
                system1 = 'Sei un assistente che risponde SOLO sulla base del documento fornito.'
                system2 = f'Contenuto documento:\n{doc_text[:12000]}' if doc_text else 'Nessun documento fornito.'
                response = client.chat.completions.create(
                    model=DEPLOYMENT_NAME,
                    messages=[
                        {'role': 'system', 'content': system1},
                        {'role': 'system', 'content': system2},
                        {'role': 'user',   'content': prompt}
                    ],
                    temperature=0.3,
                    max_tokens=700
                )
                answer = response.choices[0].message.content.strip()
                ss['chat_history'].append({'role': 'assistant', 'content': answer, 'ts': now_local_iso()})
            except Exception as api_err:
                ss['chat_history'].append({'role': 'assistant', 'content': f'Errore API: {api_err}', 'ts': now_local_iso()})
            st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)
