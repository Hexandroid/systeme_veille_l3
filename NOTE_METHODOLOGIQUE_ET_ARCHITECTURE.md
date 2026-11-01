# Note Méthodologique et d'Architecture — Système de Veille Stratégique Orienté Décision

**Domaine d'étude :** Assistants de programmation fondés sur les Grands Modèles de Langage (*LLM Programming Assistants*)  
**Nature du livrable :** Dossier méthodologique, épistémologique et architectural accompagnant le prototype logiciel  

---

## 1. Formulation et Cadrage de la Question de Veille

Un dispositif de veille scientifique et technologique ne se juge pas au volume brut de documents collectés, mais à sa capacité à réduire l'incertitude d'un décideur face à un choix engageant des ressources et des risques. Conformément aux standards d'ingénierie de la veille stratégique, la problématique traitée par ce prototype est formalisée selon cinq dimensions structurantes :

| Dimension de cadrage | Définition opérationnelle retenue |
| :--- | :--- |
| **Destinataire** | Direction des Systèmes d'Information (DSI), Direction de l'Ingénierie Logicielle (*VP Engineering*) et Responsable de la Sécurité des Systèmes d'Information (RSSI) d'une organisation développant des actifs logiciels propriétaires. |
| **Décision à éclairer** | Choisir la posture d'investissement et de déploiement vis-à-vis des assistants IA de génération et de revue de code parmi quatre options mutuellement exclusives à court terme : **Adopter** à l'échelle, **Expérimenter** sur un périmètre pilote encadré, **Surveiller** activement l'état de l'art, ou **Différer** tout déploiement. |
| **Objet et périmètre** | Évaluation croisée des performances réelles (productivité développeur, qualité logicielle, maintenabilité), des risques induits (vulnérabilités de sécurité, attaques adversariales, propriété intellectuelle, dépendance fournisseur) et de la maturité des assistants de code (*GitHub Copilot*, *Tabnine*, *Amazon Q Developer* et modèles sous-jacents étudiés dans la littérature académique). |
| **Horizon temporel** | Décision tactique et budgétaire à **6–12 mois**, assortie d'une veille continue sur les études longitudinales (dette technique et sécurité à **12–24 mois**). |
| **Contraintes** | Budget de licences par développeur limité ; exigence stricte de confidentialité du code source ; interdiction d'introduire des régressions de sécurité non maîtrisées ; exigence d'**auditabilité (« Anti-Boîte Noire »)** interdisant toute recommandation générée sans lien vérifiable vers ses sources primaires. |

**Formulation synthétique de la question centrale de veille :**
> *« Dans quelle mesure les gains de productivité revendiqués par les éditeurs d'assistants IA de programmation sont-ils corroborés par la littérature scientifique indépendante, quels angles morts sécuritaires ou méthodologiques subsistent, et quelle posture d'adoption graduée une DSI soumise à de fortes contraintes de sécurité doit-elle retenir à horizon 6–12 mois ? »*

Afin d'outiller cette démarche dès la collecte, le prototype intègre les quatre modes classiques de recherche informationnelle dans son journal d'audit (`requetes_journal`) : **Scan** (balayage large d'exploration), **Trawl** (chalutage thématique ciblé), **Mine** (extraction approfondie sur une source identifiée) et **Target** (vérification ciblée d'une hypothèse ou d'un produit).

---

## 2. Architecture Technique et Justification de la Stack

### 2.1 Vue d'ensemble en couches découplées

Le prototype repose sur une architecture modulaire à quatre composants strictement séparés afin de garantir la maintenabilité, la testabilité unitaire et l'absence de couplage entre l'interface graphique, le stockage relationnel et l'inférence par IA générative :

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                        INTERFACE UTILISATEUR (app.py)                        │
│   Streamlit : Page 1 (Collecte, Filtres Fraîcheur/Pertinence, Preuves)       │
│               Page 2 (KPIs Exécutifs, Contradictions, Options, Export .md)   │
└───────────────┬──────────────────────────────┬───────────────────────────────┘
                │                              │
                ▼                              ▼
┌───────────────────────────────┐  ┌───────────────────────────────────────────┐
│   COLLECTE (collect_engine.py)│  │   ANALYSE IA (analysis_engine.py)         │
│ • API ouverte ArXiv (XML Atom)│  │ • SDK officiel google-genai               │
│ • Corpus Écosystème (Éditeurs,│  │ • Modèle gemini-3.8-flash                 │
│   Presse, Blog + Republication│  │ • Contrats JSON stricts via Pydantic      │
│   de contrôle pour Test n°1)  │  │ • Résilience : Timeout 120s + 3x Retries  │
└───────────────┬───────────────┘  └─────────────────────┬─────────────────────┘
                │                                        │
                └───────────────────┬────────────────────┘
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                 PERSISTANCE RELATIONNELLE (database.py)                      │
│   SQLite3 local (data/veille.db) — PRAGMA foreign_keys = ON                  │
│   • Table `sources`          (URL unique, fiabilité a priori, groupe, score) │
│   • Table `faits_extraits`   (FK source_id, fait_etabli/interpretation/lacune│
│   • Table `requetes_journal` (Horodatage, mots-clés, mode Scan/Trawl/Mine/…) │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Justification raisonnée des choix technologiques

1. **Python 3.12 & Bibliothèque standard (`urllib.request`, `xml.etree.ElementTree`, `sqlite3`)** : Pour l'interrogation de l'API ouverte d'ArXiv et la persistance relationnelle, le recours aux modules natifs élimine les dépendances superflues fragiles, garantit la reproductibilité sur tout poste d'évaluation (Windows, macOS, Linux) et facilite l'audit du code.
2. **SQLite 3 avec intégrité référentielle stricte (`database.py`)** : Contrairement à un simple stockage plat en fichiers CSV ou JSON, SQLite permet de modéliser formellement la relation `1-N` entre une source primaire (`sources.id`) et ses éléments analytiques (`faits_extraits.source_id`) via `FOREIGN KEY ... ON DELETE CASCADE` avec activation systématique de `PRAGMA foreign_keys = ON`. Les migrations de schéma utilisent `PRAGMA legacy_alter_table = ON` et un mécanisme d'auto-réparation (`_repair_faits_extraits_fk_if_needed`) garantissant une robustesse totale lors des évolutions de structure.
3. **SDK officiel `google-genai` et modèle `gemini-3.8-flash` (`analysis_engine.py`)** : L'adoption du nouveau SDK unifié `google-genai` (en remplacement de l'ancien paquet déprécié `google-generativeai`) permet d'exploiter le **décodage JSON contraint par schéma Pydantic** (`response_mime_type="application/json"` et `response_schema=...`). Le modèle `gemini-3.8-flash` offre une fenêtre de contexte étendue et une excellente capacité de raisonnement analytique multilingue (corpus anglophone ArXiv restitué en synthèse francophone précise).
4. **Pydantic v2 comme contrat de sortie déterministe** : Trois familles de modèles (`QualificationResponse`, `ExtractionPreuvesResponse`, `RapportDecisionnelResponse`) verrouillent le typage des sorties de l'IA. L'IA ne peut pas produire du texte libre flou : elle est contrainte de classifier chaque énoncé dans une catégorie fermée (`Literal["fait_etabli", "interpretation", "lacune"]`), d'associer un `source_id` entier et de chiffrer la confiance entre `0.0` et `1.0`.
5. **Streamlit & Pandas (`app.py`)** : Permet de séparer clairement le plan opérationnel de l'analyste (Page 1 : collecte, dédoublonnage, filtrage du bruit, inspection des preuves et journal des requêtes) du plan exécutif du décideur (Page 2 : KPIs synthétiques, contradictions, options d'action, recommandation argumentée et export Markdown téléchargeable).

---

## 3. Application Opérationnelle de la Méthode TRACE dans le Code

Le système traduit directement les cinq piliers méthodologiques **TRACE** (*Tracer, Remonter, Apprécier, Comparer, Expliciter*) en mécanismes logiciels vérifiables :

| Pilier TRACE | Exigence méthodologique | Traduction concrète dans l'architecture du code |
| :--- | :--- | :--- |
| **T — Tracer** | Conserver la mémoire complète du processus de collecte et l'origine exacte des documents. | Chaque exécution du bouton *« Lancer la collecte »* journalise automatiquement la date/heure, l'expression exacte et le mode (`Target`, `Mine`, `Trawl`, `Scan`) dans `requetes_journal` via `insert_requete_journal()`. Chaque source conserve son URL canonique unique, sa date de publication et ses auteurs. |
| **R — Remonter** | Permettre à tout lecteur de vérifier une affirmation en remontant sans friction jusqu'au document source (« Anti-Boîte Noire »). | La table `faits_extraits` impose une clé étrangère non nulle `source_id`. La fonction `get_all_faits()` exécute un `INNER JOIN` SQL exposant simultanément l'affirmation, le titre de l'article et un lien cliquable (`st.column_config.LinkColumn`). Dans le rapport final, le prompt et l'annexe exigent des citations explicites `[Source #ID]`. |
| **A — Apprécier** | Ne jamais traiter toutes les sources ni tous les énoncés comme équivalents en crédibilité. | Double pondération : (1) un barème de **fiabilité a priori** (`DEFAULT_RELIABILITY_BY_TYPE`) distingue études académiques (`0.85`), presse spécialisée (`0.65`), communication fournisseur (`0.50`) et blogs (`0.40`) ; (2) lors de l'extraction (`extract_evidence`), chaque énoncé reçoit un statut épistémique (`fait_etabli`, `interpretation`, `lacune`) et un `niveau_confiance` propre. |
| **C — Comparer** | Neutraliser l'effet d'écho des republications et confronter les thèses contradictoires ainsi que les options d'action. | `analyze_duplicates_and_qualify()` regroupe les reprises médiatiques sous un même `groupe_sujet`. `generate_decision_report()` isole explicitement les oppositions entre revendications éditeurs et constats scientifiques dans `contradictions_identifiees`, puis met en balance les quatre options (`Adopter`, `Expérimenter`, `Surveiller`, `Différer`). |
| **E — Expliciter** | Rendre transparents le degré de certitude, les zones d'ombre et les critères qui invalideraient la décision. | Les angles morts sont extraits comme objets de première classe (`type_element = 'lacune'`) et comptabilisés en KPI exécutif. La recommandation finale affiche un badge explicite de confiance (`Faible`, `Moyen`, `Fort`), une justification proportionnée aux preuves et un bloc dédié aux **conditions de révision** (`conditions_revision`). |

---

## 4. Démonstration de Validation des 5 Tests Minimaux du Cahier des Charges

Le prototype a été conçu et instrumenté pour démontrer empiriquement la réussite des cinq tests minimaux d'évaluation :

### Test minimal n°1 — Détection des republications (une copie ne vaut pas confirmation indépendante)
- **Dispositif implémenté :** Outre la déduplication stricte sur l'URL (`UNIQUE` + `INSERT OR IGNORE` dans `insert_source`), la fonction `get_vendor_sources()` dans `collect_engine.py` injecte un cas test contrôlé : l'annonce officielle *« GitHub Copilot Documentation - Measuring Impact & Developer Productivity »* (`Fournisseur`) accompagnée de **deux republications manifestes** portant sur le même fond mais hébergées sur des URLs et typologies distinctes : un billet de reprise *DevOps Digest* (`Blog`) et une dépêche *TechPress* (`Presse`).
- **Preuve visuelle :** Après collecte (10 sources au total : 5 ArXiv + 5 écosystème), le clic sur *« Dédoublonner et Qualifier avec l'IA »* fusionne ces trois publications dans un unique `groupe_sujet`. Sur le Tableau de bord Décisionnel (Page 2), le bandeau KPI affiche côte à côte **10 Sources collectées** mais seulement **8 Groupes dédoublonnés** (ou moins si deux preprints ArXiv se recoupent), prouvant que trois répétitions d'une même annonce commerciale ne sont jamais comptées comme trois preuves indépendantes.

### Test minimal n°2 — Distinction stricte entre Fraîcheur et Pertinence
- **Dispositif implémenté :** Le schéma de données sépare `date_publication` (dimension temporelle de fraîcheur) et `pertinence_score` (adéquation sémantique au besoin décisionnel sur `[0.0, 1.0]`). Sur la Page 1, le sélecteur *« Axe de tri — Fraîcheur vs Pertinence »* permet de basculer instantanément entre un tri par **Date de publication décroissante** et un tri par **Pertinence décroissante** ou **Fiabilité a priori**.
- **Preuve visuelle :** Une dépêche très récente (`2025-02-16`) ou un article ArXiv récent tangentiel au sujet (ex. *fuzzing* assisté par LLM) apparaît en tête par fraîcheur mais redescend lors du tri par pertinence au profit d'études empiriques plus anciennes mais directement centrées sur les assistants conversationnels de programmation. Fraîcheur et pertinence ne sont jamais confondues.

### Test minimal n°3 — Détection et mise en évidence des contradictions entre sources
- **Dispositif implémenté :** Le corpus combine structurellement des sources `Fournisseur` mettant en avant des gains spectaculaires de vitesse de codage (`interpretation`) et des prépublications `Scientifique` d'ArXiv documentant les limites cognitives des développeurs, les erreurs de compréhension ou la vulnérabilité aux attaques adversariales (`fait_etabli` et `lacune`). Le schéma `RapportDecisionnelResponse` impose le champ obligatoire `contradictions_identifiees`.
- **Preuve visuelle :** Sur la Page 2, la section dédiée **« Contradictions identifiées (Fournisseurs vs Études Scientifiques) »** met visuellement en exergue (encadrés à bordure dorée `#FAA61A`) chaque tension entre promesse commerciale et constat académique indépendant, avec citation explicite des `[Source #ID]` opposés.

### Test minimal n°4 — Réduction du bruit documentaire et resserrement du corpus
- **Dispositif implémenté :** En Page 1, le curseur interactif `st.slider("Score de pertinence minimal")` agit en temps réel sur le DataFrame des sources qualifiées et met à jour le compteur dynamique *« Corpus affiché : X / Y source(s) »*. De plus, la requête ArXiv dans `fetch_arxiv()` combine les termes par conjonction logique `+AND+` pour limiter le bruit dès l'acquisition.
- **Preuve visuelle :** En déplaçant le curseur de `0.00` vers `0.75` ou `0.85`, l'évaluateur observe l'élimination immédiate des publications périphériques (bruit documentaire) pour ne conserver que le noyau dur directement mobilisable pour la décision.

### Test minimal n°5 — Proportionnalité de la recommandation, lacunes et conditions de révision
- **Dispositif implémenté :** Le système interdit toute conclusion binaire péremptoire déconnectée du corpus. Les angles morts sont extraits explicitement (`lacune`), comptabilisés dans la 4e carte KPI de la Page 2, et injectés dans le prompt de `generate_decision_report()`. Le schéma `RecommandationFinale` impose un `niveau_confiance` calibré (`Faible`, `Moyen`, `Fort`), et `RapportDecisionnelResponse` exige une liste explicite de `conditions_revision`.
- **Preuve visuelle :** Face à un corpus mêlant gains réels mais partiels et lacunes sur la sécurité ou la dette technique à long terme, le système privilégie typiquement une posture graduée (*« Expérimenter sur un périmètre pilote encadré »*) assortie d'un niveau de confiance *« Moyen »* et énonce clairement les événements futurs (audit sécurité indépendant, métriques à 12 mois, évolution tarifaire) qui commanderaient de réévaluer ce choix.

---

## 5. Limites Méthodologiques, Risques liés à l'IA et Garde-Fous Implémentés

### 5.1 Limites intrinsèques du corpus et biais méthodologiques
1. **Biais de sélection des sources académiques :** L'interrogation automatisée cible ArXiv, qui regroupe majoritairement des prépublications (*preprints*) anglophones parfois non encore évaluées par les pairs (*peer-review*). Une étude ArXiv reçoit un score de fiabilité a priori élevé (`0.85`), qui demeure toutefois inférieur à `1.0` précisément pour refléter cette nuance.
2. **Analyse sur métadonnées vs texte intégral :** Dans le cadre léger de ce prototype, la qualification thématique s'appuie sur les métadonnées structurées (titre, auteur, typologie, date). L'ingestion future des résumés complets (*abstracts*) et des PDF intégraux affinerait la granularité des faits chiffrés extraits.
3. **Asymétrie temporelle :** Les annonces fournisseurs réagissent immédiatement aux sorties commerciales tandis que les évaluations académiques indépendantes accusent un délai de publication de plusieurs mois, ce qui justifie pleinement la séparation entre fraîcheur et pertinence (Test n°2).

### 5.2 Risques spécifiques aux LLM et garde-fous techniques mis en œuvre

| Risque identifié | Garde-fou architectural implémenté dans le prototype |
| :--- | :--- |
| **Hallucination de sources inexistantes** | Dans `_validate_and_normalize_evidence()` (`analysis_engine.py`) et `insert_fait_extrait()` (`database.py`), tout `source_id` retourné par Gemini est vérifié contre l'ensemble exact `valid_source_ids` des identifiants présents dans SQLite. Toute référence forgée est immédiatement rejetée avant insertion. |
| **Dérive de format ou sortie texte non parsable** | Double barrière : (1) contrainte au décodage via `response_mime_type="application/json"` et `response_schema` Pydantic ; (2) nettoyage défensif `_clean_json_text()`, normalisation des bornes numériques `max(0.0, min(1.0, score))` et capture stricte de `json.JSONDecodeError` / `ValueError`. |
| **Latence élevée et erreurs `504 DEADLINE_EXCEEDED` / `503 UNAVAILABLE`** | Centralisation des appels dans `_call_gemini_structured()` configurant `types.HttpOptions(timeout=120000)` (120 secondes côté client et en-tête serveur) couplé à une boucle de **3 tentatives maximales** avec temporisation `time.sleep(5)` sur erreurs transitoires `503`/`504` ou coupures `httpx.HTTPError`. |
| **Absence ou invalidité de la clé API lors de l'évaluation** | Chargement exclusif par variable d'environnement (`GEMINI_API_KEY` via `python-dotenv`). Si la clé est absente ou vide, les fonctions d'analyse journalisent un message explicite en console et retournent proprement sans exception, tandis que Streamlit affiche un `st.warning` informatif tout en préservant la consultation des données et du dernier rapport sauvegardé (`data/dernier_rapport.json`). |
| **Divulgation accidentelle de secrets ou injection HTML** | Aucun secret n'est écrit dans le code source ; `.env`, `*.db` et `data/dernier_rapport.json` sont exclus via `.gitignore` (seul `.env.example` est versionné). En outre, toutes les chaînes issues du LLM injectées dans les composants CSS exécutifs de `app.py` sont systématiquement neutralisées via `html.escape()`. |
