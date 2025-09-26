# streamlit-openai.py (patched)
import os
import re
import html
from datetime import datetime, timezone

import streamlit as st

# Azure OpenAI (con AAD)
from openai import AzureOpenAI
from azure.identity import ClientSecretCredential

# Document Intelligence (Form Recognizer)
try:
    from azure.ai.formrecognizer import DocumentAnalysisClient
    from azure.core.credentials import AzureKeyCredential
    HAVE_FORMRECOGNIZER = True
except Exception:
    HAVE_FORMRECOGNIZER = False

# -----------------------
# HELPERS
# -----------------------
def clean_markdown_fences(text: str) -> str:
    """
    Rimuove code fence markdown (``` e opzionale linguaggio: ```python).
    Lascia il contenuto interno come testo semplice.
    """
    if not text:
        return ""
    # rimuove sia apertura con linguaggio che chiusura, anche con newline dopo ```lang
    text = re.sub(r"```[a-zA-Z0-9_-]*\n?", "", text)
    text = text.replace("```", "")
    return text.strip()

def local_iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()

# -----------------------
# PAGE + LOGO
# -----------------------
st.set_page_config(page_title="EasyLook.DOC Chat", page_icon="📝", layout="wide")
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
# AAD token + AzureOpenAI client
# -----------------------
if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET, AZURE_OPENAI_ENDPOINT, DEPLOYMENT_NAME]):
    st.error("Config mancante: verifica le variabili d'ambiente richieste.")
    st.stop()

try:
    credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
    aad_token = credential.get_token("https://cognitiveservices.azure.com/.default").token
except Exception as e:
    st.error(f"Errore ottenimento token AAD per OpenAI: {e}")
    st.stop()

try:
    client = AzureOpenAI(
        api_version=API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_ad_token=aad_token  # uso AAD correttamente
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
        if not container_sas_url or "?" not in container_sas_url:
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

                # Preferisci il contenuto aggregato se disponibile
                full_text = ""
                if hasattr(result, "content") and result.content:
                    full_text = result.content.strip()

                # Fallback a contenuto per pagina
                if not full_text and hasattr(result, "pages"):
                    pages_text = []
                    for page in result.pages:
                        if hasattr(page, "content") and page.content:
                            pages_text.append(page.content)
                    full_text = "\n\n".join(pages_text).strip()

                # Fallback a linee (retro-compatibilità)
                if not full_text and hasattr(result, "pages"):
                    all_lines = []
                    for page in result.pages:
                        for line in getattr(page, "lines", []) or []:
                            all_lines.append(line.content)
                    full_text = "\n".join(all_lines).strip()

                if full_text:
                    st.success("✅ Testo estratto correttamente!")
                    st.text_area("Anteprima testo (~4000 caratteri):", full_text[:4000], height=300)
                    st.session_state["document_text"] = full_text
                    st.session_state["chat_history"] = []  # reset chat quando cambi documento
                else:
                    st.warning("Nessun testo estratto. Verifica file o SAS.")

            except Exception as e:
                st.error(f"Errore durante l'analisi del documento: {e}")

# -----------------------
# STEP 2: chat (visibile SOLO dopo l'estrazione)
# -----------------------
if "document_text" in st.session_state:
    st.subheader("💬 Step 2 · Fai la tua ricerca")

    CONTEXT_CHAR_LIMIT = 12000
    ASSISTANT_SYSTEM_INSTRUCTION = "Sei un assistente che risponde SOLO sulla base del documento fornito."

    def ensure_chat_history():
        if "chat_history" not in st.session_state:
            st.session_state["chat_history"] = []  # {role, content, ts}

    def build_messages_for_api(document_text: str, history: list):
        messages = [{"role": "system", "content": ASSISTANT_SYSTEM_INSTRUCTION}]

        if document_text:
            doc_content = document_text
            if len(doc_content) > CONTEXT_CHAR_LIMIT:
                doc_content = "(---Documento troncato - mostra l'ultima parte---)\n" + doc_content[-CONTEXT_CHAR_LIMIT:]
            messages.append({"role": "system", "content": f"Contenuto documento:\n{doc_content}"})

        # include history dal più recente finché non superi il limite
        chars = 0
        kept = []
        for msg in reversed(history):
            msg_text = f"{msg['role']}: {msg['content']}\n"
            if chars + len(msg_text) > CONTEXT_CHAR_LIMIT:
                break
            kept.append(msg)
            chars += len(msg_text)
        for m in reversed(kept):
            messages.append({"role": m["role"], "content": m["content"]})

        return messages

    # HTML/CSS per bolle chat stile WhatsApp
    CHAT_CSS = """    <style>
    .chat-wrapper { max-width: 900px; margin: 10px 0; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; }
    .message-row { display: flex; margin: 6px 8px; }
    .bubble { padding: 10px 14px; border-radius: 18px; max-width: 75%; box-shadow: 0 1px 0 rgba(0,0,0,0.06);
              line-height: 1.4; white-space: pre-wrap; word-wrap: break-word; }
    .user { margin-left: auto; background: linear-gradient(180deg, #DCF8C6, #CFF2B7); text-align: left; border-bottom-right-radius: 4px; }
    .assistant { margin-right: auto; background: #ffffff; border: 1px solid #e6e6e6; text-align: left; border-bottom-left-radius: 4px; }
    .meta { font-size: 11px; color: #888; margin-top: 4px; }
    .typing { font-style: italic; opacity: 0.9; }
    .container-box { padding: 12px; border-radius: 8px; background: #f7f7f8; }
    </style>
    """

    def render_chat_html(history: list, show_typing=False):
        html_parts = [CHAT_CSS, '<div class="chat-wrapper container-box">']
        for m in history:
            role = m.get("role", "")
            # Pulisci possibili code-fences e poi escape per sicurezza HTML
            content = clean_markdown_fences(m.get("content", ""))
            content = html.escape(content)
            ts_iso = m.get("ts", "")
            # Timestamp leggibile
            try:
                ts_view = datetime.fromisoformat(ts_iso).strftime("%d/%m/%Y %H:%M")
            except Exception:
                ts_view = ts_iso
            bubble_class = "user" if role == "user" else "assistant"
            who = "Tu" if role == "user" else "Assistente"
            html_parts.append(f"""                <div class="message-row">
                  <div class="bubble {bubble_class}">{content}
                    <div class="meta">{who} · {ts_view}</div>
                  </div>
                </div>
            """)
        if show_typing:
            html_parts.append("""            <div class="message-row">
              <div class="bubble assistant typing">Sto scrivendo...</div>
            </div>
            """)
        html_parts.append("</div>")
        return "\n".join(html_parts)

    ensure_chat_history()

    cols = st.columns([1, 6, 1])
    with cols[0]:
        if st.button("🧹 Reset chat"):
            st.session_state["chat_history"] = []
            st.rerun()
    with cols[2]:
        st.caption("Sessione locale al browser")

    chat_placeholder = st.empty()
    chat_placeholder.markdown(render_chat_html(st.session_state["chat_history"]), unsafe_allow_html=True)

    with st.form(key="chat_form", clear_on_submit=True):
        user_prompt = st.text_input("✏️ Scrivi la tua domanda sul documento:", key="user_input")
        submit = st.form_submit_button("Invia")

        if submit and user_prompt:
            ts = local_iso_now()
            # Pulisci anche il messaggio dell'utente da eventuali code fences
            st.session_state["chat_history"].append({
                "role": "user",
                "content": clean_markdown_fences(user_prompt),
                "ts": ts
            })

            chat_placeholder.markdown(
                render_chat_html(st.session_state["chat_history"], show_typing=True),
                unsafe_allow_html=True
            )

            document_text = st.session_state.get("document_text", "")
            api_messages = build_messages_for_api(document_text, st.session_state["chat_history"])

            try:
                with st.spinner("Sto generando la risposta..."):
                    response = client.chat.completions.create(
                        model=DEPLOYMENT_NAME,
                        messages=api_messages,
                        temperature=0.3,
                        max_tokens=600
                    )
                assistant_content = response.choices[0].message.content or ""
                assistant_content = clean_markdown_fences(assistant_content)  # << evitare blocchi codice
                ts2 = local_iso_now()
                st.session_state["chat_history"].append({
                    "role": "assistant",
                    "content": assistant_content,
                    "ts": ts2
                })
                chat_placeholder.markdown(render_chat_html(st.session_state["chat_history"]), unsafe_allow_html=True)

            except Exception as api_err:
                chat_placeholder.markdown(render_chat_html(st.session_state["chat_history"]), unsafe_allow_html=True)
                st.error(f"❌ Errore nella chiamata API: {api_err}")
else:
    st.info("➡️ Prima completa lo Step 1 (estrai un documento) per attivare la chat.")
