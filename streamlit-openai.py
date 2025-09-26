# streamlit-openai-III-Prototipo_whatsapp_style.py
import os
import streamlit as st
from datetime import datetime, timezone
import html

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
# PAGE + LOGO
# -----------------------
st.set_page_config(page_title="EasyLook.DOC Chat", page_icon="📝", layout="wide")
# If logo missing, ignore
try:
    st.image("images/Nuovo_Logo.png", width=250)
except Exception:
    pass
st.title("EasyLook.DOC")

# -----------------------
# CONFIG
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
# AAD token for OpenAI
# -----------------------
try:
    credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
    token = credential.get_token("https://cognitiveservices.azure.com/.default")
except Exception as e:
    st.error(f"Errore ottenimento token AAD per OpenAI: {e}")
    st.stop()

# -----------------------
# AzureOpenAI client
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
# UI STEP 1: estrazione testo
# -----------------------
st.subheader("📄 Step 1 · Scegli il documento")

if not HAVE_FORMRECOGNIZER:
    st.warning("Installa azure-ai-formrecognizer>=3.3.0")
else:
    file_name = st.text_input("Nome file nel container (es. 'contratto1.pdf')")

    def build_blob_sas_url(container_sas_url: str, blob_name: str) -> str:
        if "?" not in container_sas_url:
            return ""
        base, qs = container_sas_url.split("?", 1)
        base = base.rstrip("/")
        return f"{base}/{blob_name}?{qs}"

    if st.button("🔎 Leggi documento"):
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
                    st.session_state["document_text"] = full_text
                    # reset chat when a new document is loaded
                    st.session_state.pop("chat_history", None)
                else:
                    st.warning("Nessun testo estratto. Verifica file o SAS.")

            except Exception as e:
                st.error(f"Errore durante l'analisi del documento: {e}")

# -----------------------
# STEP 2: chat
# -----------------------
st.subheader("💬 Step 2 · Fai la tua ricerca")

CONTEXT_CHAR_LIMIT = 12000
ASSISTANT_SYSTEM_INSTRUCTION = "Sei un assistente che risponde SOLO sulla base del documento fornito."

def ensure_chat_history():
    if "chat_history" not in st.session_state:
        # each item: {"role":"user"/"assistant", "content": str, "ts": iso_string}
        st.session_state["chat_history"] = []

def build_messages_for_api(document_text: str, history: list):
    messages = []
    messages.append({"role": "system", "content": ASSISTANT_SYSTEM_INSTRUCTION})

    if document_text:
        doc_content = document_text
        if len(doc_content) > CONTEXT_CHAR_LIMIT:
            doc_content = doc_content[-CONTEXT_CHAR_LIMIT:]
            doc_content = "(---Documento troncato - mostra l'ultima parte---)\n" + doc_content
        messages.append({"role": "system", "content": f"Contenuto documento:\n{doc_content}"})

    history_msgs = []
    chars = 0
    for msg in reversed(history):
        msg_text = f"{msg['role']}: {msg['content']}\n"
        if chars + len(msg_text) > CONTEXT_CHAR_LIMIT:
            break
        history_msgs.append(msg)
        chars += len(msg_text)
    history_msgs = list(reversed(history_msgs))

    for m in history_msgs:
        messages.append({"role": m["role"], "content": m["content"]})

    return messages

# HTML/CSS for chat bubbles (WhatsApp-like)
CHAT_CSS = """
<style>
.chat-wrapper {
  max-width: 900px;
  margin: 10px 0;
  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
}
.message-row {
  display: flex;
  margin: 6px 8px;
}
.bubble {
  padding: 10px 14px;
  border-radius: 18px;
  max-width: 75%;
  box-shadow: 0 1px 0 rgba(0,0,0,0.06);
  line-height: 1.4;
  white-space: pre-wrap;
  word-wrap: break-word;
}
.user {
  margin-left: auto;
  background: linear-gradient(180deg, #DCF8C6, #CFF2B7);
  text-align: left;
  border-bottom-right-radius: 4px;
}
.assistant {
  margin-right: auto;
  background: #ffffff;
  border: 1px solid #e6e6e6;
  text-align: left;
  border-bottom-left-radius: 4px;
}
.meta {
  font-size: 11px;
  color: #888;
  margin-top: 4px;
}
.typing {
  font-style: italic;
  opacity: 0.9;
}
.container-box {
  padding: 12px;
  border-radius: 8px;
  background: #f7f7f8;
}
</style>
"""

def render_chat_html(history: list, show_typing=False):
    html_parts = [CHAT_CSS, '<div class="chat-wrapper container-box">']
    for idx, m in enumerate(history):
        role = m.get("role", "")
        content = html.escape(m.get("content", ""))
        ts = m.get("ts", "")
        if role == "user":
            html_parts.append(f'''
            <div class="message-row">
              <div class="bubble user">{content}
                <div class="meta">Tu · {ts}</div>
              </div>
            </div>
            ''')
        else:
            html_parts.append(f'''
            <div class="message-row">
              <div class="bubble assistant">{content}
                <div class="meta">Assistente · {ts}</div>
              </div>
            </div>
            ''')
    # optionally show typing indicator at the end
    if show_typing:
        html_parts.append(f'''
        <div class="message-row">
          <div class="bubble assistant typing">Sto scrivendo...</div>
        </div>
        ''')
    html_parts.append("</div>")
    return "\n".join(html_parts)

ensure_chat_history()

if "document_text" not in st.session_state:
    st.info("Prima estrai un documento dal Blob (Step 1).")
else:
    # Top controls
    cols = st.columns([1, 6, 1])
    with cols[0]:
        if st.button("🧹 Reset chat"):
            st.session_state["chat_history"] = []
            st.experimental_rerun()
    with cols[2]:
        st.caption("Sessione locale al browser")

    # chat area placeholder
    chat_placeholder = st.empty()

    # initial render
    chat_placeholder.markdown(render_chat_html(st.session_state["chat_history"]), unsafe_allow_html=True)

    # Input form
    with st.form(key="chat_form", clear_on_submit=True):
        user_prompt = st.text_input("✏️ Scrivi la tua domanda sul documento:", key="user_input")
        submit = st.form_submit_button("Invia")

        if submit and user_prompt:
            # timestamp
            ts = datetime.now(timezone.utc).astimezone().isoformat()
            # append user message
            st.session_state["chat_history"].append({
                "role": "user",
                "content": user_prompt,
                "ts": ts
            })

            # show updated chat + typing indicator immediately
            chat_placeholder.markdown(render_chat_html(st.session_state["chat_history"], show_typing=True), unsafe_allow_html=True)

            # build API messages
            document_text = st.session_state.get("document_text", "")
            api_messages = build_messages_for_api(document_text, st.session_state["chat_history"])

            # call API (synchronous). We show "typing..." until response arrives.
            try:
                with st.spinner("Sto generando la risposta..."):
                    response = client.chat.completions.create(
                        model=DEPLOYMENT_NAME,
                        messages=api_messages,
                        temperature=0.3,
                        max_tokens=600
                    )

                assistant_content = response.choices[0].message.content

                # append assistant response
                ts2 = datetime.now(timezone.utc).astimezone().isoformat()
                st.session_state["chat_history"].append({
                    "role": "assistant",
                    "content": assistant_content,
                    "ts": ts2
                })

                # final render (removes typing)
                chat_placeholder.markdown(render_chat_html(st.session_state["chat_history"]), unsafe_allow_html=True)

            except Exception as api_err:
                # remove any leftover typing indicator by re-rendering history
                chat_placeholder.markdown(render_chat_html(st.session_state["chat_history"]), unsafe_allow_html=True)
                st.error(f"❌ Errore nella chiamata API: {api_err}")