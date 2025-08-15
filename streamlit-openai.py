import os
import jwt
import requests
import streamlit as st
from azure.identity import ManagedIdentityCredential, DefaultAzureCredential, ChainedTokenCredential
from openai import AzureOpenAI

# =========================
# Config
# =========================
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")  # es. https://easylookdoc-openai.openai.azure.com
DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")

# Scope CORRETTO per Azure OpenAI (puoi sovrascrivere con env AZURE_AUTH_SCOPE se proprio serve)
SCOPE = os.getenv("AZURE_AUTH_SCOPE", "https://cognitiveservices.azure.com/.default")

# =========================
# UI base
# =========================
st.set_page_config(page_title="EasyLookDOC Chat AI", layout="centered")
logo_path = "images/Logo EasyLookDOC.png"
if os.path.exists(logo_path):
    st.image(logo_path, width=250)
st.title("💬 EasyLook.DOC Chat AI — Debug")

with st.expander("🔧 Debug Variabili Ambiente"):
    st.write("Tenant ID:", TENANT_ID or "❌ MANCANTE")
    st.write("Client ID:", CLIENT_ID or "❌ MANCANTE")
    st.write("Client Secret:", "✅" if CLIENT_SECRET else "❌ MANCANTE")
    st.write("Endpoint API:", AZURE_OPENAI_ENDPOINT or "❌ MANCANTE")
    st.write("Deployment:", DEPLOYMENT_NAME)
    st.write("API Version:", API_VERSION)
    st.write("Auth Scope richiesto:", SCOPE)

# =========================
# Credenziali e Token (aud deve diventare https://cognitiveservices.azure.com)
# =========================
try:
    # Catena: prima Managed Identity (in App Service), poi DefaultAzureCredential (per locale/altro)
    credential = ChainedTokenCredential(
        ManagedIdentityCredential(),
        DefaultAzureCredential(
            exclude_managed_identity_credential=True,
            exclude_visual_studio_code_credential=True,
            exclude_shared_token_cache_credential=True,
            exclude_interactive_browser_credential=True,  # niente browser in App Service
        ),
    )

    token = credential.get_token(SCOPE)
    st.success("✅ Token ottenuto con successo!")

    # Decode per debug (senza verifica firma)
    decoded = jwt.decode(token.token, options={"verify_signature": False})
    with st.expander("🔍 Dettagli Token Azure AD (decodificato)"):
        st.json(decoded)
    st.write(f"Issuer (iss): {decoded.get('iss')}")
    st.write(f"Tenant ID (tid): {decoded.get('tid')}")
    st.write(f"Audience (aud): {decoded.get('aud')}")
    st.write(f"Expiration (exp): {decoded.get('exp')}")

    # Controllo duro sull'audience (così evitiamo di perdere tempo)
    aud = decoded.get("aud")
    if aud not in ("https://cognitiveservices.azure.com", "https://ai.azure.com"):
        st.error(
            f"❌ Audience NON corretta: {aud}. "
            "Deve essere https://cognitiveservices.azure.com (o https://ai.azure.com). "
            "Stiamo richiedendo lo scope: "
            f"{SCOPE}. Verifica che sia proprio quello in uso qui sopra."
        )
        st.stop()

except Exception as e:
    st.error(f"❌ Errore autenticazione Azure AD:\n{e}")
    st.stop()

# =========================
# Client Azure OpenAI (nuova sintassi)
# =========================
try:
    client = AzureOpenAI(
        api_version=API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_ad_token=token.token,  # passiamo il Bearer AAD
    )
except Exception as e:
    st.error(f"❌ Errore creazione client AzureOpenAI:\n{e}")
    st.stop()

# =========================
# Pulsante handshake (facoltativo ma utilissimo)
# =========================
if st.button("🔎 Test handshake (GET deployments)"):
    try:
        url = f"{AZURE_OPENAI_ENDPOINT}/openai/deployments?api-version={API_VERSION}"
        headers = {"Authorization": f"Bearer {token.token}"}
        r = requests.get(url, headers=headers, timeout=15)
        st.write("Status code handshake:", r.status_code)
        try:
            st.json(r.json())
        except Exception:
            st.write(r.text)
        if r.status_code == 401:
            st.error(
                "401: token rifiutato dal servizio. "
                "Se l’audience sopra è corretta, controlla firewall/IP in uscita dell’App Service."
            )
    except Exception as e:
        st.error(f"❌ Handshake fallito:\n{e}")

# =========================
# Chat UI
# =========================
prompt = st.text_area("✏️ Scrivi la tua domanda:")

if st.button("📤 Invia"):
    if not prompt.strip():
        st.warning("⚠️ Inserisci una domanda.")
    else:
        try:
            resp = client.chat.completions.create(
                model=DEPLOYMENT_NAME,  # deve essere il NOME della tua deployment Azure
                messages=[
                    {"role": "system", "content": "Sei un assistente utile."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=500,
            )
            st.success(resp.choices[0].message.content)
        except Exception as e:
            # Mostriamo più contesto possibile
            st.error(f"❌ Errore nella chiamata API:\n{e}")
