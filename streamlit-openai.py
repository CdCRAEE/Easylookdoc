import os, html
import streamlit as st
from datetime import datetime, timezone
from openai import AzureOpenAI
from azure.identity import ClientSecretCredential

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

# --------- TOKEN + CLIENT ---------
try:
    credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
    token = credential.get_token('https://cognitiveservices.azure.com/.default')
    client = AzureOpenAI(api_version=API_VERSION, azure_endpoint=AZURE_OPENAI_ENDPOINT, api_key=token.token)
except Exception as e:
    st.error(f'Errore inizializzazione Azure: {e}')
    st.stop()

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
CSS = '''
<style>
:root{
  --yellow:#FDF6B4; --yellow-border:#FDF6B4;
  --ai-bg:#F1F6FA; --ai-border:#F1F6FA; --text:#1f2b3a;
}

/* === SFONDO: sinistra bianca (menu) + barra, destra grigia === */
.stApp{ background:#f5f7fa !important; }

.block-container{
  max-width:1200px;               /* tienilo allineato al layout */
  min-height:100vh;
  position:relative;              /* contesto per lo sfondo */
}

/* sfondo bianco per la colonna sinistra con barra verticale */
.block-container::before{
  content:"";
  position:absolute;
  top:0; bottom:0; left:0;
  width:28%;                      /* = st.columns([0.28, 0.72]) */
  background:#ffffff;
  box-shadow:inset -1px 0 0 #e5e7eb;  /* barra verticale */
  pointer-events:none;
  z-index:0;
}

/* i contenuti stanno sopra lo sfondo */
.block-container > *{ position:relative; z-index:1; }

/* ===== CHAT ===== */
.chat-card{border:1px solid #e6eaf0;border-radius:14px;background:#fff;box-shadow:0 2px 8px rgba(16,24,40,.04);}
.chat-header{padding:12px 16px;border-bottom:1px solid #eef2f7;font-weight:800;color:#1f2b3a;}
.chat-body{padding:14px;max-height:70vh;overflow-y:auto;}
.msg-row{display:flex;gap:10px;margin:8px 0;}
.msg{padding:10px 14px;border-radius:16px;border:1px solid;max-width:78%;line-height:1.45;font-size:15px;}
.msg .meta{font-size:11px;opacity:.7;margin-top:6px;}
.msg.ai{background:var(--ai-bg);border-color:var(--ai-border);color:var(--text);}
.msg.user{background:var(--yellow);border-color:var(--yellow-border);color:#2b2b2
