import streamlit as st
import os
import openai
import jwt
from azure.identity import (
    DefaultAzureCredential,
    ManagedIdentityCredential,
    ClientSecretCredential,
)
from azure.core.exceptions import ClientAuthenticationError

# === Variabili ambiente ===
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
API_VERSION = "2024-05-01-preview"

# === Funzione per capire se siamo in locale o cloud (App Service) ===
def is_running_in_azure():
    # Se c'è la variabile Azure App Service 'WEBSITE_INSTANCE_ID' siamo in cloud
    return os.getenv("WEBSITE_INSTANCE_ID") is not None

# === Ottieni credenziale in base all'ambiente ===
def get_credential():
    if is_running_in_azure():
        st.info("🔵 Esecuzione in cloud: uso ManagedIdentityCredential")
        return ManagedIdentityCredential()
    else:
        st.info("🟠 Esecuzione in locale: uso ClientSecretCredential")
        if not (TENANT_ID and CLIENT_ID and CLIENT_SECRET):
            st.error("❌ Variabili AZURE_TENANT_ID, AZURE_CLIENT_ID e AZURE_CLIENT_SECRET devono essere definite in locale!")
            st.stop()
        return ClientSecretCredential(tenant_id=TENANT_ID, client_id=CLIENT_ID, client_secret=CLIENT_SECRET)

# === Ottieni token da Azure AD ===
try:
    credential = get_credential()
    token = credential.get_token("https://cognitiveservices.azure.com/.default")
    st.write("✅ Token ottenuto")

    decoded = jwt.decode(token.token, options={"verify_signature": False})
    st.write(f"Issuer: {decoded.get('iss')}")
    st.write(f"Tenant ID: {decoded.get('tid')}")
    st.write(f"Expires at: {decoded.get('exp')}")
    st.write(f"Audience: {decoded.get('aud')}")
except ClientAuthenticationError as e:
    st.error(f"❌ Errore autenticazione Azure AD:\n{e}")
    st.stop()
except Exception as e:
    st.error(f"❌ Errore generico:\n{e}")
    st.stop()

# === Configura openai ===
openai.api_type = "azure_ad"
openai.api_base = AZURE_OPENAI_ENDPOINT
openai.api_version = API_VERSION
openai.api_key = token.token

# === Streamlit UI ===
st.set_page_config(page_title="EasyLookDOC", layout="centered")

if os.path.exists("images/Logo EasyLookDOC.png"):
    st.image("images/Logo EasyLookDOC.png", width=250)

st.title("💬 EasyLookDOC Chat AI")

prompt = st.text_area("✏️ Scrivi la tua domanda:")

if st.button("📤 Invia"):
    if not prompt.strip():
        st.warning("⚠️ Inserisci una domanda.")
    else:
        try:
            response = openai.chat.completions.create(
                model=DEPLOYMENT_NAME,
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