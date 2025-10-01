# ... importazioni e configurazioni invariato ...

# Memorizzo l'elenco documenti e timestamp in sessione
documents_cache = st.session_state.get("documents_cache", [])
last_update = st.session_state.get("documents_cache_time")

# ============ ORIGINE ============
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
                    st.session_state["documents_cache"] = []
                    st.experimental_rerun()
            with colb2:
                if last_update:
                    st.caption(f"Elenco aggiornato alle {last_update}")
        else:
            if st.button("📥 Carica elenco documenti"):
                try:
                    from azure.search.documents.models import QueryType
                    res = search_client.search(
                        search_text="*",
                        facets=[f"{FILENAME_FIELD},count:200"],
                        top=0,
                        query_type=QueryType.SIMPLE,
                    )
                    facets = list(res.get_facets().get(FILENAME_FIELD, []))
                    paths = [f["value"] for f in facets] if facets else []
                    st.session_state["documents_cache"] = paths
                    st.session_state["documents_cache_time"] = datetime.now(local_tz).strftime("%d/%m/%Y %H:%M:%S")
                    st.experimental_rerun()
                except Exception as e:
                    st.error(f"Errore nel recupero dell'elenco documenti: {e}")
            else:
                st.info("Premi il pulsante sopra per caricare l'elenco dei documenti.")
