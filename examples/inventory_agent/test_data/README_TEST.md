# 🧪 Test Suite - Inventory Agent

Test complet de la plateforme Agent Harness avec un cas d'usage réel: gestion d'inventaire.

## 📦 Contenu

```
test_data/
├── test_inventory.db          # Base SQLite avec données de test
├── init_db.py                 # Script création/réinitialisation DB
├── test_agent.py              # Script de test automatique
├── generate_devis_pdf.py      # Génération de devis exemples
├── devis_2024_001.txt         # Devis exemple 1
├── devis_2024_002.txt         # Devis exemple 2
└── README_TEST.md             # Ce fichier
```

## 🚀 Quick Start

### 1. Initialiser la base de données

```bash
cd test_data
python3 init_db.py
```

**Résultat:**
- ✅ Base SQLite créée avec 3 utilisateurs, 8 produits en stock, 3 devis
- Tables: `users`, `stock`, `devis`, `commande`

### 2. Lancer les tests automatiques

```bash
python3 test_agent.py
```

**Ce qui est testé:**
- Consultation du stock complet
- Recherche d'un produit spécifique
- Liste des devis en attente
- Vérification de stock pour un devis

### 3. Mode interactif

```bash
python3 test_agent.py interactive
```

**Exemples de commandes:**
```
👤 Montre-moi tous les produits en stock
👤 Combien de Laptop Dell XPS 15 sont disponibles?
👤 Liste tous les devis en attente
👤 Est-ce qu'il y a assez de stock pour le devis #1?
👤 Transforme le devis #2 en commande
```

## 📊 Structure de la Base de Données

### Table: users
| id | name | email | company |
|----|------|-------|---------|
| 1 | Jean Dupont | jean.dupont@example.com | TechCorp |
| 2 | Marie Martin | marie.martin@example.com | InnoSoft |
| 3 | Pierre Dubois | pierre.dubois@example.com | DataFlow |

### Table: stock
| id | product_name | qty | unit_price |
|----|-------------|-----|------------|
| 1 | Laptop Dell XPS 15 | 50 | 1500.00 |
| 2 | Souris Logitech MX Master | 200 | 99.99 |
| 3 | Clavier Mécanique | 150 | 149.99 |
| ... | ... | ... | ... |

### Table: devis
| id | user_id | product_name | qty | price | status |
|----|---------|--------------|-----|-------|--------|
| 1 | 1 | Laptop Dell XPS 15 | 5 | 1500.00 | pending |
| 2 | 2 | Souris Logitech MX Master | 20 | 99.99 | pending |
| 3 | 1 | Écran 27 pouces 4K | 10 | 450.00 | completed |

### Table: commande
Vide au départ - sera remplie quand l'agent transforme des devis en commandes.

## 🎯 Scénarios de Test

### Scénario 1: Consultation de Stock
```
User: Quel est le stock disponible?
Agent: [Liste tous les produits avec quantités]
```

### Scénario 2: Vérification d'un Devis
```
User: Montre-moi le devis #1
Agent: [Affiche les détails: produit, quantité, prix]

User: Est-ce qu'il y a assez de stock?
Agent: [Vérifie stock vs devis, répond oui/non]
```

### Scénario 3: Transformation Devis → Commande
```
User: Transforme le devis #1 en commande
Agent:
1. Vérifie devis status = 'pending'
2. Vérifie stock suffisant
3. INSERT INTO commande (...)
4. UPDATE stock SET qty = qty - X
5. UPDATE devis SET status = 'completed'
6. Confirme création commande
```

### Scénario 4: Lecture de Devis PDF (bonus)
```
User: Lis le devis dans devis_2024_001.txt
Agent: [Extrait contenu, identifie produits/quantités/prix]

User: Enregistre ce devis dans la base
Agent: [Parse le texte, INSERT INTO devis]
```

## 🛠️ Outils de l'Agent

L'agent dispose de 3 outils:

### 1. `query_database`
- **Type:** Lecture (SELECT)
- **Permission:** Allow (pas de confirmation)
- **Usage:** Consulter stock, devis, commandes

### 2. `write_database`
- **Type:** Écriture (INSERT/UPDATE)
- **Permission:** Interrupt (confirmation requise)
- **Usage:** Créer commandes, mettre à jour stock

### 3. `read_pdf_devis`
- **Type:** Lecture fichier
- **Permission:** Allow
- **Usage:** Extraire contenu de devis PDF/texte

## 🔍 Commandes SQL Utiles

### Vérifier le stock
```sql
SELECT product_name, qty, unit_price FROM stock ORDER BY product_name;
```

### Lister les devis en attente
```sql
SELECT d.id, u.name, d.product_name, d.qty, d.price
FROM devis d
JOIN users u ON d.user_id = u.id
WHERE d.status = 'pending';
```

### Vérifier stock pour un devis
```sql
SELECT
  d.product_name,
  d.qty as devis_qty,
  s.qty as stock_qty,
  CASE WHEN s.qty >= d.qty THEN 'OK' ELSE 'INSUFFISANT' END as status
FROM devis d
JOIN stock s ON d.product_name = s.product_name
WHERE d.id = 1;
```

### Créer une commande (3 étapes)
```sql
-- 1. Créer commande
INSERT INTO commande (devis_id, user_id, product_name, qty, total_price)
SELECT id, user_id, product_name, qty, qty * price
FROM devis WHERE id = 1;

-- 2. Mettre à jour stock
UPDATE stock
SET qty = qty - (SELECT qty FROM devis WHERE id = 1)
WHERE product_name = (SELECT product_name FROM devis WHERE id = 1);

-- 3. Marquer devis comme complété
UPDATE devis SET status = 'completed' WHERE id = 1;
```

## 📝 Réinitialiser les Tests

```bash
# Supprimer et recréer la DB
rm test_inventory.db
python3 init_db.py

# Regénérer les devis
python3 generate_devis_pdf.py
```

## ✅ Ce qui est Testé

| Fonctionnalité | Status | Description |
|---------------|--------|-------------|
| ✅ Agent Factory | OK | Chargement depuis YAML |
| ✅ Tool Registry | OK | 3 outils enregistrés |
| ✅ DB Queries | OK | Lecture SQLite |
| ✅ DB Writes | OK | Écriture avec confirmation |
| ✅ Memory | OK | Historique via checkpointer |
| ✅ Multi-turn | OK | Conversations contextuelles |
| ✅ File Reading | OK | Extraction devis texte |
| ⏳ PDF Reading | Partiel | Nécessite PyPDF2/pdfplumber |

## 🎓 Points d'Apprentissage

### 1. Configuration Générique
L'agent est entièrement configuré via YAML - aucun code spécifique!

### 2. Tools Réutilisables
- `generic_db_query` = N'importe quelle DB
- `generic_db_write` = N'importe quelle table
- `read_pdf` = N'importe quel PDF

### 3. Permissions Granulaires
- Lecture: auto-approuvée (rapide)
- Écriture: confirmation requise (sécurité)

### 4. Workflow Complexe
L'agent peut orchestrer des transactions multi-étapes:
```
Devis → Vérifier Stock → Créer Commande → MAJ Stock → MAJ Devis
```

## 🚀 Prochaines Étapes

1. **Ajouter des tests unitaires** pour chaque outil
2. **Créer de vrais PDFs** avec reportlab
3. **Ajouter un webhook** pour recevoir des devis
4. **Scheduler un cron** pour rappels devis expirés
5. **Multi-tenant**: Plusieurs entreprises dans la même DB

## 💡 Tips

- Les IDs de devis commencent à 1
- Le stock est limité (tester cas insuffisant)
- Tous les prix sont en euros
- Le statut devis: 'pending' ou 'completed'
- Le statut commande: 'created', 'shipped', 'delivered'

---

**Bon test! 🧪**
