# streamlit-openai-II-Prototipo_leftmenu_chatbubbles.py
# Layout: menu sinistra + chat a destra con bolle stile WhatsApp (AI bianca, utente gialla).
# Backend rimane identico: AAD -> Azure OpenAI; Document Intelligence per estrazione testo.

import os, html
import streamlit as st
from datetime import datetime, timezone

# OpenAI (Azure)
from openai import AzureOpenAI
from azure.identity import ClientSecretCredential

# Document Intelligence
try:
    from azure.ai.formrecognizer import DocumentAnalysisClient
    from azure.core.credentials import AzureKeyCredential
    HAVE_FORMRECOGNIZER = True
except Exception:
    HAVE_FORMRECOGNIZER = False

st.set_page_config(page_title="EasyLook.DOC Chat", page_icon="💬", layout="wide")

# -----------------------
# CONFIG (invariata)
# -----------------------
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT")
API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")

AZURE_DOCINT_ENDPOINT = os.getenv("AZURE_DOCINT_ENDPOINT")
AZURE_DOCINT_KEY = os.getenv("AZURE_DOCINT_KEY")
AZURE_BLOB_CONTAINER_SAS_URL = os.getenv("AZURE_BLOB_CONTAINER_SAS_URL")

# -----------------------
# TOKEN AAD PER OPENAI
# -----------------------
try:
    credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
    token = credential.get_token("https://cognitiveservices.azure.com/.default")
except Exception as e:
    st.error(f"Errore ottenimento token AAD per OpenAI: {e}")
    st.stop()

# -----------------------
# CLIENT AZURE OPENAI
# -----------------------
try:
    client = AzureOpenAI(
        api_version=API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=token.token  # Bearer token AAD
    )
except Exception as e:
    st.error(f"Errore inizializzazione AzureOpenAI: {e}")
    st.stop()

# -----------------------
# HELPERS
# -----------------------
def build_blob_sas_url(container_sas_url: str, blob_name: str) -> str:
    if not container_sas_url or "?" not in container_sas_url:
        return ""
    base, qs = container_sas_url.split("?", 1)
    base = base.rstrip("/")
    return f"{base}/{blob_name}?{qs}"

def now_local_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def human(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts).strftime("%d/%m %H:%M")
    except Exception:
        return ts

# -----------------------
# STATE
# -----------------------
ss = st.session_state
ss.setdefault("document_text", "")
ss.setdefault("chat_history", [])  # list of dicts {role, content, ts}

# -----------------------
# STYLE (bolle chat)
# -----------------------
CSS = """
<style>
:root {
  --yellow: #f5e663; /* richiamo al logo */
  --yellow-border: #e8d742;
  --ai-bg: #ffffff;
  --ai-border: #e8edf3;
  --text: #1f2b3a;
}
.block-container { max-width: 1200px; }
.chat-card { border:1px solid #e6eaf0; border-radius:14px; background:#fff; box-shadow:0 2px 8px rgba(16,24,40,0.04); }
.chat-header { padding:12px 16px; border-bottom:1px solid #eef2f7; font-weight:800; color:#1f2b3a; }
.chat-body { padding:14px; height:520px; overflow:auto; }
.msg-row { display:flex; gap:10px; margin:8px 0; }
.msg { padding:10px 14px; border-radius:16px; border:1px solid; max-width:78%; line-height:1.45; font-size:15px; }
.msg .meta { font-size:11px; opacity:.7; margin-top:6px; }
.msg.ai   { background: var(--ai-bg);     border-color: var(--ai-border); color: var(--text); }
.msg.user { background: var(--yellow);    border-color: var(--yellow-border); color:#2b2b2b; margin-left:auto; }
.avatar { width:28px; height:28px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:14px; }
.avatar.ai { background:#d9e8ff; color:#123; }
.avatar.user { background:#fff0a6; color:#5a4a00; }
.small { font-size:12px; color:#5b6b7e; margin:6px 0 2px; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# -----------------------
# LAYOUT
# -----------------------
left, right = st.columns([0.28, 0.72], gap="large")

with left:
    try:
        st.image("images/Nuovo_Logo.png", width=200)
    except Exception:
        st.markdown("### EasyLook.DOC")
    st.markdown("---")
    nav = st.radio("Navigazione", ["Estrazione documento", "Chat"], index=0)

with right:
    st.title("EasyLook.DOC")

    if nav == "Estrazione documento":
        st.subheader("📄 Step 1 · Estrai testo da Blob")
        if not HAVE_FORMRECOGNIZER:
            st.warning("Installa azure-ai-formrecognizer>=3.3.0")
        else:
            file_name = st.text_input("Nome file nel container (es. 'contratto1.pdf')", key="file_name_input")
            col1, col2 = st.columns([1, 1])
            with col1:
                extract = st.button("🔎 Estrai testo", use_container_width=True)
            with col2:
                if st.button("🗂️ Reset documento", use_container_width=True):
                    ss["document_text"] = ""
                    ss["chat_history"] = []
                    st.experimental_rerun()

            if extract:
                if not (AZURE_DOCINT_ENDPOINT and (AZURE_DOCINT_KEY or (TENANT_ID and CLIENT_ID and CLIENT_SECRET)) and AZURE_BLOB_CONTAINER_SAS_URL and file_name):
                    st.error("Completa le variabili e inserisci il nome file.")
                else:
                    try:
                        blob_url = build_blob_sas_url(AZURE_BLOB_CONTAINER_SAS_URL, file_name)
                        if AZURE_DOCINT_KEY:
                            di_client = DocumentAnalysisClient(endpoint=AZURE_DOCINT_ENDPOINT, credential=AzureKeyCredential(AZURE_DOCINT_KEY))
                        else:
                            di_client = DocumentAnalysisClient(endpoint=AZURE_DOCINT_ENDPOINT, credential=ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET))
                        poller = di_client.begin_analyze_document_from_url(model_id="prebuilt-read", document_url=blob_url)
                        result = poller.result()

                        pages_text = []
                        for page in getattr(result, "pages", []) or []:
                            if hasattr(page, "content") and page.content:
                                pages_text.append(page.content)
                        full_text = "\n\n".join(pages_text).strip()

                        if not full_text:
                            all_lines = []
                            for page in getattr(result, "pages", []) or []:
                                for line in getattr(page, "lines", []) or []:
                                    all_lines.append(line.content)
                            full_text = "\n".join(all_lines).strip()

                        if full_text:
                            st.success("✅ Testo estratto correttamente!")
                            st.text_area("Anteprima testo (~4000 caratteri):", full_text[:4000], height=300)
                            ss["document_text"] = full_text
                            ss["chat_history"] = []  # reset chat per il nuovo doc
                        else:
                            st.warning("Nessun testo estratto. Verifica file o SAS.")
                    except Exception as e:
                        st.error(f"Errore durante l'analisi del documento: {e}")

    else:  # Chat
        st.subheader("💬 Step 2 · Chat sul documento")
        if not ss.get("document_text"):
            st.info("Prima estrai un documento dal Blob (vai in 'Estrazione documento').")
        else:
            st.markdown('<div class="chat-card">', unsafe_allow_html=True)
            st.markdown('<div class="chat-header">Conversazione</div>', unsafe_allow_html=True)

            # Corpo chat
            chat_container = st.container()
            with chat_container:
                st.markdown('<div class="chat-body">', unsafe_allow_html=True)
                if not ss["chat_history"]:
                    st.markdown('<div class="small">Nessun messaggio. Fai una domanda sul documento.</div>', unsafe_allow_html=True)
                else:
                    for m in ss["chat_history"]:
                        role = m["role"]
                        content = html.escape(m["content"]).replace("\n", "<br>")
                        ts = human(m["ts"])
                        if role == "user":
                            st.markdown(f"""
                                <div class="msg-row" style="justify-content:flex-end;">
                                  <div class="msg user">
                                    {content}
                                    <div class="meta">{ts}</div>
                                  </div>
                                  <div class="avatar user">U</div>
                                </div>""", unsafe_allow_html=True)
                        else:
                            st.markdown(f"""
                                <div class="msg-row">
                                  <div class="avatar ai">A</div>
                                  <div class="msg ai">
                                    {content}
                                    <div class="meta">{ts}</div>
                                  </div>
                                </div>""", unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)  # /chat-body

            # Input riga singola (Enter = invia)
            user_prompt = st.text_input("✏️ Scrivi la tua domanda sul documento:", key="chat_user_prompt_bubbles")

            if user_prompt:
                # Append utente
                ss["chat_history"].append({"role": "user", "content": user_prompt, "ts": now_local_iso()})
                try:
                    # Chiamata modello (singolo turno; se vuoi estendere ai turni, includi history nei messages)
                    doc_text = ss["document_text"]
                    response = client.chat.completions.create(
                        model=DEPLOYMENT_NAME,
                        messages=[
                            {"role": "system", "content": "Sei un assistente che risponde SOLO sulla base del documento fornito."},
                            {"role": "system", "content": f"Contenuto documento:\n{doc_text[:12000]}"},
                            {"role": "user", "content": user_prompt}
                        ],
                        temperature=0.3,
                        max_tokens=700
                    )
                    answer = response.choices[0].message.content.strip()
                    ss["chat_history"].append({"role": "assistant", "content": answer, "ts": now_local_iso()})
                    st.experimental_rerun()
                except Exception as api_err:
                    ss["chat_history"].append({"role": "assistant", "content": f"Errore API: {api_err}", "ts": now_local_iso()})
                    st.experimental_rerun()
