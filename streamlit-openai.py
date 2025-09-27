# streamlit-openai-II-Prototipo_leftmenu_chatright.py
# Layout minimal: menu a sinistra, contenuti a destra (Estrazione / Chat)
# Basato su 'streamlit-openai-II-Prototipo.py' mantenendo logica DI + Chat

import os
import streamlit as st
from datetime import datetime, timezone

# OpenAI (Azure)
from openai import AzureOpenAI
import jwt  # eventualmente non usato, lasciato per compatibilità

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
# PAGE CONFIG
# -----------------------
st.set_page_config(page_title="EasyLook.DOC Chat", page_icon="📝", layout="wide")

# -----------------------
# CONFIGURAZIONE (invariata)
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
# CLIENT AZURE OPENAI (invariato)
# -----------------------
try:
    client = AzureOpenAI(
        api_version=API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=token.token  # Bearer token AAD (come nel file originale)
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

# -----------------------
# LAYOUT
# -----------------------
left, right = st.columns([0.28, 0.72])

with left:
    # LOGO + NAV
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
                    st.session_state.pop("document_text", None)
                    st.experimental_rerun()

            if extract:
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

                        # Primo tentativo: page.content
                        pages_text = []
                        for page in getattr(result, "pages", []) or []:
                            if hasattr(page, "content") and page.content:
                                pages_text.append(page.content)
                        full_text = "\n\n".join(pages_text).strip()

                        # Fallback: lines
                        if not full_text:
                            all_lines = []
                            for page in getattr(result, "pages", []) or []:
                                for line in getattr(page, "lines", []) or []:
                                    all_lines.append(line.content)
                            full_text = "\n".join(all_lines).strip()

                        if full_text:
                            st.success("✅ Testo estratto correttamente!")
                            st.text_area("Anteprima testo (~4000 caratteri):", full_text[:4000], height=300)
                            st.session_state["document_text"] = full_text
                        else:
                            st.warning("Nessun testo estratto. Verifica file o SAS.")

                    except Exception as e:
                        st.error(f"Errore durante l'analisi del documento: {e}")

    elif nav == "Chat":
        st.subheader("💬 Step 2 · Chat sul documento")
        if "document_text" not in st.session_state:
            st.info("Prima estrai un documento dal Blob (vai in 'Estrazione documento').")
        else:
            # Input semplice (non chat avanzata, per stabilità)
            user_prompt = st.text_input("✏️ Scrivi la tua domanda sul documento:", key="chat_user_prompt")

            if user_prompt:
                try:
                    doc_text = st.session_state["document_text"]
                    response = client.chat.completions.create(
                        model=DEPLOYMENT_NAME,
                        messages=[
                            {"role": "system", "content": "Sei un assistente che risponde SOLO sulla base del documento fornito."},
                            {"role": "system", "content": f"Contenuto documento:\n{doc_text[:12000]}"},
                            {"role": "user", "content": user_prompt}
                        ],
                        temperature=0.3,
                        max_tokens=600
                    )
                    st.write("💬 **Risposta AI:**")
                    st.write(response.choices[0].message.content)
                except Exception as api_err:
                    st.error(f"❌ Errore nella chiamata API: {api_err}")
