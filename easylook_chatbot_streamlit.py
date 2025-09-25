import os
import streamlit as st
from datetime import datetime, timezone

# OpenAI (Azure)
from openai import AzureOpenAI
import jwt

# Credenziali AAD per OpenAI
from azure.identity import ClientSecretCredential

# Document Intelligence
try:
    from azure.ai.formrecognizer import DocumentAnalysisClient
    from azure.core.credentials import AzureKeyCredential
    HAVE_FORMRECOGNIZER = True
except Exception:
    HAVE_FORMRECOGNIZER = False

# -----------------------
# LOGO E TITOLI
# -----------------------
st.set_page_config(page_title="EasyLook.DOC Chat", page_icon="📝")
st.image("images/Nuovo_Logo.png", width=250)
st.title("EasyLook.DOC")

# -----------------------
# CONFIGURAZIONE
# -----------------------
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT")
API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")

AZURE_DOCINT_ENDPOINT = os.getenv("AZURE_DOCINT_ENDPOINT")
AZURE_DOCINT_KEY = os.getenv("AZURE_DOCINT_KEY")

AZURE_BLOB_CONTAINER_SAS_URL = os.getenv("AZURE_BLOB_CONTAINER_SAS_URL")

# -----------------------
# TOKEN AAD PER OPENAI
# -----------------------
try:
    credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
    token = credential.get_token("https://cognitiveservices.azure.com/.default")
except Exception as e:
    st.error(f"Errore ottenimento token AAD per OpenAI: {e}")
    st.stop()

# -----------------------
# CLIENT AZURE OPENAI
# -----------------------
try:
    client = AzureOpenAI(
        api_version=API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=token.token  # Bearer token AAD
    )
except Exception as e:
    st.error(f"Errore inizializzazione AzureOpenAI: {e}")
    st.stop()

# -----------------------
# CSS + helper per chat stile WhatsApp
# -----------------------
CHAT_CSS = """
<style>
/* container */
.chat-window {
  max-width: 900px;
  margin: 0 auto 12px auto;
  background: #ffffff;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 2px 6px rgba(0,0,0,0.06);
  height: 60vh;
  overflow-y: auto;
}
/* rows */
.row { display: flex; flex-direction: column; margin-bottom: 8px; }
/* user (right) */
.row.right { align-items: flex-end; }
/* assistant (left) */
.row.left { align-items: flex-start; }
/* bubble */
.msg { padding: 10px 14px; border-radius: 18px; display: inline-block; max-width: 78%; word-wrap: break-word; line-height: 1.3; }
/* user style */
.msg.user { background: #DCF8C6; color: #000; border-bottom-right-radius: 4px; }
/* assistant style */
.msg.assistant { background: #ffffff; color: #000; border: 1px solid #e6e6e6; border-bottom-left-radius: 4px; }
/* meta timestamp */
.meta { font-size: 11px; color: #666; margin-top: 4px; }
/* input row */
.input-row { display:flex; gap:8px; margin-top:12px; max-width:900px; margin-left:auto; margin-right:auto; }
input[type="te]()
