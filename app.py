"""Point d'entrée principal de l'application Streamlit de veille stratégique."""

from datetime import datetime
import html
import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import pandas as pd
import streamlit as st

from analysis_engine import (
    analyze_duplicates_and_qualify,
    extract_evidence,
    generate_decision_report,
)
from collect_engine import fetch_arxiv, get_vendor_sources
from database import (
    get_all_faits,
    get_all_requetes,
    get_all_sources,
    init_db,
    insert_fait_extrait,
    insert_requete_journal,
    insert_source,
    update_source_qualification,
)

BASE_DIR = Path(__file__).resolve().parent
LAST_REPORT_PATH = BASE_DIR / "data" / "dernier_rapport.json"

# Chargement des variables d'environnement (aucun secret en clair dans le code)
load_dotenv(dotenv_path=BASE_DIR / ".env")

# Initialisation et migration automatique de la base de données locale au démarrage
init_db()

# Barème initial de fiabilité a priori selon la typologie de source (sur 1.0)
DEFAULT_RELIABILITY_BY_TYPE: dict[str, float] = {
    "scientifique": 0.85,
    "presse": 0.65,
    "fournisseur": 0.50,
    "blog": 0.40,
}

EXECUTIVE_CSS = """
<style>
.exec-kpi-card {
    background: #FFFFFF;
    border: 2px solid #12239E;
    border-top: 6px solid #FAA61A;
    border-radius: 10px;
    padding: 1rem 1.15rem;
    box-shadow: 0 3px 10px rgba(18, 35, 158, 0.08);
    min-height: 128px;
    margin-bottom: 0.75rem;
}
.exec-kpi-label {
    font-size: 0.82rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #475569;
    margin-bottom: 0.35rem;
}
.exec-kpi-value {
    font-size: 1.85rem;
    font-weight: 800;
    color: #12239E;
    line-height: 1.15;
    margin-bottom: 0.25rem;
}
.exec-kpi-sub {
    font-size: 0.78rem;
    color: #64748B;
}
.exec-section-box {
    background: #FFFFFF;
    border: 1.5px solid #12239E;
    border-radius: 10px;
    padding: 1.25rem 1.4rem;
    margin-bottom: 1rem;
    color: #0F172A;
}
.exec-contradiction-item {
    background: #FFFDF5;
    border: 1px solid #12239E;
    border-left: 6px solid #FAA61A;
    border-radius: 8px;
    padding: 0.85rem 1.1rem;
    margin-bottom: 0.65rem;
    color: #1E293B;
    font-size: 0.95rem;
}
.exec-option-card {
    background: #FFFFFF;
    border: 1.5px solid #12239E;
    border-top: 4px solid #12239E;
    border-radius: 10px;
    padding: 1rem 1.1rem;
    height: 100%;
    min-height: 185px;
    color: #1E293B;
    margin-bottom: 0.75rem;
}
.exec-option-card-highlight {
    border: 2px solid #12239E;
    border-top: 6px solid #FAA61A;
    background: #F8FAFF;
}
.exec-option-title {
    font-size: 1.05rem;
    font-weight: 800;
    color: #12239E;
    margin-bottom: 0.5rem;
}
.exec-rec-banner {
    background: linear-gradient(135deg, #F8FAFF 0%, #EEF2FF 100%);
    border: 2px solid #12239E;
    border-left: 8px solid #FAA61A;
    border-radius: 12px;
    padding: 1.4rem 1.6rem;
    margin: 0.75rem 0 1.25rem 0;
    color: #0F172A;
    box-shadow: 0 4px 14px rgba(18, 35, 158, 0.10);
}
.exec-rec-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-bottom: 0.75rem;
}
.exec-rec-action {
    font-size: 1.3rem;
    font-weight: 800;
    color: #12239E;
}
.exec-badge {
    display: inline-block;
    background: #FAA61A;
    color: #0F172A;
    border: 1.5px solid #12239E;
    font-weight: 800;
    font-size: 0.85rem;
    padding: 0.25rem 0.75rem;
    border-radius: 999px;
}
.exec-revision-box {
    background: #F8FAFC;
    border: 1.5px solid #12239E;
    border-left: 6px solid #12239E;
    border-radius: 10px;
    padding: 1rem 1.3rem;
    color: #1E293B;
}
</style>
"""


def _load_persisted_report() -> dict[str, Any] | None:
    """Charge le dernier rapport décisionnel sauvegardé sur disque s'il existe."""
    if not LAST_REPORT_PATH.exists():
        return None
    try:
        return json.loads(LAST_REPORT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_persisted_report(report: dict[str, Any]) -> None:
    """Sauvegarde le rapport décisionnel localement dans ``data/dernier_rapport.json``."""
    try:
        LAST_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        LAST_REPORT_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _build_markdown_export(
    report: dict[str, Any],
    sources: list[dict[str, Any]],
    kpi_summary: dict[str, Any],
) -> str:
    """Construit le document Markdown complet prêt à être téléchargé."""
    rec = report.get("recommandation_finale", {})
    contradictions = report.get("contradictions_identifiees", [])
    options = report.get("options", [])
    conditions = report.get("conditions_revision", [])
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines: list[str] = [
        "# Note de Synthèse & Aide à la Décision — Veille Stratégique",
        "",
        f"*Généré le : {generated_at}*",
        "",
        "## 1. Indicateurs Clés du Corpus (KPIs)",
        f"- **Sources collectées** : {kpi_summary['total_sources']}",
        f"- **Groupes thématiques dédoublonnés** : {kpi_summary['nb_groupes']}",
        f"- **Faits établis vs Interprétations** : {kpi_summary['nb_faits']} fait(s) établi(s) / {kpi_summary['nb_interpretations']} interprétation(s)",
        f"- **Lacunes identifiées** : {kpi_summary['nb_lacunes']}",
        "",
        "## 2. Synthèse Globale",
        report.get("synthese_globale", ""),
        "",
        "## 3. Contradictions Identifiées (Sources Scientifiques vs Fournisseurs)",
    ]

    if contradictions:
        for item in contradictions:
            lines.append(f"- {item}")
    else:
        lines.append("- Aucune contradiction explicite relevée dans le corpus actuel.")

    lines.extend(
        [
            "",
            "## 4. Comparaison des Options d'Action",
            "",
            "| Option stratégique | Implications techniques, sécurité et coûts |",
            "| :--- | :--- |",
        ]
    )
    for opt in options:
        act = str(opt.get("action", "")).replace("|", "\\|")
        imp = str(opt.get("implications", "")).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| **{act}** | {imp} |")

    lines.extend(
        [
            "",
            "## 5. Recommandation Finale",
            f"- **Action proposée** : {rec.get('action_proposee', 'Non renseignée')}",
            f"- **Niveau de confiance** : {rec.get('niveau_confiance', 'Moyen')}",
            f"- **Justification** : {rec.get('justification', '')}",
            "",
            "## 6. Conditions de Révision de la Décision",
        ]
    )
    if conditions:
        for cond in conditions:
            lines.append(f"- {cond}")
    else:
        lines.append("- Aucune condition de révision spécifiée.")

    if sources:
        lines.extend(["", "## 7. Annexe — Référentiel des Sources Traçables"])
        for src in sources:
            lines.append(
                f"- **[Source #{src['id']}]** ({src['type_source']}) *{src['titre']}* — "
                f"{src.get('auteur', '')} ({src.get('date_publication', '')}) : {src.get('url', '')}"
            )

    return "\n".join(lines) + "\n"


st.set_page_config(
    page_title="Système de Veille Stratégique",
    layout="wide",
)

# Injection de la feuille de style exécutive (#12239E / #FAA61A)
st.markdown(EXECUTIVE_CSS, unsafe_allow_html=True)

st.title("Système de Veille Stratégique")

# Restauration automatique du dernier rapport sauvegardé si présent
if "decision_report" not in st.session_state:
    persisted = _load_persisted_report()
    if persisted is not None:
        st.session_state["decision_report"] = persisted

# Menu latéral de navigation
st.sidebar.header("Navigation")
page = st.sidebar.radio(
    "Aller vers :",
    options=[
        "1. Collecte & Qualification",
        "2. Tableau de bord Décisionnel",
    ],
)

if page == "1. Collecte & Qualification":
    st.subheader("1. Collecte & Qualification")

    col_kw, col_mode = st.columns([3, 1])
    with col_kw:
        keyword = st.text_input(
            "Mots-clés de recherche :",
            value="LLM programming assistants",
        )
    with col_mode:
        search_mode = st.selectbox(
            "Mode de veille :",
            options=["Target", "Mine", "Trawl", "Scan"],
            index=0,
            help="Typologie méthodologique de recherche enregistrée dans le journal.",
        )

    col_collect, col_qualify = st.columns(2)

    with col_collect:
        collect_clicked = st.button("Lancer la collecte")
    with col_qualify:
        qualify_clicked = st.button("Dédoublonner et Qualifier avec l'IA")

    if collect_clicked:
        if not keyword.strip():
            st.warning("Veuillez saisir au moins un mot-clé avant de lancer la collecte.")
        else:
            insert_requete_journal(mots_cles=keyword, mode_recherche=search_mode)
            with st.spinner("Collecte des sources scientifiques (ArXiv) et écosystème en cours..."):
                arxiv_results = fetch_arxiv(keyword=keyword, max_results=5)
                vendor_results = get_vendor_sources()
                merged_sources = arxiv_results + vendor_results

                inserted_count = 0
                for src in merged_sources:
                    score = src.get(
                        "fiabilite_score",
                        DEFAULT_RELIABILITY_BY_TYPE.get(src["type_source"].lower(), 0.50),
                    )
                    was_inserted = insert_source(
                        titre=src["titre"],
                        url=src["url"],
                        type_source=src["type_source"],
                        date_pub=src["date_publication"],
                        auteur=src["auteur"],
                        fiabilite_score=score,
                    )
                    if was_inserted:
                        inserted_count += 1

            if not arxiv_results:
                st.warning(
                    "Aucun résultat ArXiv récupéré (vérifiez la connexion réseau ou les mots-clés). "
                    "Les sources fournisseurs ont néanmoins été traitées."
                )

            duplicates_count = len(merged_sources) - inserted_count
            st.success(
                f"Collecte terminée avec succès : {inserted_count} nouvelle(s) source(s) ajoutée(s) "
                f"({duplicates_count} doublon(s) ignoré(s) sur {len(merged_sources)} source(s) analysée(s))."
            )

    if qualify_clicked:
        sources_in_db = get_all_sources()
        if not sources_in_db:
            st.warning("Aucune source en base à qualifier. Lancez d'abord la collecte.")
        else:
            with st.spinner("Dédoublonnage sémantique et qualification IA (Gemini) en cours..."):
                analysis_result = analyze_duplicates_and_qualify(sources_in_db)

            if isinstance(analysis_result, dict) and "groupes" in analysis_result:
                groupes = analysis_result["groupes"]
                updated_sources = 0
                for grp in groupes:
                    sujet = grp.get("sujet_principal", "Sujet non spécifié")
                    score = float(grp.get("pertinence_score", 0.0))
                    for src_id in grp.get("source_ids", []):
                        if update_source_qualification(src_id, sujet, score):
                            updated_sources += 1

                st.success(
                    f"Qualification IA terminée : {len(groupes)} groupe(s) thématique(s) trouvé(s) "
                    f"({updated_sources} source(s) mise(s) à jour)."
                )
            else:
                st.warning(
                    "L'analyse IA n'a pas pu aboutir (clé GEMINI_API_KEY absente, vide ou indisponible). "
                    "Les sources existantes ont été conservées sans modification."
                )

    st.divider()
    st.markdown("### Base de connaissances (`sources`)")

    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        min_pertinence = st.slider(
            "Score de pertinence minimal (Réduction du bruit — Test 4) :",
            min_value=0.0,
            max_value=1.0,
            value=0.0,
            step=0.05,
            help="Permet de filtrer les sources hors-sujet ou faiblement pertinentes après qualification IA.",
        )
    with filter_col2:
        sort_choice = st.selectbox(
            "Axe de tri — Fraîcheur vs Pertinence (Test 2) :",
            options=[
                "Date de publication — Fraîcheur décroissante",
                "Pertinence décroissante (Qualification IA)",
                "Fiabilité a priori décroissante",
                "Ordre d'insertion (ID décroissant)",
            ],
            help="Démontre que la fraîcheur (date) et la pertinence (score IA) sont deux dimensions distinctes.",
        )

    all_sources = get_all_sources()
    if all_sources:
        df_sources = pd.DataFrame(all_sources)
        df_sources["pertinence_score"] = pd.to_numeric(
            df_sources["pertinence_score"], errors="coerce"
        )
        df_sources["fiabilite_score"] = pd.to_numeric(
            df_sources["fiabilite_score"], errors="coerce"
        )

        if min_pertinence > 0.0:
            df_sources = df_sources[
                df_sources["pertinence_score"].fillna(0.0) >= min_pertinence
            ]

        if sort_choice == "Date de publication — Fraîcheur décroissante":
            df_sources = df_sources.sort_values(
                by=["date_publication", "id"], ascending=[False, False], na_position="last"
            )
        elif sort_choice == "Pertinence décroissante (Qualification IA)":
            df_sources = df_sources.sort_values(
                by=["pertinence_score", "fiabilite_score"],
                ascending=[False, False],
                na_position="last",
            )
        elif sort_choice == "Fiabilité a priori décroissante":
            df_sources = df_sources.sort_values(
                by=["fiabilite_score", "date_publication"],
                ascending=[False, False],
                na_position="last",
            )
        else:
            df_sources = df_sources.sort_values(by="id", ascending=False)

        st.caption(
            f"Corpus affiché : **{len(df_sources)}** / {len(all_sources)} source(s) "
            f"(seuil de pertinence ≥ {min_pertinence:.2f} · tri : *{sort_choice}*)."
        )
        st.dataframe(
            df_sources,
            width="stretch",
            hide_index=True,
            column_config={
                "date_publication": st.column_config.TextColumn(
                    "Date de publication (Fraîcheur)",
                ),
                "pertinence_score": st.column_config.ProgressColumn(
                    "Pertinence IA",
                    min_value=0.0,
                    max_value=1.0,
                    format="%.2f",
                ),
                "fiabilite_score": st.column_config.ProgressColumn(
                    "Fiabilité a priori",
                    min_value=0.0,
                    max_value=1.0,
                    format="%.2f",
                ),
                "groupe_sujet": st.column_config.TextColumn(
                    "Groupe thématique (Dédoublonnage)",
                ),
                "url": st.column_config.LinkColumn(
                    "URL Source",
                ),
            },
        )
    else:
        empty_df = pd.DataFrame(
            columns=[
                "id",
                "titre",
                "url",
                "type_source",
                "date_publication",
                "auteur",
                "fiabilite_score",
                "groupe_sujet",
                "pertinence_score",
            ]
        )
        st.dataframe(empty_df, width="stretch", hide_index=True)

    st.divider()

    extract_clicked = st.button("Extraire les Preuves (Faits, Interprétations, Lacunes)")

    if extract_clicked:
        sources_for_evidence = get_all_sources()
        if not sources_for_evidence:
            st.warning("Aucune source en base. Lancez d'abord la collecte avant d'extraire des preuves.")
        else:
            with st.spinner("Extraction structurée des preuves (Anti-Boîte Noire) avec Gemini en cours..."):
                evidence_result = extract_evidence(sources_for_evidence)

            if isinstance(evidence_result, dict) and "preuves" in evidence_result:
                preuves = evidence_result["preuves"]
                inserted_faits = 0
                for item in preuves:
                    if insert_fait_extrait(
                        source_id=item["source_id"],
                        type_element=item["type_element"],
                        description=item["description"],
                        niveau_confiance=item["niveau_confiance"],
                    ):
                        inserted_faits += 1

                st.success(
                    f"Extraction terminée avec succès : {inserted_faits} nouvelle(s) preuve(s) enregistrée(s) "
                    f"(sur {len(preuves)} élément(s) extrait(s) et relié(s) à leurs sources)."
                )
            else:
                st.warning(
                    "L'extraction des preuves n'a pas pu aboutir (clé GEMINI_API_KEY absente, vide ou indisponible)."
                )

    st.subheader("Preuves extraites")
    st.caption(
        "Traçabilité Anti-Boîte Noire : chaque fait établi, interprétation ou lacune est directement relié "
        "à sa source d'origine et à son URL vérifiable."
    )

    all_faits = get_all_faits()
    evidence_columns = [
        "type_element",
        "description",
        "niveau_confiance",
        "source_titre",
        "source_url",
        "type_source",
        "source_id",
        "id",
    ]
    df_faits = (
        pd.DataFrame(all_faits)
        if all_faits
        else pd.DataFrame(columns=evidence_columns)
    )

    st.dataframe(
        df_faits,
        width="stretch",
        hide_index=True,
        column_order=[
            "type_element",
            "description",
            "niveau_confiance",
            "source_titre",
            "source_url",
            "type_source",
            "source_id",
        ],
        column_config={
            "type_element": st.column_config.TextColumn(
                "Type d'élément (type_element)",
                help="Classification épistémique : fait_etabli, interpretation ou lacune",
            ),
            "description": st.column_config.TextColumn(
                "Description de la preuve",
            ),
            "niveau_confiance": st.column_config.ProgressColumn(
                "Niveau de confiance",
                min_value=0.0,
                max_value=1.0,
                format="%.2f",
            ),
            "source_titre": st.column_config.TextColumn(
                "Titre de la source associée",
            ),
            "source_url": st.column_config.LinkColumn(
                "Lien vers la source (URL)",
                help="Lien cliquable vers la publication d'origine",
            ),
            "type_source": st.column_config.TextColumn(
                "Nature source",
            ),
            "source_id": st.column_config.NumberColumn(
                "ID Source",
                format="%d",
            ),
        },
    )

    st.divider()
    with st.expander("Journal des requêtes de veille"):
        requetes_log = get_all_requetes()
        if requetes_log:
            df_journal = pd.DataFrame(requetes_log)
            st.dataframe(
                df_journal,
                width="stretch",
                hide_index=True,
                column_config={
                    "id": st.column_config.NumberColumn("ID Requête", format="%d"),
                    "date_requete": st.column_config.TextColumn("Horodatage"),
                    "mots_cles": st.column_config.TextColumn("Mots-clés recherchés"),
                    "mode_recherche": st.column_config.TextColumn("Mode de veille"),
                },
            )
        else:
            st.info("Aucune requête enregistrée dans le journal pour le moment.")

elif page == "2. Tableau de bord Décisionnel":
    st.subheader("2. Tableau de bord Décisionnel")

    sources_dash = get_all_sources()
    faits_dash = get_all_faits()

    if not sources_dash or not faits_dash:
        st.warning(
            "Les bases de connaissances sont incomplètes ou vides. Rendez-vous sur la page "
            "« 1. Collecte & Qualification » pour lancer la collecte des sources puis "
            "l'extraction structurée des preuves avant de générer la synthèse décisionnelle."
        )

    # Calcul des KPIs exécutifs
    total_sources = len(sources_dash)
    nb_sci = sum(1 for s in sources_dash if str(s.get("type_source", "")).lower() == "scientifique")
    nb_fourn = sum(1 for s in sources_dash if str(s.get("type_source", "")).lower() == "fournisseur")
    nb_media = sum(
        1 for s in sources_dash if str(s.get("type_source", "")).lower() in ("presse", "blog")
    )

    distinct_groups = {
        str(s["groupe_sujet"]).strip()
        for s in sources_dash
        if s.get("groupe_sujet") and str(s["groupe_sujet"]).strip()
    }
    nb_groupes = len(distinct_groups)

    nb_faits_etablis = sum(
        1 for f in faits_dash if str(f.get("type_element", "")).lower() == "fait_etabli"
    )
    nb_interpretations = sum(
        1 for f in faits_dash if str(f.get("type_element", "")).lower() == "interpretation"
    )
    nb_lacunes = sum(
        1 for f in faits_dash if str(f.get("type_element", "")).lower() == "lacune"
    )

    kpi_summary = {
        "total_sources": total_sources,
        "nb_groupes": nb_groupes,
        "nb_faits": nb_faits_etablis,
        "nb_interpretations": nb_interpretations,
        "nb_lacunes": nb_lacunes,
    }

    # Bandeau supérieur de 4 cartes KPIs exécutives (#12239E & #FAA61A)
    kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)

    with kpi_col1:
        st.markdown(
            f"""
            <div class="exec-kpi-card">
                <div class="exec-kpi-label">Sources Collectées</div>
                <div class="exec-kpi-value">{total_sources}</div>
                <div class="exec-kpi-sub">{nb_sci} Sci. · {nb_fourn} Fourn. · {nb_media} Presse/Blog</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with kpi_col2:
        group_sub = (
            "Sujets uniques après dédoublonnage IA"
            if nb_groupes > 0
            else "Qualification IA non exécutée"
        )
        st.markdown(
            f"""
            <div class="exec-kpi-card">
                <div class="exec-kpi-label">Groupes Dédoublonnés</div>
                <div class="exec-kpi-value">{nb_groupes}</div>
                <div class="exec-kpi-sub">{group_sub}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with kpi_col3:
        st.markdown(
            f"""
            <div class="exec-kpi-card">
                <div class="exec-kpi-label">Faits Établis vs Interprétations</div>
                <div class="exec-kpi-value">{nb_faits_etablis} / {nb_interpretations}</div>
                <div class="exec-kpi-sub">Preuves empiriques vs promesses éditeurs</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with kpi_col4:
        st.markdown(
            f"""
            <div class="exec-kpi-card">
                <div class="exec-kpi-label">Lacunes Identifiées</div>
                <div class="exec-kpi-value">{nb_lacunes}</div>
                <div class="exec-kpi-sub">Angles morts & limites méthodologiques</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.divider()

    generate_clicked = st.button("Générer le Rapport Décisionnel")

    if generate_clicked:
        if not sources_dash or not faits_dash:
            st.warning(
                "Impossible de générer le rapport : veuillez d'abord collecter des sources "
                "et extraire les preuves depuis la page « 1. Collecte & Qualification »."
            )
        else:
            with st.spinner(
                "Synthèse exécutive et détection des contradictions en cours avec Gemini..."
            ):
                new_report = generate_decision_report(sources_dash, faits_dash)

            if isinstance(new_report, dict):
                st.session_state["decision_report"] = new_report
                _save_persisted_report(new_report)
                st.success("Rapport décisionnel généré et sauvegardé avec succès.")
            else:
                st.warning(
                    "La génération du rapport décisionnel n'a pas pu aboutir "
                    "(clé GEMINI_API_KEY absente, vide ou indisponible)."
                )

    report_data: dict[str, Any] | None = st.session_state.get("decision_report")

    if isinstance(report_data, dict):
        # 1. Synthèse globale
        st.markdown("### Synthèse globale")
        safe_synthese = html.escape(str(report_data.get("synthese_globale", ""))).replace(
            "\n", "<br>"
        )
        st.markdown(
            f'<div class="exec-section-box">{safe_synthese}</div>',
            unsafe_allow_html=True,
        )

        # 2. Contradictions identifiées (Test minimal n°3)
        st.markdown("### Contradictions identifiées (Fournisseurs vs Études Scientifiques)")
        contradictions_list = report_data.get("contradictions_identifiees", [])
        if contradictions_list:
            for contradiction in contradictions_list:
                safe_item = html.escape(str(contradiction))
                st.markdown(
                    f'<div class="exec-contradiction-item">⚖️ {safe_item}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.info("Aucune contradiction directe détectée sur le périmètre actuel.")

        # 3. Comparaison des Options d'action
        st.markdown("### Comparaison des Options d'action")
        options_list = report_data.get("options", [])
        rec_finale = report_data.get("recommandation_finale", {})
        rec_action_lower = str(rec_finale.get("action_proposee", "")).lower()

        if options_list:
            opt_cols = st.columns(min(len(options_list), 4))
            for idx, opt in enumerate(options_list):
                action_label = str(opt.get("action", "Option"))
                implications_text = str(opt.get("implications", ""))
                is_recommended = action_label.lower() in rec_action_lower
                extra_cls = " exec-option-card-highlight" if is_recommended else ""
                star_prefix = "★ " if is_recommended else ""

                with opt_cols[idx % len(opt_cols)]:
                    st.markdown(
                        f"""
                        <div class="exec-option-card{extra_cls}">
                            <div class="exec-option-title">{star_prefix}{html.escape(action_label)}</div>
                            <div>{html.escape(implications_text)}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            with st.expander("Voir la matrice comparative tabulaire des options"):
                df_options = pd.DataFrame(options_list).rename(
                    columns={
                        "action": "Option stratégique",
                        "implications": "Implications (techniques, sécurité, coûts)",
                    }
                )
                st.dataframe(df_options, width="stretch", hide_index=True)

        # 4. Encadré mis en valeur pour la Recommandation finale
        st.markdown("### Recommandation finale")
        safe_action = html.escape(str(rec_finale.get("action_proposee", "Non définie")))
        safe_conf = html.escape(str(rec_finale.get("niveau_confiance", "Moyen")))
        safe_justif = html.escape(str(rec_finale.get("justification", ""))).replace("\n", "<br>")

        st.markdown(
            f"""
            <div class="exec-rec-banner">
                <div class="exec-rec-header">
                    <div class="exec-rec-action">Décision recommandée : {safe_action}</div>
                    <span class="exec-badge">Niveau de confiance : {safe_conf}</span>
                </div>
                <div>{safe_justif}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # 5. Conditions de révision & Export Markdown (.md)
        st.markdown("### Conditions de révision de la décision")
        conditions_list = report_data.get("conditions_revision", [])
        if conditions_list:
            items_html = "".join(
                f"<li>{html.escape(str(cond))}</li>" for cond in conditions_list
            )
            st.markdown(
                f'<div class="exec-revision-box"><ul style="margin-bottom:0;">{items_html}</ul></div>',
                unsafe_allow_html=True,
            )
        else:
            st.info("Aucune condition de révision spécifiée.")

        st.write("")
        md_content = _build_markdown_export(report_data, sources_dash, kpi_summary)
        st.download_button(
            label="📥 Exporter le rapport complet en Markdown (.md)",
            data=md_content,
            file_name="rapport_decisionnel_veille.md",
            mime="text/markdown",
        )
