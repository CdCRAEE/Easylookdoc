import os, html, re, pytz
import streamlit as st
from datetime import datetime, timezone
from openai import AzureOpenAI
from azure.identity import ClientSecretCredential
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
import streamlit.components.v1 as components

st.set_page_config(page_title="EasyLook.DOC Chat", page_icon="💬", layout="wide")

# ========= CONFIG =========
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")

AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX", "azureblob-index")
FILENAME_FIELD = "metadata_storage_path"

# ========= TIME =========
local_tz = pytz.timezone("Europe/Rome")
def ts_now_it():
    return datetime.now(local_tz).strftime("%d/%m/%Y %H:%M:%S")

# ========= HELPERS =========
def spacer(n=1):
    for _ in range(n):
        st.write("")

def safe_filter_eq(field, value):
    if not value:
        return None
    safe_value = str(value).replace("'", "''")
    return f"{field} eq '{safe_value}'"

def build_chat_messages(user_q, context_snippets):
    sys_msg = {
        "role": "system",
        "content": ("Sei un assistente che risponde SOLO in base ai documenti forniti nel contesto. "
                    "Se l'informazione non è presente, dillo chiaramente."),
    }
    ctx = "\n\n".join(["- " + s for s in context_snippets]) if context_snippets else "(nessun contesto)"
    user_msg = {"role": "user", "content": f"CONTEXTPASS:\n{ctx}\n\nDOMANDA:\n{user_q}"}
    return [sys_msg, user_msg]

# ========= CLIENTS =========
try:
    credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
    now_ts = datetime.now(timezone.utc).timestamp()
    refresh = True
    if "aad_token" in st.session_state and "aad_exp" in st.session_state:
        if now_ts < st.session_state["aad_exp"] - 300:
            refresh = False
    if refresh:
        access = credential.get_token("https://cognitiveservices.azure.com/.default")
        st.session_state["aad_token"] = access.token
        st.session_state["aad_exp"] = access.expires_on

    client = AzureOpenAI(
        api_version=API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_ad_token=st.session_state["aad_token"],
    )

    key_tuple = (AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_KEY, AZURE_SEARCH_INDEX)
    if "search_client" not in st.session_state or st.session_state.get("search_key") != key_tuple:
        if AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY and AZURE_SEARCH_INDEX:
            st.session_state["search_client"] = SearchClient(
                endpoint=AZURE_SEARCH_ENDPOINT,
                index_name=AZURE_SEARCH_INDEX,
                credential=AzureKeyCredential(AZURE_SEARCH_KEY),
            )
            st.session_state["search_key"] = key_tuple
    search_client = st.session_state.get("search_client")

except Exception as e:
    st.error(f"Errore inizializzazione Azure OpenAI/Search: {e}")
    st.stop()

# ========= STATE =========
ss = st.session_state
ss.setdefault("chat_history", [])
ss.setdefault("active_doc", None)
ss.setdefault("nav", "Chat")

# ========= STYLE =========
st.markdown(f"""
<style>
:root{{
  --yellow:#FDF6B4; --yellow-border:#FDF6B4;
  --ai-bg:#F1F6FA; --ai-border:#F1F6FA; --text:#1f2b3a;
}}

.stApp{{ background:#f5f7fa !important; }}
.block-container{{
  max-width:1200px;
  min-height:100vh;
  position:relative;
}}
/* colonna sinistra bianca */
.block-container::before{{
  content:"";
  position:absolute;
  top:0; bottom:0; left:0;
  width:28%;
  background:#ffffff;
  box-shadow:inset -1px 0 0 #e5e7eb;
  pointer-events:none;
  z-index:0;
}}
.block-container > *{{ position:relative; z-index:1; }}

/* Bottoni menu sinistro */
.nav-item .stButton > button {{
  width: 100%;
  text-align: left;
  background: #ffffff !important;
  color: #2F98C7 !important;
  border: 1px solid #2F98C7 !important;   /* ← bordino blu */
  border-radius: 10px !important;
  padding: 10px 12px !important;
  box-shadow: none !important;
}}
.nav-item .stButton > button:hover {{
  background: #e2e8f0 !important;
  border: 1px solid #2F98C7 !important;
}}
.nav-item.active .stButton > button {{
  background: #2F98C7 !important;  /* blu attivo */
  color: #ffffff !important;
  font-weight: 600 !important;
  border: 1px solid #2F98C7 !important;  /* bordo blu attivo */
}}

/* Card chat */
.chat-card{{border:1px solid #e6eaf0;border-radius:14px;background:#fff;box-shadow:0 2px 8px rgba(16,24,40,.04);}}
.chat-header{{padding:12px 16px;border-bottom:1px solid #eef2f7;font-weight:800;color:#1f2b3a;}}
.chat-body{{padding:14px;max-height:70vh;overflow-y:auto;}}
.msg-row{{display:flex;gap:10px;margin:8px 0;}}
.msg{{padding:10px 14px;border-radius:16px;border:1px solid;max-width:78%;line-height:1.45;font-size:15px;}}
.msg .meta{{font-size:11px;opacity:.7;margin-top:6px;}}
.msg.ai{{background:var(--ai-bg);border-color:var(--ai-border);color:var(--text);}}
.msg.user{{background:var(--yellow);border-color:var(--yellow-border);color:#2b2b2b;margin-left:auto;}}
.avatar{{width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:14px;}}
.avatar.ai{{background:#d9e8ff;color:#123;}}
.avatar.user{{background:#fff0a6;color:#5a4a00;}}
.small{{font-size:12px;color:#5b6b7e;margin:6px 0 2px;}}
.chat-footer{{padding:10px 12px 12px;}}
</style>
""", unsafe_allow_html=True)

# ========= LAYOUT =========
left, right = st.columns([0.28, 0.72], gap='large')

with left:
    try:
        st.image('images/Nuovo_Logo.png', width=200)
    except Exception:
        st.markdown('')
    st.markdown('---')

    colA, colB = st.columns([1, 1])
    with colA:
        try: st.image("images/logoRAEE.png", width=80)
        except Exception: st.empty()
    with colB:
        try:
            st.markdown("<div style='text-align:right;'>", unsafe_allow_html=True)
            st.image("images/logoNPA.png", width=80)
            st.markdown("</div>", unsafe_allow_html=True)
        except Exception: st.empty()
    spacer(2)

    labels = [("📤 Origine", "Leggi documento"), ("💬 Chat", "Chat"), ("🕒 Cronologia", "Cronologia")]
    for label, value in labels:
        active_cls = "nav-item active" if ss["nav"] == value else "nav-item"
        st.markdown(f'<div class="{active_cls}">', unsafe_allow_html=True)
        if st.button(label, key=f"nav_{value}", type="secondary", use_container_width=True):
            ss["nav"] = value
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

with right:
    st.title('BENVENUTO!')

    # ==== ORIGINE ====
    if ss["nav"] == "Leggi documento":
        st.subheader("📤 Origine (indice)")
        if not search_client:
            st.warning("⚠️ Azure Search non configurato.")
        else:
            try:
                res = search_client.search(
                    search_text="*",
                    facets=[f"{FILENAME_FIELD},count:1000"],
                    top=0,
                )
                facets = list(res.get_facets().get(FILENAME_FIELD, []))
                paths = [f["value"] for f in facets] if facets else []
                if not paths:
                    st.info("Nessun documento trovato.")
                else:
                    import os as _os
                    display = [_os.path.basename(p.rstrip("/")) or p for p in paths]
                    idx = paths.index(ss["active_doc"]) if ss.get("active_doc") in paths else 0
                    sel_label = st.selectbox("Seleziona documento", display, index=idx)
                    sel_path = paths[display.index(sel_label)]
                    if sel_path != ss.get("active_doc"):
                        ss["active_doc"] = sel_path
                        st.success(f"Filtro attivo su: {sel_label}")
                    if st.button("🔄 Usa tutti i documenti (rimuovi filtro)"):
                        ss["active_doc"] = None
                        st.rerun()
            except Exception as e:
                st.error(f"Errore nel recupero documenti: {e}")

    elif ss["nav"] == "Chat":
        st.subheader('💬 Chiedi quello che vuoi')
        if search_client:
            st.info("Cercherò nei documenti indicizzati (Azure Search).")
        else:
            st.info("Azure Search non configurato: risponderò senza contesto.")

        st.markdown('<div class="chat-card">', unsafe_allow_html=True)
        st.markdown('<div class="chat-header">Conversazione</div>', unsafe_allow_html=True)

        st.markdown('<div class="chat-body" id="chat-body">', unsafe_allow_html=True)
        if not ss['chat_history']:
            st.markdown('<div class="small">Nessun messaggio. Fai una domanda.</div>', unsafe_allow_html=True)
        else:
            rome_tz = pytz.timezone("Europe/Rome")
            for m in ss['chat_history']:
                role = m['role']
                content = html.escape(m.get('content','')).replace('\n', '<br>')
                try:
                    dt = datetime.fromisoformat(m['ts'].replace("Z","+00:00"))
                    ts = dt.astimezone(rome_tz).strftime('%d/%m %H:%M')
                except Exception:
                    ts = m.get('ts','')
                if role == 'user':
                    st.markdown(f"""
                        <div class='msg-row' style='justify-content:flex-end;'>
                          <div class='msg user'>{content}<div class='meta'>{ts}</div></div>
                          <div class='avatar user'>U</div>
                        </div>""", unsafe_allow_html=True)
                else:
                    st.markdown(f"""
                        <div class='msg-row'>
                          <div class='avatar ai'>A</div>
                          <div class='msg ai'>{content}<div class='meta'>{ts}</div></div>
                        </div>""", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        components.html("""
            <script>
            const el = window.parent.document.getElementById('chat-body');
            if (el) { el.scrollTop = el.scrollHeight; }
            </script>
        """, height=0)

        typing_ph = st.empty()
        st.markdown('<div class="chat-footer">', unsafe_allow_html=True)
        with st.form(key="chat_form", clear_on_submit=True):
            user_q = st.text_input("Scrivi la tua domanda", value="")
            sent = st.form_submit_button("Invia")
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        if sent and user_q.strip():
            ss["chat_history"].append({"role": "user", "content": user_q.strip(), "ts": ts_now_it()})
            context_snippets, sources = [], []
            try:
                if not search_client:
                    st.warning("Azure Search non disponibile. Risposta senza contesto.")
                else:
                    flt = safe_filter_eq(FILENAME_FIELD, ss.get("active_doc")) if ss.get("active_doc") else None
                    results = search_client.search(search_text=user_q, filter=flt, top=5, query_type="simple")
                    for r in results:
                        snippet = r.get("chunk") or r.get("content") or r.get("text")
                        if snippet: context_snippets.append(str(snippet)[:400])
                        fname = r.get(FILENAME_FIELD)
                        if fname and fname not in sources: sources.append(fname)
            except Exception as e:
                st.error(f"Errore ricerca: {e}")

            try:
                messages = build_chat_messages(user_q, context_snippets)
                with typing_ph, st.spinner("Sto scrivendo…"):
                    resp = client.chat.completions.create(
                        model=AZURE_OPENAI_DEPLOYMENT,
                        messages=messages,
                        temperature=0.2,
                        max_tokens=900,
                    )
                typing_ph.empty()
                ai_text = resp.choices[0].message.content if resp.choices else "(nessuna risposta)"
                if sources:
                    import os as _os
                    shown = [_os.path.basename(s.rstrip("/")) or s for s in sources]
                    uniq = list(dict.fromkeys(shown))
                    ai_text += "\n\n— 📎 Fonti: " + ", ".join(uniq[:6])
                ss["chat_history"].append({"role": "assistant", "content": ai_text, "ts": ts_now_it()})
            except Exception as e:
                typing_ph.empty()
                ss["chat_history"].append({"role": "assistant", "content": f"Errore durante la generazione della risposta: {e}", "ts": ts_now_it()})
            st.rerun()
