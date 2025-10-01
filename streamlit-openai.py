import os, html
import streamlit as st
from datetime import datetime, timezone
from openai import AzureOpenAI
from azure.identity import ClientSecretCredential
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

# --------- CLIENTS (robusti: non bloccano il deploy se mancanti) ---------
client = None
try:
    if TENANT_ID and CLIENT_ID and CLIENT_SECRET and AZURE_OPENAI_ENDPOINT:
        credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
        token = credential.get_token('https://cognitiveservices.azure.com/.default')
        client = AzureOpenAI(
            api_version=API_VERSION,
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            azure_ad_token=token.token,  # uso AAD token
        )
    else:
        st.warning("⚠️ Configurazione Azure OpenAI mancante: userò una risposta di fallback.")
except Exception as e:
    st.warning(f'⚠️ Azure OpenAI non inizializzato: {e}')

search_client = None
try:
    if AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY and AZURE_SEARCH_INDEX:
        search_client = SearchClient(
            endpoint=AZURE_SEARCH_ENDPOINT,
            index_name=AZURE_SEARCH_INDEX,
            credential=AzureKeyCredential(AZURE_SEARCH_KEY)
        )
    else:
        st.info("ℹ️ Azure Search non configurato: la chat risponderà senza contesto.")
except Exception as e:
    st.info(f'ℹ️ Azure Search non disponibile: {e}')

# --------- STATE ---------
ss = st.session_state
ss.setdefault('chat_history', [])  # [{'role','content','ts'}]

# --------- STYLE (SOLO GRAFICA) ---------
st.markdown("""
<style>
:root{
  --yellow:#FDF6B4; --yellow-border:#FDF6B4;
  --ai-bg:#F1F6FA; --ai-border:#F1F6FA; --text:#1f2b3a;
  --menu-blue:#2F98C7;
}

/* ===== SFONDO PAGINA A DUE COLONNE (robusto) ===== */
html, body, .stApp { height: 100%; background: transparent !important; }
body {
  background: linear-gradient(to right,
    #F6FDFC 0%, #F6FDFC 28%,
    #f1f5f9 28%, #f1f5f9 100%) !important;
}
.block-container { background: transparent !important; max-width:1200px; min-height:100vh; }
[data-testid="stHorizontalBlock"] [data-testid="column"] > div:first-child { padding: 12px; }

/* ===== MENÙ SINISTRO (RADIO): 1) niente bordi 2) testo a sx 3) attivo blu ===== */
label[data-baseweb="radio"] > div:first-child { display:none !important; }  /* pallino */
div[role="radiogroup"] label[data-baseweb="radio"]{
  display:flex !important; align-items:center; gap:8px;
  padding:10px 12px; border-radius:10px; cursor:pointer; user-select:none;
  margin-bottom:12px !important; background:#ffffff; color:var(--menu-blue);
  border:none !important; box-shadow:none !important; text-align:left;
}
div[role="radiogroup"] label[data-baseweb="radio"]:hover{ background:#e6f3fb; }
label[data-baseweb="radio"]:has(input:checked){
  background:var(--menu-blue) !important; color:#ffffff !important; font-weight:600;
}
label[data-baseweb="radio"]:has(input:checked) *{ color:#ffffff !important; }

/* ===== Chat card (invariata) ===== */
mark { background:#fff3bf; padding:0 .15em; border-radius:3px; }
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
</style>
""", unsafe_allow_html=True)

# --------- LAYOUT ---------
left, right = st.columns([0.28, 0.72], gap='large')

# ===== LEFT PANE =====
with left:
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

    # loghi in basso
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

# ===== RIGHT PANE =====
with right:
    st.title('BENVENUTO !')

    if nav == 'Leggi documento':
        st.subheader('📄 Scegli il documento')
        # TODO: qui la tua logica documenti
        st.info("Questa sezione verrà completata successivamente.")
        pass

    elif nav == 'Chat':
        st.subheader('💬 Chiedi quello che vuoi')
        if search_client:
            st.info("Cercherò nei documenti indicizzati (Azure Search).")
        else:
            st.info("Azure Search non configurato: risponderò senza contesto.")

        # --- CARD CHAT ---
        st.markdown('<div class="chat-card">', unsafe_allow_html=True)
        st.markdown('<div class="chat-header">Conversazione</div>', unsafe_allow_html=True)

        # Corpo messaggi
        st.markdown('<div class="chat-body" id="chat-body">', unsafe_allow_html=True)
        if not ss['chat_history']:
            st.markdown('<div class="small">Nessun messaggio. Fai una domanda.</div>', unsafe_allow_html=True)
        else:
            for m in ss['chat_history']:
                role = m['role']
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
        st.markdown('</div>', unsafe_allow_html=True)  # chiude chat-body

        # autoscroll
        import streamlit.components.v1 as components
        components.html('''
            <script>
            const el = window.parent.document.getElementById('chat-body');
            if (el) { el.scrollTop = el.scrollHeight; }
            </script>
        ''', height=0)

        # Footer input
        st.markdown('<div class="chat-footer">', unsafe_allow_html=True)
        with st.form(key="chat_form", clear_on_submit=True):
            user_q = st.text_input("Scrivi la tua domanda", value="")
            sent = st.form_submit_button("Invia")
        st.markdown('</div>', unsafe_allow_html=True)   # chiude chat-footer
        st.markdown('</div>', unsafe_allow_html=True)   # chiude chat-card

        # Logica domanda/risposta (robusta: tenta contesto + modello, altrimenti fallback)
        if sent and user_q.strip():
            ss['chat_history'].append({
                'role': 'user',
                'content': user_q,
                'ts': datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
            })

            answer = None
            try:
                context_parts, refs = [], []
                if search_client:
                    results = search_client.search(user_q, top=3)
                    for r in results:
                        if "chunk" in r:
                            context_parts.append(str(r["chunk"]))
                        if "file_name" in r:
                            refs.append(str(r["file_name"]))
                context = "\n\n".join(context_parts)

                if client and context:
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
                    answer = (resp.choices[0].message.content or "").strip()
                    if refs:
                        answer += "\n\n— 📎 Fonti: " + ", ".join(sorted(set(refs)))
                elif client and not context:
                    # modello disponibile ma senza contesto
                    resp = client.chat.completions.create(
                        model=DEPLOYMENT_NAME,
                        messages=[
                            {"role": "system", "content": "Rispondi in modo chiaro."},
                            {"role": "user", "content": user_q},
                        ],
                        temperature=0.2,
                        max_tokens=300
                    )
                    answer = (resp.choices[0].message.content or "").strip()
                else:
                    # fallback se non c'è Azure OpenAI
                    answer = "Risposta di fallback (Azure OpenAI non configurato)."
            except Exception as e:
                answer = f"Errore durante la ricerca o la generazione della risposta: {e}"

            ss['chat_history'].append({
                'role': 'assistant',
                'content': answer or "(nessuna risposta)",
                'ts': datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
            })
            st.experimental_rerun()

    elif nav == 'Cronologia':
        st.subheader("🕒 Cronologia")
        if not ss['chat_history']:
            st.write("Nessun messaggio ancora.")
        else:
            for m in ss['chat_history']:
                who = "👤 Tu" if m["role"] == "user" else "🤖 Assistente"
                try:
                    ts = datetime.fromisoformat(m['ts']).strftime('%d/%m %H:%M')
                except Exception:
                    ts = m.get('ts', '')
                st.markdown(f"**{who}** · _{ts}_")
                st.markdown(m["content"])
                st.markdown("---")
