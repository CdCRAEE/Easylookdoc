import streamlit as st
import os
from azure.identity import DefaultAzureCredential
from azure.openai import OpenAIClient
from PIL import Image

# === CONFIGURAZIONE VARIABILI AMBIENTE ===
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
API_VERSION = "2024-05-01-preview"

# === DEBUG: VISUALIZZA VARIABILI AMBIENTE ===
with st.expander("🔧 Debug Variabili Ambiente"):
    st.write("Tenant ID:", TENANT_ID or "❌ MANCANTE")
    st.write("Client ID:", CLIENT_ID or "❌ MANCANTE")
    st.write("Client Secret:", "✅" if CLIENT_SECRET else "❌ MANCANTE")
    st.write("Endpoint:", AZURE_OPENAI_ENDPOINT or "❌ MANCANTE")
    st.write("Deployment:", DEPLOYMENT_NAME)
    st.write("API Version:", API_VERSION)

# === CREA CLIENT AZURE OPENAI AUTENTICATO CON AZURE AD ===
try:
    client = OpenAIClient(
        endpoint=AZURE_OPENAI_ENDPOINT,
        credential=DefaultAzureCredential()
    )
except Exception as e:
    st.error(f"❌ Errore durante la creazione del client Azure OpenAI: {e}")
    st.stop()

# === INTERFACCIA STREAMLIT ===
st.set_page_config(page_title="EasyLookDOC", layout="centered")

if os.path.exists("images/Logo EasyLookDOC.png"):
    logo = Image.open("images/Logo EasyLookDOC.png")
    st.image(logo, width=250)

st.title("💬 Chat AI con Azure OpenAI (via Azure AD)")

prompt = st.text_area("✏️ Scrivi la tua domanda:")

if st.button("📤 Invia"):
    if not prompt.strip():
        st.warning("⚠️ Inserisci prima una domanda.")
    else:
        try:
            response = client.chat_completions.create(
                model=DEPLOYMENT_NAME,
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
            st.error(f"❌ Errore nella chiamata Azure OpenAI:\n\n{e}")