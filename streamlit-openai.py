import os
import html
import streamlit as st
from datetime import datetime, timezone
from openai import AzureOpenAI
from azure.identity import ClientSecretCredential
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential

st.set_page_config(
    page_title="EasyLook.DOC Chat",
    page_icon="💬",
    layout="wide",
)

# ... (config e helpers invariati)

# ========= THEME / STYLES =========
is_dark = st.session_state.get("theme") == "scuro"
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

.left-pane{{
  padding: 0px;
  border: none;
  background: transparent;
  color: var(--text);
}}

.right-pane{
  background: var(--right-bg);
  padding: 20px;
  border-radius: 12px;
}

.chat-card{border:none;box-shadow:none;background:transparent;}
.chat-header{padding:12px 16px;font-weight:800;color:var(--text);display:flex;align-items:center;gap:.6rem;border:none;background:transparent;}
.chat-header .badge{font-size:11px;border:1px solid var(--border);padding:2px 8px;border-radius:999px;opacity:.9}
.chat-body{padding:16px;max-height:66vh;overflow-y:auto;background:transparent;color:var(--text);}

.msg-row{{display:flex;gap:10px;margin:10px 0;}}
.msg{{padding:12px 14px;border-radius:16px;border:1px solid var(--border);max-width:78%;line-height:1.5;font-size:15px;}}
.msg .meta{{font-size:11px;color:var(--muted);margin-top:6px;}}
.msg.ai{{background:var(--bubble-ai);color:{"#e5e7eb" if is_dark else "#1f2b3a"};}}
.msg.user{{background:var(--bubble-user);color:{"#fef9c3" if is_dark else "#2b2b2b"};margin-left:auto;}}

.composer{ position: sticky; bottom: 0; background: var(--panel); border-top:1px solid var(--border); padding: 12px 16px; border-bottom-left-radius:16px;border-bottom-right-radius:16px;}
.composer .stTextArea textarea{ background:{"#0b1220" if is_dark else "#fff"}; color:var(--text); border:1px solid var(--border); border-radius:12px;}

.chips{ display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }
.chip{ font-size:12px; border:1px solid var(--border); padding:2px 8px; border-radius:999px; opacity:.85; }

.chat-footer{padding:10px 16px;color:var(--muted);}

h1,h2,h3,h4{color:var(--text)}
</style>
""",
    unsafe_allow_html=True,
)

# ----- LEFT PANE -----
left, right = st.columns([0.28, 0.72], gap="large")
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
        if st.session_state.get("theme") != ("scuro" if is_dark else "chiaro"):
            st.rerun()
    st.markdown("---")
    nav_labels = [("📤 Origine", "Leggi documento"), ("💬 Chat", "Chat"), ("🕒 Cronologia", "Cronologia")]
    for label, value in nav_labels:
        active_cls = "nav-item active" if st.session_state["nav"] == value else "nav-item"
        st.markdown(f'<div class="{active_cls}">', unsafe_allow_html=True)
        if st.button(label, key=f"nav_{value}", type="secondary", use_container_width=True):
            st.session_state["nav"] = value
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

# ----- RIGHT PANE -----
with right:
    st.markdown('<div class="right-pane">', unsafe_allow_html=True)
    st.title("BENVENUTO !")

    if st.session_state["nav"] == "Chat":
        st.markdown('<div class="chat-card">', unsafe_allow_html=True)
        st.markdown('<div class="chat-header">💬 EasyLook.DOC Chat <span class="badge">alpha</span></div>', unsafe_allow_html=True)
        st.markdown('<div class="chat-body">', unsafe_allow_html=True)
        for m in st.session_state["chat_history"]:
            role_class = "user" if m["role"] == "user" else "ai"
            body = html.escape(m.get("content", "")).replace("\n", "<br>")
            meta = m.get("ts", "")
            html_block = (
                "<div class='msg-row'><div class='msg %s'>%s"
                "<div class='meta'>%s</div></div></div>"
            ) % (role_class, body, meta)
            st.markdown(html_block, unsafe_allow_html=True)

        # scroll automatico all'ultimo messaggio
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

        st.markdown('</div>', unsafe_allow_html=True)

        # Composer sticky con chat_input
        st.markdown('<div class="composer">', unsafe_allow_html=True)
        user_q = st.chat_input("Scrivi qui…")
        if user_q and user_q.strip():
            st.session_state["chat_history"].append(
                {
                    "role": "user",
                    "content": user_q.strip(),
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
            context_snippets = []
            sources = []
            try:
                if not search_client:
                    st.warning("Azure Search non disponibile. Risposta senza contesto.")
                else:
                    flt = safe_filter_eq(FILENAME_FIELD, st.session_state.get("active_doc")) if st.session_state.get("active_doc") else None
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
                st.session_state["chat_history"].append(
                    {
                        "role": "assistant",
                        "content": ai_text,
                        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )
            except Exception as e:
                st.session_state["chat_history"].append(
                    {
                        "role": "assistant",
                        "content": f"Si è verificato un errore durante la generazione della risposta: {e}",
                        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )
            st.experimental_rerun()
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('<div class="chat-footer">Suggerimento: usa “Origine” per filtrare le risposte. Tema attuale: <b>' + (st.session_state.get('theme') or 'chiaro') + '</b>.</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)
