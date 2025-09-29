CSS = '''
<style>
:root {
  --yellow: #FDF6B4;
  --yellow-border: #FDF6B4;
  --ai-bg: #F1F6FA;
  --ai-border: #F1F6FA;
  --text: #1f2b3a;
}

/* Sfondo generale grigio chiaro */
.stApp {
  background: #f5f7fa;
}

/* Pane sinistro bianco con barra verticale */
.left-pane {
  background: #ffffff;
  border-right: 1px solid #e5e7eb;
  min-height: 100vh;
  padding: 8px 12px;
}

/* Pane destro grigio chiaro */
.right-pane {
  background: #f5f7fa;
  min-height: 100vh;
  padding-left: 16px;
}

.block-container { max-width: 1200px; }
.chat-card { border:1px solid #e6eaf0; border-radius:14px; background:#fff; box-shadow:0 2px 8px rgba(16,24,40,0.04); }
.chat-header { padding:12px 16px; border-bottom:1px solid #eef2f7; font-weight:800; color:#1f2b3a; }
.chat-body {
    padding:14px;
    max-height:70vh;  /* o 600px */
    overflow-y:auto;
}
.msg-row { display:flex; gap:10px; margin:8px 0; }
.msg { padding:10px 14px; border-radius:16px; border:1px solid; max-width:78%; line-height:1.45; font-size:15px; }
.msg .meta { font-size:11px; opacity:.7; margin-top:6px; }
.msg.ai   { background: var(--ai-bg);     border-color: var(--ai-border); color: var(--text); }
.msg.user { background: var(--yellow);    border-color: var(--yellow-border); color:#2b2b2b; margin-left:auto; }
.avatar { width:28px; height:28px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:14px; }
.avatar.ai { background:#d9e8ff; color:#123; }
.avatar.user { background:#fff0a6; color:#5a4a00; }
.small { font-size:12px; color:#5b6b7e; margin:6px 0 2px; }
.chat-footer { padding:10px 0 0; }

/* Pulsanti outline: bordo blu + testo blu di default */
.stButton > button {
    background-color: #ffffff !important;  /* sfondo bianco */
    color: #007BFF !important;             /* testo blu */
    border: 1px solid #007BFF !important;  /* bordo blu */
    border-radius: 8px !important;
    font-weight: 600 !important;
    padding: 0.5rem 1rem !important;
    box-shadow: none !important;
}

/* Hover: pulsante diventa blu pieno con testo bianco */
.stButton > button:hover {
    background-color: #007BFF !important;  /* sfondo blu */
    color: #ffffff !important;             /* testo bianco */
    border-color: #007BFF !important;
}

/* Focus da tastiera: alone leggero blu */
.stButton > button:focus {
    outline: none !important;
    box-shadow: 0 0 0 3px rgba(0,123,255,0.25) !important;
}

/* Aumenta la distanza fra le voci del menù a sinistra */
div[role="radiogroup"] label {
    margin-bottom: 12px !important;
}
</style>
'''
st.markdown(CSS, unsafe_allow_html=True)
