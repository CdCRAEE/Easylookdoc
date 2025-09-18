import os
import streamlit as st
from datetime import datetime, timezone

# OpenAI (Azure)
from openai import AzureOpenAI

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
st.image("images/Logo EasyLookDOC.png", width=250)

st.title("EasyLook.DOC")

# -----------------------
# CONFIGURAZIONE
# -----------------------
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")      # es: https://easylookdoc-openai.openai.azure.com
DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT")           # es: gpt-4o
API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")

# Document Intelligence
AZURE_DOCINT_ENDPOINT = os.getenv("AZURE_DOCINT_ENDPOINT")       # es: https://document-ai-analyzer.cognitiveservices.azure.com
AZURE_DOCINT_KEY = os.getenv("AZURE_DOCINT_KEY")                 # se vuoto, abiliteremo AAD in step successivo

# Blob container SAS (modo semplice)
AZURE_BLOB_CONTAINER_SAS_URL = os.getenv("AZURE_BLOB_CONTAINER_SAS_URL")  # es: https://account.blob.core.windows.net/container?sv=...&sig=...

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
# (Facoltativo) HANDSHAKE veloce
# -----------------------
with st.expander("🔗 Test Handshake API (facoltativo)"):
    try:
        handshake_resp = client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": "Test di connessione"},
                {"role": "user", "content": "Scrivi OK se ricevi questa richiesta"}
            ],
            max_tokens=5,
            temperature=0
        )
        st.success("✅ Handshake riuscito!")
        st.write("Risposta handshake:", handshake_resp.choices[0].message.content)
    except Exception as handshake_err:
        st.error("❌ Handshake fallito")
        st.error(handshake_err)

# -----------------------
# 📄 STEP 1: Estrarre testo da Blob via Document Intelligence
# -----------------------
st.subheader("📄 Step 1 · Estrai testo da Blob (Document Intelligence)")

if not HAVE_FORMRECOGNIZER:
    st.warning(
        "La libreria 'azure-ai-formrecognizer' non è installata. "
        "Aggiungi a requirements.txt: azure-ai-formrecognizer>=3.3.0"
    )
else:
    if not AZURE_DOCINT_ENDPOINT:
        st.info("Imposta AZURE_DOCINT_ENDPOINT nelle variabili d'ambiente.")
    if not (AZURE_DOCINT_KEY or (TENANT_ID and CLIENT_ID and CLIENT_SECRET)):
        st.info("Servono o AZURE_DOCINT_KEY (chiave) oppure le credenziali AAD (TENANT/CLIENT/SECRET).")
    if not AZURE_BLOB_CONTAINER_SAS_URL:
        st.info("Imposta AZURE_BLOB_CONTAINER_SAS_URL con la SAS del container (permessi rl).")

    file_name = st.text_input("Nome file nel container (es. 'contratto1.pdf')")

    def build_blob_sas_url(container_sas_url: str, blob_name: str) -> str:
        """
        Costruisce l'URL del singolo blob unendo base + file + query SAS.
        container_sas_url: https://account.blob.core.windows.net/container?sv=...&sig=...
        blob_name: es. 'contratto1.pdf'
        """
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
                # Costruisci URL del blob con SAS
                blob_url = build_blob_sas_url(AZURE_BLOB_CONTAINER_SAS_URL, file_name)
                if not blob_url:
                    st.error("SAS container URL non valido.")
                else:
                    # Client Document Intelligence (chiave o AAD)
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

                    # Concateno tutto il testo pagina per pagina
                    pages_text = []
                    for page in result.pages:
                        if hasattr(page, "content") and page.content:
                            pages_text.append(page.content)
                    full_text = "\n\n".join(pages_text).strip()

                    if not full_text:
                        # fallback: alcune versioni espongono lines piuttosto che content
                        all_lines = []
                        for page in result.pages:
                            for line in getattr(page, "lines", []) or []:
                                all_lines.append(line.content)
                        full_text = "\n".join(all_lines).strip()

                    if full_text:
                        st.success("✅ Testo estratto correttamente!")
                        st.text_area("Anteprima testo (prime ~4000 caratteri):", full_text[:4000], height=300)
                    else:
                        st.warning("Nessun testo estratto. Verifica il file (scansione/qualità) o i permessi SAS.")

            except Exception as e:
                st.error(f"Errore durante l'analisi del documento: {e}")

# -----------------------
# CHAT (come già avevi)
# -----------------------
st.subheader("💬 Chat con CdC RAEE")
prompt = st.text_input("✏️ Scrivi la tua domanda:")

if prompt:
    try:
        response = client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": "Sei un assistente utile."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=500
        )
        st.write("💬 **Risposta AI:**")
        st.write(response.choices[0].message.content)
    except Exception as api_err:
        st.error(f"❌ Errore nella chiamata API: {api_err}")
