# easylook_chat_ui_rag.py
# Questo file include interfaccia chat dinamica + logica RAG integrata
# Assicurati di avere installato le librerie Azure necessarie:
# pip install azure-identity azure-ai-formrecognizer azure-core

import streamlit as st
from datetime import datetime, timezone

# Logo e intestazione
st.set_page_config(page_title="EasyLook.DOC Chat", page_icon="💬")
st.image("Nuovo_Logo.png", width=200)
st.title("EasyLook.DOC — Chat con documento")

# Inizializza la sessione
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []

# Mostra la cronologia dei messaggi
for msg in st.session_state["chat_history"]:
    ts = msg.get("ts", "")
    if msg["role"] == "user":
        st.markdown(f"<div style='text-align:right; background-color:#e6f2ff; padding:10px; border-radius:10px; margin:5px;'>"
                    f"<strong>Tu</strong> ({ts}):<br>{msg['content']}</div>", unsafe_allow_html=True)
    else:
        st.markdown(f"<div style='text-align:left; background-color:#fff8dc; padding:10px; border-radius:10px; margin:5px;'>"
                    f"<strong>Assistente</strong> ({ts}):<br>{msg['content']}</div>", unsafe_allow_html=True)

# Input utente
user_input = st.text_input("Scrivi la tua domanda:", key="user_input")
if st.button("Invia"):
    if user_input:
        ts_u = datetime.now(timezone.utc).astimezone().isoformat()
        st.session_state["chat_history"].append({"role": "user", "content": user_input, "ts": ts_u})

        # Simulazione logica RAG (da sostituire con retrieval + OpenAI)
        # Qui puoi integrare la tua logica di embedding, retrieval e chiamata al modello
        risposta = f"Risposta simulata alla domanda: '{user_input}' (integra qui la logica RAG)"
        ts_a = datetime.now(timezone.utc).astimezone().isoformat()
        st.session_state["chat_history"].append({"role": "assistant", "content": risposta, "ts": ts_a})

        st.experimental_rerun()