# easylook_doc_chat_integrated_ui.py
import os, re, html
from datetime import datetime, timezone
import streamlit as st, streamlit.components.v1 as components

# Map secrets to env
try:
    for k, v in st.secrets.items():
        os.environ.setdefault(k, str(v))
except Exception:
    pass

from openai import AzureOpenAI
from azure.identity import ClientSecretCredential
try:
    from azure.ai.formrecognizer import DocumentAnalysisClient
    from azure.core.credentials import AzureKeyCredential
    HAVE_FORMRECOGNIZER = True
except Exception:
    HAVE_FORMRECOGNIZER = False

if "doc_ready" not in st.session_state: st.session_state["doc_ready"] = False
if "document_text" not in st.session_state: st.session_state["document_text"] = ""
if "chat_history" not in st.session_state: st.session_state["chat_history"] = []
if "file_name" not in st.session_state: st.session_state["file_name"] = ""
if "nav" not in st.session_state: st.session_state["nav"] = "Estrazione"

def clean_markdown_fences(t: str) -> str:
    if not t: return ""
    t = t.replace("\\r\\n","\\n")
    t = re.sub(r"```[a-zA-Z0-9_-]*\\n([\\s\\S]*?)```", r"\\1", t)
    t = re.sub(r"~~~[a-zA-Z0-9_-]*\\n([\\s\\S]*?)~~~", r"\\1", t)
    return t.replace("```","").replace("~~~","").strip()

def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()

def build_blob_sas_url(container_sas_url: str, blob_name: str) -> str:
    if not container_sas_url or "?" not in container_sas_url: return ""
    base, qs = container_sas_url.split("?",1); base = base.rstrip("/")
    return f"{base}/{blob_name}?{qs}"

def get_aoai_client():
    TENANT_ID = os.getenv("AZURE_TENANT_ID")
    CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
    CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
    AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
    DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")
    if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET, AZURE_OPENAI_ENDPOINT, DEPLOYMENT_NAME]):
        st.error("Config OpenAI mancante."); st.stop()
    cred = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
    aad_token = cred.get_token("https://cognitiveservices.azure.com/.default").token
    client = AzureOpenAI(api_version=API_VERSION, azure_endpoint=AZURE_OPENAI_ENDPOINT, azure_ad_token=aad_token)
    return client, DEPLOYMENT_NAME

st.set_page_config(page_title="EasyLook.DOC", page_icon="💬", layout="wide")

PRIMARY=os.getenv("BRAND_PRIMARY","#2a7fa9"); ACCENT=os.getenv("BRAND_ACCENT","#e6df63"); SECONDARY=os.getenv("BRAND_SECONDARY","#0aa1c0")
css = """
<style>
:root { --brand-primary: __P__; --brand-accent: __A__; --brand-secondary: __S__; --bg:#f7f7f8; --text:#1c1c1c; }
html, body, [data-testid=stAppViewContainer]{ background: var(--bg); }
.block-container{max-width:100% !important; padding-left:16px; padding-right:16px;}
.menu-card{background:#fff;border:1px solid #eee;border-radius:14px;padding:16px;position:sticky;top:72px;height:calc(100vh - 96px);overflow:auto;}
.right-card{background:#fff;border:1px solid #eee;border-radius:14px;padding:0;overflow:hidden;}
.logo-wrap{display:flex;align-items:center;gap:12px;margin-bottom:12px;}
.logo-title{font-size:22px;font-weight:800;color:var(--brand-primary);letter-spacing:.2px;}
.badge{font-size:12px;background:linear-gradient(90deg,var(--brand-accent),var(--brand-secondary));color:#fff;padding:3px 8px;border-radius:999px;}
.nav-title{font-size:12px;letter-spacing:.8px;color:#667;text-transform:uppercase;margin:4px 0 6px;}
.nav-radio .stRadio>div{gap:6px;}
.nav-radio label{display:block;width:100%;}
.kpi{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:10px;}
.kpi .card{background:#fcfdff;border:1px solid #eef2f8;border-radius:12px;padding:10px;}
.tag{font-size:12px;color:#567;}
.panel-header{padding:12px 16px;border-bottom:1px solid #eee;background:linear-gradient(90deg,#fff,#f9fbff);display:flex;justify-content:space-between;align-items:center;}
.panel-title{font-weight:700;color:#203040;}
.stElement iframe, iframe[title="streamlit.components.v1.html"]{width:100% !important;display:block;}
.chat-wrapper{width:100%;max-width:100%;margin:0;box-sizing:border-box;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;}
.container-box{width:100%;max-width:100%;padding:14px;border-radius:8px;background:#f7f7f8;box-sizing:border-box;}
.message-row{display:flex;margin:6px 8px;}
.bubble{padding:10px 14px;border-radius:18px;max-width:85%;box-shadow:0 1px 0 rgba(0,0,0,.06);line-height:1.45;white-space:pre-wrap;word-wrap:break-word;}
.user{margin-left:auto;background:#e8f8d8;border:1px solid #d5efc6;text-align:left;border-bottom-right-radius:4px;}
.assistant{margin-right:auto;background:#fff;border:1px solid #e6e6e6;text-align:left;border-bottom-left-radius:4px;}
.meta{font-size:11px;color:#888;margin-top:4px;}
.typing{font-style:italic;opacity:.9;}
#scroll{height:100%;overflow:auto;overflow-x:hidden;padding:0 8px;width:100%;box-sizing:border-box;}
.action-bar{padding:10px 14px;border-top:1px solid #eee;display:flex;gap:10px;align-items:center;justify-content:flex-end;}
.action-bar .note{color:#667;font-size:12px;margin-right:auto;}
.primary-btn{border:none;border-radius:10px;padding:8px 12px;background:var(--brand-primary);color:#fff;font-weight:600;}
.ghost-btn{border:1px solid #dde3ea;border-radius:10px;padding:8px 12px;background:#fff;color:#203040;font-weight:600;}
</style>
""".replace("__P__", PRIMARY).replace("__A__", ACCENT).replace("__S__", SECONDARY)
st.markdown(css, unsafe_allow_html=True)

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
    parts=['<div class=\"chat-wrapper\"><div id=\"scroll\"><div class=\"container-box\">']
    for m in history:
        role=m.get("role",""); content=clean_markdown_fences(m.get("content","")); content=html.escape(content)
        ts=m.get("ts","")
        try: tsv=datetime.fromisoformat(ts).strftime("%d/%m/%Y %H:%M")
        except Exception: tsv=ts
        klass="user" if role=="user" else "assistant"; who="Tu" if role=="user" else "Assistente"
        parts.append('<div class=\"message-row\">')
        parts.append(f'<div class=\"bubble {klass}\">{content}<div class=\"meta\">{who} · {tsv}</div></div>')
        parts.append('</div>')
    if show_typing: parts.append('<div class=\"message-row\"><div class=\"bubble assistant typing\">Sta scrivendo…</div></div>')
    parts.append('</div></div></div>'); parts.append(AUTO_SCROLL_JS); return "".join(parts)

def render_chat(ph, history, show_typing=False, height=600):
    html_str=render_chat_html(history, show_typing=show_typing); ph.empty(); 
    with ph: components.html(html_str, height=height, scrolling=False)

left, right = st.columns([1,3], gap="large")

with left:
    st.markdown('<div class=\"menu-card\">', unsafe_allow_html=True)
    try: st.image("images/Nuovo_Logo.png", width=180)
    except Exception: pass
    st.markdown('<div class=\"logo-wrap\"><div class=\"logo-title\">EasyLook.<span class=\"badge\">doc</span></div></div>', unsafe_allow_html=True)
    st.markdown('<div class=\"nav-title\">Navigazione</div>', unsafe_allow_html=True)
    st.markdown('<div class=\"nav-radio\">', unsafe_allow_html=True)
    st.session_state["nav"]=st.radio("Navigazione",["Documenti","Estrazione","Chat","Cronologia","Impostazioni"],
                                     index=["Documenti","Estrazione","Chat","Cronologia","Impostazioni"].index(st.session_state["nav"]),
                                     label_visibility="collapsed",key="nav_radio")
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('<div class=\"kpi\">', unsafe_allow_html=True)
    doc_name=st.session_state.get("file_name") or "Nessun file"
    status="Estratto ✅" if st.session_state.get("doc_ready") else "Da estrarre"
    c1,c2=st.columns(2)
    with c1: st.markdown(f'<div class=\"card\"><div class=\"tag\">Documento</div><div><b>{doc_name}</b></div></div>', unsafe_allow_html=True)
    with c2: st.markdown(f'<div class=\"card\"><div class=\"tag\">Stato</div><div>{status}</div></div>', unsafe_allow_html=True)
    c3,c4=st.columns(2)
    with c3: st.markdown(f'<div class=\"card\"><div class=\"tag\">Pagine</div><div>-</div></div>', unsafe_allow_html=True)
    with c4: st.markdown(f'<div class=\"card\"><div class=\"tag\">Ultima mod.</div><div>{datetime.now().strftime("%d/%m/%Y %H:%M")}</div></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

with right:
    st.markdown('<div class=\"right-card\">', unsafe_allow_html=True)
    title_map={"Documenti":"📁 Documenti","Estrazione":"📄 Estrazione documento","Chat":"💬 Chat sul documento","Cronologia":"🕓 Cronologia","Impostazioni":"⚙️ Impostazioni"}
    st.markdown(f'<div class=\"panel-header\"><div class=\"panel-title\">{title_map.get(st.session_state["nav"], "")}</div></div>', unsafe_allow_html=True)

    if st.session_state["nav"] in ("Documenti","Estrazione"):
        if not HAVE_FORMRECOGNIZER:
            st.warning("Installa azure-ai-formrecognizer>=3.3.0")
        else:
            st.session_state["file_name"]=st.text_input("Nome file nel container (es. 'contratto1.pdf')", st.session_state.get("file_name",""))
            c1,c2=st.columns([1,1])
            with c1: read_clicked=st.button("🔎 Leggi documento", use_container_width=True, type="primary")
            with c2:
                if st.button("🔁 Cambia/Reset documento", use_container_width=True):
                    st.session_state["document_text"]=""; st.session_state["chat_history"]=[]; st.session_state["doc_ready"]=False; st.session_state["file_name"]=""; st.rerun()
            if read_clicked:
                AZURE_DOCINT_ENDPOINT=os.getenv("AZURE_DOCINT_ENDPOINT"); AZURE_DOCINT_KEY=os.getenv("AZURE_DOCINT_KEY"); AZURE_BLOB_CONTAINER_SAS_URL=os.getenv("AZURE_BLOB_CONTAINER_SAS_URL")
                file_name=st.session_state.get("file_name")
                if not (AZURE_DOCINT_ENDPOINT and (AZURE_DOCINT_KEY or os.getenv("AZURE_TENANT_ID")) and AZURE_BLOB_CONTAINER_SAS_URL and file_name):
                    st.error("Completa le variabili e inserisci il nome file.")
                else:
                    try:
                        blob_url=build_blob_sas_url(AZURE_BLOB_CONTAINER_SAS_URL, file_name)
                        if AZURE_DOCINT_KEY:
                            di_client=DocumentAnalysisClient(endpoint=AZURE_DOCINT_ENDPOINT, credential=AzureKeyCredential(AZURE_DOCINT_KEY))
                        else:
                            TENANT_ID=os.getenv("AZURE_TENANT_ID"); CLIENT_ID=os.getenv("AZURE_CLIENT_ID"); CLIENT_SECRET=os.getenv("AZURE_CLIENT_SECRET")
                            di_client=DocumentAnalysisClient(endpoint=AZURE_DOCINT_ENDPOINT, credential=ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET))
                        poller=di_client.begin_analyze_document_from_url(model_id="prebuilt-read", document_url=blob_url); result=poller.result()
                        full_text=""
                        if hasattr(result,"content") and result.content: full_text=result.content.strip()
                        if not full_text and hasattr(result,"pages"):
                            pages_text=[]; 
                            for p in result.pages:
                                if hasattr(p,"content") and p.content: pages_text.append(p.content)
                            full_text="\\n\\n".join(pages_text).strip()
                        if not full_text and hasattr(result,"pages"):
                            all_lines=[]; 
                            for p in result.pages:
                                for line in getattr(p,"lines",[]) or []: all_lines.append(line.content)
                            full_text="\\n".join(all_lines).strip()
                        if full_text:
                            st.success("✅ Testo estratto correttamente!")
                            st.text_area("Anteprima testo (~4000 caratteri):", full_text[:4000], height=240)
                            st.session_state["document_text"]=full_text; st.session_state["chat_history"]=[]; st.session_state["doc_ready"]=True
                            st.session_state["nav"]="Chat"; st.rerun()
                        else:
                            st.warning("Nessun testo estratto. Verifica file o SAS."); st.session_state["doc_ready"]=False
                    except Exception as e:
                        st.error(f"Errore durante l'analisi del documento: {e}"); st.session_state["doc_ready"]=False

    if st.session_state["nav"] == "Chat":
        if st.session_state.get("doc_ready", False):
            chat_placeholder=st.empty(); 
            def _render(show_typing=False): render_chat(chat_placeholder, st.session_state["chat_history"], show_typing=show_typing, height=600)
            _render(False)
            user_prompt=st.chat_input("Scrivi un messaggio…")
            if user_prompt:
                ts=now_iso(); st.session_state["chat_history"].append({"role":"user","content":clean_markdown_fences(user_prompt),"ts":ts}); _render(True)
                TENANT_ID=os.getenv("AZURE_TENANT_ID"); CLIENT_ID=os.getenv("AZURE_CLIENT_ID"); CLIENT_SECRET=os.getenv("AZURE_CLIENT_SECRET")
                AZURE_OPENAI_ENDPOINT=os.getenv("AZURE_OPENAI_ENDPOINT"); DEPLOYMENT_NAME=os.getenv("AZURE_OPENAI_DEPLOYMENT"); API_VERSION=os.getenv("AZURE_OPENAI_API_VERSION","2024-05-01-preview")
                if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET, AZURE_OPENAI_ENDPOINT, DEPLOYMENT_NAME]): st.error("Config OpenAI mancante."); st.stop()
                cred=ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET); aad_token=cred.get_token("https://cognitiveservices.azure.com/.default").token
                client=AzureOpenAI(api_version=API_VERSION, azure_endpoint=AZURE_OPENAI_ENDPOINT, azure_ad_token=aad_token)
                CONTEXT_CHAR_LIMIT=12000; ASSISTANT_SYSTEM_INSTRUCTION="Sei un assistente che risponde SOLO sulla base del documento fornito."; TRUNC="(---Documento troncato - mostra l'ultima parte---)\\n"
                def build_msgs(doc_text: str, hist: list):
                    msgs=[{"role":"system","content":ASSISTANT_SYSTEM_INSTRUCTION}]
                    doc_text=st.session_state.get("document_text","")
                    if doc_text:
                        d=doc_text; 
                        if len(d)>CONTEXT_CHAR_LIMIT: d=TRUNC + d[-CONTEXT_CHAR_LIMIT:]
                        msgs.append({"role":"system","content":f"Contenuto documento:\\n{d}"})
                    for m in hist: msgs.append({"role":m["role"],"content":clean_markdown_fences(m["content"])})
                    return msgs
                api_messages=build_msgs(st.session_state.get("document_text",""), st.session_state["chat_history"])
                partial=""; ts2=now_iso()
                try:
                    stream=client.chat.completions.create(model=DEPLOYMENT_NAME, messages=api_messages, temperature=0.3, max_tokens=700, stream=True)
                    for chunk in stream:
                        try:
                            choices=getattr(chunk,"choices",[])
                            if choices:
                                delta=getattr(choices[0],"delta",None)
                                if delta and getattr(delta,"content",None):
                                    piece=delta.content; partial+=piece
                                    temp=st.session_state["chat_history"]+[{"role":"assistant","content":partial,"ts":ts2}]; render_chat(chat_placeholder, temp, show_typing=False, height=600)
                        except Exception: pass
                    final=clean_markdown_fences(partial); st.session_state["chat_history"].append({"role":"assistant","content":final,"ts":ts2}); _render(False)
                except Exception as api_err:
                    _render(False); st.error(f"❌ Errore nella chiamata API (streaming): {api_err}")
            c1,c2,c3=st.columns([1,1,2])
            with c1:
                if st.button("🧹 Reset chat", use_container_width=True): st.session_state["chat_history"]=[]; st.rerun()
            with c2: st.caption("Sessione locale al browser")
        else:
            st.info("➡️ Completa lo Step 1 (Estrazione) prima di usare la chat.")

    if st.session_state["nav"] == "Cronologia":
        st.info("Cronologia conversazioni: (prossimamente) salvataggio e riapertura delle chat.")
    if st.session_state["nav"] == "Impostazioni":
        st.info("Impostazioni: (prossimamente) preferenze utente, temi, ecc.")

    st.markdown('</div>', unsafe_allow_html=True)
