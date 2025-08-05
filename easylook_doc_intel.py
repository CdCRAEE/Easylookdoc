import os
import streamlit as st
from azure.storage.blob import BlobServiceClient
import requests
from dotenv import load_dotenv
from io import BytesIO

# Carica variabili d'ambiente
load_dotenv()

# Variabili d'ambiente
ACCOUNT_NAME = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
CONTAINER_NAME = os.getenv("AZURE_STORAGE_CONTAINER_NAME")
CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

DOC_INTEL_ENDPOINT = os.getenv("DOCUMENT_INTELLIGENCE_ENDPOINT")
DOC_INTEL_KEY = os.getenv("DOCUMENT_INTELLIGENCE_KEY")

# Setup Blob client
blob_service_client = BlobServiceClient.from_connection_string(CONNECTION_STRING)
container_client = blob_service_client.get_container_client(CONTAINER_NAME)

# Streamlit UI
st.set_page_config(page_title="EasyLook.DOC", layout="centered")
st.title("📄 EasyLook.DOC – Analisi Documenti PDF con AI")
st.markdown("Seleziona un file PDF dal tuo Blob Storage per analizzarlo con Document Intelligence (Layout Model).")

# Lista dei file PDF nel container
blobs = [blob.name for blob in container_client.list_blobs() if blob.name.endswith(".pdf")]

if not blobs:
    st.warning("Nessun file PDF trovato nel container.")
else:
    selected_blob = st.selectbox("📂 Seleziona un documento", blobs)

    if st.button("Analizza documento"):
        with st.spinner("Estrazione in corso..."):

            # Scarica il PDF dal blob
            blob_client = container_client.get_blob_client(selected_blob)
            stream = BytesIO()
            blob_data = blob_client.download_blob()
            blob_data.readinto(stream)
            stream.seek(0)

            # Invio a Document Intelligence (Layout Model)
            url = f"{DOC_INTEL_ENDPOINT}formrecognizer/documentModels/prebuilt-layout:analyze?api-version=2023-07-31"
            headers = {
                "Ocp-Apim-Subscription-Key": DOC_INTEL_KEY,
                "Content-Type": "application/pdf"
            }

            response = requests.post(url, headers=headers, data=stream.read())

            if response.status_code != 202:
                st.error("Errore durante l'analisi del documento.")
                st.text(response.text)
            else:
                result_url = response.headers["operation-location"]

                # Polling del risultato
                import time
                status = "running"
                while status == "running":
                    time.sleep(1)
                    result = requests.get(result_url, headers={"Ocp-Apim-Subscription-Key": DOC_INTEL_KEY}).json()
                    status = result["status"]

                if status == "succeeded":
                    st.success("✅ Analisi completata!")
                    full_text = full_text = "\n".join([
    line["content"]
    for page in result["analyzeResult"]["pages"]
    for line in page.get("lines", [])
])

                    st.text_area("📄 Testo estratto", value=full_text, height=400)
                else:
                    st.error("❌ L'analisi non è andata a buon fine.")
                    st.json(result)
