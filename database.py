"""Module de gestion et d'initialisation de la base de données SQLite locale."""

from contextlib import closing
from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "veille.db"


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Crée et retourne une connexion SQLite configurée (clés étrangères activées).

    Args:
        db_path: Chemin vers le fichier de base de données SQLite.

    Returns:
        Objet de connexion ``sqlite3.Connection``.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _migrate_sources_table_if_needed(conn: sqlite3.Connection) -> None:
    """Met à jour la table ``sources`` existante si l'unicité sur ``url`` ou la casse manque."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'sources';"
    ).fetchone()
    if row is None:
        return

    ddl: str = row["sql"] or ""
    if "UNIQUE" in ddl.upper() and "LOWER(TYPE_SOURCE)" in ddl.upper():
        return

    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.execute("PRAGMA legacy_alter_table = ON;")
    try:
        conn.execute("ALTER TABLE sources RENAME TO _sources_legacy;")
        conn.execute(
            """
            CREATE TABLE sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titre TEXT NOT NULL,
                url TEXT UNIQUE,
                type_source TEXT NOT NULL CHECK(
                    LOWER(type_source) IN ('scientifique', 'fournisseur', 'blog', 'presse')
                ),
                date_publication TEXT,
                auteur TEXT,
                fiabilite_score REAL,
                groupe_sujet TEXT,
                pertinence_score REAL
            );
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO sources (
                id, titre, url, type_source, date_publication, auteur, fiabilite_score
            )
            SELECT id, titre, url, type_source, date_publication, auteur, fiabilite_score
            FROM _sources_legacy;
            """
        )
        conn.execute("DROP TABLE _sources_legacy;")
        conn.commit()
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF;")
        conn.execute("PRAGMA foreign_keys = ON;")


def _repair_faits_extraits_fk_if_needed(conn: sqlite3.Connection) -> None:
    """Répare la clé étrangère de ``faits_extraits`` si elle pointe vers ``_sources_legacy``."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'faits_extraits';"
    ).fetchone()
    if row is None:
        return

    ddl: str = row["sql"] or ""
    if "_sources_legacy" not in ddl:
        return

    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.execute("PRAGMA legacy_alter_table = ON;")
    try:
        conn.execute("ALTER TABLE faits_extraits RENAME TO _faits_extraits_legacy;")
        conn.execute(
            """
            CREATE TABLE faits_extraits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                type_element TEXT NOT NULL CHECK(
                    LOWER(type_element) IN ('fait_etabli', 'interpretation', 'lacune')
                ),
                description TEXT NOT NULL,
                niveau_confiance TEXT,
                FOREIGN KEY (source_id) REFERENCES sources (id) ON DELETE CASCADE
            );
            """
        )
        conn.execute(
            """
            INSERT INTO faits_extraits (
                id, source_id, type_element, description, niveau_confiance
            )
            SELECT id, source_id, type_element, description, niveau_confiance
            FROM _faits_extraits_legacy
            WHERE source_id IN (SELECT id FROM sources);
            """
        )
        conn.execute("DROP TABLE _faits_extraits_legacy;")
        conn.commit()
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF;")
        conn.execute("PRAGMA foreign_keys = ON;")


def _ensure_qualification_columns(conn: sqlite3.Connection) -> None:
    """Ajoute les colonnes ``groupe_sujet`` et ``pertinence_score`` via ``ALTER TABLE`` si absentes."""
    existing_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(sources);").fetchall()
    }
    if not existing_columns:
        return

    if "groupe_sujet" not in existing_columns:
        conn.execute("ALTER TABLE sources ADD COLUMN groupe_sujet TEXT;")
    if "pertinence_score" not in existing_columns:
        conn.execute("ALTER TABLE sources ADD COLUMN pertinence_score REAL;")


def init_db(db_path: Path = DB_PATH) -> None:
    """Initialise la base de données ``veille.db`` et crée ou migre les tables si nécessaires.

    Tables créées :
        - ``sources`` : Référentiel des sources collectées et qualifiées (URL unique).
        - ``faits_extraits`` : Éléments analytiques rattachés à une source.
        - ``requetes_journal`` : Historique des requêtes de veille effectuées.

    Args:
        db_path: Chemin vers le fichier de base de données SQLite.
    """
    with closing(get_connection(db_path)) as conn:
        conn.execute("PRAGMA legacy_alter_table = ON;")
        try:
            _migrate_sources_table_if_needed(conn)
            _repair_faits_extraits_fk_if_needed(conn)
        finally:
            conn.execute("PRAGMA legacy_alter_table = OFF;")
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titre TEXT NOT NULL,
                url TEXT UNIQUE,
                type_source TEXT NOT NULL CHECK(
                    LOWER(type_source) IN ('scientifique', 'fournisseur', 'blog', 'presse')
                ),
                date_publication TEXT,
                auteur TEXT,
                fiabilite_score REAL,
                groupe_sujet TEXT,
                pertinence_score REAL
            );
            """
        )

        # Migration ALTER TABLE si la table sources existait déjà sans les colonnes Phase 3
        _ensure_qualification_columns(conn)

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS faits_extraits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                type_element TEXT NOT NULL CHECK(
                    LOWER(type_element) IN ('fait_etabli', 'interpretation', 'lacune')
                ),
                description TEXT NOT NULL,
                niveau_confiance TEXT,
                FOREIGN KEY (source_id) REFERENCES sources (id) ON DELETE CASCADE
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS requetes_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date_requete TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                mots_cles TEXT NOT NULL,
                mode_recherche TEXT NOT NULL CHECK(
                    LOWER(mode_recherche) IN ('mine', 'trawl', 'target', 'scan')
                )
            );
            """
        )

        conn.commit()


def insert_source(
    titre: str,
    url: str,
    type_source: str,
    date_pub: str,
    auteur: str,
    fiabilite_score: float | None = None,
    db_path: Path = DB_PATH,
) -> bool:
    """Insère une source dans la table ``sources`` en évitant les doublons stricts sur l'URL.

    Args:
        titre: Titre du document ou de l'article.
        url: URL canonique de la source (contrainte d'unicité).
        type_source: Catégorie (Scientifique, Fournisseur, Blog, Presse).
        date_pub: Date de publication au format texte (ex. ``YYYY-MM-DD``).
        auteur: Nom du ou des auteurs / éditeur.
        fiabilite_score: Score de fiabilité associé à la source.
        db_path: Chemin vers le fichier SQLite.

    Returns:
        ``True`` si la source a été insérée, ``False`` si elle existait déjà.
    """
    clean_url = url.strip() if url else None

    with closing(get_connection(db_path)) as conn:
        cursor = conn.cursor()

        if clean_url:
            existing = cursor.execute(
                "SELECT 1 FROM sources WHERE url = ? LIMIT 1;",
                (clean_url,),
            ).fetchone()
            if existing is not None:
                return False

        cursor.execute(
            """
            INSERT OR IGNORE INTO sources (
                titre, url, type_source, date_publication, auteur, fiabilite_score
            )
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (titre.strip(), clean_url, type_source.strip(), date_pub, auteur, fiabilite_score),
        )
        conn.commit()
        return cursor.rowcount > 0


def update_source_qualification(
    source_id: int,
    groupe_sujet: str,
    pertinence_score: float,
    db_path: Path = DB_PATH,
) -> bool:
    """Met à jour le groupe thématique et le score de pertinence d'une source existante.

    Args:
        source_id: Identifiant unique (``id``) de la source dans la table ``sources``.
        groupe_sujet: Sujet principal attribué lors du dédoublonnage sémantique.
        pertinence_score: Score de pertinence compris entre ``0.0`` et ``1.0``.
        db_path: Chemin vers le fichier SQLite.

    Returns:
        ``True`` si la ligne correspondante a été mise à jour, ``False`` sinon.
    """
    with closing(get_connection(db_path)) as conn:
        _ensure_qualification_columns(conn)
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE sources
            SET groupe_sujet = ?, pertinence_score = ?
            WHERE id = ?;
            """,
            (groupe_sujet, float(pertinence_score), int(source_id)),
        )
        conn.commit()
        return cursor.rowcount > 0


def get_all_sources(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Retourne l'ensemble des sources enregistrées sous forme de liste de dictionnaires.

    Args:
        db_path: Chemin vers le fichier SQLite.

    Returns:
        Liste de dictionnaires représentant les lignes de la table ``sources``.
    """
    with closing(get_connection(db_path)) as conn:
        _ensure_qualification_columns(conn)
        rows = conn.execute(
            """
            SELECT
                id,
                titre,
                url,
                type_source,
                date_publication,
                auteur,
                fiabilite_score,
                groupe_sujet,
                pertinence_score
            FROM sources
            ORDER BY id DESC;
            """
        ).fetchall()
        return [dict(row) for row in rows]


def insert_fait_extrait(
    source_id: int,
    type_element: str,
    description: str,
    niveau_confiance: float,
    db_path: Path = DB_PATH,
) -> bool:
    """Insère une preuve analytique dans ``faits_extraits`` liée à sa source d'origine.

    Évite les doublons exacts (même ``source_id``, ``type_element`` et ``description``)
    et vérifie l'existence préalable de la source référencée.

    Args:
        source_id: Identifiant (``id``) de la source dans la table ``sources``.
        type_element: Catégorie (``fait_etabli``, ``interpretation`` ou ``lacune``).
        description: Énoncé synthétique de l'élément extrait.
        niveau_confiance: Niveau de confiance compris entre ``0.0`` et ``1.0``.
        db_path: Chemin vers le fichier SQLite.

    Returns:
        ``True`` si l'élément a été inséré, ``False`` s'il existait déjà ou si la source est absente.
    """
    clean_type = type_element.strip().lower()
    clean_desc = description.strip()
    if not clean_desc:
        return False

    with closing(get_connection(db_path)) as conn:
        _repair_faits_extraits_fk_if_needed(conn)
        cursor = conn.cursor()

        source_exists = cursor.execute(
            "SELECT 1 FROM sources WHERE id = ? LIMIT 1;",
            (int(source_id),),
        ).fetchone()
        if source_exists is None:
            return False

        duplicate = cursor.execute(
            """
            SELECT 1
            FROM faits_extraits
            WHERE source_id = ? AND LOWER(type_element) = ? AND description = ?
            LIMIT 1;
            """,
            (int(source_id), clean_type, clean_desc),
        ).fetchone()
        if duplicate is not None:
            return False

        cursor.execute(
            """
            INSERT INTO faits_extraits (
                source_id, type_element, description, niveau_confiance
            )
            VALUES (?, ?, ?, ?);
            """,
            (int(source_id), clean_type, clean_desc, round(float(niveau_confiance), 2)),
        )
        conn.commit()
        return cursor.rowcount > 0


def get_all_faits(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Retourne tous les éléments extraits joints au titre et à l'URL de leur source d'origine.

    Args:
        db_path: Chemin vers le fichier SQLite.

    Returns:
        Liste de dictionnaires issus de la jointure ``faits_extraits`` / ``sources``.
    """
    with closing(get_connection(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT
                f.id,
                f.type_element,
                f.description,
                CAST(f.niveau_confiance AS REAL) AS niveau_confiance,
                f.source_id,
                s.titre AS source_titre,
                s.url AS source_url,
                s.type_source
            FROM faits_extraits AS f
            INNER JOIN sources AS s ON f.source_id = s.id
            ORDER BY f.id DESC;
            """
        ).fetchall()
        return [dict(row) for row in rows]


def insert_requete_journal(
    mots_cles: str,
    mode_recherche: str = "Target",
    db_path: Path = DB_PATH,
) -> bool:
    """Enregistre une requête de collecte dans la table ``requetes_journal``.

    Args:
        mots_cles: Expression de recherche saisie par le veilleur.
        mode_recherche: Mode méthodologique (``Mine``, ``Trawl``, ``Target`` ou ``Scan``).
        db_path: Chemin vers le fichier SQLite.

    Returns:
        ``True`` si l'entrée a été journalisée avec succès.
    """
    clean_kw = mots_cles.strip()
    if not clean_kw:
        return False

    valid_modes = {"mine": "Mine", "trawl": "Trawl", "target": "Target", "scan": "Scan"}
    normalized_mode = valid_modes.get(mode_recherche.strip().lower(), "Target")
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with closing(get_connection(db_path)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO requetes_journal (date_requete, mots_cles, mode_recherche)
            VALUES (?, ?, ?);
            """,
            (timestamp_str, clean_kw, normalized_mode),
        )
        conn.commit()
        return cursor.rowcount > 0


def get_all_requetes(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Retourne l'historique complet des requêtes de veille enregistrées.

    Args:
        db_path: Chemin vers le fichier SQLite.

    Returns:
        Liste de dictionnaires représentant les entrées de ``requetes_journal``.
    """
    with closing(get_connection(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT id, date_requete, mots_cles, mode_recherche
            FROM requetes_journal
            ORDER BY id DESC;
            """
        ).fetchall()
        return [dict(row) for row in rows]


if __name__ == "__main__":
    init_db()
    print(f"Base de données initialisée avec succès : {DB_PATH}")
