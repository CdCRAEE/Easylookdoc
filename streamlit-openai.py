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
API_VERSION = os.getenv('AZURE_OPENAI_API_VERSION', '2024-05-01-preview')
AZURE_OPENAI_DEPLOYMENT = os.getenv('AZURE_OPENAI_DEPLOYMENT', 'gpt-4o-mini')

AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX = "azureblob-index"          # <== tuo indice
FILENAME_FIELD = "metadata_storage_path"        # <== campo documento (path completo)

# --------- HELPERS ---------
def spacer(n=1):
    """Inserisce n righe vuote (come st.write('')) per creare spazio verticale."""
    for _ in range(n):
        st.write("")

def safe_filter_eq(field: str, value: str) -> str:
    """Crea una OData filter string con escape degli apici singoli."""
    if value is None:
        return None
    safe_value = value.replace("'", "''")  # escape OData per apice singolo
    return f"{field} eq '{safe_value}'"

def build_chat_messages(user_q: str, context_snippets: list[str]):
    sys_msg = {
        "role": "system",
        "content": (
            "Sei un assistente che risponde SOLO in base ai documenti forniti nel contesto. "
            "Se l'informazione non è presente, dichiara esplicitamente che non la trovi."
        )
    }
    ctx = "\n\n".join([f"- {s}" for s in context_snippets]) if context_snippets else "(nessun contesto)"
    user_msg = {"role": "user", "content": f"CONTEXTPASS:\n{ctx}\n\nDOMANDA:\n{user_q}"}
    return [sys_msg, user_msg]

# --------- CLIENTS ---------
try:
    credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)

    # --- AAD token reuse con buffer 5 minuti ---
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
    st.error(f'Errore inizializzazione Azure OpenAI/Search: {e}')
    st.stop()

# --------- STATE ---------
ss = st.session_state
ss.setdefault('chat_history', [])
ss.setdefault('active_doc', None)

# --------- STYLE ---------
st.markdown("""
<style>
.stApp{ background:#f5f7fa !important; }
.left-pane{ background:#fff; padding:12px; border-radius:12px; border:1px solid #e5e7eb; }
.right-pane{ padding:10px; }
.chat-card{border:1px solid #e6eaf0;border-radius:14px;background:#fff;box-shadow:0 2px 8px rgba(16,24,40,.04);}
.chat-header{padding:12px 16px;border-bottom:1px solid #eef2f7;font-weight:800;color:#1f2b3a;}
.chat-body{padding:14px;max-height:70vh;overflow-y:auto;}
.msg-row{display:flex;gap:10px;margin:8px 0;}
.msg{padding:10px 14px;border-radius:16px;border:1px solid;max-width:78%;line-height:1.45;font-size:15px;}
.msg .meta{font-size:11px;opacity:.7;margin-top:6px;}
.msg.ai{background:#F1F6FA;border-color:#F1F6FA;color:#1f2b3a;}
.msg.user{background:#FDF6B4;border-color:#FDF6B4;color:#2b2b2b;margin-left:auto;}
</style>
""", unsafe_allow_html=True)

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

    labels = {"📤 Origine": "Leggi documento", "💬 Chat": "Chat", "🕒 Cronologia": "Cronologia"}
    choice = st.radio('', list(labels.keys()), index=1)  # default: Chat
    nav = labels[choice]

    if nav == 'Leggi documento':
        st.subheader('📤 Origine (indice)')
        if not search_client:
            st.warning("⚠️ Azure Search non configurato.")
        else:
            try:
                # facets sul campo documento
                res = search_client.search(
                    search_text="*",
                    facets=[f"{FILENAME_FIELD},count:1000"],
                    top=0
                )
                facets = list(res.get_facets().get(FILENAME_FIELD, []))
                paths = [f['value'] for f in facets] if facets else []

                if not paths:
                    st.info("Nessun documento trovato. Verifica che il campo sia 'Facetable' e che l'indice sia popolato.")
                else:
                    import os
                    display = [os.path.basename(p.rstrip("/")) or p for p in paths]
                    # mantieni selezione precedente se esiste
                    idx = paths.index(ss['active_doc']) if ss.get('active_doc') in paths else 0
                    selected_label = st.selectbox("Seleziona documento", display, index=idx)
                    selected_path = paths[display.index(selected_label)]
                    if selected_path != ss.get('active_doc'):
                        ss['active_doc'] = selected_path
                        st.success(f"Filtro attivo su: {selected_label}")

                    # reset filtro
                    if st.button("🔄 Usa tutti i documenti (rimuovi filtro)"):
                        ss['active_doc'] = None
                        st.rerun()

            except Exception as e:
                st.error(f"Errore nel recupero dell'elenco documenti: {e}")

    elif nav == 'Cronologia':
        st.subheader('🕒 Cronologia')
        if not ss['chat_history']:
            st.write("Nessun messaggio ancora.")
        else:
            for m in ss['chat_history']:
                who = "👤 Tu" if m['role'] == 'user' else "🤖 Assistente"
                st.markdown(f"**{who}** · _{m['ts']}_")
                st.markdown(m['content'])
                st.markdown('---')

    # loghi in basso (regola l'altezza come preferisci)
    spacer(3)
    colA, colB = st.columns([1, 1])
    with colA:
        try: st.image('images/logoRAEE.png', width=80)
        except Exception: st.markdown('')
    with colB:
        try: st.image('images/logoNPA.png', width=80)
        except Exception: st.markdown('')

    st.markdown('</div>', unsafe_allow_html=True)

# ===== RIGHT PANE =====
with right:
    st.markdown('<div class="right-pane">', unsafe_allow_html=True)
    st.title('BENVENUTO !')

    # --- CHAT UI ---
    st.markdown('<div class="chat-card">', unsafe_allow_html=True)
    st.markdown('<div class="chat-header">EasyLook.DOC Chat</div>', unsafe_allow_html=True)
    st.markdown('<div class="chat-body">', unsafe_allow_html=True)

    # storico chat
    for m in ss['chat_history']:
        role_class = 'user' if m['role'] == 'user' else 'ai'
        st.markdown(
            f"<div class='msg-row'><div class='msg {role_class}'>"
            f"{html.escape(m['content']).replace('\\n','<br>')}"
            f"<div class='meta'>{m['ts']}</div></div></div>",
            unsafe_allow_html=True
        )

    st.markdown('</div>', unsafe_allow_html=True)  # chiude chat-body

    with st.form("chat_form", clear_on_submit=True):
        user_q = st.text_area("Scrivi qui…", height=90,
                              placeholder="Fai una domanda sui documenti indicizzati…")
        submitted = st.form_submit_button("Invia")
        if submitted and user_q.strip():
            # append utente
            ss['chat_history'].append({
                "role": "user",
                "content": user_q.strip(),
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

            # --- RICERCA NEL MOTORE ---
            context_snippets = []
            sources = []
            try:
                if search_client:
                    flt = safe_filter_eq(FILENAME_FIELD, ss.get('active_doc')) if ss.get('active_doc') else None

                    results = search_client.search(
                        search_text=user_q,
                        filter=flt,
                        top=5,
                        query_type="simple"  # se hai Semantic: query_type="semantic", semantic_configuration_name="default"
                        # semantic_configuration_name="default"
                    )
                    for r in results:
                        # testo del chunk (adatta ai tuoi campi reali)
                        snippet = r.get('chunk') or r.get('content') or r.get('text')
                        if snippet:
                            context_snippets.append(str(snippet)[:400])

                        # documento usato
                        fname = r.get(FILENAME_FIELD)
                        if fname and fname not in sources:
                            sources.append(fname)
                else:
                    st.warning("Azure Search non disponibile. Risposta senza contesto.")
            except Exception as e:
                st.error(f"Errore ricerca: {e}")

            # --- CHIAMATA MODELLO ---
            try:
                messages = build_chat_messages(user_q, context_snippets)
                with st.spinner("Sto scrivendo…"):
                    resp = client.chat.completions.create(
                        model=AZURE_OPENAI_DEPLOYMENT,
                        messages=messages,
                        temperature=0.2,
                        max_tokens=900
                    )
                ai_text = resp.choices[0].message.content if resp.choices else "(nessuna risposta)"

                # aggiungi fonti (mostra solo basename per leggibilità)
                if sources:
                    import os
                    shown = [os.path.basename(s.rstrip("/")) or s for s in sources]
                    uniq = list(dict.fromkeys(shown))
                    ai_text += "\n\n— 📎 Fonti: " + ", ".join(uniq[:6])

                ss['chat_history'].append({
                    "role": "assistant",
                    "content": ai_text,
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
            except Exception as e:
                ss['chat_history'].append({
                    "role": "assistant",
                    "content": f"Si è verificato un errore durante la generazione della risposta: {e}",
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })

            st.rerun()

    st.markdown('<div class="chat-footer">Suggerimento: seleziona un documento in “Origine” per filtrare le risposte.</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)  # chiude chat-card
    st.markdown('</div>', unsafe_allow_html=True)  # chiude right-pane
