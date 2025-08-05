import streamlit as st
from openai import AzureOpenAI

# Inserisci i tuoi dati reali qui:
AZURE_OPENAI_ENDPOINT = "https://easylookdoc-openai.openai.azure.com/"
AZURE_OPENAI_KEY = "DWzOqzIuJFKMRcfimbsydMe5nYelzbMeco4ODcPiknmqDdlwCVTFJQQJ99BGACYeBjFXJ3w3AAABACOGmisq"
DEPLOYMENT_NAME = "gpt-4o"

# Client Azure OpenAI con nuova sintassi
client = AzureOpenAI(
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_key=AZURE_OPENAI_KEY,
    api_version="2023-05-15"
)

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
            response = client.chat.completions.create(
                model=DEPLOYMENT_NAME,
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
