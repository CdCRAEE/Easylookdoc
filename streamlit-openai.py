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
    token = credential.get_token('https://cognitiveservices.azure.com/.default')
    client = AzureOpenAI(
        api_version=API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=token.token
    )
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

# --------- STYLE ---------
CSS = """
<style>
:root{
  --yellow:#FDF6B4; --yellow-border:#FDF6B4;
  --ai-bg:#F1F6FA; --ai-border:#F1F6FA; --text:#1f2b3a;
}

/* sfondo app generale */
.stApp{ background:#f5f7fa !important; }

.block-container{
  max-width:1200px;
  min-height:100vh;
  position:relative;
}

/* colonna sinistra bianca con “barra” e bordino destro */
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

/* riportiamo il contenuto sopra la “barra” */
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

/* Pulsanti generici (se li usi altrove) */
.stButton>button{
  background:#fff!important;color:#007BFF!important;border:1px solid #007BFF!important;
  border-radius:8px!important;font-weight:600!important;padding:.5rem 1rem!important;box-shadow:none!important;
}
.stButton>button:hover{background:#007BFF!important;color:#fff!important;border-color:#007BFF!important;}
.stButton>button:focus{outline:none!important;box-shadow:0 0 0 3px rgba(0,123,255,.25)!important;}

/* Menù sinistro (radio) */
label[data-baseweb="radio"]>div:first-child{display:none!important;} /* nasconde il pallino */
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

    # spaziatore -> loghi in basso
    st.markdown("<div style='flex-grow:1'></div>", unsafe_allow_html=True)
    colA, colB = st.columns(2)
    with colA:
        try:
            st.image('images/logoRAEE.png', width=80)
        except Exception:
            st.markdown('')
    with colB:
        try:
            st.image('images/logoNPA.png', width=80)
        except Exception:
            st.markdown('')

    st.markdown('</div>', unsafe_allow_html=True)

# ===== RIGHT PANE =====
with right:
    st.markdown('<div class="right-pane">', unsafe_allow_html=True)
    st.title('BENVENUTO !')

    if nav == 'Leggi documento':
        st.subheader('📄 Scegli il documento')
        st.info("Questa sezione verrà sistemata dopo. Nel frattempo usa la Chat.")

    elif nav == 'Chat':
        st.subheader('💬 Chiedi quello che vuoi')
        st.info("Cercherò nei documenti indicizzati (Azure Search).")

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
                    content = html.escape(m['content']).replace('\n', '<br>')
                    try:
                        ts = datetime.fromisoformat(m['ts']).strftime('%d/%m %H:%M')
                    except Exception:
                        ts = m.get('ts', '')
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

        # Logica domanda/risposta
        if sent and user_q.strip():
            ss['chat_history'].append({
                'role': 'user',
                'content': user_q,
                'ts': datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
            })
            try:
                if not search_client:
                    raise RuntimeError("Azure Search non è configurato.")

                results = search_client.search(user_q, top=3)

                docs_text, references = [], []
                for r in results:
                    if "chunk" in r:
                        docs_text.append(r["chunk"])
                    if "file_name" in r:
                        references.append(r["file_name"])

                context = "\n\n".join(docs_text)

                if not context:
                    answer = "⚠️ Nessun documento rilevante trovato nell'indice."
                else:
                    resp = client.chat.completions.create(
                        model=DEPLOYMENT_NAME,
                        messages=[
                            {"role": "system", "content": "Sei un assistente che risponde solo basandosi sui documenti forniti."},
                            {"role": "system", "content": f"Contesto:\n{context}"},
                            {"role": "user", "content": user_q},
                        ],
                        temperature=0,
                        max_tokens=500
                    )
                    answer = resp.choices[0].message.content.strip()
                    if references:
                        answer += "\n\n— 📎 Fonti: " + ", ".join(sorted(set(references)))
            except Exception as e:
                answer = f"Errore durante la ricerca o risposta: {e}"

            ss['chat_history'].append({
                'role': 'assistant',
                'content': answer,
                'ts': datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
            })
            st.experimental_rerun()

    st.markdown('</div>', unsafe_allow_html=True)
