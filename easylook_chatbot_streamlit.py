
import os
import math
import numpy as np
import streamlit as st
from datetime import datetime, timezone
from typing import List, Dict

# OpenAI (Azure)
from openai import AzureOpenAI

# AAD per token
try:
    from azure.identity import ClientSecretCredential
    from azure.ai.formrecognizer import DocumentAnalysisClient
    from azure.core.credentials import AzureKeyCredential
    HAVE_AZURE = True
except ImportError:
    HAVE_AZURE = False

# -----------------------
# CONFIGURAZIONE PAGINA
# -----------------------
st.set_page_config(page_title="EasyLook.DOC Chat (RAG)", page_icon="📝", layout="wide")

# Logo e titolo
if os.path.exists("Nuovo_Logo.png"):
    st.image("Nuovo_Logo.png", width=180)
st.markdown("<h1 style='color:#003366;'>EasyLook.DOC — Chat con Retrieval</h1>", unsafe_allow_html=True)

# -----------------------
# INIZIALIZZAZIONE SESSIONE
# -----------------------
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []

# -----------------------
# INTERFACCIA CHAT
# -----------------------
st.markdown("## 💬 Conversazione")

# Mostra la cronologia della chat
for msg in st.session_state["chat_history"]:
    ts = msg.get("ts", "")
    if msg["role"] == "user":
        st.markdown(
            f"<div style='background-color:#e6f2ff;padding:10px;border-radius:10px;margin-bottom:5px;'>"
            f"<strong>Tu</strong> ({ts}):<br>{msg['content']}</div>",
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            f"<div style='background-color:#fff8dc;padding:10px;border-radius:10px;margin-bottom:5px;'>"
            f"<strong>Assistente</strong> ({ts}):<br>{msg['content']}</div>",
            unsafe_allow_html=True
        )

# Input utente e bottone
user_q = st.text_input("✏️ Scrivi la tua domanda sul documento:", key="rag_user_input")
if st.button("Invia"):
    if user_q:
        ts_u = datetime.now(timezone.utc).astimezone().isoformat()
        st.session_state["chat_history"].append({"role": "user", "content": user_q, "ts": ts_u})
        # Qui andrebbe la logica di retrieval e risposta, che manteniamo invariata nel file originale
        st.info("✅ Domanda inviata. Integra qui la logica di risposta del tuo assistente.")
