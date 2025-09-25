import os
import streamlit as st
from datetime import datetime, timezone

# OpenAI (Azure)
from openai import AzureOpenAI
import jwt

# Credenziali AAD per OpenAI
from azure.identity import ClientSecretCredential

# Document Intelligence
try:
    from azure.ai.formrecognizer import DocumentAnalysisClient
    from azure.core.credentials import AzureKeyCredential
    HAVE_FORMRECOGNIZER = True
except Exception:
    HAVE_FORMRECOGNIZER = False

# -----------------------
# LOGO E TITOLI
# -----------------------
st.set_page_config(page_title="EasyLook.DOC Chat", page_icon="📝")
st.image("images/Nuovo_Logo.png", width=250)
st.title("EasyLook.DOC")

# -----------------------
# CONFIGURAZIONE
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
# CSS + helper per chat stile WhatsApp
# -----------------------
CHAT_CSS = """
<style>
/* container */
.chat-window {
  max-width: 900px;
  margin: 0 auto 12px auto;
  background: #ffffff;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 2px 6px rgba(0,0,0,0.06);
  height: 60vh;
  overflow-y: auto;
}
/* rows */
.row { display: flex; flex-direction: column; margin-bottom: 8px; }
/* user (right) */
.row.right { align-items: flex-end; }
/* assistant (left) */
.row.left { align-items: flex-start; }
/* bubble */
.msg { padding: 10px 14px; border-radius: 18px; display: inline-block; max-width: 78%; word-wrap: break-word; line-height: 1.3; }
/* user style */
.msg.user { background: #DCF8C6; color: #000; border-bottom-right-radius: 4px; }
/* assistant style */
.msg.assistant { background: #ffffff; color: #000; border: 1px solid #e6e6e6; border-bottom-left-radius: 4px; }
/* meta timestamp */
.meta { font-size: 11px; color: #666; margin-top: 4px; }
/* input row */
.input-row { display:flex; gap:8px; margin-top:12px; max-width:900px; margin-left:auto; margin-right:auto; }
input[type="text"] { flex:1; padding:10px 14px; border-radius:20px; border:1px solid #ddd; font-size:14px; }
button.send { background:#128C7E; color:white; border:none; padding:8px 14px; border-radius:18px; cursor:pointer; font-weight:600; }
.small-muted { font-size:13px; color:#666; margin-bottom:6px; }
</style>
"""

st.markdown(CHAT_CSS, unsafe_allow_html=True)

# -----------------------
# Inizializza session_state
# -----------------------
if "document_text" not in st.session_state:
    st.session_state["document_text"] = None
if "chat_history" not in st.session_state:
    # ogni elemento: {"role":"user"/"assistant", "content": str, "ts": iso}
    st.session_state["chat_history"] = []

# -----------------------
# 📄 STEP 1: Estrarre testo da Blob via Document Intelligence
# -----------------------
st.subheader("📄 Step 1 · Estrai testo da Blob")

if not HAVE_FORMRECOGNIZER:
    st.warning("Installa azure-ai-formrecognizer>=3.3.0")
else:
    file_name = st.text_input("Nome file nel container (es. 'contratto1.pdf')", key="file_input")

    def build_blob_sas_url(container_sas_url: str, blob_name: str) -> str:
        if "?" not in container_sas_url:
            return ""
        base, qs = container_sas_url.split("?", 1)
        base = base.rstrip("/")
        return f"{base}/{blob_name}?{qs}"

    if st.button("🔎 Estrai testo"):
        if not (AZURE_DOCINT_ENDPOINT and (AZURE_DOCINT_KEY or (TENANT_ID and CLIENT_ID and CLIENT_SECRET)) and AZURE_BLOB_CONTAINER_SAS_URL and file_name):
            st.error("Completa le variabili e inserisci il nome file.")
        else:
            try:
                blob_url = build_blob_sas_url(AZURE_BLOB_CONTAINER_SAS_URL, file_name)

                # Client Document Intelligence
                if AZURE_DOCINT_KEY:
                    di_client = DocumentAnalysisClient(
                        endpoint=AZURE_DOCINT_ENDPOINT,
                        credential=AzureKeyCredential(AZURE_DOCINT_KEY)
                    )
                else:
                    di_client = DocumentAnalysisClient(
                        endpoint=AZURE_DOCINT_ENDPOINT,
                        credential=ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
                    )

                poller = di_client.begin_analyze_document_from_url(
                    model_id="prebuilt-read",
                    document_url=blob_url
                )
                result = poller.result()

                pages_text = []
                for page in result.pages:
                    if hasattr(page, "content") and page.content:
                        pages_text.append(page.content)
                full_text = "\n\n".join(pages_text).strip()

                if not full_text:
                    all_lines = []
                    for page in result.pages:
                        for line in getattr(page, "lines", []) or []:
                            all_lines.append(line.content)
                    full_text = "\n".join(all_lines).strip()

                if full_text:
                    st.success("✅ Testo estratto correttamente!")
                    st.text_area("Anteprima testo (~4000 caratteri):", full_text[:4000], height=300)
                    # salva documento e reset chat_history (per evitare mix tra documenti)
                    st.session_state["document_text"] = full_text
                    st.session_state["chat_history"] = []
                else:
                    st.warning("Nessun testo estratto. Verifica file o SAS.")

            except Exception as e:
                st.error(f"Errore durante l'analisi del documento: {e}")

# -----------------------
# 💬 STEP 2: Chat in stile WhatsApp (sul documento estratto)
# -----------------------
st.subheader("💬 Step 2 · Chat sul documento (stile WhatsApp)")

if not st.session_state.get("document_text"):
    st.info("Prima estrai un documento dal Blob (Step 1).")
else:
    st.markdown('<div class="small-muted">Chat collegata al documento caricato. La cronologia è salvata nella sessione del browser.</div>', unsafe_allow_html=True)

    # container per la chat (render)
    chat_container = st.container()

    def render_chat(history):
        chat_html = '<div class="chat-window" id="chat-window">'
        for msg in history:
            role = msg.get("role", "assistant")
            ts = msg.get("ts", "")
            content = msg.get("content", "").replace("\n", "<br>")
            if role == "user":
                chat_html += f'''
                <div class="row right">
                  <div class="msg user">{content}</div>
                  <div class="meta">{ts}</div>
                </div>
                '''
            else:
                chat_html += f'''
                <div class="row left">
                  <div class="msg assistant">{content}</div>
                  <div class="meta">{ts}</div>
                </div>
                '''
        chat_html += '</div>'
        # js per scroll to bottom
        chat_html += """
        <script>
        const el = document.getElementById("chat-window");
        if (el) { el.scrollTop = el.scrollHeight; }
        </script>
        """
        st.markdown(chat_html, unsafe_allow_html=True)

    # mostra chat corrente
    render_chat(st.session_state["chat_history"])

    # controlli: reset chat manuale
    col1, col2 = st.columns([1, 6])
    with col1:
        if st.button("🧹 Reset chat"):
            st.session_state["chat_history"] = []
            st.experimental_rerun()
    with col2:
        st.markdown("")

    # form di invio (l'input si pulisce dopo l'invio)
    with st.form(key="wa_chat_form", clear_on_submit=True):
        user_text = st.text_input("✏️ Scrivi un messaggio sul documento:", key="wa_input")
        submitted = st.form_submit_button("Invia")
        if submitted and user_text and user_text.strip():
            # aggiungi messaggio utente alla history
            ts_u = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            st.session_state["chat_history"].append({
                "role": "user",
                "content": user_text.strip(),
                "ts": ts_u
            })

            # costruisci messages per l'API usando il documento come context (troncato)
            doc_text = st.session_state.get("document_text", "")
            # troncamento sicuro per non inviare troppi caratteri (12k)
            DOC_CHAR_LIMIT = 12000
            if len(doc_text) > DOC_CHAR_LIMIT:
                doc_to_send = "(---Documento troncato - mostro la parte finale---)\n" + doc_text[-DOC_CHAR_LIMIT:]
            else:
                doc_to_send = doc_text

            messages = [
                {"role": "system", "content": "Sei un assistente che risponde SOLO sulla base del documento fornito."},
                {"role": "system", "content": f"Contenuto documento:\n{doc_to_send}"},
            ]
            # aggiungi ultimi N messaggi della conversazione per contesto
            last_msgs = st.session_state["chat_history"][-8:]  # user+assistant entries
            for m in last_msgs:
                messages.append({"role": m["role"], "content": m["content"]})
            # aggiungi l'ultimo user (ridondanza ma assicura che l'API riceva la domanda)
            messages.append({"role": "user", "content": user_text.strip()})

            # chiamata API
            try:
                with st.spinner("Generazione risposta..."):
                    response = client.chat.completions.create(
                        model=DEPLOYMENT_NAME,
                        messages=messages,
                        temperature=0.3,
                        max_tokens=600
                    )
                assistant_reply = response.choices[0].message.content

            except Exception as api_err:
                assistant_reply = f"❌ Errore nella chiamata API: {api_err}"

            # aggiungi risposta alla history e rerun per render aggiornato
            ts_a = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            st.session_state["chat_history"].append({
                "role": "assistant",
                "content": assistant_reply,
                "ts": ts_a
            })
            st.experimental_rerun()
