import streamlit as st
from azure.identity import ClientSecretCredential
from openai import OpenAI
import os
from PIL import Image

# === CONFIGURAZIONE CREDENZIALI AZURE AD ===
TENANT_ID = os.getenv("AZURE_TENANT_ID", "754c7658-c909-4d49-8871-10c93d970018")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "89ae9197-afd1-4ca6-8c63e4f3f1cd")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "kZm8Q~Ay4kRfxYKYYz4J02envFEIaQJGjq-u7cdq")

# === CONFIGURAZIONE AZURE OPENAI ===
AZURE_OPENAI_ENDPOINT = "https://easylookdoc-openai.openai.azure.com/"
DEPLOYMENT_NAME = "gpt-4o"
API_VERSION = "2024-05-01-preview"

# === CREA CREDENZIALE AZURE AD ===
credential = ClientSecretCredential(
    tenant_id=TENANT_ID,
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET
)

# === CREA CLIENT OPENAI CON CREDENZIALE AZURE AD ===
client = OpenAI(
    base_url=AZURE_OPENAI_ENDPOINT,
    api_version=API_VERSION,
    credential=credential
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
