import streamlit as st
import os
from azure.identity import DefaultAzureCredential
from openai import get_bearer_token_provider
from PIL import Image

# === CONFIGURAZIONE CREDENZIALI AZURE AD ===
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")

# === CONFIGURAZIONE AZURE OPENAI ===
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
API_VERSION = "2024-05-01-preview"

# === DEBUG VARIABILI AMBIENTE ===
st.write("Tenant ID:", TENANT_ID)
st.write("Client ID:", CLIENT_ID)
st.write("Client Secret:", "****" if CLIENT_SECRET else "NON SETTATO")
st.write("Endpoint:", AZURE_OPENAI_ENDPOINT)
st.write("Deployment:", DEPLOYMENT_NAME)
st.write("API Version:", API_VERSION)

# === CREA CREDENZIALE AZURE AD ===
token_provider = get_bearer_token_provider(
    DefaultAzureCredential(),
    "https://cognitiveservices.azure.com/.default"
)

# === CREA CLIENT OPENAI CON CREDENZIALE AZURE AD ===
client = AzureOpenAI(
    api_version="2024-05-01-preview",
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    azure_ad_token_provider=token_provider,
)

# === INTERFACCIA STREAMLIT ===
logo = Image.open("images/Logo EasyLookDOC.png")
st.image(logo, width=250)

st.set_page_config(page_title="EasyLookDOC", layout="centered")
st.title("💬 Chat AI con Azure OpenAI (via Azure AD)")

prompt = st.text_area("Scrivi la tua domanda:")

if st.button("Invia"):
    if not prompt.strip():
        st.warning("⚠️ Inserisci prima una domanda.")
    else:
        try:
            response = client.chat.completions.create(
                deployment_id=DEPLOYMENT_NAME,
                messages=[
                    {"role": "system", "content": "Sei un assistente utile."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=500,
            )
            answer = response.choices[0].message.content
            st.success(answer)
        except Exception as e:
            st.error(f"❌ Errore nella chiamata API:\n\n{e}")
