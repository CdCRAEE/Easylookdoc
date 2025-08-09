import streamlit as st
import os
from openai import OpenAI
from azure.identity import DefaultAzureCredential

# === CONFIGURAZIONE VARIABILI ===
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
API_VERSION = "2024-05-01-preview"

# === DEBUG ===
with st.expander("🔧 Debug Variabili Ambiente"):
    st.write("Tenant ID:", TENANT_ID or "❌ MANCANTE")
    st.write("Client ID:", CLIENT_ID or "❌ MANCANTE")
    st.write("Client Secret:", "✅" if CLIENT_SECRET else "❌ MANCANTE")
    st.write("Endpoint:", AZURE_OPENAI_ENDPOINT or "❌ MANCANTE")
    st.write("Deployment:", DEPLOYMENT_NAME)
    st.write("API Version:", API_VERSION)

# === CREDENZIALI AZURE AD ===
try:
    credential = DefaultAzureCredential(
        exclude_managed_identity_credential=True,
        exclude_visual_studio_code_credential=True,
        exclude_shared_token_cache_credential=True,
        exclude_interactive_browser_credential=False
    )
    token = credential.get_token("https://cognitiveservices.azure.com/.default")
except Exception as e:
    st.error(f"❌ Errore autenticazione Azure AD:\n{e}")
    st.stop()

# === INIZIALIZZA CLIENT OPENAI ===
client = OpenAI(
    api_key=token.token,
    api_type="azure_ad",
    api_base=AZURE_OPENAI_ENDPOINT,
    api_version=API_VERSION,
)

# === UI ===
st.set_page_config(page_title="EasyLookDOC", layout="centered")

if os.path.exists("images/Logo EasyLookDOC.png"):
    st.image("images/Logo EasyLookDOC.png", width=250)

st.title("💬 AI Chat con il CdC RAEE")

prompt = st.text_area("✏️ Scrivi la tua domanda:")

if st.button("📤 Invia"):
    if not prompt.strip():
        st.warning("⚠️ Inserisci una domanda.")
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
            st.success(response.choices[0].message.content)
        except Exception as e:
            st.error(f"❌ Errore nella risposta AI:\n{e}")