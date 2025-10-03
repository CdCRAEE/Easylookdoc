import os, html, re, unicodedata, datetime as dt
import pytz
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, timezone
from openai import AzureOpenAI
from azure.identity import ClientSecretCredential, DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from azure.storage.blob import BlobServiceClient, BlobSasPermissions, generate_blob_sas
from io import BytesIO  # per eventuali export futuri
import base64 as _b64, posixpath as _pp
from urllib.parse import urlparse as _urlparse, urlunparse as _urlunparse, unquote as _unquote

# ======================= APP CONFIG =======================
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
FILENAME_FIELD = "metadata_storage_path"  # campo usato per filtrare per file

ACCOUNT_NAME = "cdcraeeaieastus"
CONTAINER_OVERRIDES = {
    # "utente.particolare@cdcraee.it": "c-x-cognome-personalizzato",
}

# --------- TIMEZONE ---------
local_tz = pytz.timezone("Europe/Rome")
def ts_now_it():
    return datetime.now(local_tz).strftime("%d/%m/%Y %H:%M:%S")

# ======================= HELPERS =======================
_B64_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/_-=")

def _looks_like_b64(s: str) -> bool:
    if not s or len(s) < 8 or " " in s:
        return False
    return all(c in _B64_CHARS for c in s)

def _pad_b64(s: str) -> str:
    return s + "=" * ((4 - (len(s) % 4)) % 4)

def decode_maybe_b64(s: str) -> str:
    """Se sembra Base64 (anche URL-safe), decodifica; altrimenti restituisce s."""
    if not _looks_like_b64(s):
        return s
    try:
        return _b64.urlsafe_b64decode(_pad_b64(s)).decode("utf-8")
    except Exception:
        try:
            return _b64.b64decode(_pad_b64(s)).decode("utf-8")
        except Exception:
            return s

def clean_azure_blob_url(url: str) -> str:
    """Rimuove query/SAS e lascia solo schema+host+path."""
    try:
        u = _urlparse(url)
        return _urlunparse((u.scheme, u.netloc, u.path, "", "", ""))
    except Exception:
        return url

def display_name_from_url(url: str) -> str:
    base = _pp.basename(url.rstrip("/")) or url.strip("/")
    return _unquote(base).replace("_", " ").replace("-", " ")

def normalize_source_id(raw: str) -> tuple[str, str]:
    """
    Converte un ID/URL (anche codificato Base64) in (url_pulito, nome_file).
    Se non è un URL, torna (decoded, decoded).
    """
    decoded = decode_maybe_b64(raw)
    if isinstance(decoded, str) and decoded.startswith(("http://", "https://")):
        clean = clean_azure_blob_url(decoded)
        return clean, display_name_from_url(clean)
    return decoded, decoded

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

def fmt_ts(ts_raw: str) -> str:
    try:
        if "T" in ts_raw and ("+" in ts_raw or "Z" in ts_raw):
            dtv = datetime.fromisoformat(ts_raw.replace("Z","+00:00"))
            return dtv.astimezone(local_tz).strftime('%d/%m %H:%M')
        return ts_raw
    except Exception:
        return ts_raw

def highlight_nth(text: str, q: str, global_idx: int):
    escaped = html.escape(text)
    if not q or (isinstance(global_idx, int) and global_idx < 0):
        return escaped.replace("\n", "<br>"), global_idx

    pat = re.compile(re.escape(q), re.IGNORECASE)
    matches = list(pat.finditer(escaped))
    if not matches:
        return escaped.replace("\n", "<br>"), global_idx

    if global_idx < len(matches):
        parts, last_end = [], 0
        for i, m in enumerate(matches):
            parts.append(escaped[last_end:m.start()])
            parts.append(f"<mark>{m.group(0)}</mark>" if i == global_idx else m.group(0))
            last_end = m.end()
        parts.append(escaped[last_end:])
        return "".join(parts).replace("\n", "<br>"), -1
    else:
        return escaped.replace("\n", "<br>"), global_idx - len(matches)

def _slugify_ascii(s: str) -> str:
    """Normalizza accenti e rimuove caratteri non ammessi."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s

def upn_to_container(upn: str) -> str:
    """
    Converte 'nome.cognome@dominio' -> 'c-n-cognome'
    """
    upn_l = upn.strip().lower()
    if upn_l in CONTAINER_OVERRIDES:
        return CONTAINER_OVERRIDES[upn_l]

    left = upn_l.split("@", 1)[0]
    parts = [p for p in re.split(r"[^a-z0-9]+", left) if p]
    if not parts:
        return "c-u-user"

    first = parts[0]
    last = parts[-1] if len(parts) > 1 else parts[0]
    initial = _slugify_ascii(first)[:1] or "x"
    surname = _slugify_ascii(last) or "user"

    name = f"c-{initial}-{surname}"
    name = re.sub(r"-+", "-", name).strip("-")
    if len(name) < 3:
        name = (name + "000")[:3]
    if len(name) > 63:
        name = name[:63].rstrip("-")
    if not re.match(r"^[a-z0-9].*[a-z0-9]$", name):
        name = re.sub(r"^[^a-z0-9]+", "", name)
        name = re.sub(r"[^a-z0-9]+$", "", name)
        if len(name) < 3:
            name = "c-u-user"
    return name

@st.cache_resource(show_spinner=False)
def _svc():
    cred = DefaultAzureCredential()
    return BlobServiceClient(f"https://{ACCOUNT_NAME}.blob.core.windows.net", credential=cred)

def make_upload_sas(container: str, blob_name: str, ttl_minutes: int = 10) -> str:
    svc = _svc()
    # Delegation key valida pochi minuti
    now = dt.datetime.utcnow()
    udk = svc.get_user_delegation_key(now - dt.timedelta(minutes=1), now + dt.timedelta(minutes=ttl_minutes))
    sas = generate_blob_sas(
        account_name=ACCOUNT_NAME,
        container_name=container,
        blob_name=blob_name,
        user_delegation_key=udk,
        permission=BlobSasPermissions(create=True, write=True),
        expiry=now + dt.timedelta(minutes=ttl_minutes),
    )
    return f"https://{ACCOUNT_NAME}.blob.core.windows.net/{container}/{blob_name}?{sas}"

def ensure_container(svc: BlobServiceClient, container: str):
    """Crea il container se non esiste (idempotente)."""
    try:
        svc.create_container(container)
    except Exception:
        pass

def sas_for_user_blob(upn: str, blob_name: str, ttl_minutes: int = 15) -> str:
    """Deriva il container dall'UPN e genera una SAS di upload."""
    container = upn_to_container(upn)
    svc = _svc()
    ensure_container(svc, container)
    return make_upload_sas(container, blob_name, ttl_minutes=ttl_minutes)

# ======================= CLIENTS =======================
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

    # SearchClient in sessione
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

# ======================= STATE =======================
ss = st.session_state
ss.setdefault('chat_history', [])
ss.setdefault("active_doc", None)     # filtro documento correntemente selezionato
ss.setdefault("nav", "Chat")
ss.setdefault("search_index", 0)
ss.setdefault("last_search_q", "")
ss.setdefault("saved_chats", [])      # [{id, name, created_at, history}]
ss.setdefault("save_open", False)

# ======================= STYLE =======================
CSS = """
<style>
:root{
  --yellow:#FDF6B4; --yellow-border:#FDF6B4;
  --ai-bg:#F1F6FA; --ai-border:#F1F6FA; --text:#1f2b3a;
  --vh: 100vh;
  --top-offset: 0px;
}
.stApp{
  background-image:
    linear-gradient(to right, #ffffff 0, #ffffff 32%, rgba(255,255,255,0) 32%),
    linear-gradient(to right, #e5e7eb, #e5e7eb);
  background-repeat: no-repeat, no-repeat;
  background-size: 100% 100%, 1px 100%;
  background-position: 0 0, 32% 0;
}
.chat-card{
  border:1px solid #e6eaf0;
  border-radius:14px;
  background:#fff;
  box-shadow:0 2px 8px rgba(16,24,40,.04);
  display:grid;
  grid-template-rows:auto minmax(0,1fr) auto;
  min-height: calc(var(--vh) - var(--top-offset));
  overflow: visible;
}
.chat-header{
  padding:12px 16px;
  border-bottom:1px solid #eef2f7;
  font-weight:800;
  color:#1f2b3a;
}
.chat-body{
  padding:14px;
  overflow:auto;
  min-height:0;
  background:#fff;
  -webkit-overflow-scrolling: touch;
  overscroll-behavior: auto;
}
.chat-footer{
  padding:10px 12px 12px;
  border-top:1px solid #eef2f7;
  border-radius:0 0 14px 14px;
  background:#fff;
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
label[data-baseweb="radio"]>div:first-child{display:none!important;}
div[role="radiogroup"] label[data-baseweb="radio"]{
  display:flex!important;align-items:center;gap:8px;padding:8px 10px;border-radius:10px;cursor:pointer;user-select:none;
  margin-bottom:12px!important;border:1px solid #2F98C7;
}
div[role="radiogroup"] label[data-baseweb="radio"]:hover{background:#eef5ff;}
label[data-baseweb="radio"]:has(input:checked){background:#2F98C7;color:#ffffff;font-weight:600;}
label[data-baseweb="radio"]:has(input:checked),
label[data-baseweb="radio"]:has(input:checked) *{color:#ffffff !important;}
.stButton>button{border:1px solid #2F98C7 !important;color:#2F98C7 !important;background:#fff !important;border-radius:8px !important;}
.stButton>button:hover{background:#eef5ff !important;}
div[data-testid="column"] > div:first-child { position: static; min-height: 0; height: auto; overflow: visible; }
html, body, .stApp { height: auto !important; overflow: auto !important; }
#search-nav .stButton>button{padding:4px 10px;font-size:12px;line-height:1.1;height:auto;border-radius:8px;}
#search-nav .counter{font-size:12px;color:#1f2b3a;display:flex; align-items:center; height:100%;}
mark{ background:#C8E7EA; padding:0 .15em; border-radius:3px; }

/* === NO WRAP per i bottoni della chat === */
#chat-buttons .stButton > button{
  white-space: nowrap !important;
  padding-left: 14px !important;
  padding-right: 14px !important;
}

</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ======================= LAYOUT =======================
left, right = st.columns([0.32, 0.68], gap='large')

# ===== LEFT PANE =====
with left:
    # --- Loghi sopra al menù, allineati a destra e vicini ---
    l1, l2, l3 = st.columns([6, 1, 1])
    with l2:
        try: st.image('images/logoRAEE.png', width=80)
        except Exception: pass
    with l3:
        try: st.image('images/logoNPA.png', width=80)
        except Exception: pass
    st.markdown("<div style='margin-top:-6px;'></div>", unsafe_allow_html=True)
    try:
        st.image('images/Nuovo_Logo.png', width=200)
    except Exception:
        st.markdown('')
    st.markdown('---')

    labels = {
    labels = {
        "📂 Documenti": "Leggi documento",
        "💬 Chat": "Chat",
        "🕒 Cronologia": "Cronologia",
    }
    ss.setdefault("main_nav", "💬 Chat")  # default
    '',
    list(labels.keys()),
    index=list(labels.keys()).index(ss["main_nav"]) if ss.get("main_nav") in labels else 1,
    key="main_nav"  # <— la radio è legata a questa chiave
)
nav = labels[choice]

    spacer(10)
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

    # ======= DOCUMENTI: elenco documenti + filtro =======
    if nav == 'Leggi documento':
        st.subheader("📤 Documenti")
        if not search_client:
            st.warning("⚠️ Azure Search non configurato.")
        else:
            try:
                # recupero facet con l'elenco dei file (usa il campo FILENAME_FIELD)
                res = search_client.search(
                    search_text="*",
                    facets=[f"{FILENAME_FIELD},count:1000"],
                    top=0,
                )
                facets = list(res.get_facets().get(FILENAME_FIELD, []))
                paths = [f["value"] for f in facets] if facets else []

                if not paths:
                    st.info("Nessun documento trovato nell'indice (controlla che il campo sia facetable e l'indice popolato).")
                else:
                    # Costruisco coppie (nome_legibile, path) per evitare ambiguità in caso di nomi duplicati
                    display_items = [(normalize_source_id(p)[1], p) for p in paths]
                    names = [n for n, _ in display_items]

                    # Opzione per nessun filtro
                    ALL_OPT = "— Tutti i documenti —"
                    options = [ALL_OPT] + names

                    # indice di default: 0 se nessun filtro, altrimenti file selezionato +1
                    if ss.get("active_doc") in paths:
                        default_idx = 1 + paths.index(ss["active_doc"])
                    else:
                        default_idx = 0

                    if ss.get("reset_doc_select", False):
    if "doc_select" in st.session_state:
        del st.session_state["doc_select"]
    ss["reset_doc_select"] = False  # consumo il flag

display_items = [(normalize_source_id(p)[1], p) for p in paths]
names = [n for n, _ in display_items]

ALL_OPT = "— Tutti i documenti —"
options = [ALL_OPT] + names

if ss.get("active_doc") in paths:
    default_idx = 1 + paths.index(ss["active_doc"])
else:
    default_idx = 0

selected_label = st.selectbox(
    "Seleziona documento", options, index=default_idx, key="doc_select"
)

if selected_label == ALL_OPT:
    if ss.get("active_doc") is not None:
        ss["active_doc"] = None
        st.info("Filtro rimosso: userai tutti i documenti.")
else:
    selected_path = dict(display_items)[selected_label]
    if selected_path != ss.get("active_doc"):
        ss["active_doc"] = selected_path
        st.success(f"Filtro attivo su: {selected_label}")

                    # (opzionale) bottone che sincronizza anche la select
                    if st.button("Usa tutti i documenti (rimuovi filtro)"):
                        ss["active_doc"] = None
                        ss["doc_select"] = ALL_OPT
                        st.rerun()

            except Exception as e:
                st.error(f"Errore nel recupero dell'elenco documenti: {e}")

        # ======= SEZIONE: Upload per-utente con SAS =======
        st.divider()
        with st.expander("📂 Carica un nuovo documento"):
            upn_val = st.text_input(
                "Inserisci la tua mail",
                value=ss.get("user_upn", ""),
                placeholder="nome.cognome@cdcraee.it",
                key="user_upn"
            )
            # ⚠️ non scrivere su ss["user_upn"] perché è la stessa key del widget

            if ss.get("user_upn"):  # il widget popola direttamente ss["user_upn"]
                uploaded = st.file_uploader(
                    "Seleziona un file da caricare nel tuo contenitore personale",
                    type=["pdf", "docx", "txt", "md"],
                    accept_multiple_files=False
                )

                if uploaded is not None:
                    blob_name = f"uploads/{int(dt.datetime.utcnow().timestamp())}_{uploaded.name}"
                    try:
                        upn_norm = ss["user_upn"].strip().lower()
                        upload_url = sas_for_user_blob(
                            upn_norm,
                            blob_name,
                            ttl_minutes=15
                        )
                        st.success(f"Documento correttamente caricato su {upn_norm}")
                    except Exception as e:
                        st.error(f"Impossibile generare la SAS: {e}")
            else:
                st.warning("Inserisci l'email utente (UPN) qui sopra per generare la SAS del tuo contenitore.")

    # ======= CHAT =======
    elif nav == 'Chat':
        st.subheader('💬 Chiedi quello che vuoi')

        # Messaggio dinamico su dove cerco
        if search_client:
            if ss.get("active_doc"):
                _, nice_name = normalize_source_id(ss["active_doc"])
                st.info(f"Cercherò nel documento: {nice_name}")
            else:
                st.info("Cercherò in tutti i documenti")
        else:
            st.info("Azure Search non configurato: risponderò senza contesto.")

        # --- Pulsanti utilità (Esporta → Svuota → Salva)
        col_e, col_c, col_s, _ = st.columns([2, 2, 2, 6])

        with col_e:
            if st.button("Esporta chat (.md)"):
                if ss['chat_history']:
                    md_lines = ["# Conversazione\n"]
                    for m in ss['chat_history']:
                        who = "Utente" if m['role'] == 'user' else "Assistente"
                        ts = m.get('ts', '')
                        md_lines.append(f"**{who}** ({ts}):\n\n{m.get('content','')}\n")
                    md_str = "\n".join(md_lines)
                    st.download_button(
                        "Scarica .md",
                        data=md_str,
                        file_name="chat_export.md",
                        mime="text/markdown"
                    )

        with col_s:
    # Toggle: quando apro il form inizializzo il nome SOLO una volta
    if st.button("Salva chat"):
        if not ss.get("save_open", False):
            ss["save_open"] = True
            ss["save_name"] = f"Chat del {ts_now_it()}"  # inizializzo il default
        else:
            ss["save_open"] = False
            if "save_name" in ss:
                del ss["save_name"]
        st.markdown('</div>', unsafe_allow_html=True)

# --- Form di salvataggio (mostrato quando richiesto) ---
if ss.get("save_open"):
    with st.form("save_chat_form", clear_on_submit=False):
        # IMPORTANTE: usiamo SOLO la chiave, niente `value=` qui
        save_name = st.text_input(
            "Nome del salvataggio",
            key="save_name",
            help="Dai un nome a questa chat"
        )
        do_save = st.form_submit_button("Conferma salvataggio")

    if do_save:
        if not ss['chat_history']:
            st.warning("Non c'è nulla da salvare: la chat è vuota.")
        else:
            import uuid
            # prendo il nome dallo stato (se vuoto, ricado sul default al momento del salvataggio)
            final_name = (ss.get("save_name") or "").strip() or f"Chat del {ts_now_it()}"
            entry = {
                "id": str(uuid.uuid4()),
                "name": final_name,
                "created_at": ts_now_it(),
                "history": list(ss['chat_history'])  # copia
            }
            ss['saved_chats'].insert(0, entry)
            # chiudo e pulisco lo stato del form
            ss["save_open"] = False
            if "save_name" in ss:
                del ss["save_name"]
            st.success(f"Chat salvata come: {entry['name']}")

        # ---------------- CHAT CARD ----------------
        st.markdown('<div class="chat-card">', unsafe_allow_html=True)

        # Script di misura altezza/offset — messo DOPO che la card esiste
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
            doc.documentElement.style.setProperty('--top-offset', Math.max(0, Math.round(rect.top)) + 'px');
          }
          function recompute(){ setVH(); setTopOffset(); }
          recompute();
          window.addEventListener('resize', recompute);
          const target = (window.parent && window.parent.document) ? window.parent.document.body : document.body;
          if (target && 'ResizeObserver' in window){ new ResizeObserver(recompute).observe(target); }
        })();
        </script>
        """, height=0)

        st.markdown('<div class="chat-header">Conversazione</div>', unsafe_allow_html=True)

        # --- Ricerca nella chat (sotto l'header) ---
        search_q = st.text_input("🔎 Cerca nella chat", value="", placeholder="Cerca messaggi…")
        if search_q != ss.last_search_q:
            ss.search_index = 0
            ss.last_search_q = search_q

        # Navigatori (conteggio match)
        def count_occurrences(text: str, q: str) -> int:
            if not q:
                return 0
            return len(re.findall(re.escape(q), text, flags=re.IGNORECASE))

        total_matches = sum(count_occurrences(m.get("content",""), search_q) for m in ss["chat_history"]) if search_q else 0
        if search_q:
            st.caption(f"Risultati totali: {total_matches}")
            if total_matches > 0:
                st.markdown("<div id='search-nav'>", unsafe_allow_html=True)
                c1, c2, c3 = st.columns([0.18, 0.18, 0.64])
                with c1:
                    if st.button("◀️ Precedente", key="nav_prev"):
                        ss.search_index = (ss.search_index - 1) % total_matches
                with c2:
                    if st.button("▶️ Successivo", key="nav_next"):
                        ss.search_index = (ss.search_index + 1) % total_matches
                with c3:
                    st.markdown(
                        f"<div class='counter'>Match corrente: <strong>{(ss.search_index % total_matches) + 1} / {total_matches}</strong></div>",
                        unsafe_allow_html=True
                    )
                st.markdown("</div>", unsafe_allow_html=True)
            else:
                st.caption("Nessun risultato per questa ricerca.")

        # Corpo messaggi
        if ss["chat_history"]:
            st.markdown('<div class="chat-body" id="chat-body">', unsafe_allow_html=True)
            remaining_idx = (ss.search_index % total_matches) if (search_q and total_matches > 0) else -1
            for m in ss["chat_history"]:
                role = m['role']
                raw_text = m.get('content','')
                if search_q and total_matches > 0:
                    content_html, remaining_idx = highlight_nth(raw_text, search_q, remaining_idx)
                else:
                    content_html = html.escape(raw_text).replace("\n","<br>")
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

        # Footer input SEMPRE visibile
        typing_ph = st.empty()
        st.markdown('<div class="chat-footer">', unsafe_allow_html=True)
        with st.form(key="chat_form", clear_on_submit=True):
            user_q = st.text_input("Scrivi la tua domanda", value="")
            sent = st.form_submit_button("Invia")
        st.markdown('</div>', unsafe_allow_html=True)   # chiude chat-footer
        st.markdown('</div>', unsafe_allow_html=True)   # chiude chat-card

        # autoscroll nel box chat
        components.html("""
            <script>
              const el = window.parent.document.getElementById('chat-body');
              if (el) { el.scrollTop = el.scrollHeight; }
            </script>
        """, height=0)

        # --- Invio: Azure Search (contesto) + modello ---
        if sent and user_q.strip():
            ss['chat_history'].append({'role':'user','content':user_q.strip(),'ts':ts_now_it()})
        
            # RICERCA NEL MOTORE (con eventuale filtro documento attivo)
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
                    seen = set()
                    for r in results:
                        snippet = r.get("chunk") or r.get("content") or r.get("text")
                        if snippet:
                            context_snippets.append(str(snippet)[:400])
        
                        raw_id = r.get(FILENAME_FIELD)
                        if raw_id:
                            url, name = normalize_source_id(str(raw_id))
                            key = (url or "").lower()
                            if key not in seen:
                                seen.add(key)
                                sources.append({"url": url, "name": name})
            except Exception as e:
                st.error(f"Errore ricerca: {e}")
        
            # CHIAMATA MODELLO con contesto
            try:
                messages = build_chat_messages(user_q, context_snippets)
                with typing_ph, st.spinner("Sto scrivendo…"):
                    resp = client.chat.completions.create(
                        model=AZURE_OPENAI_DEPLOYMENT,
                        messages=messages,
                        temperature=0.2,
                        max_tokens=900,
                    )
                typing_ph.empty()
                ai_text = resp.choices[0].message.content if resp.choices else "(nessuna risposta)"
        
                # elenco fonti: solo nomi, niente URL
                if sources:
                    links = [s['name'] for s in sources[:6]]
                    ai_text += "\n\n— 📎 Fonti: " + ", ".join(links)
        
                ss['chat_history'].append({'role':'assistant','content':ai_text,'ts':ts_now_it()})
            except Exception as e:
                typing_ph.empty()
                ss['chat_history'].append({'role':'assistant','content':f"Si è verificato un errore durante la generazione della risposta: {e}",'ts':ts_now_it()})
            st.rerun()

    # ======= CRONOLOGIA =======
    elif nav == "Cronologia":
        st.subheader("🕒 Cronologia chat salvate")

        if not ss.get("saved_chats"):
            st.info("Non ci sono chat salvate. Torna nella chat e usa **Salva chat**.")
        else:
            for i, item in enumerate(ss["saved_chats"]):
                box = st.container(border=True)
                with box:
                    c1, c2, c3, c4 = st.columns([6, 3, 1.5, 1.5])
                    c1.markdown(f"**{item['name']}**")
                    c2.caption(f"Creato il: {item['created_at']}")
                    if c3.button("Apri", key=f"open_{item['id']}"):
    ss["chat_history"] = list(item["history"])
    ss["main_nav"] = "💬 Chat"  # cambia il tab selezionato
    st.rerun()
                    if c4.button("Elimina", key=f"del_{item['id']}"):
                        ss["saved_chats"].pop(i)
                        st.rerun()

        st.divider()
        st.caption("Suggerimento: apri un salvataggio per riprendere la conversazione da dove l'hai lasciata.")