"""Moteur d'analyse IA (SDK google-genai) : dédoublonnage, qualification et extraction de preuves."""

import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Literal

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import APIError
import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

ENV_PATH = Path(__file__).resolve().parent / ".env"

# Chargement des variables d'environnement (.env) si présentes
load_dotenv(dotenv_path=ENV_PATH)

MODEL_NAME = "gemini-3.8-flash"
TARGET_TOPIC = "LLM programming assistants"
CLIENT_TIMEOUT_MS = 120000  # 120 secondes en millisecondes
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5
VALID_EVIDENCE_TYPES = {"fait_etabli", "interpretation", "lacune"}


class GroupeThematique(BaseModel):
    """Schéma d'un groupe de sources traitant d'un même sujet."""

    sujet_principal: str = Field(
        description="Intitulé synthétique du sujet commun aux sources regroupées."
    )
    pertinence_score: float = Field(
        description="Score de pertinence vis-à-vis du sujet cible, compris entre 0.0 et 1.0."
    )
    source_ids: list[int] = Field(
        description="Liste des identifiants (id) des sources appartenant à ce groupe."
    )


class QualificationResponse(BaseModel):
    """Schéma racine de la réponse JSON structurée pour le dédoublonnage et la qualification."""

    groupes: list[GroupeThematique]


class PreuveExtraite(BaseModel):
    """Schéma d'une preuve analytique rattachée à sa source d'origine (Anti-Boîte Noire)."""

    source_id: int = Field(
        description="Identifiant exact (id) de la source d'origine dans la liste fournie."
    )
    type_element: Literal["fait_etabli", "interpretation", "lacune"] = Field(
        description="Catégorie : 'fait_etabli', 'interpretation' ou 'lacune'."
    )
    description: str = Field(
        description="Formulation courte et précise en français de l'élément extrait."
    )
    niveau_confiance: float = Field(
        description="Niveau de confiance associé (flottant compris entre 0.0 et 1.0)."
    )


class ExtractionPreuvesResponse(BaseModel):
    """Schéma racine de la réponse JSON structurée pour l'extraction des preuves."""

    preuves: list[PreuveExtraite]


class OptionDecision(BaseModel):
    """Option stratégique évaluée avec ses implications opérationnelles."""

    action: Literal["Adopter", "Expérimenter", "Surveiller", "Différer"] = Field(
        description="Action stratégique parmi : Adopter, Expérimenter, Surveiller, Différer."
    )
    implications: str = Field(
        description="Conséquences techniques, sécurité et coûts de ce choix."
    )


class RecommandationFinale(BaseModel):
    """Recommandation exécutive finale proportionnée à la solidité des preuves."""

    action_proposee: str = Field(
        description="Intitulé précis de la recommandation d'action."
    )
    niveau_confiance: Literal["Faible", "Moyen", "Fort"] = Field(
        description="Niveau de confiance global : Faible, Moyen ou Fort."
    )
    justification: str = Field(
        description="Argumentaire proportionné à la qualité réelle des preuves et lacunes."
    )


class RapportDecisionnelResponse(BaseModel):
    """Schéma racine du rapport de synthèse orienté décision."""

    synthese_globale: str = Field(
        description="Résumé analytique concis avec citations explicites des IDs de sources."
    )
    contradictions_identifiees: list[str] = Field(
        description=(
            "Oppositions explicites entre affirmations fournisseurs et études indépendantes "
            "(avec IDs des sources)."
        )
    )
    options: list[OptionDecision] = Field(
        description="Comparaison des options Adopter, Expérimenter, Surveiller, Différer."
    )
    recommandation_finale: RecommandationFinale
    conditions_revision: list[str] = Field(
        description="Événements futurs ou nouvelles preuves imposant de réviser cette décision."
    )


def _clean_json_text(raw_text: str) -> str:
    """Extrait le bloc JSON principal en retirant d'éventuelles balises Markdown."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    start_idx = cleaned.find("{")
    end_idx = cleaned.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        cleaned = cleaned[start_idx : end_idx + 1]
    return cleaned


def _call_gemini_structured(
    prompt: str,
    response_schema: type[BaseModel],
) -> str | None:
    """Exécute un appel Gemini résilient (timeout 120s, 3 tentatives, gestion 503/504).

    Args:
        prompt: Instructions et données envoyées au modèle.
        response_schema: Classe Pydantic imposant le schéma JSON de sortie.

    Returns:
        Texte JSON brut retourné par Gemini, ou ``None`` en cas d'échec après réessais.
    """
    http_opts = types.HttpOptions(timeout=CLIENT_TIMEOUT_MS)

    try:
        client = genai.Client(
            api_key=os.environ.get("GEMINI_API_KEY"),
            http_options=http_opts,
        )
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        http_options=http_opts,
                        response_mime_type="application/json",
                        response_schema=response_schema,
                        temperature=0.1,
                    ),
                )
                if not response.text:
                    error_msg = "[ERREUR] Réponse vide retournée par le modèle Gemini."
                    print(error_msg)
                    logger.error(error_msg)
                    return None
                return response.text
            except APIError as exc:
                status_code = getattr(exc, "code", None)
                err_str = str(exc)
                is_retryable_status = (
                    status_code in (503, 504)
                    or "504" in err_str
                    or "503" in err_str
                )
                if is_retryable_status and attempt < MAX_RETRIES:
                    warn_msg = (
                        f"[AVERTISSEMENT] Tentative {attempt}/{MAX_RETRIES} échouée "
                        f"(APIError {status_code or ''}: {exc}). "
                        f"Nouvel essai dans {RETRY_DELAY_SECONDS} secondes..."
                    )
                    print(warn_msg)
                    logger.warning(warn_msg)
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue
                raise
            except (httpx.HTTPError, TimeoutError, OSError) as exc:
                if attempt < MAX_RETRIES:
                    warn_msg = (
                        f"[AVERTISSEMENT] Tentative {attempt}/{MAX_RETRIES} interrompue par le réseau "
                        f"({exc}). Nouvel essai dans {RETRY_DELAY_SECONDS} secondes..."
                    )
                    print(warn_msg)
                    logger.warning(warn_msg)
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue
                raise
    except APIError as exc:
        warn_msg = (
            f"[AVERTISSEMENT] Échec de l'appel à l'API Gemini ({MODEL_NAME}) après "
            f"{MAX_RETRIES} tentatives maximum : {exc}"
        )
        print(warn_msg)
        logger.warning(warn_msg)
        return None
    except (httpx.HTTPError, TimeoutError, OSError) as exc:
        warn_msg = (
            f"[AVERTISSEMENT] Échec réseau lors de l'appel à Gemini après "
            f"{MAX_RETRIES} tentatives : {exc}"
        )
        print(warn_msg)
        logger.warning(warn_msg)
        return None
    except Exception as exc:  # noqa: BLE001
        warn_msg = f"[AVERTISSEMENT] Échec inattendu lors de l'appel à Gemini : {exc}"
        print(warn_msg)
        logger.warning(warn_msg)
        return None

    return None


def _validate_and_normalize_payload(payload: Any) -> dict[str, list[dict[str, Any]]]:
    """Valide et normalise la structure JSON de qualification retournée par Gemini."""
    if not isinstance(payload, dict) or not isinstance(payload.get("groupes"), list):
        raise ValueError("Le JSON retourné ne contient pas la clé attendue 'groupes' (liste).")

    normalized_groups: list[dict[str, Any]] = []
    for item in payload["groupes"]:
        if not isinstance(item, dict):
            continue

        sujet = str(item.get("sujet_principal", "Sujet non spécifié")).strip()

        try:
            score = float(item.get("pertinence_score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(1.0, round(score, 2)))

        raw_ids = item.get("source_ids", [])
        clean_ids: list[int] = []
        if isinstance(raw_ids, list):
            for sid in raw_ids:
                try:
                    clean_ids.append(int(sid))
                except (TypeError, ValueError):
                    continue

        if clean_ids:
            normalized_groups.append(
                {
                    "sujet_principal": sujet,
                    "pertinence_score": score,
                    "source_ids": clean_ids,
                }
            )

    return {"groupes": normalized_groups}


def _validate_and_normalize_evidence(
    payload: Any,
    valid_source_ids: set[int],
) -> dict[str, list[dict[str, Any]]]:
    """Valide et normalise la structure JSON d'extraction de preuves retournée par Gemini."""
    if not isinstance(payload, dict) or not isinstance(payload.get("preuves"), list):
        raise ValueError("Le JSON retourné ne contient pas la clé attendue 'preuves' (liste).")

    normalized_preuves: list[dict[str, Any]] = []
    for item in payload["preuves"]:
        if not isinstance(item, dict):
            continue

        try:
            source_id = int(item.get("source_id"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue

        if valid_source_ids and source_id not in valid_source_ids:
            continue

        raw_type = str(item.get("type_element", "")).strip().lower()
        if raw_type not in VALID_EVIDENCE_TYPES:
            continue

        description = str(item.get("description", "")).strip()
        if not description:
            continue

        try:
            confiance = float(item.get("niveau_confiance", 0.5))
        except (TypeError, ValueError):
            confiance = 0.5
        confiance = max(0.0, min(1.0, round(confiance, 2)))

        normalized_preuves.append(
            {
                "source_id": source_id,
                "type_element": raw_type,
                "description": description,
                "niveau_confiance": confiance,
            }
        )

    return {"preuves": normalized_preuves}


def analyze_duplicates_and_qualify(
    sources_list: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]] | list[dict[str, Any]]:
    """Regroupe sémantiquement les sources redondantes et qualifie leur pertinence via Gemini.

    Si ``GEMINI_API_KEY`` est absente ou vide, retourne immédiatement ``sources_list``
    sans modification et affiche un message explicite dans la console.

    Args:
        sources_list: Liste de dictionnaires issus de la table ``sources``.

    Returns:
        Un dictionnaire structuré ``{"groupes": [...]}`` en cas de succès, ou
        ``sources_list`` sans modification si la clé API est absente ou en cas d'erreur.
    """
    load_dotenv(dotenv_path=ENV_PATH)
    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        error_msg = (
            "[ERREUR] Clé API Gemini absente ou vide (variable GEMINI_API_KEY). "
            "Retour de la liste originale sans modification."
        )
        print(error_msg)
        logger.error(error_msg)
        return sources_list

    if not sources_list:
        return {"groupes": []}

    compact_sources = [
        {
            "id": src.get("id"),
            "titre": src.get("titre"),
            "type_source": src.get("type_source"),
            "auteur": src.get("auteur"),
            "url": src.get("url"),
        }
        for src in sources_list
    ]

    prompt = (
        "Tu es un expert en veille scientifique et technologique orientée décision.\n"
        f'Analyse la liste de sources suivante par rapport au sujet cible : "{TARGET_TOPIC}".\n\n'
        "Instructions :\n"
        "1. Regroupe les sources qui parlent exactement du même sujet, de la même étude "
        "ou de la même annonce (republications / doublons sémantiques). Si une source "
        "traite d'un sujet unique, place-la seule dans son propre groupe.\n"
        "2. Chaque ID de source présent en entrée doit figurer dans exactement un groupe.\n"
        f'3. Évalue la pertinence de chaque groupe vis-à-vis du sujet "{TARGET_TOPIC}" '
        "avec un score flottant compris entre 0.0 (hors-sujet) et 1.0 (très pertinent).\n"
        "4. Réponds UNIQUEMENT au format JSON structuré respectant le schéma fourni.\n\n"
        f"Sources à analyser :\n{json.dumps(compact_sources, ensure_ascii=False, indent=2)}"
    )

    raw_response_text = _call_gemini_structured(
        prompt=prompt,
        response_schema=QualificationResponse,
    )
    if raw_response_text is None:
        return sources_list

    try:
        cleaned_json = _clean_json_text(raw_response_text)
        parsed = json.loads(cleaned_json)
        return _validate_and_normalize_payload(parsed)
    except (json.JSONDecodeError, ValueError) as exc:
        error_msg = f"[ERREUR] Impossible de parser le JSON retourné par Gemini : {exc}"
        print(error_msg)
        logger.error("%s | Réponse brute : %s", error_msg, raw_response_text)
        return sources_list


def extract_evidence(
    sources_list: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]] | None:
    """Extrait des faits établis, interprétations et lacunes traçables vers leurs sources.

    Applique une approche « Anti-Boîte Noire » : chaque affirmation produite est
    obligatoirement rattachée à un ``source_id`` existant et typée épistémiquement.

    Args:
        sources_list: Liste des dictionnaires issus de la table ``sources``.

    Returns:
        Un dictionnaire ``{"preuves": [...]}`` en cas de succès, ou ``None`` si la clé API
        est absente ou si l'appel échoue après les 3 tentatives.
    """
    load_dotenv(dotenv_path=ENV_PATH)
    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        error_msg = (
            "[ERREUR] Clé API Gemini absente ou vide (variable GEMINI_API_KEY). "
            "Extraction des preuves annulée."
        )
        print(error_msg)
        logger.error(error_msg)
        return None

    if not sources_list:
        return {"preuves": []}

    valid_source_ids: set[int] = set()
    compact_sources: list[dict[str, Any]] = []
    for src in sources_list:
        raw_id = src.get("id")
        if raw_id is None:
            continue
        sid = int(raw_id)
        valid_source_ids.add(sid)
        compact_sources.append(
            {
                "id": sid,
                "titre": src.get("titre"),
                "type_source": src.get("type_source"),
                "auteur": src.get("auteur"),
                "date_publication": src.get("date_publication"),
                "fiabilite_score": src.get("fiabilite_score"),
            }
        )

    prompt = (
        "Tu es un analyste en veille scientifique et technologique appliquant une méthode "
        "stricte « Anti-Boîte Noire » orientée décision.\n"
        f'À partir de la liste de sources ci-dessous sur le sujet "{TARGET_TOPIC}", '
        "extrais les éléments analytiques les plus importants et rattache chacun à son "
        "`source_id` exact.\n\n"
        "Règles de classification (`type_element`) :\n"
        '- "fait_etabli" : résultat empirique ou constat objectivé issu d\'une étude '
        "scientifique (ex: une étude académique montre X).\n"
        '- "interpretation" : promesse commerciale, argument marketing d\'un éditeur/fournisseur '
        "ou projection non vérifiée indépendamment (ex: un fournisseur promet Y).\n"
        '- "lacune" : angle mort, limite méthodologique ou manque de données identifié '
        "(ex: manque de données empiriques sur la sécurité, la confidentialité ou la maintenabilité).\n\n"
        "Contraintes strictes :\n"
        "1. Produis des descriptions courtes, précises et rédigées en français.\n"
        "2. Assure-toi de couvrir les trois catégories (`fait_etabli`, `interpretation`, `lacune`) "
        "lorsque le corpus le permet.\n"
        "3. `source_id` doit obligatoirement correspondre à un `id` existant dans la liste fournie.\n"
        "4. `niveau_confiance` doit être un flottant entre 0.0 et 1.0 reflétant la solidité de l'élément.\n"
        "5. Réponds UNIQUEMENT au format JSON structuré respectant le schéma fourni.\n\n"
        f"Sources disponibles :\n{json.dumps(compact_sources, ensure_ascii=False, indent=2)}"
    )

    raw_response_text = _call_gemini_structured(
        prompt=prompt,
        response_schema=ExtractionPreuvesResponse,
    )
    if raw_response_text is None:
        return None

    try:
        cleaned_json = _clean_json_text(raw_response_text)
        parsed = json.loads(cleaned_json)
        return _validate_and_normalize_evidence(parsed, valid_source_ids)
    except (json.JSONDecodeError, ValueError) as exc:
        error_msg = (
            f"[ERREUR] Impossible de parser le JSON des preuves retourné par Gemini : {exc}"
        )
        print(error_msg)
        logger.error("%s | Réponse brute : %s", error_msg, raw_response_text)
        return None


def _validate_and_normalize_report(payload: Any) -> dict[str, Any]:
    """Valide et normalise le rapport décisionnel JSON retourné par Gemini."""
    if not isinstance(payload, dict):
        raise ValueError("Le rapport retourné n'est pas un objet JSON valide.")

    synthese = str(payload.get("synthese_globale", "")).strip()
    if not synthese:
        raise ValueError("Le champ 'synthese_globale' est manquant ou vide.")

    raw_contradictions = payload.get("contradictions_identifiees", [])
    contradictions = (
        [str(c).strip() for c in raw_contradictions if str(c).strip()]
        if isinstance(raw_contradictions, list)
        else []
    )

    valid_actions = {"adopter": "Adopter", "expérimenter": "Expérimenter", "experimenter": "Expérimenter", "surveiller": "Surveiller", "différer": "Différer", "differer": "Différer"}
    raw_options = payload.get("options", [])
    options: list[dict[str, str]] = []
    if isinstance(raw_options, list):
        for opt in raw_options:
            if not isinstance(opt, dict):
                continue
            raw_act = str(opt.get("action", "")).strip()
            act = valid_actions.get(raw_act.lower(), raw_act or "Expérimenter")
            imp = str(opt.get("implications", "")).strip()
            if imp:
                options.append({"action": act, "implications": imp})

    raw_rec = payload.get("recommandation_finale", {})
    if not isinstance(raw_rec, dict):
        raw_rec = {}
    conf_map = {"faible": "Faible", "moyen": "Moyen", "fort": "Fort"}
    raw_conf = str(raw_rec.get("niveau_confiance", "Moyen")).strip()
    recommandation = {
        "action_proposee": str(raw_rec.get("action_proposee", "Expérimenter")).strip(),
        "niveau_confiance": conf_map.get(raw_conf.lower(), "Moyen"),
        "justification": str(raw_rec.get("justification", "")).strip(),
    }

    raw_conditions = payload.get("conditions_revision", [])
    conditions = (
        [str(cond).strip() for cond in raw_conditions if str(cond).strip()]
        if isinstance(raw_conditions, list)
        else []
    )

    return {
        "synthese_globale": synthese,
        "contradictions_identifiees": contradictions,
        "options": options,
        "recommandation_finale": recommandation,
        "conditions_revision": conditions,
    }


def generate_decision_report(
    sources_list: list[dict[str, Any]],
    faits_list: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Génère une note de synthèse exécutive orientée décision à partir des sources et preuves.

    Met en évidence les convergences et contradictions entre fournisseurs et études
    scientifiques indépendantes, compare les options d'action et formule une recommandation
    proportionnée aux preuves accompagnée de ses conditions de révision.

    Args:
        sources_list: Liste des sources enregistrées dans ``sources``.
        faits_list: Liste des preuves extraites issues de ``get_all_faits()``.

    Returns:
        Dictionnaire structuré conforme à ``RapportDecisionnelResponse``, ou ``None``
        si la clé API est absente ou si l'appel échoue après réessais.
    """
    load_dotenv(dotenv_path=ENV_PATH)
    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        error_msg = (
            "[ERREUR] Clé API Gemini absente ou vide (variable GEMINI_API_KEY). "
            "Génération du rapport décisionnel annulée."
        )
        print(error_msg)
        logger.error(error_msg)
        return None

    if not sources_list and not faits_list:
        return None

    compact_sources = [
        {
            "id": src.get("id"),
            "titre": src.get("titre"),
            "type_source": src.get("type_source"),
            "auteur": src.get("auteur"),
            "date_publication": src.get("date_publication"),
            "fiabilite_score": src.get("fiabilite_score"),
            "groupe_sujet": src.get("groupe_sujet"),
            "pertinence_score": src.get("pertinence_score"),
        }
        for src in sources_list
    ]

    compact_faits = [
        {
            "id": fait.get("id"),
            "source_id": fait.get("source_id"),
            "type_element": fait.get("type_element"),
            "description": fait.get("description"),
            "niveau_confiance": fait.get("niveau_confiance"),
            "type_source": fait.get("type_source"),
        }
        for fait in faits_list
    ]

    prompt = (
        "Tu es un directeur de la veille scientifique et technologique rédigeant une note "
        "d'aide à la décision exécutive sur l'adoption des assistants IA de programmation "
        f'("{TARGET_TOPIC}").\n\n'
        "Instructions méthodologiques strictes (approche Anti-Boîte Noire) :\n"
        "1. `synthese_globale` : rédige un résumé analytique concis en français citant "
        "explicitement les identifiants des sources entre crochets (ex: [Source #1], [Source #4]).\n"
        "2. `contradictions_identifiees` : identifie explicitement les divergences, tensions ou "
        "contradictions entre les promesses commerciales des éditeurs (`Fournisseur` / `interpretation`) "
        "et les constats ou limites des études académiques indépendantes (`Scientifique` / `fait_etabli` "
        "ou `lacune`), en citant systématiquement les IDs des sources opposées.\n"
        "3. `options` : évalue successivement les 4 postures stratégiques (`Adopter`, `Expérimenter`, "
        "`Surveiller`, `Différer`) en précisant leurs implications techniques, sécurité et coûts.\n"
        "4. `recommandation_finale` : propose une décision claire (`action_proposee`), attribue un "
        "`niveau_confiance` (`Faible`, `Moyen` ou `Fort`) et rédige une `justification` strictement "
        "proportionnée à la solidité réelle des preuves et au poids des lacunes identifiées.\n"
        "5. `conditions_revision` : liste les événements futurs, seuils critiques ou nouvelles preuves "
        "empiriques qui imposeraient de réviser cette décision.\n"
        "6. Réponds UNIQUEMENT au format JSON structuré respectant le schéma fourni.\n\n"
        f"Référentiel des sources :\n{json.dumps(compact_sources, ensure_ascii=False, indent=2)}\n\n"
        f"Preuves extraites (faits, interprétations, lacunes) :\n"
        f"{json.dumps(compact_faits, ensure_ascii=False, indent=2)}"
    )

    raw_response_text = _call_gemini_structured(
        prompt=prompt,
        response_schema=RapportDecisionnelResponse,
    )
    if raw_response_text is None:
        return None

    try:
        cleaned_json = _clean_json_text(raw_response_text)
        parsed = json.loads(cleaned_json)
        return _validate_and_normalize_report(parsed)
    except (json.JSONDecodeError, ValueError) as exc:
        error_msg = (
            f"[ERREUR] Impossible de parser le rapport décisionnel JSON retourné par Gemini : {exc}"
        )
        print(error_msg)
        logger.error("%s | Réponse brute : %s", error_msg, raw_response_text)
        return None
