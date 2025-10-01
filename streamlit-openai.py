import os
import html
import streamlit as st
from datetime import datetime, timezone
import pytz
from typing import Optional
from azure.identity import ClientSecretCredential
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI

st.set_page_config(page_title="EasyLook.DOC Chat", page_icon="💬", layout="wide")

# CONFIG
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX = "azureblob-index"
FILENAME_FIELD = "metadata_storage_path"

local_tz = pytz.timezone("Europe/Rome")

# HELPERS
def spacer(n: int = 1):
    for _ in range(n):
        st.write("")

def safe_filter_eq(field, value):
    if not value:
        return None
    safe_value = str(value).replace("'", "''")
    return f"{field} eq '{safe_value}'"

def build_chat_messages(user_q, context_snippets):
    sys_msg = {
        "role": "system",
        "content": (
            "Sei un assistente che risponde SOLO in base ai documenti forniti nel contesto. "
            "Se l'informazione non è presente, dillo chiaramente."
        ),
    }
    ctx = "\n\n".join(["- " + s for s in context_snippets]) if context_snippets else "(nessun contesto)"
    user_msg = {"role": "user", "content": f"CONTEXTPASS:\n{ctx}\n\nDOMANDA:\n{user_q}"}
    return [sys_msg, user_msg]

# CLIENTS (lazy + cache)
@st.cache_resource(show_spinner=False)
def get_credential() -> ClientSecretCredential:
    return ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)

@st.cache_resource(show_spinner=False)
def get_search_client() -> Optional[SearchClient]:
    if not (AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY and AZURE_SEARCH_INDEX):
        return None
    return SearchClient(
        endpoint=AZURE_SEARCH_ENDPOINT,
        index_name=AZURE_SEARCH_INDEX,
        credential=AzureKeyCredential(AZURE_SEARCH_KEY),
    )

@st.cache_resource(show_spinner=False)
def get_aoai_client(aad_token: str) -> AzureOpenAI:
    return AzureOpenAI(
        api_version=API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_ad_token=aad_token,
    )

# Token AAD
if "aad_token" not in st.session_state or "aad_exp" not in st.session_state:
    cred = get_credential()
    access = cred.get_token("https://cognitiveservices.azure.com/.default")
    st.session_state["aad_token"] = access.token
    st.session_state["aad_exp"] = access.expires_on

# rinnovo con buffer 5 min
now_ts = datetime.now(timezone.utc).timestamp()
if now_ts >= st.session_state.get("aad_exp", 0) - 300:
    cred = get_credential()
    access = cred.get_token("https://cognitiveservices.azure.com/.default")
    st.session_state["aad_token"] = access.token
    st.session_state["aad_exp"] = access.expires_on

client = get_aoai_client(st.session_state["aad_token"])
search_client = get_search_client()

# STATE
ss = st.session_state
ss.setdefault("chat_history", [])
ss.setdefault("active_doc", None)
ss.setdefault("nav", "Chat")
ss.setdefault("theme", "chiaro")
documents_cache = ss.get("documents_cache", [])
last_update = ss.get("documents_cache_time")

# STYLES
is_dark = ss.get("theme") == "scuro"
accent = "#2563eb"
st.markdown(
    f"""
<style>
:root {{
  --bg: {"#0b1220" if is_dark else "#f8fafc"};
  --panel: {"#0f172a" if is_dark else "#ffffff"};
  --text: {"#e5e7eb" if is_dark else "#0f172a"};
  --muted: {"#93a2b1" if is_dark else "#475569"};
  --border: {"#1f2937" if is_dark else "#e5e7eb"};
  --bubble-ai: {"#0e3a53" if is_dark else "#F1F6FA"};
  --bubble-user: {"#3f3a12" if is_dark else "#FFF7CC"};
  --right-bg: {"#1e293b" if is_dark else "#f1f5f9"};
}}

.left-pane{{ padding: 0; border: none; background: transparent; color: var(--text); }}
.right-pane{{ background: var(--right-bg); padding: 20px; border-radius: 12px; }}

.nav-item button[kind="secondary"]{{ width:100%; text-align:left; background: {"#111827" if is_dark else "#f8fafc"}!important; color: var(--text)!important; border-radius:12px!important; padding:10px 12px!important; }}
.nav-item:hover button[kind="secondary"]{{ background:{"#0b1220" if is_dark else "#e2e8f0"}!important; }}
.nav-item.active button[kind="secondary"]{{ background:{"#0b172a" if is_dark else "#cbd5e1"}!important; color: var(--text)!important; border:1px solid {accent}!important; box-shadow:0 0 0 2px rgba(37,99,235,.25); }}

.chat-card{{ border:none; box-shadow:none; background:transparent; }}
.chat-header{{ padding:12px 16px; font-weight:800; color:var(--text); display:flex; align-items:center; gap:.6rem; border:none; background:transparent; }}
.chat-header .badge{{ font-size:11px; border:1px solid var(--border); padding:2px 8px; border-radius:999px; opacity:.9 }}
.chat-body{{ padding:16px; max-height:66vh; overflow-y:auto; background:transparent; color:var(--text); }}

.msg-row{{ display:flex; gap:10px; margin:10px 0; }}
.msg{{ padding:12px 14px; border-radius:16px; border:1px solid var(--border); max-width:78%; line-height:1.5; font-size:15px; }}
.msg .meta{{ font-size:11px; color:var(--muted); margin-top:6px; }}
.msg.ai{{ background:var(--bubble-ai); color:{"#e5e7eb" if is_dark else "#1f2b3a"}; }}
.msg.user{{ background:var(--bubble-user); color:{"#fef9c3" if is_dark else "#2b2b2b"}; margin-left:auto; }}

.composer{{ position: sticky; bottom: 0; background: var(--panel); border-top:1px solid var(--border); padding: 12px 16px; border-bottom-left-radius:16px; border-bottom-right-radius:16px; }}

.chips{{ display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }}
.chip{{ font-size:12px; border:1px solid var(--border); padding:2px 8px; border-radius:999px; opacity:.85; }}

.chat-footer{{ padding:10px 16px; color:var(--muted); }}
</style>
""",
    unsafe_allow_html=True,
)

# LAYOUT
left, right = st.columns([0.28, 0.72], gap="large")

# LEFT PANE
with left:
    st.markdown('<div class="left-pane">', unsafe_allow_html=True)
    col_logo, col_toggle = st.columns([1, 1])
    with col_logo:
        try:
            st.image("images/Nuovo_Logo.png", width=180)
        except Exception:
            st.markdown("")
    with col_toggle:
        st.write("")
        st.selectbox(
            "Tema",
            options=["chiaro", "scuro"],
            index=1 if is_dark else 0,
            key="theme",
            help="Cambia il tema della UI",
        )
        if ss.get("theme") != ("scuro" if is_dark else "chiaro"):
            st.rerun()
    st.markdown("---")
    nav_labels = [("📤 Origine", "Leggi documento"), ("💬 Chat", "Chat"), ("🕒 Cronologia", "Cronologia")]
    for label, value in nav_labels:
        active_cls = "nav-item active" if ss["nav"] == value else "nav-item"
        st.markdown(f'<div class="{active_cls}">', unsafe_allow_html=True)
        if st.button(label, key=f"nav_{value}", type="secondary", use_container_width=True):
            ss["nav"] = value
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

# RIGHT PANE
with right:
    st.markdown('<div class="right-pane">', unsafe_allow_html=True)
    st.title("BENVENUTO !")

    # ORIGINE
    if ss["nav"] == "Leggi documento":
        st.subheader("📤 Origine (indice)")
        if not search_client:
            st.warning("⚠️ Azure Search non configurato.")
        else:
            if documents_cache:
                paths = documents_cache
                import os as _os
                display = [_os.path.basename(p.rstrip("/")) or p for p in paths]
                idx = paths.index(ss["active_doc"]) if ss.get("active_doc") in paths else 0
                selected_label = st.selectbox("Seleziona documento", display, index=idx)
                selected_path = paths[display.index(selected_label)]
                cols = st.columns([1,1,2])
                with cols[0]:
                    if st.button("✅ Applica filtro"):
                        ss["active_doc"] = selected_path
                        st.success(f"Filtro attivo su: {selected_label}")
                with cols[1]:
                    if st.button("🔄 Rimuovi filtro"):
                        ss["active_doc"] = None
                        st.experimental_rerun()
                if ss.get("active_doc"):
                    st.caption(f"Documento attivo: **{_os.path.basename(ss['active_doc'])}**")
                colb1, colb2 = st.columns([1,2])
                with colb1:
                    if st.button("📥 Aggiorna elenco documenti"):
                        ss["documents_cache"] = []
                        st.experimental_rerun()
                with colb2:
                    if last_update:
                        st.caption(f"Elenco aggiornato alle {last_update}")
            else:
                if st.button("📥 Carica elenco documenti"):
                    from azure.search.documents.models import QueryType
                    res = search_client.search(
                        search_text="*",
                        facets=[f"{FILENAME_FIELD},count:200"],
                        top=0,
                        query_type=QueryType.SIMPLE,
                    )
                    facets = list(res.get_facets().get(FILENAME_FIELD, []))
                    paths = [f["value"] for f in facets] if facets else []
                    ss["documents_cache"] = paths
                    ss["documents_cache_time"] = datetime.now(local_tz).strftime("%d/%m/%Y %H:%M:%S")
                    st.experimental_rerun()
                else:
                    st.info("Premi il pulsante sopra per caricare l'elenco dei documenti.")

    # CRONOLOGIA
    elif ss["nav"] == "Cronologia":
        st.subheader("🕒 Cronologia")
        if not ss["chat_history"]:
            st.write("Nessun messaggio ancora.")
        else:
            for m in ss["chat_history"]:
                who = "👤 Tu" if m["role"] == "user" else "🤖 Assistente"
                st.markdown(f"**{who}** · _{m['ts']}_")
                st.markdown(m["content"])
                st.markdown("---")

    # CHAT
    else:
        st.markdown('<div class="chat-card">', unsafe_allow_html=True)
        st.markdown('<div class="chat-header">💬 EasyLook.DOC Chat <span class="badge">alpha</span></div>', unsafe_allow_html=True)
        st.markdown('<div class="chat-body">', unsafe_allow_html=True)

        for m in ss["chat_history"]:
            role_class = "user" if m["role"] == "user" else "ai"
            body = html.escape(m.get("content", "")).replace("\n", "<br>")
            meta = m.get("ts", "")
            html_block = (
                "<div class='msg-row'><div class='msg %s'>%s"
                "<div class='meta'>%s</div></div></div>"
            ) % (role_class, body, meta)
            st.markdown(html_block, unsafe_allow_html=True)

        # scroll automatico
        st.markdown(
            """
            <script>
            var chatBody = window.parent.document.querySelectorAll('.chat-body')[0];
            if (chatBody) {
                chatBody.scrollTop = chatBody.scrollHeight;
            }
            </script>
            """,
            unsafe_allow_html=True
        )

        st.markdown('</div>', unsafe_allow_html=True)  # chiude chat-body

        # Composer sticky con chat_input
        st.markdown('<div class="composer">', unsafe_allow_html=True)
        user_q = st.chat_input("Scrivi qui…")
        if user_q and user_q.strip():
            ss["chat_history"].append(
                {
                    "role": "user",
                    "content": user_q.strip(),
                    "ts": datetime.now(local_tz).strftime("%d/%m/%Y %H:%M:%S"),
                }
            )
            context_snippets = []
            sources = []
            try:
                if not search_client:
                    st.warning("Azure Search non disponibile. Risposta senza contesto.")
                else:
                    from azure.search.documents.models import QueryType
                    flt = safe_filter_eq(FILENAME_FIELD, ss.get("active_doc")) if ss.get("active_doc") else None
                    results = search_client.search(
                        search_text=user_q,
                        filter=flt,
                        top=3,
                        query_type=QueryType.SIMPLE,
                    )
                    for r in results:
                        snippet = r.get("chunk") or r.get("content") or r.get("text")
                        if snippet:
                            context_snippets.append(str(snippet)[:400])
                        fname = r.get(FILENAME_FIELD)
                        if fname and fname not in sources:
                            sources.append(fname)
            except Exception as e:
                st.error(f"Errore ricerca: {e}")

            try:
                messages = build_chat_messages(user_q, context_snippets)
                with st.spinner("Sto scrivendo…"):
                    resp = client.chat.completions.create(
                        model=AZURE_OPENAI_DEPLOYMENT,
                        messages=messages,
                        temperature=0.2,
                        max_tokens=900,
                    )
                ai_text = resp.choices[0].message.content if resp.choices else "(nessuna risposta)"
                if sources:
                    import os as _os
                    shown = [_os.path.basename(s.rstrip("/")) or s for s in sources]
                    uniq = list(dict.fromkeys(shown))
                    chips = "".join([f"<span class='chip'>📎 {html.escape(s)}</span>" for s in uniq[:8]])
                    ai_text += f"\n\n<div class='chips'>{chips}</div>"
                ss["chat_history"].append(
                    {
                        "role": "assistant",
                        "content": ai_text,
                        "ts": datetime.now(local_tz).strftime("%d/%m/%Y %H:%M:%S"),
                    }
                )
            except Exception as e:
                ss["chat_history"].append(
                    {
                        "role": "assistant",
                        "content": f"Si è verificato un errore durante la generazione della risposta: {e}",
                        "ts": datetime.now(local_tz).strftime("%d/%m/%Y %H:%M:%S"),
                    }
                )
            st.experimental_rerun()
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('<div class="chat-footer">Suggerimento: usa “Origine” per filtrare le risposte. Tema attuale: <b>' + (ss.get('theme') or 'chiaro') + '</b>.</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)