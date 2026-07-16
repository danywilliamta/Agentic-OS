# Inventory Agent Example

Exemple complet d'un agent de gestion d'inventaire avec :
- Gestion de stock
- Traitement de devis (PDF/TXT)
- Création de commandes
- Base de données SQLite

## Structure

```
inventory_agent/
├── configs/
│   └── agents/
│       └── inventory_agent.yml    # Configuration de l'agent
├── test_data/
│   ├── init_db.py                 # Initialisation DB
│   ├── test_agent.py              # Tests de l'agent
│   ├── test_scheduler.py          # Test du scheduler
│   ├── devis_2024_001.txt         # Exemples de devis
│   └── test_inventory.db          # Base de données
└── README.md
```

## Installation

```bash
# Depuis la racine du repo
pip install -e .

# Ou avec Poetry
poetry install
```

## Configuration

L'agent nécessite :
- Une base de données SQLite (créée par `init_db.py`)
- Une clé API Anthropic (dans `.env`)

Fichier `.env` :
```
ANTHROPIC_API_KEY=sk-ant-api03-xxxxx
```

## Initialisation de la base de données

```bash
cd examples/inventory_agent/test_data
python init_db.py
```

Cela crée `test_inventory.db` avec :
- Table `users` : Clients
- Table `stock` : Produits en stock
- Table `devis_raw` : Devis bruts (fichiers PDF/TXT)
- Table `devis` : Devis structurés
- Table `devis_items` : Lignes de devis
- Table `commande` : Commandes
- Table `commande_items` : Lignes de commande

## Utilisation

### Test simple

```bash
cd examples/inventory_agent/test_data
python test_agent.py
```

### Mode interactif

```bash
python test_agent.py interactive
```

Exemples de prompts :
- "Montre-moi tous les produits en stock"
- "Combien de Laptop Dell XPS 15 sont disponibles?"
- "Traite le devis brut #1"
- "Crée une commande pour le devis #1"

### Test du scheduler

```bash
python test_scheduler.py
```

## Depuis ton propre code

```python
from agent_harness import agent_factory

# Charger l'agent
agent = agent_factory.create_from_file(
    "examples/inventory_agent/configs/agents/inventory_agent.yml"
)

# Utiliser l'agent
result = await agent.invoke(
    user_id="user123",
    message="Quel est le stock de Laptop Dell XPS 15?"
)

print(result['response'])
```

## Capacités de l'agent

L'agent inventory peut :
- ✅ Consulter le stock (lecture DB)
- ✅ Lire des devis PDF/TXT
- ✅ Extraire des informations de devis
- ✅ Créer des enregistrements structurés
- ✅ Vérifier la disponibilité de stock
- ✅ Créer des commandes
- ✅ Mettre à jour le stock

## Tools utilisés

- `query_database` : Lecture DB (SQLite)
- `write_database` : Écriture DB (INSERT/UPDATE)
- `read_pdf_devis` : Lecture de fichiers PDF/TXT

## Architecture

```
User → Inventory Agent → Tools → SQLite DB
                      ↓
                   Devis Files
```

## Next steps

- Ajouter plus de validations métier
- Intégrer avec un vrai système de facturation
- Ajouter des notifications (email/Slack)
- Déployer en production avec K8s CronJobs
