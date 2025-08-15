import os
import streamlit as st
from azure.identity import ClientSecretCredential
from openai import AzureOpenAI
import jwt
from datetime import datetime, timezone

# -----------------------
# LOGO
# -----------------------
st.set_page_config(page_title="EasyLook.DOC Chat", page_icon="📝")
st.image("images/Logo EasyLookDOC.png", width=250)  # Percorso relativo alla cartella Images

# -----------------------
# CONFIGURAZIONE
# -----------------------
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")  # es: https://easylookdoc-openai.openai.azure.com
DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT")       # es: gpt-4o
API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")

# -----------------------
# DEBUG VARIABILI
# -----------------------
st.subheader("🔧 Debug Variabili Ambiente")
st.write(f"Tenant ID: {TENANT_ID}")
st.write(f"Client ID: {CLIENT_ID}")
st.write(f"Client Secret: {'✅' if CLIENT_SECRET else '❌'}")
st.write(f"Endpoint API: {AZURE_OPENAI_ENDPOINT}")
st.write(f"Deployment: {DEPLOYMENT_NAME}")
st.write(f"API Version: {API_VERSION}")

# -----------------------
# OTTIENI TOKEN CON SCOPE CORRETTO
# -----------------------
try:
    credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
    # ✅ Scope corretto per Azure OpenAI
    token = credential.get_token("https://cognitiveservices.azure.com/.default")
    st.success("✅ Token ottenuto con successo!")

    # Decodifica per debug
    decoded = jwt.decode(token.token, options={"verify_signature": False})
    st.write("🔍 Dettagli Token Azure AD (decodificato)")
    st.json(decoded)

    st.write(f"Issuer (iss): {decoded.get('iss')}")
    st.write(f"Tenant ID (tid): {decoded.get('tid')}")
    st.write(f"Audience (aud): {decoded.get('aud')}")
    st.write(f"Expiration (exp): {decoded.get('exp')}")
    st.write(
        f"Token valido fino a: "
        f"{datetime.fromtimestamp(decoded.get('exp', 0), tz=timezone.utc)}"
    )

except Exception as e:
    st.error(f"Errore ottenimento token: {e}")
    st.stop()

# -----------------------
# INIZIALIZZA CLIENTE AZURE OPENAI
# -----------------------
try:
    client = AzureOpenAI(
        api_version=API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=token.token  # Passiamo il Bearer token
    )
except Exception as e:
    st.error(f"Errore inizializzazione AzureOpenAI: {e}")
    st.stop()

# -----------------------
# HANDSHAKE DI TEST
# -----------------------
st.subheader("🔗 Test Handshake API")
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
    st.stop()

# -----------------------
# INTERFACCIA CHAT
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
        st.json(getattr(api_err, "response", {}))
