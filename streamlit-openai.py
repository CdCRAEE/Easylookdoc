import os, html
import streamlit as st
from datetime import datetime, timezone
from openai import AzureOpenAI
from azure.identity import ClientSecretCredential
# [ADD] Azure Cognitive Search
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential

# Document Intelligence (opzionale)
try:
    from azure.ai.formrecognizer import DocumentAnalysisClient
    from azure.core.credentials import AzureKeyCredential
    HAVE_FORMRECOGNIZER = True
except Exception:
    HAVE_FORMRECOGNIZER = False

st.set_page_config(page_title='EasyLook.DOC Chat', page_icon='💬', layout='wide')

# --------- CONFIG ---------
TENANT_ID = os.getenv('AZURE_TENANT_ID')
CLIENT_ID = os.getenv('AZURE_CLIENT_ID')
CLIENT_SECRET = os.getenv('AZURE_CLIENT_SECRET')
AZURE_OPENAI_ENDPOINT = os.getenv('AZURE_OPENAI_ENDPOINT')
DEPLOYMENT_NAME = os.getenv('AZURE_OPENAI_DEPLOYMENT')
API_VERSION = os.getenv('AZURE_OPENAI_API_VERSION', '2024-05-01-preview')

AZURE_DOCINT_ENDPOINT = os.getenv('AZURE_DOCINT_ENDPOINT')
AZURE_DOCINT_KEY = os.getenv('AZURE_DOCINT_KEY')
AZURE_BLOB_CONTAINER_SAS_URL = os.getenv('AZURE_BLOB_CONTAINER_SAS_URL')

# [ADD] --- CONFIGURAZIONE SEARCH ---
AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")   # es: https://easylookdoc-search.search.windows.net
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")


# --------- TOKEN + CLIENT ---------
try:
    credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
    token = credential.get_token('https://cognitiveservices.azure.com/.default')
    client = AzureOpenAI(api_version=API_VERSION, azure_endpoint=AZURE_OPENAI_ENDPOINT, api_key=token.token)
except Exception as e:
    st.error(f'Errore inizializzazione Azure: {e}')
    st.stop()

# >>> QUI <<< subito dopo il try/except
search_client = None
if AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY and AZURE_SEARCH_INDEX:
    search_client = SearchClient(
        endpoint=AZURE_SEARCH_ENDPOINT,
        index_name=AZURE_SEARCH_INDEX,
        credential=AzureKeyCredential(AZURE_SEARCH_KEY)
    )
else:
    st.error("⚠️ Configurazione Azure Search mancante.")

# --------- HELPERS ---------
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

# --------- STATE ---------
ss = st.session_state
ss.setdefault('document_text', '')
ss.setdefault('chat_history', [])  # [{'role','content','ts'}]

# --------- STYLE ---------
CSS = """
<style>
:root{
  --yellow:#FDF6B4; --yellow-border:#FDF6B4;
  --ai-bg:#F1F6FA; --ai-border:#F1F6FA; --text:#1f2b3a;
}

/* === Sfondo: sinistra bianca (menu) + barra, destra grigia === */
.stApp{ background:#f5f7fa !important; }

.block-container{
  max-width:1200px;           /* tienilo allineato al layout */
  min-height:100vh;
  position:relative;          /* contesto per lo sfondo */
}

/* sfondo bianco per la colonna sinistra con barra verticale */
.block-container::before{
  content:"";
  position:absolute;
  top:0; bottom:0; left:0;
  width:28%;                  /* = st.columns([0.28, 0.72]) */
  background:#ffffff;
  box-shadow:inset -1px 0 0 #e5e7eb; /* barra verticale */
  pointer-events:none;
  z-index:0;
}

/* i contenuti stanno sopra lo sfondo */
.block-container > *{ position:relative; z-index:1; }

/* ===== Chat ===== */
.chat-card{border:1px solid #e6eaf0;border-radius:14px;background:#fff;box-shadow:0 2px 8px rgba(16,24,40,.04);}
.chat-header{padding:12px 16px;border-bottom:1px solid #eef2f7;font-weight:800;color:#1f2b3a;}
.chat-body{padding:14px;max-height:70vh;overflow-y:auto;}
.msg-row{display:flex;gap:10px;margin:8px 0;}
.msg{padding:10px 14px;border-radius:16px;border:1px solid;max-width:78%;line-height:1.45;font-size:15px;}
.msg .meta{font-size:11px;opacity:.7;margin-top:6px;}
.msg.ai{background:var(--ai-bg);border-color:var(--ai-border);color:var(--text);}
.msg.user{background:var(--yellow);border-color:var(--yellow-border);color:#2b2b2b;margin-left:auto;}
.avatar{width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:14px;}
.avatar.ai{background:#d9e8ff;color:#123;}
.avatar.user{background:#fff0a6;color:#5a4a00;}
.small{font-size:12px;color:#5b6b7e;margin:6px 0 2px;}
.chat-footer{padding:10px 0 0;}

/* ===== Pulsanti (outline blu, hover blu pieno) ===== */
.stButton>button{
  background:#fff!important;color:#007BFF!important;border:1px solid #007BFF!important;
  border-radius:8px!important;font-weight:600!important;padding:.5rem 1rem!important;box-shadow:none!important;
}
.stButton>button:hover{background:#007BFF!important;color:#fff!important;border-color:#007BFF!important;}
.stButton>button:focus{outline:none!important;box-shadow:0 0 0 3px rgba(0,123,255,.25)!important;}

/* ===== Menù sinistro (icone, niente pallino, hover/selected) ===== */
label[data-baseweb="radio"]>div:first-child{display:none!important;}
div[role="radiogroup"] label[data-baseweb="radio"]{
  display:flex!important;align-items:center;gap:8px;padding:8px 10px;border-radius:10px;cursor:pointer;user-select:none;
  margin-bottom:12px!important;
}
div[role="radiogroup"] label[data-baseweb="radio"]:hover{background:#eef5ff;}
label[data-baseweb="radio"]:has(input:checked){background:#e6f0ff;font-weight:600;}
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)


# --------- LAYOUT ---------
left, right = st.columns([0.28, 0.72], gap='large')

with left:
    st.markdown('<div class="left-pane">', unsafe_allow_html=True)
    try:
        st.image('images/Nuovo_Logo.png', width=200)
    except Exception:
        st.markdown('')
    st.markdown('---')

    # Menù sinistro con icone
    labels = {
        "📤 Estrazione": "Leggi documento",
        "💬 Chat": "Chat",
        "🕒 Cronologia": "Cronologia",
    }
    choice = st.radio('', list(labels.keys()), index=0)
    nav = labels[choice]

# --- QUI: spingiamo i loghi in fondo ---
    st.markdown(
        """
        <div style="flex-grow:1"></div> <!-- spaziatore -->
        """,
        unsafe_allow_html=True
    )

    # blocco loghi in basso
    colA, colB = st.columns(2)
    with colA:
        st.image('images/logoRAEE.png', width=80)
    with colB:
        st.image('images/logoNPA.png', width=80)

    st.markdown('</div>', unsafe_allow_html=True)


with right:
    st.markdown('<div class="right-pane">', unsafe_allow_html=True)
    st.title('BENVENUTO !')

    if nav == 'Leggi documento':
        st.subheader('📄 Scegli il documento')
        if not HAVE_FORMRECOGNIZER:
            st.warning('Installa azure-ai-formrecognizer>=3.3.0')
        else:
            file_name = st.text_input("Nome file (es. Elenco - R1.pdf)", key='file_name_input')
            col1, col2 = st.columns([1, 1])
            with col1:
                extract = st.button('🔎 Leggi documento', use_container_width=True)
            with col2:
                if st.button('🗂️ Cambia documento', use_container_width=True):
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
                            st.text_area('Anteprima testo (~4000 caratteri):', full_text[:4000], height=300)
                            ss['document_text'] = full_text
                            ss['chat_history'] = []  # reset chat per il nuovo doc
                        else:
                            st.warning('Nessun testo estratto. Verifica file o SAS.')
                    except Exception as e:
                        st.error(f"Errore durante l'analisi del documento: {e}")

    else:
        st.subheader('💬 Chiedi quello che vuoi')
	st.info("Puoi fare una domanda: cercherò nei documenti dell'indice configurato")
        else:
            # --- Scheda chat: prima i messaggi (in alto) ---
            st.markdown('<div class="chat-card">', unsafe_allow_html=True)
            st.markdown('<div class="chat-header">Conversazione</div>', unsafe_allow_html=True)

            chat_container = st.container()
            with chat_container:
                st.markdown('<div class="chat-body" id="chat-body">', unsafe_allow_html=True)
                if not ss['chat_history']:
                    st.markdown('<div class="small">Nessun messaggio. Fai una domanda sul documento.</div>', unsafe_allow_html=True)
                else:
                    for m in ss['chat_history']:
                        role = m['role']
                        content = html.escape(m['content']).replace('\n', '<br>')
                        ts = human(m['ts'])
                        if role == 'user':
                            st.markdown(f"""
                                <div class='msg-row' style='justify-content:flex-end;'>
                                  <div class='msg user'>
                                    {content}
                                    <div class='meta'>{ts}</div>
                                  </div>
                                  <div class='avatar user'>U</div>
                                </div>""", unsafe_allow_html=True)
                        else:
                            st.markdown(f"""
                                <div class='msg-row'>
                                  <div class='avatar ai'>A</div>
                                  <div class='msg ai'>
                                    {content}
                                    <div class='meta'>{ts}</div>
                                  </div>
                                </div>""", unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

                import streamlit.components.v1 as components
                components.html('''
                    <script>
                    const el = window.parent.document.getElementById('chat-body');
                    if (el) { el.scrollTop = el.scrollHeight; }
                    </script>
                ''', height=0)

            # --- Input in basso (fuori dal riquadro scrollabile) ---
            st.markdown('<div class="chat-footer">', unsafe_allow_html=True)
            prompt = st.chat_input('Scrivi la tua domanda sul documento:')
            st.markdown('</div>', unsafe_allow_html=True)

if prompt:
    ss['chat_history'].append({'role': 'user', 'content': prompt, 'ts': now_local_iso()})
    try:
        if not search_client:
            raise RuntimeError("Azure Search non è configurato.")

        # Step 1: recupero documenti dal tuo indice (top-k)
        results = search_client.search(prompt, top=3)

        docs_text = []
        references = []
        for r in results:
            # Campi tipici dello schema di chunking: "chunk" e "file_name"
            if "chunk" in r:
                docs_text.append(r["chunk"])
            if "file_name" in r:
                references.append(r["file_name"])

        context = "\n\n".join(docs_text)

        if not context:
            ss['chat_history'].append({
                'role': 'assistant',
                'content': "⚠️ Nessun documento rilevante trovato nell'indice.",
                'ts': now_local_iso()
            })
        else:
            # Step 2: chiamata a GPT con il contesto recuperato da Search
            response = client.chat.completions.create(
                model=DEPLOYMENT_NAME,
                messages=[
                    {"role": "system", "content": "Sei un assistente che risponde solo basandosi sui documenti forniti."},
                    {"role": "system", "content": f"Contesto:\n{context}"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,        # coerente con Q/A su base documentale
                max_tokens=500
            )

            answer = response.choices[0].message.content.strip()
            if references:
                answer += "\n\n— 📎 Fonti: " + ", ".join(sorted(set(references)))

            ss['chat_history'].append({'role': 'assistant', 'content': answer, 'ts': now_local_iso()})

    except Exception as api_err:
        ss['chat_history'].append({'role': 'assistant', 'content': f'Errore durante la ricerca o risposta: {api_err}', 'ts': now_local_iso()})
    st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)