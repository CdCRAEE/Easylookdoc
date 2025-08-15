import streamlit as st
import os
import openai
import jwt
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential, ChainedTokenCredential
from azure.core.exceptions import ClientAuthenticationError

# === Variabili ambiente ===
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
API_VERSION = "2024-05-01-preview"

# === Streamlit UI ===
st.set_page_config(page_title="EasyLookDOC Debug Chat AI", layout="centered")

if os.path.exists("images/Logo EasyLookDOC.png"):
    st.image("images/Logo EasyLookDOC.png", width=250)

st.title("💬 EasyLook.DOC Chat AI - Debug Mode")

# === Mostra le variabili ambiente ===
with st.expander("🔧 Debug Variabili Ambiente"):
    st.write("Tenant ID:", TENANT_ID or "❌ MANCANTE")
    st.write("Client ID:", CLIENT_ID or "❌ MANCANTE")
    st.write("Client Secret:", "✅" if CLIENT_SECRET else "❌ MANCANTE")
    st.write("Endpoint API:", AZURE_OPENAI_ENDPOINT or "❌ MANCANTE")
    st.write("Deployment:", DEPLOYMENT_NAME)
    st.write("API Version:", API_VERSION)

# === Setup credenziali con debug ===
try:
    credential = ChainedTokenCredential(
        ManagedIdentityCredential(),
        DefaultAzureCredential(
            exclude_managed_identity_credential=True,
            exclude_visual_studio_code_credential=True,
            exclude_shared_token_cache_credential=True,
            exclude_interactive_browser_credential=False
        )
    )

    token = credential.get_token("https://cognitiveservices.azure.com/.default")
    st.success("✅ Token ottenuto con successo!")

    decoded = jwt.decode(token.token, options={"verify_signature": False})
    with st.expander("🔍 Dettagli Token Azure AD (decodificato)"):
        st.json(decoded)

    st.write(f"Issuer (iss): {decoded.get('iss')}")
    st.write(f"Tenant ID (tid): {decoded.get('tid')}")
    st.write(f"Audience (aud): {decoded.get('aud')}")
    st.write(f"Expiration (exp): {decoded.get('exp')}")
    st.write(f"Token valido fino a: {decoded.get('exp')} (epoch)")

except ClientAuthenticationError as auth_err:
    st.error(f"❌ Errore autenticazione Azure AD:\n{auth_err}")
    st.stop()
except Exception as e:
    st.error(f"❌ Errore generale:\n{e}")
    st.stop()

# === Configura client OpenAI ===
client = openai.AzureOpenAI(
    api_version=API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    azure_ad_token=token.token
)

# === UI di chat ===
prompt = st.text_area("✏️ Scrivi la tua domanda:")

if st.button("📤 Invia"):
    if not prompt.strip():
        st.warning("⚠️ Inserisci una domanda.")
    else:
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
            st.success(response.choices[0].message["content"])

        except Exception as e:
            st.error(f"❌ Errore nella chiamata API:\n{e}")
