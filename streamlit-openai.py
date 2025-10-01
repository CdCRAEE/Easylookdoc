import os
import html
import streamlit as st
from datetime import datetime, timezone
from openai import AzureOpenAI
from azure.identity import ClientSecretCredential
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential

st.set_page_config(page_title="EasyLook.DOC Chat", page_icon="💬", layout="wide")

# ========= CONFIG =========
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")

AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX = "azureblob-index"            # <== il tuo indice
FILENAME_FIELD = "metadata_storage_path"          # <== campo documento (path completo)

# ========= HELPERS =========
def spacer(n=1):
    """Inserisce n righe vuote per creare spazio verticale."""
    for _ in range(n):
        st.write("")

def safe_filter_eq(field, value):
    """OData filter: field eq 'value' con escape apici singoli."""
    if not value:
        return None
    safe_value = str(value).replace("'", "''")
    return f"{field} eq '{safe_value}'"

def build_chat_messages(user_q, context_snippets):
    sys_msg = {
        "role": "system",
        "content": ("Sei un assistente che risponde SOLO in base ai documenti forniti nel contesto. "
                    "Se l'informazione non è presente, dillo chiaramente."),
    }
    ctx = "\n\n".join(["- " + s for s in context_snippets]) if context_snippets else "(nessun contesto)"
    user_msg = {"role": "user", "content": f"CONTEXTPASS:\n{ctx}\n\nDOMANDA:\n{user_q}"}
    return [sys_msg, user_msg]

# ========= CLIENTS =========
try:
    credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)

    # Token reuse AAD (buffer 5 minuti)
    now_ts = datetime.now(timezone.utc).timestamp()
    refresh = True
    if "aad_token" in st.session_state and "aad_exp" in st.session_state:
        if now_ts < st.session_state["aad_exp"] - 300:
            refresh = False
    if refresh:
        access = credential.get_token("https://cognitiveservices.azure.com/.default")
        st.session_state["aad_token"] = access.token
        st.session_state["aad_exp"] = access.expires_on

    client = AzureOpenAI(
        api_version=API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_ad_token=st.session_state["aad_token"],
    )

    # SearchClient reuse
    search_key_tuple = (AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_KEY, AZURE_SEARCH_INDEX)
    if "search_client" not in st.session_state or st.session_state.get("search_key") != search_key_tuple:
        if AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY and AZURE_SEARCH_INDEX:
            st.session_state["search_client"] = SearchClient(
                endpoint=AZURE_SEARCH_ENDPOINT,
                index_name=AZURE_SEARCH_INDEX,
                credential=AzureKeyCredential(AZURE_SEARCH_KEY),
            )
            st.session_state["search_key"] = search_key_tuple
    search_client = st.session_state.get("search_client")

except Exception as e:
    st.error(f"Errore inizializzazione Azure OpenAI/Search: {e}")
    st.stop()

# ========= STATE =========
ss = st.session_state
ss.setdefault("chat_history", [])
ss.setdefault("active_doc", None)
ss.setdefault("nav", "Chat")   # default pannello destro

# ========= STYLE =========
st.markdown(
    """
<style>
/* Card bianca a sinistra */
.left-pane{
  background:#ffffff;
  padding:12px;
  border-radius:12px;
  border:1px solid #e5e7eb;
}
/* Nav menu custom (niente pallini) */
.nav-item button[kind="secondary"]{
  width:100%;
  text-align:left;
  border:0 !important;
  background:#f8fafc !important;
  color:#0f172a !important;
  border-radius:10px !important;
  padding:10px 12px !important;
  box-shadow:none !important;
}
.nav-item:hover button[kind="secondary"]{
  background:#e2e8f0 !important; /* hover */
}
.nav-item.active button[kind="secondary"]{
  background:#dbeafe !important; /* selezionato */
  color:#0c4a6e !important;
  font-weight:600 !important;
  border:1px solid #bfdbfe !important;
}
/* Chat card */
.chat-card{border:1px solid #e6eaf0;border-radius:14px;background:#fff;box-shadow:0 2px 8px rgba(16,24,40,.04);}
.chat-header{padding:12px 16px;border-bottom:1px solid #eef2f7;font-weight:800;color:#1f2b3a;}
.chat-body{padding:14px;max-height:70vh;overflow-y:auto;background:#fff;border-radius:0 0 14px 14px;}
.msg-row{display:flex;gap:10px;margin:8px 0;}
.msg{padding:10px 14px;border-radius:16px;border:1px solid;max-width:78%;line-height:1.45;font-size:15px;}
.msg .meta{font-size:11px;opacity:.7;margin-top:6px;}
.msg.ai{background:#F1F6FA;border-color:#F1F6FA;color:#1f2b3a;}
.msg.user{background:#FDF6B4;border-color:#FDF6B4;color:#2b2b2b;margin-left:auto;}
</style>
""",
    unsafe_allow_html=True,
)

# ========= LAYOUT =========
left, right = st.columns([0.28, 0.72], gap="large")

# ----- LEFT PANE (menu + loghi dentro card bianca) -----
with left:
    st.markdown('<div class="left-pane">', unsafe_allow_html=True)
    try:
        st.image("images/Nuovo_Logo.png", width=200)
    except Exception:
        st.markdown("")

    st.markdown("---")

    # NAV senza pallini: 3 pulsanti con hover/active
    nav_labels = [("📤 Origine", "Leggi documento"), ("💬 Chat", "Chat"), ("🕒 Cronologia", "Cronologia")]
    for label, value in nav_labels:
        active_cls = "nav-item active" if ss["nav"] == value else "nav-item"
        st.markdown(f'<div class="{active_cls}">', unsafe_allow_html=True)
        if st.button(label, key=f"nav_{value}", type="secondary", use_container_width=True):
            ss["nav"] = value
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    # loghi in basso
    spacer(3)
    colA, colB = st.columns([1, 1])
    with colA:
        try:
            st.image("images/logoRAEE.png", width=80)
        except Exception:
            st.markdown("")
    with colB:
        try:
            st.image("images/logoNPA.png", width=80)
        except Exception:
            st.markdown("")

    st.markdown("</div>", unsafe_allow_html=True)  # chiude left-pane

# ----- RIGHT PANE (contenuti) -----
with right:
    st.title("BENVENUTO !")

    # =================== ORIGINE ===================
    if ss["nav"] == "Leggi documento":
        st.subheader("📤 Origine (indice)")
        if not search_client:
            st.warning("⚠️ Azure Search non configurato.")
        else:
            try:
                res = search_client.search(
                    search_text="*",
                    facets=[f"{FILENAME_FIELD},count:1000"],
                    top=0,
                )
                facets = list(res.get_facets().get(FILENAME_FIELD, []))
                paths = [f["value"] for f in facets] if facets else []

                if not paths:
                    st.info("Nessun documento trovato. Verifica che il campo sia 'Facetable' e che l'indice sia popolato.")
                else:
                    import os as _os
                    display = [_os.path.basename(p.rstrip("/")) or p for p in paths]
                    idx = paths.index(ss["active_doc"]) if ss.get("active_doc") in paths else 0
                    selected_label = st.selectbox("Seleziona documento", display, index=idx)
                    selected_path = paths[display.index(selected_label)]
                    if selected_path != ss.get("active_doc"):
                        ss["active_doc"] = selected_path
                        st.success(f"Filtro attivo su: {selected_label}")
                    if st.button("🔄 Usa tutti i documenti (rimuovi filtro)"):
                        ss["active_doc"] = None
                        st.rerun()
            except Exception as e:
                st.error(f"Errore nel recupero dell'elenco documenti: {e}")

    # =================== CRONOLOGIA ===================
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

    # =================== CHAT ===================
    else:  # 'Chat'
        st.markdown('<div class="chat-card">', unsafe_allow_html=True)
        st.markdown('<div class="chat-header">EasyLook.DOC Chat</div>', unsafe_allow_html=True)
        st.markdown('<div class="chat-body">', unsafe_allow_html=True)

        # storico chat (niente f-string complesse)
        for m in ss["chat_history"]:
            role_class = "user" if m["role"] == "user" else "ai"
            body = html.escape(m.get("content", "")).replace("\n", "<br>")
            meta = m.get("ts", "")
            html_block = (
                "<div class='msg-row'><div class='msg %s'>%s"
                "<div class='meta'>%s</div></div></div>"
            ) % (role_class, body, meta)
            st.markdown(html_block, unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)  # chiude chat-body

        # --- FORM CHAT ---
        with st.form("chat_form", clear_on_submit=True):
            user_q = st.text_area(
                "Scrivi qui…",
                height=90,
                placeholder="Fai una domanda sui documenti indicizzati…",
            )
            submitted = st.form_submit_button("Invia")

            if submitted and user_q.strip():
                # append utente
                ss["chat_history"].append(
                    {
                        "role": "user",
                        "content": user_q.strip(),
                        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )

                # --- RICERCA NEL MOTORE ---
                context_snippets = []
                sources = []
                try:
                    if not search_client:
                        st.warning("Azure Search non disponibile. Risposta senza contesto.")
                    else:
                        flt = safe_filter_eq(FILENAME_FIELD, ss.get("active_doc")) if ss.get("active_doc") else None
                        results = search_client.search(
                            search_text=user_q,
                            filter=flt,
                            top=5,
                            query_type="simple",  # per Semantic: query_type="semantic", semantic_configuration_name="default"
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

                # --- CHIAMATA MODELLO ---
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

                    # Fonti (basename per leggibilità)
                    if sources:
                        import os as _os
                        shown = [_os.path.basename(s.rstrip("/")) or s for s in sources]
                        uniq = list(dict.fromkeys(shown))
                        ai_text += "\n\n— 📎 Fonti: " + ", ".join(uniq[:6])

                    ss["chat_history"].append(
                        {
                            "role": "assistant",
                            "content": ai_text,
                            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        }
                    )
                except Exception as e:
                    ss["chat_history"].append(
                        {
                            "role": "assistant",
                            "content": f"Si è verificato un errore durante la generazione della risposta: {e}",
                            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        }
                    )

                st.rerun()

        st.markdown('<div class="chat-footer">Suggerimento: seleziona un documento in “Origine” per filtrare le risposte.</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)  # chiude chat-card
