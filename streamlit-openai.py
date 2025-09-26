# easylook_verticalnav_integrated.py
# EasyLook.DOC • Vertical Nav Integrated App
# - Left sidebar: logo + vertical menu (Documenti, Estrazione, Chat, Cronologia, Impostazioni)
# - Right: panels for Estrazione (Step 1) and Chat (Step 2)
# - Chat: bolle 85%, autoscroll smart, "sta scrivendo…", streaming Azure OpenAI
# - Estrazione: Azure Document Intelligence (prebuilt-read) da Blob SAS
# - Brand UI (blu/giallo/ciano), nessun rosso

import os, re, html
from datetime import datetime, timezone
import streamlit as st
import streamlit.components.v1 as components

# ---------- Map secrets -> env (utile su Streamlit Cloud) ----------
try:
    for k, v in st.secrets.items():
        os.environ.setdefault(k, str(v))
except Exception:
    pass

# ---------- Azure SDK ----------
from openai import AzureOpenAI
from azure.identity import ClientSecretCredential

try:
    from azure.ai.formrecognizer import DocumentAnalysisClient
    from azure.core.credentials import AzureKeyCredential
    HAVE_FORMRECOGNIZER = True
except Exception:
    HAVE_FORMRECOGNIZER = False

# ---------- Session State ----------
ss = st.session_state
ss.setdefault("doc_ready", False)
ss.setdefault("document_text", "")
ss.setdefault("chat_history", [])  # list of {role, content, ts}
ss.setdefault("file_name", "")
ss.setdefault("nav", "Estrazione")  # default section

# ---------- Helpers ----------
def clean_markdown_fences(t: str) -> str:
    """Rimuove i blocchi di codice markdown (``` e ~~~) e restituisce testo pulito."""
    if not t:
        return ""
    t = t.replace("\r\n", "\n")
    t = re.sub(r"```[a-zA-Z0-9_-]*\n([\s\S]*?)```", r"\1", t)
    t = re.sub(r"~~~[a-zA-Z0-9_-]*\n([\s\S]*?)~~~", r"\1", t)
    return t.replace("```", "").replace("~~~", "").strip()

def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()

def build_blob_sas_url(container_sas_url: str, blob_name: str) -> str:
    if not container_sas_url or "?" not in container_sas_url:
        return ""
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
        st.error("Config OpenAI mancante: verifica le variabili d'ambiente richieste.")
        st.stop()
    cred = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
    aad_token = cred.get_token("https://cognitiveservices.azure.com/.default").token
    client = AzureOpenAI(api_version=API_VERSION, azure_endpoint=AZURE_OPENAI_ENDPOINT, azure_ad_token=aad_token)
    return client, DEPLOYMENT_NAME

# ---------- Page & Brand ----------
st.set_page_config(page_title="EasyLook.DOC", page_icon="💬", layout="wide")
PRIMARY=os.getenv("BRAND_PRIMARY","#2a7fa9")
ACCENT=os.getenv("BRAND_ACCENT","#e6df63")
SECOND=os.getenv("BRAND_SECONDARY","#0aa1c0")
LIGHT_ASSIST = "#eef5fb"
LIGHT_USER = "#fff4a8"

CSS = f"""
<style>
:root {{ --brand-primary:{PRIMARY}; --brand-accent:{ACCENT}; --brand-secondary:{SECOND}; --bg:#ffffff; --text:#1c1c1c; }}
html, body, [data-testid=stAppViewContainer] {{ background: var(--bg); }}
.block-container {{ max-width: 1200px; }}

/* Layout colonne */
.left-col {{ position: sticky; top: 16px; align-self: flex-start; }}
.menu-card {{ background:#fff; border:1px solid #eaeef3; border-radius:12px; padding:16px; }}
.logo-title {{ font-weight:900; color:{PRIMARY}; font-size:20px; line-height:1; }}
.logo-sub   {{ color:{ACCENT}; font-weight:900; }}
.logo-dot   {{ color:{SECOND}; font-weight:900; }}
.nav-title {{ font-size:12px; letter-spacing:.8px; color:#667; text-transform:uppercase; margin-top:8px; }}

/* Nav verticale (radio styled) */
.nav-radio .stRadio > div {{ display:flex; flex-direction:column; gap:6px; }}
.nav-radio label {{ width: 100%; }}
.nav-item {{ display:block; padding:10px 12px; border-radius:10px; border:1px solid transparent; color:#223; font-weight:600; }}
.nav-item:hover {{ background:#f5f7fb; }}
/* hack: evidenzia l'opzione selezionata */
div[data-baseweb="radio"] > div > div {{ gap:6px; }}
/* Bottoni brand */
.stButton>button {{ background: var(--brand-primary) !important; color: #fff !important; border-radius:10px !important; border:1px solid transparent !important; }}
.stButton>button:hover {{ filter: brightness(0.95); }}
/* Pannelli a destra */
.panel {{ background:#fff; border:1px solid #eaeef3; border-radius:12px; padding:18px; }}
.section-title {{ font-size:22px; font-weight:800; color:#1f2b3a; }}

/* Chat bolle */
.stElement iframe, iframe[title="streamlit.components.v1.html"] {{ width:100% !important; display:block; }}
.chat-wrapper {{ width:100%; max-width:100%; margin:0; }}
.container-box {{ width:100%; padding:14px; border-radius:8px; background:#fff; box-sizing:border-box; }}
.message-row {{ display:flex; margin:8px 0; }}
.bubble {{ padding:12px 16px; border-radius:14px; max-width:85%; line-height:1.45; border:1px solid #e6edf5; }}
.bubble.assistant {{ background:{LIGHT_ASSIST}; }}
.bubble.user {{ background:{LIGHT_USER}; border-color:#efe39a; margin-left:auto; }}
.badge-assistant {{ display:inline-block; background: var(--brand-primary); color:#fff; border-radius:999px; padding:6px 10px; font-weight:700; margin-right:10px; }}
.meta {{ font-size:11px; color:#889; margin-top:4px; }}
.typing {{ font-style:italic; opacity:.9; }}
#scroll {{ height: 560px; overflow:auto; overflow-x:hidden; padding-right:6px; }}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ---------- Chat rendering (HTML component) ----------
AUTO_SCROLL_JS = (
    "<script>"
    "try{const sc=document.getElementById('scroll');"
    "const need=()=>sc&&(sc.scrollHeight-sc.clientHeight)>4;"
    "const near=()=>sc&&need()&&(sc.scrollTop>=(sc.scrollHeight-sc.clientHeight-120));"
    "let stick=near();"
    "new MutationObserver(()=>{if(!sc)return; if(stick&&need()) sc.scrollTop=sc.scrollHeight; stick=near();}).observe(sc||document.body,{childList:true,subtree:true,characterData:true});"
    "}catch(e){}"
    "</script>"
)
def render_chat_html(history, show_typing=False):
    parts=['<div class="chat-wrapper"><div id="scroll"><div class="container-box">']
    for m in history:
        role=m.get("role","")
        content=clean_markdown_fences(m.get("content",""))
        content=html.escape(content)
        ts=m.get("ts","")
        try: tsv=datetime.fromisoformat(ts).strftime("%d/%m/%Y %H:%M")
        except Exception: tsv=ts
        if role=="assistant":
            parts.append('<div class="message-row"><span class="badge-assistant">Assistant</span>')
            parts.append(f'<div class="bubble assistant">{content}<div class="meta">Assistente · {tsv}</div></div></div>')
        else:
            parts.append('<div class="message-row">')
            parts.append(f'<div class="bubble user">{content}<div class="meta">Tu · {tsv}</div></div></div>')
    if show_typing:
        parts.append('<div class="message-row"><span class="badge-assistant">Assistant</span><div class="bubble assistant typing">Sta scrivendo…</div></div>')
    parts.append('</div></div></div>'); parts.append(AUTO_SCROLL_JS)
    return "".join(parts)

def render_chat(ph, history, show_typing=False):
    ph.empty()
    with ph:
        components.html(render_chat_html(history, show_typing), height=600, scrolling=False)

# ---------- LAYOUT ----------
left, right = st.columns([0.9, 3.1], gap="large")

# LEFT: logo + vertical nav + (facoltativo) KPI
with left:
    st.markdown('<div class="left-col">', unsafe_allow_html=True)
    st.markdown('<div class="menu-card">', unsafe_allow_html=True)
    # Logo (usa PNG se presente)
    logo_shown = False
    try:
        st.image("images/Nuovo_Logo.png", width=180)
        logo_shown = True
    except Exception:
        pass
    if not logo_shown:
        st.markdown(f'<div class="logo-title">easy<span class="logo-sub">look</span><span class="logo-dot">.doc</span></div>', unsafe_allow_html=True)

    st.markdown('<div class="nav-title">Menu</div>', unsafe_allow_html=True)
    st.markdown('<div class="nav-radio">', unsafe_allow_html=True)
    ss["nav"] = st.radio(
        "Navigazione",
        ["Documenti", "Estrazione", "Chat", "Cronologia", "Impostazioni"],
        index=["Documenti","Estrazione","Chat","Cronologia","Impostazioni"].index(ss["nav"]),
        label_visibility="collapsed",
        key="nav_radio_vertical",
    )
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# RIGHT: panels based on nav
with right:
    # Estrazione / Documenti
    if ss["nav"] in ("Documenti","Estrazione"):
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Nome documento</div>', unsafe_allow_html=True)
        if not HAVE_FORMRECOGNIZER:
            st.warning("Installa azure-ai-formrecognizer>=3.3.0")
        else:
            ss["file_name"] = st.text_input(" ", value=ss.get("file_name",""), placeholder="es. 'contratto1.pdf' nel container", label_visibility="hidden")
            col_a, col_b = st.columns([1, 0.22])
            with col_a:
                st.caption("")
            with col_b:
                extract_clicked = st.button("Estrai", use_container_width=True)
            st.markdown("")
            if st.button("Pulisci documento"):
                ss["document_text"] = ""
                ss["chat_history"] = []
                ss["doc_ready"] = False
                ss["file_name"] = ""
                st.rerun()

            if extract_clicked:
                AZURE_DOCINT_ENDPOINT = os.getenv("AZURE_DOCINT_ENDPOINT")
                AZURE_DOCINT_KEY = os.getenv("AZURE_DOCINT_KEY")
                AZURE_BLOB_CONTAINER_SAS_URL = os.getenv("AZURE_BLOB_CONTAINER_SAS_URL")
                file_name = ss.get("file_name")
                if not (AZURE_DOCINT_ENDPOINT and (AZURE_DOCINT_KEY or os.getenv("AZURE_TENANT_ID")) and AZURE_BLOB_CONTAINER_SAS_URL and file_name):
                    st.error("Completa le variabili e inserisci il nome file.")
                else:
                    try:
                        blob_url = build_blob_sas_url(AZURE_BLOB_CONTAINER_SAS_URL, file_name)
                        if AZURE_DOCINT_KEY:
                            di_client = DocumentAnalysisClient(endpoint=AZURE_DOCINT_ENDPOINT, credential=AzureKeyCredential(AZURE_DOCINT_KEY))
                        else:
                            TENANT_ID=os.getenv("AZURE_TENANT_ID"); CLIENT_ID=os.getenv("AZURE_CLIENT_ID"); CLIENT_SECRET=os.getenv("AZURE_CLIENT_SECRET")
                            di_client = DocumentAnalysisClient(endpoint=AZURE_DOCINT_ENDPOINT, credential=ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET))
                        poller = di_client.begin_analyze_document_from_url(model_id="prebuilt-read", document_url=blob_url)
                        result = poller.result()

                        full_text = ""
                        if hasattr(result, "content") and result.content:
                            full_text = result.content.strip()
                        if not full_text and hasattr(result, "pages"):
                            pages_text = []
                            for p in result.pages:
                                if hasattr(p, "content") and p.content:
                                    pages_text.append(p.content)
                            full_text = "\n\n".join(pages_text).strip()
                        if not full_text and hasattr(result, "pages"):
                            lines = []
                            for p in result.pages:
                                for line in getattr(p, "lines", []) or []:
                                    lines.append(line.content)
                            full_text = "\n".join(lines).strip()

                        if full_text:
                            st.success("✅ Testo estratto correttamente!")
                            st.text_area("Anteprima (~4000 char):", full_text[:4000], height=220)
                            ss["document_text"] = full_text
                            ss["chat_history"] = []
                            ss["doc_ready"] = True
                            ss["nav"] = "Chat"  # vai automaticamente in Chat
                            st.rerun()
                        else:
                            st.warning("Nessun testo estratto. Verifica file o SAS.")
                            ss["doc_ready"] = False
                    except Exception as e:
                        st.error(f"Errore durante l'analisi del documento: {e}")
                        ss["doc_ready"] = False
        st.markdown('</div>', unsafe_allow_html=True)

    # Chat
    if ss["nav"] == "Chat":
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Chat</div>', unsafe_allow_html=True)
        if ss.get("doc_ready", False):
            chat_ph = st.empty()
            render_chat(chat_ph, ss["chat_history"], show_typing=False)

            user_prompt = st.chat_input("Scrivi un messaggio…")
            if user_prompt:
                ts = now_iso()
                ss["chat_history"].append({"role":"user","content":clean_markdown_fences(user_prompt),"ts":ts})
                render_chat(chat_ph, ss["chat_history"], show_typing=True)

                client, DEPLOYMENT_NAME = get_aoai_client()

                CONTEXT_CHAR_LIMIT = 12000
                SYS = "Sei un assistente che risponde SOLO sulla base del documento fornito."
                TRUNC = "(---Documento troncato - mostra l'ultima parte---)\n"

                def build_msgs(doc_text: str, hist: list):
                    msgs=[{"role":"system","content":SYS}]
                    doc = ss.get("document_text","")
                    if doc:
                        d = doc
                        if len(d) > CONTEXT_CHAR_LIMIT:
                            d = TRUNC + d[-CONTEXT_CHAR_LIMIT:]
                        msgs.append({"role":"system","content":f"Contenuto documento:\n{d}"})
                    for m in hist:
                        msgs.append({"role":m["role"],"content":clean_markdown_fences(m["content"])})
                    return msgs

                api_messages = build_msgs(ss.get("document_text",""), ss["chat_history"])

                partial = ""
                ts2 = now_iso()
                try:
                    stream = client.chat.completions.create(
                        model=DEPLOYMENT_NAME,
                        messages=api_messages,
                        temperature=0.3,
                        max_tokens=700,
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
                                    temp = ss["chat_history"] + [{"role":"assistant","content":partial,"ts":ts2}]
                                    render_chat(chat_ph, temp, show_typing=False)
                        except Exception:
                            pass
                    final = clean_markdown_fences(partial)
                    ss["chat_history"].append({"role":"assistant","content":final,"ts":ts2})
                    render_chat(chat_ph, ss["chat_history"], show_typing=False)
                except Exception as api_err:
                    render_chat(chat_ph, ss["chat_history"], show_typing=False)
                    st.error(f"❌ Errore nella chiamata API: {api_err}")

            col1, col2 = st.columns([1,1])
            with col1:
                if st.button("Reset chat", use_container_width=True):
                    ss["chat_history"] = []
                    st.rerun()
            with col2:
                st.caption("Sessione locale al browser")
        else:
            st.info("➡️ Completa lo Step 1 (Estrazione) prima di usare la chat.")
        st.markdown('</div>', unsafe_allow_html=True)

    # Cronologia & Impostazioni placeholder
    if ss["nav"] == "Cronologia":
        st.markdown('<div class="panel"><div class="section-title">Cronologia</div><p>Prossimamente: salvataggio e riapertura conversazioni.</p></div>', unsafe_allow_html=True)
    if ss["nav"] == "Impostazioni":
        st.markdown('<div class="panel"><div class="section-title">Impostazioni</div><p>Prossimamente: preferenze utente, temi, ecc.</p></div>', unsafe_allow_html=True)