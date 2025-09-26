# streamlit-openai.py (patched v9: fixed-height chat area)
import os
import re
import html
from datetime import datetime, timezone

import streamlit as st
import streamlit.components.v1 as components

# Azure OpenAI (con AAD)
from openai import AzureOpenAI
from azure.identity import ClientSecretCredential

# Document Intelligence (Form Recognizer)
try:
    from azure.ai.formrecognizer import DocumentAnalysisClient
    from azure.core.credentials import AzureKeyCredential
    HAVE_FORMRECOGNIZER = True
except Exception:
    HAVE_FORMRECOGNIZER = False

# -----------------------
# STATE INIT
# -----------------------
if "doc_ready" not in st.session_state:
    st.session_state["doc_ready"] = False
if "document_text" not in st.session_state:
    st.session_state["document_text"] = ""
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []  # {role, content, ts}

# -----------------------
# HELPERS
# -----------------------
def clean_markdown_fences(text: str) -> str:
    """
    Rimuove i riquadri di codice Markdown:
    - ```lang ... ```
    - ~~~lang ... ~~~
    """
    if not text:
        return ""
    t = text.replace("\r\n", "\n")
    t = re.sub(r"```[a-zA-Z0-9_-]*\n([\s\S]*?)```", r"\1", t)
    t = re.sub(r"~~~[a-zA-Z0-9_-]*\n([\s\S]*?)~~~", r"\1", t)
    t = t.replace("```", "").replace("~~~", "")
    return t.strip()

def local_iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()

# -----------------------
# PAGE + LOGO
# -----------------------
st.set_page_config(page_title="EasyLook.DOC Chat", page_icon="📝", layout="wide")

# Full-width container override
st.markdown("""
<style>
.block-container {max-width: 100% !important; padding-left: 1rem; padding-right: 1rem;}
main .block-container, [data-testid="block-container"] {max-width: 100% !important;}
</style>
""", unsafe_allow_html=True)

try:
    st.image("images/Nuovo_Logo.png", width=250)
except Exception:
    pass
st.title("EasyLook.DOC")

# -----------------------
# STEP 1: estrazione testo
# -----------------------
st.subheader("📄 Step 1 · Scegli il documento")

if not HAVE_FORMRECOGNIZER:
    st.warning("Installa azure-ai-formrecognizer>=3.3.0")
else:
    file_name = st.text_input("Nome file nel container (es. 'contratto1.pdf')")

    def build_blob_sas_url(container_sas_url: str, blob_name: str) -> str:
        if not container_sas_url or "?" not in container_sas_url:
            return ""
        base, qs = container_sas_url.split("?", 1)
        base = base.rstrip("/")
        return f"{base}/{blob_name}?{qs}"

    cols_step1 = st.columns([1,1,6])
    with cols_step1[0]:
        read_clicked = st.button("🔎 Leggi documento")
    with cols_step1[1]:
        if st.button("🔁 Cambia/Reset documento"):
            st.session_state["document_text"] = ""
            st.session_state["chat_history"] = []
            st.session_state["doc_ready"] = False
            st.experimental_rerun() if hasattr(st, "experimental_rerun") else st.rerun()

    if read_clicked:
        AZURE_DOCINT_ENDPOINT = os.getenv("AZURE_DOCINT_ENDPOINT")
        AZURE_DOCINT_KEY = os.getenv("AZURE_DOCINT_KEY")
        AZURE_BLOB_CONTAINER_SAS_URL = os.getenv("AZURE_BLOB_CONTAINER_SAS_URL")

        if not (AZURE_DOCINT_ENDPOINT and (AZURE_DOCINT_KEY or os.getenv("AZURE_TENANT_ID")) and AZURE_BLOB_CONTAINER_SAS_URL and file_name):
            st.error("Completa le variabili e inserisci il nome file.")
        else:
            try:
                blob_url = build_blob_sas_url(AZURE_BLOB_CONTAINER_SAS_URL, file_name)

                # Client Document Intelligence
                if AZURE_DOCINT_KEY:
                    di_client = DocumentAnalysisClient(
                        endpoint=AZURE_DOCINT_ENDPOINT,
                        credential=AzureKeyCredential(AZURE_DOCINT_KEY)
                    )
                else:
                    TENANT_ID = os.getenv("AZURE_TENANT_ID")
                    CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
                    CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
                    di_client = DocumentAnalysisClient(
                        endpoint=AZURE_DOCINT_ENDPOINT,
                        credential=ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
                    )

                poller = di_client.begin_analyze_document_from_url(
                    model_id="prebuilt-read",
                    document_url=blob_url
                )
                result = poller.result()

                # Prefer contenuto aggregato se disponibile
                full_text = ""
                if hasattr(result, "content") and result.content:
                    full_text = result.content.strip()

                # Fallback a contenuto per pagina
                if not full_text and hasattr(result, "pages"):
                    pages_text = []
                    for page in result.pages:
                        if hasattr(page, "content") and page.content:
                            pages_text.append(page.content)
                    full_text = "\n\n".join(pages_text).strip()

                # Fallback a linee (retro-compatibilità)
                if not full_text and hasattr(result, "pages"):
                    all_lines = []
                    for page in result.pages:
                        for line in getattr(page, "lines", []) or []:
                            all_lines.append(line.content)
                    full_text = "\n".join(all_lines).strip()

                if full_text:
                    st.success("✅ Testo estratto correttamente!")
                    st.text_area("Anteprima testo (~4000 caratteri):", full_text[:4000], height=300)
                    st.session_state["document_text"] = full_text
                    st.session_state["chat_history"] = []  # reset chat quando cambi documento
                    st.session_state["doc_ready"] = True   # abilita Step 2
                else:
                    st.warning("Nessun testo estratto. Verifica file o SAS.")
                    st.session_state["doc_ready"] = False

            except Exception as e:
                st.error(f"Errore durante l'analisi del documento: {e}")
                st.session_state["doc_ready"] = False

# -----------------------
# (Lazy) init Azure OpenAI solo quando serve
# -----------------------
def get_aoai_client():
    TENANT_ID = os.getenv("AZURE_TENANT_ID")
    CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
    CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
    AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
    DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")

    if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET, AZURE_OPENAI_ENDPOINT, DEPLOYMENT_NAME]):
        st.error("Config OpenAI mancante: verifica le variabili d'ambiente richieste.")
        st.stop()

    credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
    aad_token = credential.get_token("https://cognitiveservices.azure.com/.default").token
    client = AzureOpenAI(api_version=API_VERSION, azure_endpoint=AZURE_OPENAI_ENDPOINT, azure_ad_token=aad_token)
    return client, DEPLOYMENT_NAME

# -----------------------
# Rendering bolle (FULL-BLEED + 85%) con area fissa a scorrimento
# -----------------------
CHAT_CSS = (
    "<style>"
    "html,body,#root{height:100%;margin:0;padding:0;}"
    ".full-bleed{width:100vw;position:relative;left:50%;right:50%;margin-left:-50vw;margin-right:-50vw;}"
    ".chat-outer{width:100%;height:100%;}"
    ".chat-wrapper{width:100%;max-width:none;margin:10px 0;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;}"
    ".message-row{display:flex;margin:6px 8px;}"
    ".bubble{padding:10px 14px;border-radius:18px;max-width:85%;box-shadow:0 1px 0 rgba(0,0,0,0.06);line-height:1.4;white-space:pre-wrap;word-wrap:break-word;}"
    ".user{margin-left:auto;background:linear-gradient(180deg,#DCF8C6,#CFF2B7);text-align:left;border-bottom-right-radius:4px;}"
    ".assistant{margin-right:auto;background:#ffffff;border:1px solid #e6e6e6;text-align:left;border-bottom-left-radius:4px;}"
    ".meta{font-size:11px;color:#888;margin-top:4px;}"
    ".typing{font-style:italic;opacity:.9;}"
    ".container-box{padding:12px;border-radius:8px;background:#f7f7f8;}"
    "#scroll{height:100%;overflow:auto;overflow-x:hidden;padding-right:6px;}"
    "</style>"
)

AUTO_SCROLL_JS = (
    "<script>"
    "try{"
    "const go=()=>{const sc=document.getElementById('scroll');if(sc){sc.scrollTop=sc.scrollHeight;}};"
    "go();"
    "const obs=new MutationObserver(()=>go());"
    "obs.observe(document.body,{childList:true,subtree:true,characterData:true});"
    "}catch(e){}"
    "</script>"
)

# Altezza fissa configurabile
CHAT_HEIGHT_PX = int(os.getenv("CHAT_HEIGHT_PX", "640"))

def render_chat_html(history: list, show_typing: bool=False) -> str:
    parts = [
        CHAT_CSS,
        '<div class="full-bleed"><div class="chat-outer"><div id="scroll"><div class="chat-wrapper container-box">'
    ]
    for m in history:
        role = m.get("role", "")
        content = clean_markdown_fences(m.get("content", ""))
        content = html.escape(content)
        ts_iso = m.get("ts", "")
        try:
            ts_view = datetime.fromisoformat(ts_iso).strftime("%d/%m/%Y %H:%M")
        except Exception:
            ts_view = ts_iso
        bubble_class = "user" if role == "user" else "assistant"
        who = "Tu" if role == "user" else "Assistente"
        parts.append('<div class="message-row">')
        parts.append(f'<div class="bubble {bubble_class}">{content}<div class="meta">{who} · {ts_view}</div></div>')
        parts.append('</div>')
    if show_typing:
        parts.append('<div class="message-row"><div class="bubble assistant typing">Sta scrivendo…</div></div>')
    parts.append('</div></div></div>')  # end wrapper + scroll + full-bleed
    parts.append(AUTO_SCROLL_JS)
    return "".join(parts)

def render_chat(placeholder, history, show_typing=False, height=CHAT_HEIGHT_PX):
    html_str = render_chat_html(history, show_typing=show_typing)
    placeholder.empty()
    with placeholder:
        components.html(html_str, height=height, scrolling=False)

# -----------------------
# STEP 2: chat (visibile SOLO quando doc_ready=True)
# -----------------------
if st.session_state.get("doc_ready", False):
    st.subheader("💬 Step 2 · Fai la tua ricerca (altezza fissa con scorrimento)")

    chat_placeholder = st.empty()
    render_chat(chat_placeholder, st.session_state["chat_history"], show_typing=False)

    # Composer in stile chat (senza bottone, field nativo streamlit)
    user_prompt = st.chat_input("Scrivi un messaggio…")  # <- interfaccia tipo chat
    if user_prompt:
        ts = local_iso_now()
        st.session_state["chat_history"].append({
            "role": "user",
            "content": clean_markdown_fences(user_prompt),
            "ts": ts
        })

        # mostra 'sta scrivendo…'
        render_chat(chat_placeholder, st.session_state["chat_history"], show_typing=True)

        # Lazy init client solo quando serve
        client, DEPLOYMENT_NAME = get_aoai_client()

        # Prepara messaggi
        CONTEXT_CHAR_LIMIT = 12000
        ASSISTANT_SYSTEM_INSTRUCTION = "Sei un assistente che risponde SOLO sulla base del documento fornito."

        def build_messages_for_api(document_text: str, history: list):
            messages = [{"role": "system", "content": ASSISTANT_SYSTEM_INSTRUCTION}]
            document_text = st.session_state.get("document_text", "")
            if document_text:
                doc_content = document_text
                if len(doc_content) > CONTEXT_CHAR_LIMIT:
                    doc_content = "(---Documento troncato - mostra l'ultima parte---)
" + doc_content[-CONTEXT_CHAR_LIMIT:]
                messages.append({"role": "system", "content": f"Contenuto documento:
{doc_content}"})
            # include history (pulita)
            for m in history:
                messages.append({"role": m["role"], "content": clean_markdown_fences(m["content"]) })
            return messages

        api_messages = build_messages_for_api(st.session_state.get("document_text", ""), st.session_state["chat_history"])

        # Streaming con aggiornamento progressivo della bolla assistente
        partial = ""
        ts2 = local_iso_now()
        try:
            stream = client.chat.completions.create(
                model=DEPLOYMENT_NAME,
                messages=api_messages,
                temperature=0.3,
                max_tokens=600,
                stream=True
            )
            for chunk in stream:
                try:
                    choices = getattr(chunk, "choices", [])
                    if choices:
                        delta = getattr(choices[0], "delta", None)
                        if delta and getattr(delta, "content", None):
                            piece = delta.content
                            partial += piece
                            temp_history = st.session_state["chat_history"] + [{"role": "assistant", "content": partial, "ts": ts2}]
                            render_chat(chat_placeholder, temp_history, show_typing=False)
                except Exception:
                    pass

            final = clean_markdown_fences(partial)
            st.session_state["chat_history"].append({"role": "assistant", "content": final, "ts": ts2})
            render_chat(chat_placeholder, st.session_state["chat_history"], show_typing=False)

        except Exception as api_err:
            render_chat(chat_placeholder, st.session_state["chat_history"], show_typing=False)
            st.error(f"❌ Errore nella chiamata API (streaming): {api_err}")

    cols = st.columns([1, 6, 1])
    with cols[0]:
        if st.button("🧹 Reset chat"):
            st.session_state["chat_history"] = []
            st.rerun()
    with cols[2]:
        st.caption("Sessione locale al browser")

else:
    # Step 2 completamente nascosto fin dall'inizio
    st.info("➡️ Completa lo Step 1 (estrai un documento) per attivare la chat.")
