# Supervisor Multi-Agent Example

Exemple d'orchestration multi-agent avec un superviseur qui délègue les tâches à des agents spécialisés.

## Architecture

```
User
  ↓
Supervisor Agent (Orchestrateur)
  ↓
  ├─→ Inventory Agent (Stock, devis, commandes)
  ├─→ CRM Agent (Clients, contacts) [À ajouter]
  └─→ Billing Agent (Facturation) [À ajouter]
```

## Structure

```
supervisor_multi_agent/
├── configs/
│   └── agents/
│       └── supervisor_agent.yml    # Configuration du superviseur
└── README.md
```

## Installation

```bash
# Depuis la racine du repo
pip install -e .
```

## Prérequis

Le superviseur a besoin d'au moins un agent spécialisé pour déléguer.
Cet exemple utilise l'inventory_agent, donc :

1. Initialiser la DB de l'inventory agent :
```bash
cd examples/inventory_agent/test_data
python init_db.py
```

2. S'assurer que le fichier `.env` contient :
```
ANTHROPIC_API_KEY=sk-ant-api03-xxxxx
```

## Utilisation

### Test avec script

```bash
cd examples/inventory_agent/test_data
python test_supervisor.py
```

### Mode interactif

```bash
python test_supervisor.py interactive
```

Exemples de prompts :
- "Bonjour, que peux-tu faire pour moi?" (pas de délégation)
- "Combien de Laptop Dell XPS 15 sont disponibles?" (délégation à inventory)
- "Traite le devis brut #1" (délégation à inventory)

## Depuis ton propre code

```python
from agent_harness import agent_factory

# Charger les deux agents
inventory_agent = agent_factory.create_from_file(
    "examples/inventory_agent/configs/agents/inventory_agent.yml"
)

supervisor = agent_factory.create_from_file(
    "examples/supervisor_multi_agent/configs/agents/supervisor_agent.yml"
)

# Utiliser le supervisor
result = await supervisor.invoke(
    user_id="user123",
    message="Quel est le stock de laptops?"
)

print(result['response'])
```

## Comment ça marche

### 1. Le supervisor analyse la requête

```python
User: "Quel est le stock de laptops?"
  ↓
Supervisor: "Cette requête concerne l'inventaire, je dois déléguer"
```

### 2. Le supervisor utilise le tool `delegate_to_agent`

```python
delegate_to_agent(
    target_agent_id="inventory-agent",
    task_description="Vérifier le stock de laptops",
    user_id="user123"
)
```

### 3. L'inventory agent traite la tâche

```python
Inventory Agent:
  - Query DB
  - Résultat: "50 Laptop Dell XPS 15 disponibles"
```

### 4. Le supervisor reçoit et synthétise

```python
Supervisor: "D'après l'agent inventaire, il y a 50 Laptop Dell XPS 15 en stock."
```

## Workflow complet

```
┌─────────────────────────────────────┐
│ User: "Check stock"                 │
└────────────┬────────────────────────┘
             ↓
┌─────────────────────────────────────┐
│ Supervisor Agent                    │
│ 1. Analyse requête                  │
│ 2. Décide de déléguer               │
│ 3. Tool: delegate_to_agent          │
└────────────┬────────────────────────┘
             ↓
┌─────────────────────────────────────┐
│ Inventory Agent                     │
│ 1. Query DB                         │
│ 2. Retourne résultat                │
└────────────┬────────────────────────┘
             ↓
┌─────────────────────────────────────┐
│ Supervisor Agent                    │
│ Synthétise et répond au user        │
└────────────┬────────────────────────┘
             ↓
User reçoit la réponse
```

## Ajouter d'autres agents spécialisés

### 1. Créer la config de ton nouvel agent

```yaml
# configs/agents/crm_agent.yml
agent_id: crm-agent
name: CRM Agent
tools:
  - name: query_customers
    type: generic_db_query
```

### 2. Le charger au démarrage

```python
crm_agent = agent_factory.create_from_file("configs/agents/crm_agent.yml")
```

### 3. Mettre à jour le supervisor

```yaml
# supervisor_agent.yml
system_prompt: |
  Agents disponibles:
  - inventory-agent: Stock, devis, commandes
  - crm-agent: Clients, contacts      # ← Ajouter ici

tools:
  - name: delegate_to_agent
    config:
      allowed_agents:
        - inventory-agent
        - crm-agent                    # ← Et ici
```

## Délégations en chaîne

Le supervisor peut orchestrer plusieurs agents :

```python
# 1. Récupérer info client
result1 = delegate_to_agent("crm-agent", "Get user info for John")

# 2. Créer commande avec ces infos
result2 = delegate_to_agent(
    "inventory-agent",
    f"Create order for user_id={result1['user_id']}"
)
```

## Next steps

- Ajouter CRM Agent
- Ajouter Billing Agent
- Implémenter délégations parallèles
- Ajouter une UI pour visualiser les délégations
