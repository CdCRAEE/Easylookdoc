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
# 📄 STEP 1: Estrarre testo da Blob via Document Intelligence
# -----------------------
st.subheader("📄 Step 1 · Estrai testo da Blob")

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
                    st.session_state["document_text"] = full_text
                    # reset chat when a new document is loaded
                    st.session_state.pop("chat_history", None)
                else:
                    st.warning("Nessun testo estratto. Verifica file o SAS.")

            except Exception as e:
                st.error(f"Errore durante l'analisi del documento: {e}")

# -----------------------
# 💬 STEP 2: Chat continua sul documento estratto
# -----------------------
st.subheader("💬 Step 2 · Chat continua sul documento")

# Configurazione per il contesto (limite in caratteri, adatta se serve)
CONTEXT_CHAR_LIMIT = 12000  # tieni entro un valore per evitare token explosion
ASSISTANT_SYSTEM_INSTRUCTION = "Sei un assistente che risponde SOLO sulla base del documento fornito."

def ensure_chat_history():
    if "chat_history" not in st.session_state:
        # ogni item: {"role": "user"/"assistant", "content": str, "ts": iso_string}
        st.session_state["chat_history"] = []

def build_messages_for_api(document_text: str, history: list):
    """
    Costruisce la lista messages per AzureOpenAI in modo efficiente:
    - Aggiunge il system instruction
    - Aggiunge una singola system message con il documento (troncato se necessario)
    - Aggiunge gli ultimi messaggi della history fino al limite di caratteri
    """
    messages = []
    # system instruction
    messages.append({"role": "system", "content": ASSISTANT_SYSTEM_INSTRUCTION})

    # document content (troncato)
    if document_text:
        doc_content = document_text
        if len(doc_content) > CONTEXT_CHAR_LIMIT:
            # conserva la coda del documento (spesso è importante l'ultima parte),
            # oppure potresti utilizzare una summarization preventiva.
            doc_content = doc_content[-CONTEXT_CHAR_LIMIT:]
            doc_content = "(---Documento troncato - mostra l'ultima parte---)\n" + doc_content
        messages.append({"role": "system", "content": f"Contenuto documento:\n{doc_content}"})

    # aggiungi storia recente (ultima N conversazioni)
    # costruiamo da history dal più vecchio al più nuovo ma limitando chars
    history_msgs = []
    chars = 0
    # consideriamo la history dal più recente al più vecchio per prendere i messaggi finali
    for msg in reversed(history):
        msg_text = f"{msg['role']}: {msg['content']}\n"
        if chars + len(msg_text) > CONTEXT_CHAR_LIMIT:
            break
        history_msgs.append(msg)
        chars += len(msg_text)
    # restore order (vecchio -> nuovo)
    history_msgs = list(reversed(history_msgs))

    for m in history_msgs:
        messages.append({"role": m["role"], "content": m["content"]})

    return messages

def display_chat(history: list):
    chat_container = st.container()
    # semplice stile; puoi migliorarlo con HTML/CSS se vuoi
    for m in history:
        ts = m.get("ts", "")
        if m["role"] == "user":
            chat_container.markdown(f"**Tu** ({ts}):\n\n> {m['content']}")
        else:
            chat_container.markdown(f"**Assistente** ({ts}):\n\n{m['content']}")

ensure_chat_history()

if "document_text" not in st.session_state:
    st.info("Prima estrai un documento dal Blob (Step 1).")
else:
    # display current chat
    st.markdown("### Conversazione")
    if len(st.session_state["chat_history"]) == 0:
        st.info("La chat è vuota: scrivi la tua prima domanda sul documento qui sotto.")
    else:
        display_chat(st.session_state["chat_history"])

    # Controls: clear chat
    col1, col2 = st.columns([1, 6])
    with col1:
        if st.button("🧹 Reset chat"):
            st.session_state["chat_history"] = []
            st.experimental_rerun()
    with col2:
        st.caption("La cronologia è conservata solo nella sessione corrente del browser.")

    # Input form per invio
    with st.form(key="chat_form", clear_on_submit=True):
        user_prompt = st.text_input("✏️ Scrivi la tua domanda sul documento:", key="user_input")
        submit = st.form_submit_button("Invia")

        if submit and user_prompt:
            # registra il messaggio utente nella storia (con timestamp)
            ts = datetime.now(timezone.utc).astimezone().isoformat()
            st.session_state["chat_history"].append({
                "role": "user",
                "content": user_prompt,
                "ts": ts
            })

            # costruiamo i messages per l'API
            document_text = st.session_state.get("document_text", "")
            api_messages = build_messages_for_api(document_text, st.session_state["chat_history"])

            # chiamata API con spinner + gestione errori
            try:
                with st.spinner("Sto generando la risposta..."):
                    response = client.chat.completions.create(
                        model=DEPLOYMENT_NAME,
                        messages=api_messages,
                        temperature=0.3,
                        max_tokens=600
                    )

                assistant_content = response.choices[0].message.content

                # aggiungi risposta alla history
                ts2 = datetime.now(timezone.utc).astimezone().isoformat()
                st.session_state["chat_history"].append({
                    "role": "assistant",
                    "content": assistant_content,
                    "ts": ts2
                })

                # rerun per mostrare la nuova storia aggiornata (st.form clear_on_submit fa già il reset dell'input)
                st.experimental_rerun()

            except Exception as api_err:
                st.error(f"❌ Errore nella chiamata API: {api_err}")