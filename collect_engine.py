"""Moteur de collecte de sources scientifiques (ArXiv) et commerciales (fournisseurs)."""

import logging
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

ATOM_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_API_BASE_URL = "http://export.arxiv.org/api/query"


def fetch_arxiv(keyword: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Interroge l'API publique ArXiv et retourne une liste d'articles scientifiques.

    Args:
        keyword: Mots-clés de recherche (ex. ``"LLM programming assistants"``).
        max_results: Nombre maximal d'articles à récupérer (par défaut 5).

    Returns:
        Liste de dictionnaires contenant ``titre``, ``url``, ``type_source``,
        ``date_publication`` et ``auteur``. Retourne une liste vide en cas d'erreur.
    """
    cleaned_keyword = keyword.strip()
    if not cleaned_keyword:
        return []

    terms = cleaned_keyword.split()
    if len(terms) > 1 and not any(op in terms for op in ("AND", "OR", "ANDNOT")):
        search_query = "+AND+".join(
            f"all:{urllib.parse.quote_plus(term)}" for term in terms
        )
    else:
        search_query = f"all:{urllib.parse.quote_plus(cleaned_keyword)}"

    url = f"{ARXIV_API_BASE_URL}?search_query={search_query}&max_results={max_results}"

    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "SystemeVeilleStrategique/1.0 (Academic Prototype)"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            xml_bytes = response.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        logger.error("Erreur réseau lors de l'appel à l'API ArXiv (%s) : %s", url, exc)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.error("Erreur inattendue lors de la requête ArXiv : %s", exc)
        return []

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        logger.error("Erreur de parsing XML sur la réponse ArXiv : %s", exc)
        return []

    results: list[dict[str, Any]] = []
    for entry in root.findall(f"{ATOM_NS}entry"):
        raw_title = entry.findtext(f"{ATOM_NS}title", default="")
        titre = " ".join(raw_title.split())

        raw_url = entry.findtext(f"{ATOM_NS}id", default="").strip()

        raw_published = entry.findtext(f"{ATOM_NS}published", default="").strip()
        date_publication = raw_published[:10] if raw_published else "Non renseignée"

        authors = [
            name_elem.text.strip()
            for author_elem in entry.findall(f"{ATOM_NS}author")
            if (name_elem := author_elem.find(f"{ATOM_NS}name")) is not None
            and name_elem.text
        ]
        auteur = ", ".join(authors) if authors else "Auteur inconnu"

        if titre and raw_url:
            results.append(
                {
                    "titre": titre,
                    "url": raw_url,
                    "type_source": "Scientifique",
                    "date_publication": date_publication,
                    "auteur": auteur,
                }
            )

    return results


def get_vendor_sources() -> list[dict[str, Any]]:
    """Retourne un jeu de sources écosystème (Fournisseur, Blog, Presse) incluant des republications.

    Inclut volontairement deux republications manifestes (un article de blog tech et une
    dépêche presse) de l'annonce officielle GitHub Copilot afin de démontrer et valider
    le Test minimal n°1 (dédoublonnage sémantique : les copies ne valent pas confirmation).

    Returns:
        Liste de 5 dictionnaires (3 sources Fournisseur + 1 reprise Blog + 1 dépêche Presse).
    """
    return [
        {
            "titre": "GitHub Copilot Documentation - Measuring Impact & Developer Productivity",
            "url": "https://docs.github.com/en/copilot/about-github-copilot/measuring-impact",
            "type_source": "Fournisseur",
            "date_publication": "2025-02-14",
            "auteur": "GitHub / Microsoft",
        },
        {
            "titre": "DevOps Digest (Reprise) - GitHub Copilot : Measuring Impact & Developer Productivity",
            "url": "https://devops-digest.example.com/2025/02/github-copilot-measuring-impact-repost",
            "type_source": "Blog",
            "date_publication": "2025-02-15",
            "auteur": "Rédaction DevOps Digest (Republication annonce GitHub)",
        },
        {
            "titre": "TechPress Dépêche - GitHub publie son guide 'Measuring Impact & Developer Productivity' pour Copilot",
            "url": "https://techpress-actu.example.com/depeches/github-copilot-measuring-impact-2025",
            "type_source": "Presse",
            "date_publication": "2025-02-16",
            "auteur": "Agence TechPress (Dépêche sur annonce GitHub)",
        },
        {
            "titre": "Tabnine Blog - Enterprise AI Code Assistant: Privacy, Security & Context",
            "url": "https://www.tabnine.com/blog/enterprise-ai-code-assistant-architecture/",
            "type_source": "Fournisseur",
            "date_publication": "2025-01-22",
            "auteur": "Tabnine Engineering Team",
        },
        {
            "titre": "Amazon Q Developer Announcement - Autonomous Software Development Agents",
            "url": "https://aws.amazon.com/blogs/aws/amazon-q-developer-agents-announcement/",
            "type_source": "Fournisseur",
            "date_publication": "2024-12-03",
            "auteur": "Amazon Web Services (AWS)",
        },
    ]
