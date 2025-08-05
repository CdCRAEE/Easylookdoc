import streamlit as st
from openai import AzureOpenAI

from azure.identity import ClientSecretCredential
import openai
import os

# Inserisci i tuoi dati reali qui:
TENANT_ID = os.getenv("AZURE_TENANT_ID", "89ae9197-afd1-4ca6-8d3e-8c63e4f3f1cd")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "754c7658-c909-4d49-8871-10c93d970018")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "kZm8Q~Ay4kRfxYKYYz4J02envFEIaQJGjq-u7cdq")

# Endpoint del tuo Azure OpenAI
AZURE_OPENAI_ENDPOINT = "https://easylookdoc-openai.openai.azure.com/"
AZURE_OPENAI_DEPLOYMENT = "gpt-4o"  # o il nome del tuo deployment
AZURE_OPENAI_API_VERSION = "2024-05-01-preview"

# Ottieni un token tramite Azure AD
credential = ClientSecretCredential(
    tenant_id=TENANT_ID,
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
)

token = credential.get_token("https://cognitiveservices.azure.com/.default")

# Configura OpenAI con il token
openai.api_type = "azure_ad"
openai.api_base = AZURE_OPENAI_ENDPOINT
openai.api_version = AZURE_OPENAI_API_VERSION
openai.api_key = token.token


st.set_page_config(page_title="Chat con il CdC RAEE")
st.title("Chat con il CdC RAEE")

# Input da utente
prompt = st.text_area("Scrivi la tua domanda:")

if st.button("Invia"):
    if prompt.strip() == "":
        st.warning("Inserisci un prompt prima di inviare.")
    else:
        try:
            # Nuova chiamata API compatibile con openai>=1.0.0

response = openai.ChatCompletion.create(
    deployment_id=AZURE_OPENAI_DEPLOYMENT,
    messages=[
        {"role": "system", "content": "Sei un assistente utile."},
        {"role": "user", "content": prompt}
    ],
    max_tokens=500,
    temperature=0.7,
)

     
            answer = response.choices[0].message.content
            st.success(answer)
        except Exception as e:
            st.error(f"Errore nella chiamata API: {e}")
