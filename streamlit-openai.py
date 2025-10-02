import os, html, re
import pytz
import streamlit as st
from datetime import datetime, timezone
from openai import AzureOpenAI
from azure.identity import ClientSecretCredential
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
import streamlit.components.v1 as components

st.set_page_config(page_title='EasyLook.DOC Chat', page_icon='💬', layout='wide')

# --------- CONFIG ---------
TENANT_ID = os.getenv('AZURE_TENANT_ID')
CLIENT_ID = os.getenv('AZURE_CLIENT_ID')
CLIENT_SECRET = os.getenv('AZURE_CLIENT_SECRET')
AZURE_OPENAI_ENDPOINT = os.getenv('AZURE_OPENAI_ENDPOINT')
AZURE_OPENAI_DEPLOYMENT = os.getenv('AZURE_OPENAI_DEPLOYMENT')
API_VERSION = os.getenv('AZURE_OPENAI_API_VERSION', '2024-05-01-preview')

AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")
FILENAME_FIELD = "metadata_storage_path"

# --------- TIMEZONE ---------
local_tz = pytz.timezone("Europe/Rome")
def ts_now_it():
    return datetime.now(local_tz).strftime("%d/%m/%Y %H:%M:%S")

# --------- HELPERS ---------
def spacer(n=1):
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
        "content": ("Sei un assistente che risponde SOLO in base ai documenti forniti nel contesto. "
                    "Se l'informazione non è presente, dillo chiaramente.")
    }
    ctx = "\n\n".join(["- " + s for s in context_snippets]) if context_snippets else "(nessun contesto)"
    user_msg = {"role": "user", "content": f"CONTEXTPASS:\n{ctx}\n\nDOMANDA:\n{user_q}"}
    return [sys_msg, user_msg]

# --------- CLIENTS ---------
try:
    credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)

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

# --------- STATE ---------
ss = st.session_state
ss.setdefault('chat_history', [])
ss.setdefault("active_doc", None)
ss.setdefault("nav", "Chat")

# preferenze modello/UI
ss.setdefault("temperature", 0.2)
ss.setdefault("max_tokens", 900)
ss.setdefault("show_context_used", False)
ss.setdefault("confirm_clear", False)

# ricerca: indice del match globale corrente
ss.setdefault("search_index", 0)
ss.setdefault("last_search_q", "")

# --------- STYLE ---------
CSS = """
<style>
:root{
  --yellow:#FDF6B4; --yellow-border:#FDF6B4;
  --ai-bg:#F1F6FA; --ai-border:#F1F6FA; --text:#1f2b3a;
  --vh: 100vh;          /* aggiornato via JS */
  --top-offset: 0px;    /* aggiornato via JS */
}

/* blocco scroll pagina e altezza fissa */
html, body{ height:100%; overflow:hidden; }
.stApp{ height:100vh; overflow:hidden !important; background:#f5f7fa !important; }
.block-container{
  max-width:1200px;
  min-height:100vh;
  height:100vh;
  position:relative;
  overflow:hidden;
}

/* colonna sinistra bianca (coerente con colonna Streamlit) */
.block-container::before{
  content:"";
  position:absolute;
  top:0; bottom:0; left:0;
  width:32%;    /* fascia bianca */
  background:#ffffff;
  box-shadow:inset -1px 0 0 #e5e7eb;
  pointer-events:none;
  z-index:-1;
}

.block-container > *{ position:relative; z-index:1; }

/* Card chat a tutta altezza (meno lo spazio sopra misurato) */
.chat-card{
  border:1px solid #e6eaf0;border-radius:14px;background:#fff;box-shadow:0 2px 8px rgba(16,24,40,.04);
  display:flex; flex-direction:column;
  height:calc(var(--vh) - var(--top-offset));
}
.chat-header{padding:12px 16px;border-bottom:1px solid #eef2f7;font-weight:800;color:#1f2b3a;}

/* corpo chat con scroll interno UNICO */
.chat-body{
  padding:14px;
  flex:1;
  min-height:0;
  overflow-y:auto;
  background:#fff;
  border-radius:0 0 14px 14px;
}

.msg-row{display:flex;gap:10px;margin:8px 0;}
.msg{padding:10px 14px;border-radius:16px;border:1px solid;max-width:78%;line-height:1.45;font-size:15px;}
.msg .meta{font-size:11px;opacity:.7;margin-top:6px;}
.msg.ai{background:var(--ai-bg);border-color:var(--ai-border);color:var(--text);}
.msg.user{background:var(--yellow);border-color:var(--yellow-border);color:#2b2b2b;margin-left:auto;}
.avatar{width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:14px;}
.avatar.ai{background:#d9e8ff;color:#123;}
.avatar.user{background:#fff0a6;color:#5a4a00;}
.small{font-size:12px;color:#5b6b7e;margin:6px 0 2px;}
.chat-footer{padding:10px 12px 12px;}

/* menu sinistro */
label[data-baseweb="radio"]>div:first-child{display:none!important;}
div[role="radiogroup"] label[data-baseweb="radio"]{
  display:flex!important;align-items:center;gap:8px;padding:8px 10px;border-radius:10px;cursor:pointer;user-select:none;
  margin-bottom:12px!important;border:1px solid #2F98C7;
}
div[role="radiogroup"] label[data-baseweb="radio"]:hover{background:#eef5ff;}

/* selezionato: sfondo blu + forza testo bianco anche nei figli */
label[data-baseweb="radio"]:has(input:checked){
  background:#2F98C7; color:#ffffff; font-weight:600;
}
label[data-baseweb="radio"]:has(input:checked),
label[data-baseweb="radio"]:has(input:checked) *{
  color:#ffffff !important;
}
div[role="radiogroup"] label[data-baseweb="radio"]:has(input:checked):hover{
  background:#2F98C7; color:#ffffff !important;
}

/* evidenziatore ricerca */
mark{ background:#fff59d; padding:0 .15em; border-radius:3px; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# --------- LAYOUT ---------
left, right = st.columns([0.32, 0.68], gap='large')  # coerente con la fascia bianca

# ===== LEFT PANE =====
with left:
    try:
        st.image('images/Nuovo_Logo.png', width=200)
    except Exception:
        st.markdown('')
    st.markdown('---')

    labels = {
        "📤 Origine": "Leggi documento",
        "💬 Chat": "Chat",
        "🕒 Cronologia": "Cronologia",
        "📂 Carica documenti": "Carica documenti",
    }
    choice = st.radio('', list(labels.keys()), index=1)
    nav = labels[choice]

    st.markdown('---')
    st.subheader("Impostazioni", divider="gray")
    ss.temperature = st.slider("Temperature", 0.0, 1.0, float(ss.temperature), 0.05, help="Creatività del modello")
    ss.max_tokens = st.slider("Max tokens risposta", 100, 2000, int(ss.max_tokens), 50)
    ss.show_context_used = st.toggle("Mostra contesto usato", value=bool(ss.show_context_used))

    st.markdown('---')
    st.subheader("Utility chat", divider="gray")
    col_util_a, col_util_b = st.columns(2)
    with col_util_a:
        if st.button("🧹 Svuota chat"):
            ss.confirm_clear = True
        if ss.confirm_clear:
            st.warning("Confermi di voler svuotare la chat?")
            cc1, cc2 = st.columns(2)
            with cc1:
                if st.button("✅ Conferma"):
                    ss['chat_history'] = []
                    ss.confirm_clear = False
                    st.rerun()
            with cc2:
                if st.button("❌ Annulla"):
                    ss.confirm_clear = False
    with col_util_b:
        if st.button("⬇️ Esporta chat"):
            if ss['chat_history']:
                md_lines = ["# Conversazione\n"]
                for m in ss['chat_history']:
                    who = "Utente" if m['role'] == 'user' else "Assistente"
                    ts = m.get('ts', '')
                    md_lines.append(f"**{who}** ({ts}):\n\n{m.get('content','')}\n")
                md_str = "\n".join(md_lines)
                st.download_button("Scarica .md", data=md_str, file_name="chat_export.md", mime="text/markdown")

    st.markdown("<div style='flex-grow:1'></div>", unsafe_allow_html=True)
    colA, colB = st.columns(2)
    with colA:
        try:
            st.image('images/logoRAEE.png', width=80)
        except Exception:
            st.markdown('')
    with colB:
        try:
            st.image('images/logoNPA.png', width=80)
        except Exception:
            st.markdown('')

# ===== RIGHT PANE =====
with right:
    st.title('BENVENUTO !')

    # Script per altezza dinamica e offset
    components.html("""
    <script>
    (function(){
      function setVH(){
        const h = window.innerHeight || document.documentElement.clientHeight;
        (window.parent.document || document).documentElement.style.setProperty('--vh', h + 'px');
      }
      function setTopOffset(){
        const doc = window.parent.document || document;
        const card = doc.querySelector('.chat-card');
        if(!card) return;
        const rect = card.getBoundingClientRect();
        const offset = Math.max(0, Math.round(rect.top));
        doc.documentElement.style.setProperty('--top-offset', offset + 'px');
      }
      function recompute(){ setVH(); setTopOffset(); }
      recompute();
      window.addEventListener('resize', recompute);
      const target = window.parent.document ? window.parent.document.body : document.body;
      if (target && 'ResizeObserver' in window){ new ResizeObserver(recompute).observe(target); }
    })();
    </script>
    """, height=0)

    if nav == 'Leggi documento':
        st.subheader('📄 Scegli il documento')
        st.info("Questa sezione verrà sistemata dopo. Nel frattempo usa la Chat.")

    elif nav == 'Chat':
        st.subheader('💬 Chiedi quello che vuoi')
        if search_client:
            st.info("Cercherò nei documenti indicizzati (Azure Search).")
        else:
            st.info("Azure Search non configurato: risponderò senza contesto.")

        # --- Ricerca nella chat (navigazione match) ---
        search_q = st.text_input("🔎 Cerca nella chat", value="", placeholder="Cerca messaggi…")
        if search_q != ss.last_search_q:
            ss.search_index = 0
            ss.last_search_q = search_q

        spacer(1)
        st.markdown("---")
        spacer(1)

        # --- util per timestamp e ricerca ---
        rome_tz = pytz.timezone("Europe/Rome")

        def fmt_ts(ts_raw: str) -> str:
            try:
                if "T" in ts_raw and ("+" in ts_raw or "Z" in ts_raw):
                    dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    return dt.astimezone(rome_tz).strftime('%d/%m %H:%M')
                return ts_raw
            except Exception:
                return ts_raw

        def count_occurrences(text: str, q: str) -> int:
            if not q:
                return 0
            return len(re.findall(re.escape(q), text, flags=re.IGNORECASE))

        def highlight_nth(text: str, q: str, global_idx: int):
            escaped = html.escape(text)
            if not q:
                return escaped.replace("\n", "<br>"), global_idx
            pat = re.compile(re.escape(q), re.IGNORECASE)
            matches = list(pat.finditer(escaped))
            if not matches:
                return escaped.replace("\n", "<br>"), global_idx
            if global_idx < len(matches):
                parts = []
                last_end = 0
                for i, m in enumerate(matches):
                    parts.append(escaped[last_end:m.start()])
                    if i == global_idx:
                        parts.append(f"<mark>{m.group(0)}</mark>")
                    else:
                        parts.append(m.group(0))
                    last_end = m.end()
                parts.append(escaped[last_end:])
                return "".join(parts).replace("\n", "<br>"), 0
            else:
                return escaped.replace("\n", "<br>"), global_idx - len(matches)

        if search_q:
            total_matches = sum(count_occurrences(m.get("content", ""), search_q) for m in ss["chat_history"])
        else:
            total_matches = 0
            ss.search_index = 0

        if search_q:
            st.caption(f"Risultati totali: {total_matches}")
            if total_matches > 0:
                colnav1, colnav2, colnav3 = st.columns([1,1,3])
                with colnav1:
                    if st.button("◀️ Precedente"):
                        ss.search_index = (ss.search_index - 1) % total_matches
                with colnav2:
                    if st.button("▶️ Successivo"):
                        ss.search_index = (ss.search_index + 1) % total_matches
                with colnav3:
                    st.markdown(f"Match corrente: **{(ss.search_index % total_matches) + 1 if total_matches else 0} / {total_matches}**")
            else:
                st.caption("Nessun risultato per questa ricerca.")

        # --- Card chat ---
        st.markdown('<div class="chat-card">', unsafe_allow_html=True)
        st.markdown('<div class="chat-header">Conversazione</div>', unsafe_allow_html=True)

        messages_to_show = ss["chat_history"]

        # Corpo messaggi (scroll solo qui)
        st.markdown('<div class="chat-body" id="chat-body">', unsafe_allow_html=True)
        if not messages_to_show:
            st.markdown('<div class="small">Nessun messaggio. Fai una domanda.</div>', unsafe_allow_html=True)
        else:
            remaining_idx = (ss.search_index % total_matches) if (search_q and total_matches > 0) else 0
            for m in messages_to_show:
                role = m['role']
                raw_text = m.get('content', '')
                if search_q and total_matches > 0:
                    content_html, remaining_idx = highlight_nth(raw_text, search_q, remaining_idx)
                else:
                    content_html = html.escape(raw_text).replace("\n", "<br>")
                ts = fmt_ts(m.get('ts',''))
                if role == 'user':
                    st.markdown(f"""
                        <div class='msg-row' style='justify-content:flex-end;'>
                          <div class='msg user'>{content_html}<div class='meta'>{ts}</div></div>
                          <div class='avatar user'>U</div>
                        </div>""", unsafe_allow_html=True)
                else:
                    st.markdown(f"""
                        <div class='msg-row'>
                          <div class='avatar ai'>A</div>
                          <div class='msg ai'>{content_html}<div class='meta'>{ts}</div></div>
                        </div>""", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)  # chiude chat-body

        # placeholder per spinner SOPRA al form
        typing_ph = st.empty()

        # autoscroll nel box chat
        components.html("""
            <script>
            const el = window.parent.document.getElementById('chat-body');
            if (el) { el.scrollTop = el.scrollHeight; }
            </script>
        """, height=0)

        # Footer input
        st.markdown('<div class="chat-footer">', unsafe_allow_html=True)
        with st.form(key="chat_form", clear_on_submit=True):
            user_q = st.text_input("Scrivi la tua domanda", value="")
            sent = st.form_submit_button("Invia")
        st.markdown('</div>', unsafe_allow_html=True)   # chiude chat-footer
        st.markdown('</div>', unsafe_allow_html=True)   # chiude chat-card  ✅ (questa mancava)

        # Invio: cerca su Azure Search + chiamata modello
        if sent and user_q.strip():
            ss['chat_history'].append({'role': 'user', 'content': user_q.strip(), 'ts': ts_now_it()})

            # Ricerca nel motore
            context_snippets, sources = [], []
            try:
                if not search_client:
                    st.warning("Azure Search non disponibile. Risposta senza contesto.")
                else:
                    flt = safe_filter_eq(FILENAME_FIELD, ss.get("active_doc")) if ss.get("active_doc") else None
                    results = search_client.search(
                        search_text=user_q,
                        filter=flt,
                        top=5,
                        query_type="simple",
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

            # Chiamata modello
            try:
                messages = build_chat_messages(user_q, context_snippets)
                with typing_ph, st.spinner("Sto scrivendo…"):
                    resp = client.chat.completions.create(
                        model=AZURE_OPENAI_DEPLOYMENT,
                        messages=messages,
                        temperature=float(ss.temperature),
                        max_tokens=int(ss.max_tokens),
                    )
                typing_ph.empty()
                ai_text = resp.choices[0].message.content if resp.choices else "(nessuna risposta)"

                if sources:
                    import os as _os
                    shown = [_os.path.basename(s.rstrip("/")) or s for s in sources]
                    uniq = list(dict.fromkeys(shown))
                    ai_text += "\n\n— 📎 Fonti: " + ", ".join(uniq[:6])

                ss['chat_history'].append({'role': 'assistant', 'content': ai_text, 'ts': ts_now_it()})

                if ss.show_context_used and (context_snippets or sources):
                    with st.expander("Contesto usato per questa risposta"):
                        if sources:
                            st.markdown("**Fonti individuate**")
                            for s in sources[:6]:
                                if isinstance(s, str) and (s.startswith("http://") or s.startswith("https://")):
                                    st.markdown(f"- [{s}]({s})")
                                else:
                                    st.markdown(f"- {s}")
                        if context_snippets:
                            st.markdown("**Snippet (max 400 char ciascuno)**")
                            for i, sn in enumerate(context_snippets, 1):
                                st.code(sn, language="markdown")

            except Exception as e:
                typing_ph.empty()
                ss['chat_history'].append({'role': 'assistant', 'content': f"Si è verificato un errore durante la generazione della risposta: {e}", 'ts': ts_now_it()})
            st.rerun()