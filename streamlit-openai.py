import os, re, html
from datetime import datetime, timezone
import streamlit as st
import streamlit.components.v1 as components

# ----------------------
# Page config
# ----------------------
st.set_page_config(page_title="EasyLook.DOC", page_icon="💬", layout="wide")

# ----------------------
# Optional SDKs (UI works even if not installed; only extraction/chat need them)
# ----------------------
from openai import AzureOpenAI
from azure.identity import ClientSecretCredential
try:
    from azure.ai.formrecognizer import DocumentAnalysisClient
    from azure.core.credentials import AzureKeyCredential
    HAVE_DOCINT = True
except Exception:
    HAVE_DOCINT = False

# ----------------------
# Session state
# ----------------------
ss = st.session_state
ss.setdefault("doc_ready", False)
ss.setdefault("document_text", "")
ss.setdefault("chat_history", [])
ss.setdefault("file_name", "")
ss.setdefault("nav", "Estrazione")

# ----------------------
# Helpers
# ----------------------
def clean_md(t: str) -> str:
    if not t: return ""
    t = t.replace("\r\n","\n")
    t = re.sub(r"```[a-zA-Z0-9_-]*\n([\s\S]*?)```", r"\1", t)
    t = re.sub(r"~~~[a-zA-Z0-9_-]*\n([\s\S]*?)~~~", r"\1", t)
    return t.replace("```","").replace("~~~","").strip()

def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()

def build_blob_sas_url(container_sas_url: str, blob_name: str) -> str:
    if not container_sas_url or "?" not in container_sas_url: return ""
    base, qs = container_sas_url.split("?",1); base = base.rstrip("/")
    return f"{base}/{blob_name}?{qs}"

def get_aoai_client():
    TENANT_ID=os.getenv("AZURE_TENANT_ID"); CLIENT_ID=os.getenv("AZURE_CLIENT_ID"); CLIENT_SECRET=os.getenv("AZURE_CLIENT_SECRET")
    ENDPOINT=os.getenv("AZURE_OPENAI_ENDPOINT"); DEPLOYMENT=os.getenv("AZURE_OPENAI_DEPLOYMENT")
    API_VERSION=os.getenv("AZURE_OPENAI_API_VERSION","2024-05-01-preview")
    if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET, ENDPOINT, DEPLOYMENT]):
        st.error("Configurazione OpenAI mancante."); st.stop()
    cred=ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
    token=cred.get_token("https://cognitiveservices.azure.com/.default").token
    client=AzureOpenAI(api_version=API_VERSION, azure_endpoint=ENDPOINT, azure_ad_token=token)
    return client, DEPLOYMENT

# ----------------------
# Styles: LEFT = white flat panel; RIGHT = boxed chat; WhatsApp-like bubbles
# ----------------------
PRIMARY = os.getenv("BRAND_PRIMARY", "#2a7fa9")
ACCENT  = os.getenv("BRAND_ACCENT",  "#e6df63")
SECOND  = os.getenv("BRAND_SECONDARY", "#0aa1c0")
BG_APP  = "#f0f2f5"  # app background

CSS = f"""
<style>
:root {{ --brand-primary:{PRIMARY}; --brand-accent:{ACCENT}; --brand-secondary:{SECOND}; }}
html, body, [data-testid=stAppViewContainer] {{ background:{BG_APP}; }}
.block-container {{ max-width: 1240px; }}

/* generic boxed container (only for right column) */
.box {{
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 16px;
  height: calc(100vh - 120px);
  overflow: hidden;
  background:#e5ddd5; /* WhatsApp-like */
}}

/* LEFT column: flat white panel (no border, no extra padding) */
.menu-panel {{
  background:#ffffff;
  padding: 0;           /* no top bar */
  border: none;
  border-radius: 0;
  box-shadow:none;
  min-height: calc(100vh - 120px);
}}

.menu-inner {{
  padding: 0 8px 8px 0; /* small right/bottom padding to breathe */
}}

/* titles */
.panel-title {{ font-weight:900; font-size:20px; margin: 0 0 8px 0; color:#1f2b3a; }}

/* radio spacing */
.nav-radio [data-baseweb="radio"] > div {{ display:flex; flex-direction:column; row-gap:12px; }}
.nav-radio input[type="radio"] {{ accent-color: var(--brand-primary) !important; width:18px; height:18px; }}
.nav-radio label p {{ font-weight:600; color:#203040; font-size:15px; }}

/* document preview */
.preview {{ background:#f8fafc; border:1px solid #e5e7eb; border-radius:10px; padding:8px; }}

/* chat area */
.chat-surface {{
  background-image: linear-gradient(0deg, rgba(0,0,0,0.02) 1px, transparent 1px), linear-gradient(90deg, rgba(0,0,0,0.02) 1px, transparent 1px);
  background-size: 14px 14px;
  height: 100%;
  border-radius: 12px;
  padding: 12px;
  overflow: auto;
}}

/* WhatsApp-like bubbles */
.row {{ display:flex; margin:6px 0; }}
.row.assistant {{ justify-content:flex-start; }}
.row.user {{ justify-content:flex-end; }}

.bubble {{
  max-width: 75%;
  padding: 8px 10px;
  border-radius: 10px;
  line-height: 1.45;
  box-shadow: 0 1px 1px rgba(0,0,0,0.06);
  position: relative;
  word-wrap: break-word;
  border: 1px solid rgba(0,0,0,0.05);
}}

.bubble.assistant {{ background:#ffffff; border-top-left-radius: 0; }}
.bubble.user {{ background:#dcf8c6; border-top-right-radius: 0; }}

.meta {{ font-size:11px; color:#6b7280; margin-top:4px; text-align:right; }}

/* buttons look */
.stButton>button {{ background: var(--brand-primary) !important; color:#fff !important; border-radius:10px !important; border:1px solid transparent !important; }}
.stButton>button:hover {{ filter:brightness(0.95); }}
.stTextInput>div>div>input {{ background:#f8fafc; }}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ----------------------
# Chat renderer (HTML) with autoscroll
# ----------------------
AUTO_SCROLL_JS=(
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
    parts=['<div id="scroll" class="chat-surface">']
    for m in history:
        role=m.get("role","")
        content=clean_md(m.get("content",""))
        content=html.escape(content)
        ts=m.get("ts","")
        try: tsv=datetime.fromisoformat(ts).strftime("%d/%m/%Y %H:%M")
        except Exception: tsv=ts
        cls = "user" if role=="user" else "assistant"
        parts.append(f'<div class="row {cls}"><div class="bubble {cls}">{content}<div class="meta">{tsv}</div></div></div>')
    if show_typing:
        parts.append('<div class="row assistant"><div class="bubble assistant" style="opacity:.85;">Sta scrivendo…</div></div>')
    parts.append('</div>'); parts.append(AUTO_SCROLL_JS)
    return "".join(parts)

def render_chat(ph, history, show_typing=False):
    ph.empty()
    with ph:
        components.html(render_chat_html(history, show_typing), height=600, scrolling=False)

# ----------------------
# Layout: two Streamlit columns
# ----------------------
left, right = st.columns([0.9, 3.1], gap="large")

# ----- LEFT: FLAT WHITE PANEL (no .box) -----
with left:
    st.markdown('<div class="menu-panel"><div class="menu-inner">', unsafe_allow_html=True)

    # Logo / brand (optional)
    try:
        st.image("images/Nuovo_Logo.png", width=180)
    except Exception:
        st.markdown(f'<div class="panel-title">easy<span style="color:{ACCENT}">look</span><span style="color:{SECOND}">.doc</span></div>', unsafe_allow_html=True)

    st.markdown("<div class='panel-title' style='font-size:12px; letter-spacing:.8px; color:#667; text-transform:uppercase; margin-top:4px;'>Menu</div>", unsafe_allow_html=True)
    ss["nav"] = st.radio("Navigazione", ["Documenti","Estrazione","Chat","Cronologia","Impostazioni"],
                         index=["Documenti","Estrazione","Chat","Cronologia","Impostazioni"].index(ss["nav"]),
                         label_visibility="collapsed", key="nav_v10")

    st.markdown('<div class="panel-title" style="margin-top:8px;">Documento</div>', unsafe_allow_html=True)

    if not HAVE_DOCINT:
        st.warning("Installa azure-ai-formrecognizer>=3.3.0 per l\'estrazione.")
    else:
        ss["file_name"]=st.text_input("Nome file nel container (es. 'contratto1.pdf')", ss.get("file_name",""))
        c1,c2 = st.columns([1,1])
        with c1:
            read_clicked = st.button("🔎 Leggi documento", use_container_width=True)
        with c2:
            if st.button("🗂️ Reset documento", use_container_width=True):
                ss["document_text"]=""; ss["chat_history"]=[]; ss["doc_ready"]=False; ss["file_name"]=""; st.rerun()
        if read_clicked:
            END=os.getenv("AZURE_DOCINT_ENDPOINT"); KEY=os.getenv("AZURE_DOCINT_KEY"); SAS=os.getenv("AZURE_BLOB_CONTAINER_SAS_URL")
            fname=ss.get("file_name")
            if not (END and (KEY or os.getenv("AZURE_TENANT_ID")) and SAS and fname):
                st.error("Completa le variabili e inserisci il nome file.")
            else:
                try:
                    blob_url=build_blob_sas_url(SAS, fname)
                    if KEY:
                        di_client=DocumentAnalysisClient(endpoint=END, credential=AzureKeyCredential(KEY))
                    else:
                        TENANT_ID=os.getenv("AZURE_TENANT_ID"); CLIENT_ID=os.getenv("AZURE_CLIENT_ID"); CLIENT_SECRET=os.getenv("AZURE_CLIENT_SECRET")
                        di_client=DocumentAnalysisClient(endpoint=END, credential=ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET))
                    poller=di_client.begin_analyze_document_from_url(model_id="prebuilt-read", document_url=blob_url); result=poller.result()
                    full_text=""
                    if hasattr(result,"content") and result.content: full_text=result.content.strip()
                    if not full_text and hasattr(result,"pages"):
                        parts=[]; 
                        for p in result.pages:
                            if hasattr(p,"content") and p.content: parts.append(p.content)
                        full_text="\\n\\n".join(parts).strip()
                    if not full_text and hasattr(result,"pages"):
                        lines=[]; 
                        for p in result.pages:
                            for line in getattr(p,"lines",[]) or []: lines.append(line.content)
                        full_text="\\n".join(lines).strip()
                    if full_text:
                        st.success("✅ Testo estratto correttamente!")
                        st.markdown('<div class="preview">', unsafe_allow_html=True)
                        st.text_area("Anteprima (~4000 caratteri):", full_text[:4000], height=160, label_visibility="collapsed")
                        st.markdown('</div>', unsafe_allow_html=True)
                        ss["document_text"]=full_text; ss["chat_history"]=[]; ss["doc_ready"]=True
                    else:
                        st.warning("Nessun testo estratto. Verifica file o SAS."); ss["doc_ready"]=False
                except Exception as e:
                    st.error(f"Errore durante l\'analisi del documento: {e}"); ss["doc_ready"]=False

    st.markdown('</div></div>', unsafe_allow_html=True)  # end menu-panel + inner

# ----- RIGHT: BOXED CHAT -----
with right:
    st.markdown('<div class="box">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">Chat</div>', unsafe_allow_html=True)

    # Chat area
    chat_ph = st.empty()
    if ss.get("doc_ready", False):
        render_chat(chat_ph, ss["chat_history"], show_typing=False)
        user_prompt = st.chat_input("Scrivi un messaggio…")
        if user_prompt:
            ts=now_iso(); ss["chat_history"].append({"role":"user","content":clean_md(user_prompt),"ts":ts})
            render_chat(chat_ph, ss["chat_history"], show_typing=True)
            # call AOAI
            client, DEPLOYMENT = get_aoai_client()
            LIMIT=12000; SYS="Sei un assistente che risponde SOLO sulla base del documento fornito."; TRUNC="(---Documento troncato - mostra l'ultima parte---)\\n"
            def build_msgs():
                msgs=[{"role":"system","content":SYS}]
                doc=ss.get("document_text","")
                if doc:
                    d=doc; 
                    if len(d)>LIMIT: d=TRUNC + d[-LIMIT:]
                    msgs.append({"role":"system","content":f"Contenuto documento:\\n{d}"})
                for m in ss["chat_history"]:
                    msgs.append({"role":m["role"],"content":clean_md(m["content"])})
                return msgs
            partial=""; ts2=now_iso()
            try:
                stream=client.chat.completions.create(model=DEPLOYMENT, messages=build_msgs(), temperature=0.3, max_tokens=700, stream=True)
                for chunk in stream:
                    try:
                        choices=getattr(chunk,"choices",[])
                        if choices:
                            delta=getattr(choices[0],"delta",None)
                            if delta and getattr(delta,"content",None):
                                piece=delta.content; partial+=piece
                                temp=ss["chat_history"]+[{"role":"assistant","content":partial,"ts":ts2}]
                                render_chat(chat_ph, temp, show_typing=False)
                    except Exception: pass
                final=clean_md(partial) if partial.strip() else "Mi dispiace, non posso rispondere a questa domanda in base al documento fornito."
                ss["chat_history"].append({"role":"assistant","content":final,"ts":ts2})
                render_chat(chat_ph, ss["chat_history"], show_typing=False)
            except Exception as api_err:
                render_chat(chat_ph, ss["chat_history"], show_typing=False)
                st.error(f"❌ Errore API: {api_err}")
        c1,c2 = st.columns([1,1])
        with c1:
            if st.button("Reset chat", use_container_width=True): ss["chat_history"]=[]; st.rerun()
        with c2: st.caption("Sessione locale al browser")
    else:
        st.info("➡️ Carica/leggi prima un documento per abilitare la chat.")
        render_chat(chat_ph, [], show_typing=False)

    st.markdown('</div>', unsafe_allow_html=True)  # end right box
