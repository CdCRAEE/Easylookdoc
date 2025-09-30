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
AZURE_SEARCH_INDEX = "azureblob-index"           # <== tuo indice
FILENAME_FIELD = "metadata_storage_path"         # <== campo documento (path completo)

# --------- HELPERS ---------
def spacer(n=1):
    """Aggiunge n righe vuote per spazio verticale."""
    for _ in range(n):
        st.write("")

def safe_filter_eq(field: str, value: str) -> str:
    """Crea una OData filter string con escape degli apici singoli."""
    if value is None:
        return None
    safe_value = value.replace("'", "''")  # escape OData per apice singolo
    return f"{field} eq '{safe_value}'"

def build_chat_messages(user_q: str, context_snippets):
    sys_msg = {
        "role": "system",
        "content": (
            "Sei un assistente che risponde SOLO in base ai documenti forniti nel contesto. "
            "Se l'informazione non è presente, dichiara esplicitamente che non la trovi."
        )
    }
    ctx = "\n\n".join([f"- {s}" for s in (context_snippets or [])]) if context_snippets else "(nessun contesto)"
    user_msg = {"role": "user", "content": f"CONTEXTPASS:\n{ctx}\n\nDOMANDA:\n{user_q}"}
    return [sys_msg, user_msg]

# --------- CLIENTS ---------
try:
    credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)

    # AAD token reuse (buffer 5 min)
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

    # Azure Search client reuse
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

# --------- STYLE (solo per la card chat) ---------
st.markdown("""
<style>
.stApp{ background:#f5f7fa !important; }
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
    left_box = st.container()
    with left_box:
        try:
            st.image('images/Nuovo_Logo.png', width=200)
        except Exception:
            st.markdown('')

        st.markdown('---')

        labels = {"📤 Origine": "Leggi documento", "💬 Chat": "Chat", "🕒 Cronologia": "Cronologia"}
        choice = st.radio('', list(labels.keys()), index=1)
        nav = labels[choice]

        if nav == 'Leggi documento':
            st.subheader('📤 Origine (indice)')
            if not search_client:
