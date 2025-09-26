# easylook_doc_chat_integrated.py
import os
import re
import html
from datetime import datetime, timezone

import streamlit as st
import streamlit.components.v1 as components

from openai import AzureOpenAI
from azure.identity import ClientSecretCredential

try:
    from azure.ai.formrecognizer import DocumentAnalysisClient
    from azure.core.credentials import AzureKeyCredential
    HAVE_FORMRECOGNIZER = True
except Exception:
    HAVE_FORMRECOGNIZER = False

if "doc_ready" not in st.session_state:
    st.session_state["doc_ready"] = False
if "document_text" not in st.session_state:
    st.session_state["document_text"] = ""
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []
if "file_name" not in st.session_state:
    st.session_state["file_name"] = ""

def clean_markdown_fences(text: str) -> str:
    if not text: return ""
    t = text.replace("\r\n","\n")
    t = re.sub(r"```[a-zA-Z0-9_-]*\n([\s\S]*?)```", r"\1", t)
    t = re.sub(r"~~~[a-zA-Z0-9_-]*\n([\s\S]*?)~~~", r"\1", t)
    t = t.replace("```","").replace("~~~","")
    return t.strip()

def local_iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()

st.set_page_config(page_title="EasyLook.DOC", page_icon="💬", layout="wide")
PRIMARY = "#2a7fa9"; ACCENT = "#e6df63"; SECONDARY = "#0aa1c0"

st.markdown(f"""
<style>
:root {{
  --brand-primary: {PRIMARY};
  --brand-accent: {ACCENT};
  --brand-secondary: {SECONDARY};
  --bg: #f7f7f8;
}}
html, body, [data-testid=stAppViewContainer] {{ background: var(--bg); }}
.block-container {{max-width: 100% !important; padding-left: 1rem; padding-right: 1rem;}}
.menu-card {{ background:white; border:1px solid #eee; border-radius:14px; padding:14px; }}
.right-card {{ background:white; border:1px solid #eee; border-radius:14px; padding:14px; }}
.logo-title {{ font-size: 26px; font-weight: 800; color: var(--brand-primary); letter-spacing: .2px; }}
.badge {{ font-size: 12px; background: linear-gradient(90deg, var(--brand-accent), var(--brand-secondary)); color:white; padding: 3px 8px; border-radius: 999px; }}
.nav a {{ text-decoration:none; color:#334; padding:10px 12px; border-radius:10px; display:block; }}
.nav a:hover {{ background:#f0f2f6; }}
.nav a.active {{ background: linear-gradient(90deg, var(--brand-accent)10%, #fff 100%); border:1px solid #e8f1ff; }}
.kpi .card {{ background:#fcfdff; border:1px solid #eef2f8; border-radius:12px; padding:10px; }}
.stElement iframe, iframe[title="streamlit.components.v1.html"] {{ width: 100% !important; display:block; }}
.chat-wrapper {{width:100%;max-width:100%;margin:0;box-sizing:border-box; font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;}}
.container-box{{width:100%;max-width:100%;padding:12px;border-radius:8px;background:#f7f7f8;box-sizing:border-box;}}
.message-row{{display:flex;margin:6px 8px;}}
.bubble{{padding:10px 14px;border-radius:18px;max-width:85%;box-shadow:0 1px 0 rgba(0,0,0,0.06);line-height:1.4;white-space:pre-wrap;word-wrap:break-word;}}
.user{{margin-left:auto;background:#e8f8d8;border:1px solid #d5efc6;text-align:left;border-bottom-right-radius:4px;}}
.assistant{{margin-right:auto;background:#ffffff;border:1px solid #e6e6e6;text-align:left;border-bottom-left-radius:4px;}}
.meta{{font-size:11px;color:#888;margin-top:4px;}}
.typing{{font-style:italic;opacity:.9;}}
#scroll{{height:100%;overflow:auto;overflow-x:hidden;padding-right:6px;width:100%;box-sizing:border-box;}}
</style>
""", unsafe_allow_html=True)

def build_blob_sas_url(container_sas_url: str, blob_name: str) -> str:
    if not container_sas_url or "?" not in container_sas_url: return ""
    base, qs = container_sas_url.split("?", 1)
    base = base.rstrip("/")
    return f"{base}/{blob_name}?{qs}"

def get_aoai_client():
    TENANT_ID = os.getenv("AZURE_TENANT_ID")
    CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
    CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
    AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
    DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")
    if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET, AZURE_OPENAI_ENDPOINT, DEPLOYMENT_NAME]):
        st.error("Config OpenAI mancante: verifica le variabili d'ambiente richieste."); st.stop()
    credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
    aad_token = credential.get_token("https://cognitiveservices.azure.com/.default").token
    client = AzureOpenAI(api_version=API_VERSION, azure_endpoint=AZURE_OPENAI_ENDPOINT, azure_ad_token=aad_token)
    return client, DEPLOYMENT_NAME

AUTO_SCROLL_JS = (
    "<script>"
    "try{"
    "const sc = document.getElementById('scroll');"
    "const needOverflow = ()=> sc && (sc.scrollHeight - sc.clientHeight) > 4;"
    "const nearBottom = ()=> sc && needOverflow() && (sc.scrollTop >= (sc.scrollHeight - sc.clientHeight - 120));"
    "let stick = nearBottom();"
    "const obs = new MutationObserver(()=>{"
    "  if (!sc) return;"
    "  if (stick && needOverflow()) { sc.scrollTop = sc.scrollHeight; }"
    "  stick = nearBottom();"
    "});"
    "obs.observe(sc || document.body, {childList:true,subtree:true,characterData:true});"
    "}catch(e){}"
    "</script>"
)

def render_chat_html(history, show_typing=False):
    parts = ['<div class="chat-wrapper"><div id="scroll"><div class="container-box">']
    for m in history:
        role = m.get("role",""); content = clean_markdown_fences(m.get("content","")); content = html.escape(content)
        ts_iso = m.get("ts","")
        try: ts_view = datetime.fromisoformat(ts_iso).strftime("%d/%m/%Y %H:%M")
        except Exception: ts_view = ts_iso
        bubble_class = "user" if role=="user" else "assistant"; who = "Tu" if role=="user" else "Assistente"
        parts.append('<div class="message-row">')
        parts.append(f'<div class="bubble {bubble_class}">{content}<div class="meta">{who} · {ts_view}</div></div>')
        parts.append('</div>')
    if show_typing: parts.append('<div class="message-row"><div class="bubble assistant typing">Sta scrivendo…</div></div>')
    parts.append('</div></div></div>'); parts.append(AUTO_SCROLL_JS); return "".join(parts)

def render_chat(placeholder, history, show_typing=False, height=560):
    html_str = render_chat_html(history, show_typing=show_typing)
    placeholder.empty(); 
    with placeholder: components.html(html_str, height=height, scrolling=False)

left, right = st.columns([1,3], gap="large")

with left:
    st.markdown('<div class="menu-card">', unsafe_allow_html=True)
    try:
        st.image("images/Nuovo_Logo.png", width=180)
    except Exception:
        st.write("")
    st.markdown('<div class="logo-title">EasyLook.<span class="badge">doc</span></div>', unsafe_allow_html=True)
    st.markdown('<div class="nav">', unsafe_allow_html=True)
    st.markdown('<a class="active">📄 Documenti</a>', unsafe_allow_html=True)
    st.markdown('<a>🔎 Estrazione</a>', unsafe_allow_html=True)
    st.markdown('<a>💬 Chat</a>', unsafe_allow_html=True)
    st.markdown('<a>🕓 Cronologia</a>', unsafe_allow_html=True)
    st.markdown('<a>⚙️ Impostazioni</a>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="kpi">', unsafe_allow_html=True)
    doc_name = st.session_state.get("file_name") or "Nessun file"
    status = "Estratto ✅" if st.session_state.get("doc_ready") else "Da estrarre"
    c1, c2 = st.columns(2)
    with c1: st.markdown(f'<div class="card"><div class="tag">Documento</div><div><b>{doc_name}</b></div></div>', unsafe_allow_html=True)
    with c2: st.markdown(f'<div class="card"><div class="tag">Stato</div><div>{status}</div></div>', unsafe_allow_html=True)
    c3, c4 = st.columns(2)
    with c3: st.markdown(f'<div class="card"><div class="tag">Pagine</div><div>-</div></div>', unsafe_allow_html=True)
    with c4: st.markdown(f'<div class="card"><div class="tag">Ultima mod.</div><div>{datetime.now().strftime("%d/%m/%Y %H:%M")}</div></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

with right:
    st.markdown('<div class="right-card">', unsafe_allow_html=True)
    st.subheader("📄 Step 1 · Scegli il documento")
    if not HAVE_FORMRECOGNIZER:
        st.warning("Installa azure-ai-formrecognizer>=3.3.0")
    else:
        st.session_state["file_name"] = st.text_input("Nome file nel container (es. 'contratto1.pdf')", st.session_state.get("file_name",""))
        c1, c2 = st.columns(2)
        with c1: read_clicked = st.button("🔎 Leggi documento")
        with c2:
            if st.button("🔁 Cambia/Reset documento"):
                st.session_state["document_text"] = ""; st.session_state["chat_history"] = []; st.session_state["doc_ready"]=False; st.session_state["file_name"]=""; st.rerun()

        if read_clicked:
            AZURE_DOCINT_ENDPOINT = os.getenv("AZURE_DOCINT_ENDPOINT"); AZURE_DOCINT_KEY = os.getenv("AZURE_DOCINT_KEY"); AZURE_BLOB_CONTAINER_SAS_URL = os.getenv("AZURE_BLOB_CONTAINER_SAS_URL")
            file_name = st.session_state.get("file_name")
            if not (AZURE_DOCINT_ENDPOINT and (AZURE_DOCINT_KEY or os.getenv("AZURE_TENANT_ID")) and AZURE_BLOB_CONTAINER_SAS_URL and file_name):
                st.error("Completa le variabili e inserisci il nome file.")
            else:
                try:
                    def build_blob_sas_url(container_sas_url: str, blob_name: str) -> str:
                        if not container_sas_url or "?" not in container_sas_url: return ""
                        base, qs = container_sas_url.split("?", 1); base = base.rstrip("/")
                        return f"{base}/{blob_name}?{qs}"
                    blob_url = build_blob_sas_url(AZURE_BLOB_CONTAINER_SAS_URL, file_name)
                    if AZURE_DOCINT_KEY:
                        di_client = DocumentAnalysisClient(endpoint=AZURE_DOCINT_ENDPOINT, credential=AzureKeyCredential(AZURE_DOCINT_KEY))
                    else:
                        TENANT_ID = os.getenv("AZURE_TENANT_ID"); CLIENT_ID = os.getenv("AZURE_CLIENT_ID"); CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
                        di_client = DocumentAnalysisClient(endpoint=AZURE_DOCINT_ENDPOINT, credential=ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET))
                    poller = di_client.begin_analyze_document_from_url(model_id="prebuilt-read", document_url=blob_url); result = poller.result()
                    full_text = ""
                    if hasattr(result,"content") and result.content: full_text = result.content.strip()
                    if not full_text and hasattr(result,"pages"):
                        pages_text=[]; 
                        for p in result.pages:
                            if hasattr(p,"content") and p.content: pages_text.append(p.content)
                        full_text = "\n\n".join(pages_text).strip()
                    if not full_text and hasattr(result,"pages"):
                        all_lines=[]; 
                        for p in result.pages:
                            for line in getattr(p,"lines",[]) or []: all_lines.append(line.content)
                        full_text = "\n".join(all_lines).strip()
                    if full_text:
                        st.success("✅ Testo estratto correttamente!"); st.text_area("Anteprima testo (~4000 caratteri):", full_text[:4000], height=220)
                        st.session_state["document_text"]=full_text; st.session_state["chat_history"]=[]; st.session_state["doc_ready"]=True
                    else:
                        st.warning("Nessun testo estratto. Verifica file o SAS."); st.session_state["doc_ready"]=False
                except Exception as e:
                    st.error(f"Errore durante l'analisi del documento: {e}"); st.session_state["doc_ready"]=False

    if st.session_state.get("doc_ready", False):
        st.subheader("💬 Step 2 · Chat sul documento")
        chat_placeholder = st.empty()
        render_chat(chat_placeholder, st.session_state["chat_history"], show_typing=False, height=560)

        user_prompt = st.chat_input("Scrivi un messaggio…")
        if user_prompt:
            ts = local_iso_now()
            st.session_state["chat_history"].append({"role":"user","content":clean_markdown_fences(user_prompt),"ts":ts})
            render_chat(chat_placeholder, st.session_state["chat_history"], show_typing=True, height=560)

            TENANT_ID = os.getenv("AZURE_TENANT_ID"); CLIENT_ID = os.getenv("AZURE_CLIENT_ID"); CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
            AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT"); DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT"); API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION","2024-05-01-preview")
            if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET, AZURE_OPENAI_ENDPOINT, DEPLOYMENT_NAME]): st.error("Config OpenAI mancante."); st.stop()
            credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET); aad_token = credential.get_token("https://cognitiveservices.azure.com/.default").token
            client = AzureOpenAI(api_version=API_VERSION, azure_endpoint=AZURE_OPENAI_ENDPOINT, azure_ad_token=aad_token)

            CONTEXT_CHAR_LIMIT = 12000; ASSISTANT_SYSTEM_INSTRUCTION = "Sei un assistente che risponde SOLO sulla base del documento fornito."; TRUNCATION_BANNER="(---Documento troncato - mostra l'ultima parte---)\n"
            def build_messages_for_api(document_text: str, history: list):
                messages=[{"role":"system","content":ASSISTANT_SYSTEM_INSTRUCTION}]
                document_text = st.session_state.get("document_text","")
                if document_text:
                    doc_content = document_text
                    if len(doc_content)>CONTEXT_CHAR_LIMIT: doc_content = TRUNCATION_BANNER + doc_content[-CONTEXT_CHAR_LIMIT:]
                    messages.append({"role":"system","content":f"Contenuto documento:\n{doc_content}"})
                for m in history: messages.append({"role":m["role"],"content":clean_markdown_fences(m["content"])})
                return messages
            api_messages = build_messages_for_api(st.session_state.get("document_text",""), st.session_state["chat_history"])

            partial=""; ts2 = local_iso_now()
            try:
                stream = client.chat.completions.create(model=DEPLOYMENT_NAME, messages=api_messages, temperature=0.3, max_tokens=600, stream=True)
                for chunk in stream:
                    try:
                        choices = getattr(chunk,"choices",[])
                        if choices:
                            delta = getattr(choices[0],"delta",None)
                            if delta and getattr(delta,"content",None):
                                piece = delta.content; partial += piece
                                temp_history = st.session_state["chat_history"] + [{"role":"assistant","content":partial,"ts":ts2}]
                                render_chat(chat_placeholder, temp_history, show_typing=False, height=560)
                    except Exception: pass
                final = clean_markdown_fences(partial); st.session_state["chat_history"].append({"role":"assistant","content":final,"ts":ts2})
                render_chat(chat_placeholder, st.session_state["chat_history"], show_typing=False, height=560)
            except Exception as api_err:
                render_chat(chat_placeholder, st.session_state["chat_history"], show_typing=False, height=560); st.error(f"❌ Errore nella chiamata API (streaming): {api_err}")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("🧹 Reset chat"): st.session_state["chat_history"]=[]; st.rerun()
        with c2: st.caption("Sessione locale al browser")
    else:
        st.info("➡️ Completa lo Step 1 per attivare la chat.")
    st.markdown('</div>', unsafe_allow_html=True)
