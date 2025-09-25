# streamlit_app_with_retrieval.py
import os
import math
import numpy as np
import streamlit as st
from datetime import datetime, timezone
from typing import List, Dict

# OpenAI (Azure)
from openai import AzureOpenAI

# AAD per token
from azure.identity import ClientSecretCredential

# Document Intelligence (come prima)
try:
    from azure.ai.formrecognizer import DocumentAnalysisClient
    from azure.core.credentials import AzureKeyCredential
    HAVE_FORMRECOGNIZER = True
except Exception:
    HAVE_FORMRECOGNIZER = False

# -----------------------
# PAGE
# -----------------------
st.set_page_config(page_title="EasyLook.DOC Chat (RAG)", page_icon="📝")
st.image("images/Nuovo_Logo.png", width=250)
st.title("EasyLook.DOC — Chat con Retrieval (chunking)")

# -----------------------
# CONFIG
# -----------------------
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT")  # chat/completion model
API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")
# embedding model / deployment (separato se lo hai)
EMBEDDING_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", DEPLOYMENT_NAME)

AZURE_DOCINT_ENDPOINT = os.getenv("AZURE_DOCINT_ENDPOINT")
AZURE_DOCINT_KEY = os.getenv("AZURE_DOCINT_KEY")
AZURE_BLOB_CONTAINER_SAS_URL = os.getenv("AZURE_BLOB_CONTAINER_SAS_URL")

# -----------------------
# AUTH: AAD token per AzureOpenAI
# -----------------------
try:
    credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
    token = credential.get_token("https://cognitiveservices.azure.com/.default")
except Exception as e:
    st.error(f"Errore ottenimento token AAD per OpenAI: {e}")
    st.stop()

try:
    client = AzureOpenAI(
        api_version=API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=token.token,
    )
except Exception as e:
    st.error(f"Errore inizializzazione AzureOpenAI: {e}")
    st.stop()

# -----------------------
# Helpers per chunking + embeddings + retrieval
# -----------------------
def chunk_text(text: str, chunk_size: int = 2000, overlap: int = 200) -> List[Dict]:
    """
    Divide il testo in chunk con overlap. Restituisce lista di dict
    [{'id': idx, 'text': chunk_text}, ...]
    chunk_size e overlap in caratteri (non token).
    """
    if not text:
        return []
    chunks = []
    start = 0
    idx = 0
    text_len = len(text)
    while start < text_len:
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append({"id": idx, "text": chunk})
            idx += 1
        if end >= text_len:
            break
        start = end - overlap
    return chunks

def embed_texts(texts: List[str], batch_size: int = 16) -> List[List[float]]:
    """
    Usa AzureOpenAI embeddings (client.embeddings.create).
    Restituisce lista di vettori (list of floats).
    """
    # process in batches
    embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        resp = client.embeddings.create(model=EMBEDDING_DEPLOYMENT, input=batch)
        # resp.data è una lista con .embedding
        for item in resp.data:
            embeddings.append(item.embedding)
    return embeddings

def cosine_similarity_matrix(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """
    query_vec: (d,), matrix: (n,d) -> restituisce array (n,) di similarità coseno
    """
    # evitare divisione per zero
    q_norm = np.linalg.norm(query_vec)
    m_norms = np.linalg.norm(matrix, axis=1)
    # se qualche norma è zero, sostituiscila con eps
    eps = 1e-8
    m_norms = np.where(m_norms == 0, eps, m_norms)
    q_norm = q_norm if q_norm != 0 else eps
    sims = np.dot(matrix, query_vec) / (m_norms * q_norm)
    return sims

def build_index_from_document(doc_text: str, chunk_size: int = 2000, overlap: int = 200):
    """
    Genera i chunk, calcola embeddings e salva in session_state:
    st.session_state['doc_index'] = {
        'chunks': [{'id', 'text', 'embedding': list[float]}...],
        'matrix': np.array([...])  # shape (n,d)
    }
    """
    chunks = chunk_text(doc_text, chunk_size=chunk_size, overlap=overlap)
    if not chunks:
        return None
    texts = [c["text"] for c in chunks]
    with st.spinner("Calcolo embeddings per i chunk (potrebbe volerci qualche secondo)..."):
        embeds = embed_texts(texts)
    # salva embedding per chunk
    for c, e in zip(chunks, embeds):
        c["embedding"] = e
    matrix = np.array(embeds, dtype=np.float32)
    st.session_state["doc_index"] = {"chunks": chunks, "matrix": matrix}
    return st.session_state["doc_index"]

def retrieve_chunks(query: str, top_k: int = 5) -> List[Dict]:
    """
    Dato query, calcola embedding e ritorna top_k chunk ordinati per similarità (desc).
    """
    idx = st.session_state.get("doc_index")
    if not idx:
        return []
    # embedding query
    q_emb = embed_texts([query])[0]
    q_vec = np.array(q_emb, dtype=np.float32)
    sims = cosine_similarity_matrix(q_vec, idx["matrix"])
    # top_k indices
    top_k = min(top_k, len(sims))
    top_idx = np.argsort(-sims)[:top_k]
    results = []
    for i in top_idx:
        chunk = idx["chunks"][int(i)]
        results.append({"id": chunk["id"], "text": chunk["text"], "score": float(sims[int(i)])})
    return results

# -----------------------
# STEP 1: estrazione da Blob (mantieni la tua logica)
# -----------------------
st.subheader("📄 Step 1 · Estrai testo da Blob")

if not HAVE_FORMRECOGNIZER:
    st.warning("Installa azure-ai-formrecognizer>=3.3.0 per usare l'estrazione da PDF/immagini.")
else:
    file_name = st.text_input("Nome file nel container (es. 'contratto1.pdf')", key="file_name_rag")

    def build_blob_sas_url(container_sas_url: str, blob_name: str) -> str:
        if "?" not in container_sas_url:
            return ""
        base, qs = container_sas_url.split("?", 1)
        base = base.rstrip("/")
        return f"{base}/{blob_name}?{qs}"

    if st.button("🔎 Estrai testo"):
        if not (AZURE_DOCINT_ENDPOINT and (AZURE_DOCINT_KEY or (TENANT_ID and CLIENT_ID and CLIENT_SECRET)) and AZURE_BLOB_CONTAINER_SAS_URL and file_name):
            st.error("Completa le variabili e inserisci il nome file.")
        else:
            try:
                blob_url = build_blob_sas_url(AZURE_BLOB_CONTAINER_SAS_URL, file_name)
                if AZURE_DOCINT_KEY:
                    di_client = DocumentAnalysisClient(
                        endpoint=AZURE_DOCINT_ENDPOINT,
                        credential=AzureKeyCredential(AZURE_DOCINT_KEY)
                    )
                else:
                    di_client = DocumentAnalysisClient(
                        endpoint=AZURE_DOCINT_ENDPOINT,
                        credential=ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
                    )
                poller = di_client.begin_analyze_document_from_url(
                    model_id="prebuilt-read",
                    document_url=blob_url
                )
                result = poller.result()

                pages_text = []
                for page in result.pages:
                    if hasattr(page, "content") and page.content:
                        pages_text.append(page.content)
                full_text = "\n\n".join(pages_text).strip()

                if not full_text:
                    all_lines = []
                    for page in result.pages:
                        for line in getattr(page, "lines", []) or []:
                            all_lines.append(line.content)
                    full_text = "\n".join(all_lines).strip()

                if full_text:
                    st.success("✅ Testo estratto correttamente!")
                    st.text_area("Anteprima testo (~4000 caratteri):", full_text[:4000], height=300)
                    st.session_state["document_text"] = full_text
                    # invalid index se documento nuovo
                    st.session_state.pop("doc_index", None)
                    st.session_state.pop("chat_history", None)
                else:
                    st.warning("Nessun testo estratto. Verifica file o SAS.")

            except Exception as e:
                st.error(f"Errore durante l'analisi del documento: {e}")

# -----------------------
# STEP 2: costruisci index (chunk+emb) e chat con retrieval
# -----------------------
st.subheader("💬 Step 2 · Costruisci indice e chat (RAG)")

# init session keys
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []  # ogni item: {"role","content","ts"}
if "doc_index" not in st.session_state:
    st.session_state["doc_index"] = None

# settings UI
st.sidebar.header("Impostazioni RAG")
chunk_size = st.sidebar.number_input("Chunk size (caratteri)", min_value=500, max_value=8000, value=2000, step=100)
overlap = st.sidebar.number_input("Overlap (caratteri)", min_value=50, max_value=2000, value=200, step=50)
top_k = st.sidebar.slider("Top-K chunks da recuperare", min_value=1, max_value=10, value=4)
context_char_limit = st.sidebar.number_input("Max chars dal contesto recuperato", min_value=2000, max_value=40000, value=12000, step=500)
sidebar_info = st.sidebar.info("Usiamo le embedding per cercare i chunk più rilevanti e li passiamo al modello come contesto.")

# Index builder
if "document_text" in st.session_state:
    st.markdown("### Stato indice")
    if st.session_state.get("doc_index") is None:
        st.warning("Indice non ancora costruito per il documento corrente.")
        if st.button("🧱 Costruisci indice (chunk + embeddings)"):
            doc = st.session_state["document_text"]
            idx = build_index_from_document(doc, chunk_size=chunk_size, overlap=overlap)
            if idx:
                st.success(f"Indice costruito con {len(idx['chunks'])} chunk.")
            else:
                st.error("Impossibile costruire indice (documento vuoto?).")
    else:
        idx = st.session_state["doc_index"]
        st.success(f"Indice pronto: {len(idx['chunks'])} chunk, embedding dim = {idx['matrix'].shape[1]}")
        if st.button("♻️ Ricostruisci indice (nuove impostazioni)"):
            doc = st.session_state["document_text"]
            idx = build_index_from_document(doc, chunk_size=chunk_size, overlap=overlap)
            st.success(f"Indice ricostruito: {len(idx['chunks'])} chunk.")
        if st.button("🧹 Cancella indice"):
            st.session_state.pop("doc_index", None)
            st.success("Indice cancellato.")

else:
    st.info("Carica ed estrai prima un documento (Step 1).")

st.markdown("---")

# Chat RAG
st.markdown("### Conversazione (RAG)")

if "document_text" not in st.session_state:
    st.info("Prima estrai un documento (Step 1) e costruisci l'indice.")
else:
    # mostra eventuale history
    if len(st.session_state["chat_history"]) == 0:
        st.info("La chat è vuota — scrivi la tua prima domanda qui sotto.")
    else:
        for m in st.session_state["chat_history"]:
            ts = m.get("ts", "")
            if m["role"] == "user":
                st.markdown(f"**Tu** ({ts}):\n> {m['content']}")
            else:
                st.markdown(f"**Assistente** ({ts}):\n{m['content']}")

    # form di invio
    with st.form(key="rag_form", clear_on_submit=True):
        user_q = st.text_input("✏️ Scrivi la tua domanda sul documento:", key="rag_user_input")
        submit = st.form_submit_button("Invia")

        if submit and user_q:
            ts_u = datetime.now(timezone.utc).astimezone().isoformat()
            st.session_state["chat_history"].append({"role": "user", "content": user_q, "ts": ts_u})

            # retrieval
            if st.session_state.get("doc_index") is None:
                st.warning("Indice non costruito — procedo a costruirlo ora (automatico).")
                # build with current UI settings
                build_index_from_document(st.session_state["document_text"], chunk_size=chunk_size, overlap=overlap)

            retrieved = retrieve_chunks(user_q, top_k=top_k)
            if not retrieved:
                st.warning("Nessun chunk recuperato; prova a ricostruire l'indice o verifica il documento.")
                st.experimental_rerun()

            # concateno il contesto dei chunk recuperati (rispetto a un limite in char)
            ctx_parts = []
            chars = 0
            for r in retrieved:
                piece = r["text"]
                if chars + len(piece) > context_char_limit:
                    # se superiamo il limite, tagliamo il pezzo rimanente
                    remaining = context_char_limit - chars
                    if remaining > 0:
                        ctx_parts.append(piece[:remaining])
                        chars += remaining
                    break
                ctx_parts.append(piece)
                chars += len(piece)
            retrieved_context = "\n\n---\n\n".join(ctx_parts)

            # costruisco i messages per l'API (system + context + history + user)
            system_instructions = [
                {"role": "system", "content": "Sei un assistente che risponde SOLO sulla base del documento fornito nel contesto. Se la risposta non è nel documento, rispondi che non ci sono informazioni sufficienti."},
                {"role": "system", "content": f"Contesto recuperato (da document):\n{retrieved_context}"}
            ]

            # costruiamo la storia: possiamo includere l'intera history o solo gli ultimi N messaggi
            # per semplicità includiamo gli ultimi 8 messaggi (utente+assistente) dalla sessione
            history_msgs = st.session_state.get("chat_history", [])
            # trasformiamo in messages compatibili con l'API (role/content)
            recent_msgs = []
            # prendi gli ultimi 8 messaggi (separati per role)
            for msg in history_msgs[-8:]:
                recent_msgs.append({"role": msg["role"], "content": msg["content"]})

            messages_for_api = system_instructions + recent_msgs + [{"role": "user", "content": user_q}]

            # chiamata API
            try:
                with st.spinner("Interrogo il modello (RAG)..."):
                    response = client.chat.completions.create(
                        model=DEPLOYMENT_NAME,
                        messages=messages_for_api,
                        temperature=0.2,
                        max_tokens=600
                    )
                assistant_text = response.choices[0].message.content
                ts_a = datetime.now(timezone.utc).astimezone().isoformat()
                st.session_state["chat_history"].append({"role": "assistant", "content": assistant_text, "ts": ts_a})

                # mostra la risposta (il rerun non è strettamente necessario qui, ma mantiene coerenza)
                st.experimental_rerun()

            except Exception as e:
                st.error(f"Errore nella chiamata API: {e}")
                # non interrompiamo la history dell'utente; permetti retry

# -----------------------
# Extra: mostra i chunk recuperati per debug (opzionale)
# -----------------------
st.markdown("---")
if st.checkbox("Mostra chunk recuperati (debug)"):
    if st.session_state.get("doc_index"):
        idx = st.session_state["doc_index"]
        st.write(f"Tot chunk: {len(idx['chunks'])}, embedding dim: {idx['matrix'].shape[1]}")
        # mostra i primi 5 chunk
        for c in idx["chunks"][:5]:
            st.markdown(f"**Chunk {c['id']}** (len={len(c['text'])}):\n\n{c['text'][:800]}...")
    else:
        st.info("Nessun indice costruito.")

