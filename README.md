# Système de Veille Stratégique Orienté Décision

Prototype complet de veille scientifique et technologique appliqué à l'évaluation décisionnelle des **assistants IA de programmation** (*LLM Programming Assistants*), conçu selon une approche **Anti-Boîte Noire** et la méthode **TRACE** (*Tracer, Remonter, Apprécier, Comparer, Expliciter*).

---

## Architecture du Projet

```text
Systeme_veille/
├── .env.example                            # Modèle de configuration (sans secret en clair)
├── .gitignore                              # Exclusion de .env, *.db, .venv/ et rapports locaux
├── NOTE_METHODOLOGIQUE_ET_ARCHITECTURE.md  # Livrable académique : cadrage, architecture, TRACE et 5 tests
├── README.md                               # Guide d'installation, configuration et démonstration
├── requirements.txt                        # Dépendances Python (streamlit, pandas, python-dotenv, google-genai)
├── app.py                                  # Application Streamlit (Collecte/Qualification + Dashboard Exécutif)
├── analysis_engine.py                      # Moteur IA Gemini 3.8 Flash (dédoublonnage, preuves, synthèse)
├── collect_engine.py                       # Collecte multi-sources (API ouverte ArXiv + corpus écosystème)
├── database.py                             # Couche SQLite3 relationnelle, migrations et intégrité FK
└── data/
    ├── .gitkeep                            # Maintien du dossier data/ dans Git
    ├── veille.db                           # Base SQLite locale générée automatiquement (ignorée par Git)
    └── dernier_rapport.json                # Dernier rapport exécutif persisté localement (ignoré par Git)
```

---

## Prérequis

- **Python 3.10+** (testé et validé sous Python 3.12)
- Une connexion Internet (pour l'interrogation temps réel de l'API publique ArXiv et de l'API Gemini)
- Une clé API Google Gemini (`GEMINI_API_KEY`) issue de Google AI Studio *(l'application intègre un mode dégradé robuste : elle ne plante jamais si la clé est absente ou vide)*

---

## Installation Pas à Pas

### 1. Créer et activer l'environnement virtuel

**Sous Windows (PowerShell) :**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Sous macOS / Linux (Bash / Zsh) :**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Installer les dépendances

```powershell
pip install -r requirements.txt
```

### 3. Configurer la clé API Gemini (sans aucun secret dans le code)

Copiez le fichier modèle `.env.example` vers `.env`, puis renseignez votre clé personnelle :

**Sous Windows (PowerShell) :**
```powershell
Copy-Item .env.example .env
```

**Sous macOS / Linux :**
```bash
cp .env.example .env
```

Éditez ensuite `.env` :
```env
GEMINI_API_KEY=votre_cle_api_gemini_ici
```

### 4. Lancer l'application

La base de données SQLite (`data/veille.db`) et ses tables sont initialisées automatiquement au premier démarrage :

```powershell
streamlit run app.py
```

---

## Guide de Démonstration pour l'Évaluateur (Validation des 5 Tests Minimaux)

Ce scénario de démonstration en **5 minutes** permet de vérifier successivement toutes les fonctionnalités et les 5 tests minimaux du cahier des charges :

### Étape 1 — Collecte multi-sources et traçabilité des requêtes (*Page 1 : Collecte & Qualification*)
1. Conservez les mots-clés par défaut `"LLM programming assistants"`, choisissez un mode de veille (`Target`, `Mine`, `Trawl` ou `Scan`) et cliquez sur **« Lancer la collecte »**.
2. **Résultat attendu :** **10 sources** sont insérées en base (`5` prépublications académiques issues d'ArXiv + `3` sources `Fournisseur` + `1` reprise `Blog` + `1` dépêche `Presse`). Un second clic confirme que `0` doublon d'URL n'est réinséré.
3. Dépliez **« Journal des requêtes de veille »** tout en bas de la Page 1 pour vérifier l'horodatage et la journalisation de la requête (*Pilier Tracer*).

### Étape 2 — Dédoublonnage sémantique et Test minimal n°1 (*Republication ≠ Confirmation*)
1. Cliquez sur **« Dédoublonner et Qualifier avec l'IA »**.
2. **Résultat attendu (Test n°1) :** Le moteur Gemini identifie que l'annonce officielle *GitHub Copilot - Measuring Impact*, le billet *DevOps Digest* (`Blog`) et la dépêche *TechPress* (`Presse`) constituent des republications d'un même sujet et leur attribue un unique `groupe_sujet` (passant typiquement de **10 sources à 8 groupes uniques**).

### Étape 3 — Fraîcheur vs Pertinence (Test minimal n°2) et Réduction du bruit (Test minimal n°4)
1. Au-dessus du tableau des sources, basculez le menu **« Axe de tri — Fraîcheur vs Pertinence »** entre *Date de publication — Fraîcheur décroissante* et *Pertinence décroissante (Qualification IA)*.
2. **Résultat attendu (Test n°2) :** L'ordre des documents change, prouvant que la récence d'une annonce ne préjuge pas de sa pertinence analytique.
3. Déplacez le curseur **« Score de pertinence minimal »** (ex. à `0.75`).
4. **Résultat attendu (Test n°4) :** Les sources périphériques sont filtrées dynamiquement pour resserrer le corpus utile.

### Étape 4 — Extraction Anti-Boîte Noire des preuves (*Faits, Interprétations, Lacunes*)
1. Cliquez sur **« Extraire les Preuves (Faits, Interprétations, Lacunes) »**.
2. **Résultat attendu :** Le tableau **« Preuves extraites »** distingue explicitement les résultats empiriques (`fait_etabli`), les promesses éditeurs (`interpretation`) et les angles morts (`lacune`), chacun étant relié par jointure SQL au titre et au **lien URL cliquable** de sa source primaire (*Pilier Remonter*).

### Étape 5 — Synthèse exécutive, Contradictions (Test n°3) et Recommandation proportionnée (Test n°5)
1. Dans le menu latéral, ouvrez **« 2. Tableau de bord Décisionnel »**.
2. Observez le bandeau des **4 cartes KPIs** (*Sources collectées*, *Groupes dédoublonnés*, *Faits établis vs Interprétations*, *Lacunes identifiées*), puis cliquez sur **« Générer le Rapport Décisionnel »**.
3. **Résultat attendu (Tests n°3 & n°5) :**
   - La section **« Contradictions identifiées »** oppose explicitement les affirmations des fournisseurs aux résultats et réserves des études scientifiques avec leurs `[Source #ID]`.
   - Les **4 options d'action** (*Adopter*, *Expérimenter*, *Surveiller*, *Différer*) sont comparées côte à côte.
   - L'encadré **« Recommandation finale »** propose une décision graduée assortie d'un **niveau de confiance** (*Faible / Moyen / Fort*) et d'un bloc **« Conditions de révision »**.
4. Cliquez sur **« 📥 Exporter le rapport complet en Markdown (.md) »** pour télécharger le livrable final prêt à être diffusé.

---

## Documentation Complémentaire

Pour l'analyse complète du cadrage décisionnel, de la méthode **TRACE**, des choix d'architecture et des garde-fous contre les risques liés aux LLM, consultez le document dédié : [`NOTE_METHODOLOGIQUE_ET_ARCHITECTURE.md`](./NOTE_METHODOLOGIQUE_ET_ARCHITECTURE.md).
