import os
import html
import pytz
import streamlit as st
from datetime import datetime, timezone
from openai import AzureOpenAI
from azure.identity import ClientSecretCredential
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential

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
AZURE_SEARCH_INDEX = "azureblob-index"            # indice
FILENAME_FIELD = "metadata_storage_path"          # campo con path documento

# ========= TIMEZONE =========
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

    search_key_tuple = (AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_KEY, AZURE_SEARCH_INDEX)
    if "search_client" not in st.session_state or st.session_state.get("search_key") != search_key_tuple:
        if AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY and AZURE_SEARCH_INDEX:
            st.session_state["search_client"] = SearchClient(
                endpoint=AZURE_SEARCH_ENDPOINT,
                index_name=AZURE_SEARCH_INDEX,
                credential=AzureKeyCredential(AZURE_SEARCH_KEY),
            )
            st.session_state["search_key"] = search_key_tuple
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
st.markdown("""
<style>
/* Sfondo pagina diviso: sinistra #F6FDFC (28%), destra #f1f5f9 (72%) */
.stApp::before{
  content:"";
  position:fixed;
  inset:0;
  z-index:-1;
  background: linear-gradient(to right,
    #F6FDFC 0%, #F6FDFC 28%,
    #f1f5f9 28%, #f1f5f9 100%);
}

/* Container centrale trasparente */
.block-container { background: transparent !important; padding-top:12px; padding-bottom:12px; }

/* Padding dentro le colonne */
[data-testid="stHorizontalBlock"] [data-testid="column"] > div:first-child { padding: 12px; }

/* Menu */
/* ===== NAV MENU (definitivo) ===== */

/* Base: niente bordini, testo a sinistra, full-width */
.nav-item .stButton > button,
.nav-item .stButton [data-testid="baseButton-secondary"] {
  width: 100%;
  display: block;
  text-align: left;                 /* (2) allineate a sinistra */
  background: #ffffff !important;
  color: #2F98C7 !important;
  border: none !important;          /* (1) togli i bordini */
  box-shadow: none !important;
  border-radius: 10px !important;
  padding: 10px 12px !important;
}

/* Hover (solo feedback) */
.nav-item .stButton > button:hover,
.nav-item .stButton [data-testid="baseButton-secondary"]:hover {
  background: #e6f3fb !important;   /* azzurrino chiaro */
  color: #2F98C7 !important;
  border: none !important;
}

/* Attivo: sfondo BLU pieno, testo bianco */
.nav-item.active .stButton > button,
.nav-item.active .stButton [data-testid="baseButton-secondary"] {
  background: #2F98C7 !important;   /* (3) blu attivo */
  color: #ffffff !important;
  font-weight: 600 !important;
  border: none !important;          /* niente bordini anche da attivo */
  box-shadow: none !important;
}

/* evidenziazione ricerca */
mark { background:#fff3bf; padding:0 .15em; border-radius:3px; }

/* Chat */
.chat-card{border:1px solid #e6eaf0;border-radius:14px;background:#fff;box-shadow:0 2px 8px rgba(16,24,40,.04);}
.chat-header{padding:12px 16px;border-bottom:1px solid #eef2f7;font-weight:800;color:#1f2b3a;}
.chat-body{padding:14px;max-height:70vh;overflow-y:auto;background:#fff;border-radius:0 0 14px 14px;}
.msg-row{display:flex;gap:10px;margin:8px 0;}
.msg{padding:10px 14px;border-radius:16px;border:1px solid;max-width:78%;line-height:1.45;font-size:15px;}
.msg .meta{font-size:11px;opacity:.7;margin-top:6px;}
.msg.ai{background:#F1F6FA;border-color:#F1F6FA;color:#1f2b3a;}
.msg.user{background:#FDF6B4;border-color:#FDF6B4;color:#2b2b2b;margin-left:auto;}
</style>
""", unsafe_allow_html=True)

# ========= LAYOUT =========
left, right = st.columns([0.28, 0.72], gap="large")

# ----- LEFT PANE -----
with left:
    try:
        st.image("images/Nuovo_Logo.png", width=200)
    except Exception:
        st.markdown("")

    st.markdown("---")

    nav_labels = [("📤 Documenti", "Leggi documento"), ("💬 Chat", "Chat"), ("🕒 Cronologia", "Cronologia")]
    for label, value in nav_labels:
        active_cls = "nav-item active" if ss["nav"] == value else "nav-item"
        st.markdown(f'<div class="{active_cls}">', unsafe_allow_html=True)
        if st.button(label, key=f"nav_{value}", type="secondary", use_container_width=True):
            ss["nav"] = value
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    spacer(10)
    st.markdown(
        """
        <div style="display:flex; justify-content:space-between; align-items:center; width:100%;">
            <div><img src="images/logoRAEE.png" width="80"></div>
            <div><img src="images/logoNPA.png" width="80"></div>
        </div>
        """,
        unsafe_allow_html=True
    )

# ----- RIGHT PANE -----
with right:
    st.title("BENVENUTO !")

    if ss["nav"] == "Leggi documento":
        # il tuo codice documenti qui
        pass

    elif ss["nav"] == "Cronologia":
        # il tuo codice cronologia qui
        pass

    else:  # 'Chat'
        st.markdown('<div class="chat-card">', unsafe_allow_html=True)
        st.markdown('<div class="chat-header">EasyLook.DOC Chat</div>', unsafe_allow_html=True)
        st.markdown('<div class="chat-body">', unsafe_allow_html=True)

        # --- Barra di ricerca ---
        import re
        def _highlight(text: str, q: str) -> str:
            if not q:
                return html.escape(text).replace("\n", "<br>")
            escaped = html.escape(text)
            pat = re.compile(re.escape(q), re.IGNORECASE)
            return pat.sub(lambda m: f"<mark>{m.group(0)}</mark>", escaped).replace("\n", "<br>")

        search_q = st.text_input("🔎 Cerca nella chat", value="", placeholder="Cerca messaggi…", label_visibility="visible")
        spacer(2)
        st.markdown("---")
        spacer(1)

        messages_to_show = ss["chat_history"]
        if search_q:
            sq = search_q.strip().lower()
            messages_to_show = [m for m in ss["chat_history"] if sq in m.get("content","").lower()]
            st.caption(f"Risultati: {len(messages_to_show)}")

        for m in messages_to_show:
            role_class = "user" if m["role"] == "user" else "ai"
            body_html = _highlight(m.get("content", ""), search_q)
            meta = m.get("ts", "")
            html_block = (
                "<div class='msg-row'><div class='msg %s'>%s"
                "<div class='meta'>%s</div></div></div>"
            ) % (role_class, body_html, meta)
            st.markdown(html_block, unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

        user_q = st.chat_input("Scrivi qui…")
        if user_q and user_q.strip():
            ss["chat_history"].append({"role": "user", "content": user_q.strip(), "ts": ts_now_it()})
            # qui la parte ricerca + completamento come nel tuo file …

        st.markdown('<div class="chat-footer">Suggerimento: seleziona un documento in “Documenti” per filtrare le risposte.</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)