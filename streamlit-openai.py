import os, html
import streamlit as st
from datetime import datetime, timezone
from openai import AzureOpenAI
from azure.identity import ClientSecretCredential

# Azure Cognitive Search
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential

st.set_page_config(page_title='EasyLook.DOC Chat', page_icon='💬', layout='wide')

# --------- CONFIG ---------
TENANT_ID = os.getenv('AZURE_TENANT_ID')
CLIENT_ID = os.getenv('AZURE_CLIENT_ID')
CLIENT_SECRET = os.getenv('AZURE_CLIENT_SECRET')
AZURE_OPENAI_ENDPOINT = os.getenv('AZURE_OPENAI_ENDPOINT')
DEPLOYMENT_NAME = os.getenv('AZURE_OPENAI_DEPLOYMENT')
API_VERSION = os.getenv('AZURE_OPENAI_API_VERSION', '2024-05-01-preview')

# --- CONFIGURAZIONE SEARCH ---
AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")

# --------- CLIENTS ---------
try:
    credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)

    # --- AAD token reuse with 5-minute safety buffer ---
    now_ts = datetime.now(timezone.utc).timestamp()
    needs_token = True
    if 'aad_token' in st.session_state and 'aad_exp' in st.session_state:
        if now_ts < st.session_state['aad_exp'] - 300:
            needs_token = False

    if needs_token:
        access = credential.get_token('https://cognitiveservices.azure.com/.default')
        st.session_state['aad_token'] = access.token
        st.session_state['aad_exp'] = access.expires_on

    client = AzureOpenAI(
        api_version=API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_ad_token=st.session_state['aad_token']
    )

# --- Azure Cognitive Search client con reuse ---
search_key = (AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_KEY, AZURE_SEARCH_INDEX)
if 'search_client' not in st.session_state or st.session_state.get('search_key') != search_key:
    if AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY and AZURE_SEARCH_INDEX:
        st.session_state['search_client'] = SearchClient(
            endpoint=AZURE_SEARCH_ENDPOINT,
            index_name=AZURE_SEARCH_INDEX,
            credential=AzureKeyCredential(AZURE_SEARCH_KEY)
        )
        st.session_state['search_key'] = search_key

search_client = st.session_state.get('search_client')

except Exception as e:
    st.error(f'Errore inizializzazione Azure OpenAI: {e}')
    st.stop()
search_client = None
try:
    if AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY and AZURE_SEARCH_INDEX:
        search_client = SearchClient(
            endpoint=AZURE_SEARCH_ENDPOINT,
            index_name=AZURE_SEARCH_INDEX,
            credential=AzureKeyCredential(AZURE_SEARCH_KEY)
        )
    else:
        st.warning("⚠️ Configurazione Azure Search mancante (endpoint/chiave/indice).")
except Exception as e:
    st.error(f'Errore inizializzazione Azure Search: {e}')

# --------- STATE ---------
ss = st.session_state
ss.setdefault('chat_history', [])  # [{'role','content','ts'}]
ss.setdefault('active_doc', None)  # NEW: file selezionato da "Origine"

# --------- STYLE ---------
CSS = """
<style>
:root{
  --yellow:#FDF6B4; --yellow-border:#FDF6B4;
  --ai-bg:#F1F6FA; --ai-border:#F1F6FA; --text:#1f2b3a;
}

.stApp{ background:#f5f7fa !important; }

.block-container{
  max-width:1200px;
  min-height:100vh;
  position:relative;
}

/* colonna sinistra bianca con barra */
.block-container::before{
  content:"";
  position:absolute;
  top:0; bottom:0; left:0;
  width:28%;
  background:#ffffff;
  box-shadow:inset -1px 0 0 #e5e7eb;
  pointer-events:none;
  z-index:0;
}

.block-container > *{ position:relative; z-index:1; }

/* Card chat */
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
.chat-footer{padding:10px 12px 12px;}
.stButton>button{
  background:#fff!important;color:#007BFF!important;border:1px solid #007BFF!important;
  border-radius:8px!important;font-weight:600!important;padding:.5rem 1rem!important;box-shadow:none!important;
}
.stButton>button:hover{background:#007BFF!important;color:#fff!important;border-color:#007BFF!important;}
.stButton>button:focus{outline:none!important;box-shadow:0 0 0 3px rgba(0,123,255,.25)!important;}

/* Menù sinistro */
label[data-baseweb="radio"]>div:first-child{display:none!important;}
div[role="radiogroup"] label[data-baseweb="radio"]{
  display:flex!important;align-items:center;gap:8px;padding:8px 10px;border-radius:10px;cursor:pointer;user-select:none;
  margin-bottom:12px!important;
}
div[role="radiogroup"] label[data-baseweb="radio"]:hover{background:#eef5ff;}
label[data-baseweb="radio"]:has(input:checked){background:#e6f0ff;font-weight:600;}

/* Make the left pane a positioned container */
.left-pane{
  position: relative;
  min-height: 100vh;
}

/* Footer anchored to bottom of the left pane only */
.left-footer{
  position: absolute;
  left: 0; right: 0; bottom: 12px;
  display: flex;
  justify-content: space-around;
  align-items: center;
  padding: 8px 0;
  background: transparent;
}

</style>"""
st.markdown(CSS, unsafe_allow_html=True)

# --------- LAYOUT ---------
left, right = st.columns([0.28, 0.72], gap='large')

# ===== LEFT PANE =====
with left:
    st.markdown('<div class="left-pane">', unsafe_allow_html=True)
    try:
        st.image('images/Nuovo_Logo.png', width=200)
    except Exception:
        st.markdown('')
    st.markdown('---')

    labels = {
        "📤 Origine": "Leggi documento",
        "💬 Chat": "Chat",
        "🕒 Cronologia": "Cronologia",
    }
    choice = st.radio('', list(labels.keys()), index=1)  # default: Chat
    nav = labels[choice]

    
# Footer anchored to bottom of the left sidebar
st.markdown("""
<div class="left-footer">
  <img src='images/logoRAEE.png' width='80'>
  <img src='images/logoNPA.png' width='80'>
</div>
""", unsafe_allow_html=True)

# chiudi il contenitore della left-pane
st.markdown('</div>', unsafe_allow_html=True)
# ===== RIGHT PANE =====
with right:
    st.markdown('<div class="right-pane">', unsafe_allow_html=True)
    st.title('BENVENUTO !')

    if nav == 'Leggi documento':
        st.subheader('📄 Scegli il documento')

        # NEW: elenco documenti dall’indice tramite facets su file_name
        if not search_client:
            st.error("Azure Search non è configurato.")
        else:
            try:
                results = search_client.search(
                    search_text="*",
                    top=0,
                    facets=["file_path,count:1000"]  # richiede file_path facetable
                )
                facets = results.get_facets() or {}
                files = [f["value"] for f in facets.get("file_path", [])]

                if not files:
                    st.info("Nessun documento trovato nell'indice.")
                else:
                    files = sorted(files, key=lambda x: x.lower())
                    default_index = 0
                    if ss.get('active_doc') in files:
                        default_index = files.index(ss['active_doc'])
                    sel = st.selectbox("Documenti indicizzati", files, index=default_index)
                    st.caption("Seleziona un documento per filtrare la Chat (opzionale).")

                    # salva selezione in stato
                    ss['active_doc'] = sel

                    # UI alternativa: elenco semplice
                    # for name in files: st.markdown(f"- {name}")

                    # Pulsante per azzerare il filtro (ricerca globale)
                    if st.button("🔄 Usa tutti i documenti (rimuovi filtro)"):
                        ss['active_doc'] = None
                        st.rerun()
            except Exception as e:
                st.error(f"Errore nel recupero dell'elenco documenti: {e}")

    elif nav == 'Chat':
        st.subheader('💬 Chiedi quello che vuoi')
        st.info("Cercherò nei documenti indicizzati (Azure Search).")

        # NEW: mostra lo stato del filtro attivo (se selezionato in Origine)
        if ss.get('active_doc'):
            st.success(f"Filtro attivo: **{ss['active_doc']}** (la ricerca riguarda solo questo documento)")
        else:
            st.caption("Nessun filtro selezionato: la ricerca riguarda tutta la cartella indicizzata.")

        # Card chat
        st.markdown('<div class="chat-card">', unsafe_allow_html=True)
        st.markdown('<div class="chat-header">Conversazione</div>', unsafe_allow_html=True)

        # Corpo messaggi (sopra)
        chat_container = st.container()
        with chat_container:
            st.markdown('<div class="chat-body" id="chat-body">', unsafe_allow_html=True)
            if not ss['chat_history']:
                st.markdown('<div class="small">Nessun messaggio. Fai una domanda.</div>', unsafe_allow_html=True)
            else:
                for m in ss['chat_history']:
                    role = m['role']
                    # NB: lasciamo l'escape; se vuoi usare markup nel placeholder, togli html.escape
                    content = html.escape(m['content']).replace('\n', '<br>')
                    ts = datetime.fromisoformat(m['ts']).strftime('%d/%m %H:%M')
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

            # autoscroll
            import streamlit.components.v1 as components
            components.html('''
                <script>
                const el = window.parent.document.getElementById('chat-body');
                if (el) { el.scrollTop = el.scrollHeight; }
                </script>
            ''', height=0)

        # Footer input (sotto) dentro la card
        st.markdown('<div class="chat-footer">', unsafe_allow_html=True)
        with st.form(key="chat_form", clear_on_submit=True):
            user_q = st.text_input("Scrivi la tua domanda", value="")
            sent = st.form_submit_button("Invia")
        st.markdown('</div>', unsafe_allow_html=True)   # chiude chat-footer
        st.markdown('</div>', unsafe_allow_html=True)    # chiude chat-card

# --- LOGICA DOMANDA/RISPOSTA CON PLACEHOLDER "STA SCRIVENDO" ---

# 1) Se sto “processando” una domanda pendente, eseguo ORA il lavoro e rimpiazzo il placeholder
if st.session_state.get('do_process'):
    try:
        user_q_pending = st.session_state.get('pending_q', '')
        if not search_client:
            raise RuntimeError("Azure Search non è configurato.")

        # NEW: filtra per documento se selezionato in Origine
        filter_expr = None
        if st.session_state.get('active_doc'):
            safe_name = st.session_state['active_doc'].replace("'", "''")
            filter_expr = f"file_path eq '{safe_name}'"

        if filter_expr:
            results = search_client.search(user_q_pending, top=3, filter=filter_expr)
        else:
            results = search_client.search(user_q_pending, top=3)

        docs_text, references = [], []
        for r in results:
            if "chunk" in r:
                docs_text.append(r["chunk"])
            if "file_path" in r:
                references.append(r["file_path"])

        context = "\n\n".join(docs_text)

        if not context:
            answer = "⚠️ Nessun documento rilevante trovato nell'indice."
        else:
            resp = client.chat.completions.create(
                model=DEPLOYMENT_NAME,
                messages=[
                    {"role": "system", "content": "Sei un assistente che risponde solo basandosi sui documenti forniti."},
                    {"role": "system", "content": f"Contesto:\n{context}"},
                    {"role": "user", "content": user_q_pending},
                ],
                temperature=0,
                max_tokens=500
            )
            answer = resp.choices[0].message.content.strip()
            if references:
                answer += "\n\n— 📎 Fonti: " + ", ".join(sorted(set(references)))
    except Exception as e:
        answer = f"Errore durante la ricerca o risposta: {e}"

    # Sostituisco l'ULTIMO messaggio (il placeholder) con la risposta reale
    if ss['chat_history'] and ss['chat_history'][-1]['role'] == 'assistant':
        ss['chat_history'][-1] = {
            'role': 'assistant',
            'content': answer,
            'ts': datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
        }

    # Pulizia stato
    st.session_state['do_process'] = False
    st.session_state.pop('pending_q', None)
    # Non serve rerun: la risposta è già in chat

# 2) Gestione invio dal form: aggiungo utente + placeholder e chiedo un rerun
if 'sent' in locals() and sent and user_q.strip():
    # messaggio utente
    ss['chat_history'].append({
        'role': 'user',
        'content': user_q,
        'ts': datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
    })
    # placeholder "sta scrivendo…" come messaggio AI
    ss['chat_history'].append({
        'role': 'assistant',
        'content': '💬 Sta scrivendo...',
        'ts': datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
    })

    # salvo la domanda e imposto il flag per processare al prossimo run
    st.session_state['pending_q'] = user_q
    st.session_state['do_process'] = True

    st.rerun()

    # (il resto del layout chiude il right-pane)
    st.markdown('</div>', unsafe_allow_html=True)
