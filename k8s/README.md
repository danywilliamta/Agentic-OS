# Kubernetes CronJobs for Agent Harness

Ce dossier contient les configurations Kubernetes pour exécuter des tâches d'agents schedulées.

## Architecture

```
┌─────────────────────────┐
│  Kubernetes Cluster     │
│                         │
│  ┌──────────────────┐   │
│  │   CronJob        │   │  ← Déclenche au schedule
│  └────────┬─────────┘   │
│           ↓             │
│  ┌──────────────────┐   │
│  │   Job            │   │  ← Créé par le CronJob
│  └────────┬─────────┘   │
│           ↓             │
│  ┌──────────────────┐   │
│  │   Pod            │   │  ← Exécute la tâche
│  │ (agent-harness)  │   │
│  │ run_scheduled_   │   │
│  │    task.py       │   │
│  └──────────────────┘   │
└─────────────────────────┘
```

## Prérequis

1. **Kubernetes cluster** (local ou cloud)
2. **Docker image** de agent-harness pushée dans un registry
3. **Secrets** configurés (API keys, DB credentials)

## Installation

### 1. Créer le namespace

```bash
kubectl create namespace agent-harness
```

### 2. Créer les secrets

```bash
# Option A : Depuis la ligne de commande
kubectl create secret generic agent-secrets \
  --from-literal=anthropic-api-key='sk-ant-api03-xxxxx' \
  --from-literal=database-url='postgresql://user:pass@host:5432/db' \
  --namespace=agent-harness

# Option B : Depuis un fichier
cp secrets.example.yaml secrets.yaml
# Éditer secrets.yaml avec les vraies valeurs
kubectl apply -f secrets.yaml
```

### 3. Build et push l'image Docker

```bash
# Build l'image
docker build -t your-registry/agent-harness:latest .

# Push vers le registry
docker push your-registry/agent-harness:latest
```

### 4. Mettre à jour les CronJobs

Éditer les fichiers dans `cronjobs/` et remplacer `your-registry/agent-harness:latest` par ton image.

### 5. Déployer les CronJobs

```bash
# Déployer tous les CronJobs
kubectl apply -f cronjobs/

# Ou déployer individuellement
kubectl apply -f cronjobs/daily-stock-check.yaml
kubectl apply -f cronjobs/hourly-devis-processing.yaml
kubectl apply -f cronjobs/weekly-report.yaml
```

## Vérification

### Lister les CronJobs

```bash
kubectl get cronjobs -n agent-harness
```

Sortie attendue :
```
NAME                        SCHEDULE      SUSPEND   ACTIVE   LAST SCHEDULE   AGE
daily-stock-check           0 9 * * *     False     0        8h              2d
hourly-devis-processing     0 * * * *     False     0        45m             2d
weekly-report               0 10 * * 1    False     0        3d              2d
```

### Voir les Jobs créés

```bash
kubectl get jobs -n agent-harness
```

### Voir les Pods en cours d'exécution

```bash
kubectl get pods -n agent-harness
```

### Voir les logs d'un Job

```bash
# Lister les pods du job
kubectl get pods -n agent-harness -l task=daily-stock-check

# Voir les logs
kubectl logs <pod-name> -n agent-harness
```

## Tester immédiatement

Pour tester un CronJob sans attendre le schedule :

```bash
# Créer un Job manuellement depuis le CronJob
kubectl create job --from=cronjob/daily-stock-check manual-test-1 -n agent-harness

# Voir les logs
kubectl logs -f job/manual-test-1 -n agent-harness
```

## Schedules Cron

Format : `minute hour day month day_of_week`

| Expression | Description |
|------------|-------------|
| `* * * * *` | Chaque minute |
| `0 * * * *` | Chaque heure |
| `0 9 * * *` | Chaque jour à 9h00 |
| `0 */6 * * *` | Toutes les 6 heures |
| `0 9 * * 1` | Chaque lundi à 9h00 |
| `0 9 1 * *` | Le 1er de chaque mois à 9h00 |
| `0 9 * * 1-5` | Lun-Ven à 9h00 |

Utilise [crontab.guru](https://crontab.guru/) pour tester tes expressions.

## Debugging

### CronJob ne se déclenche pas

```bash
# Vérifier le statut du CronJob
kubectl describe cronjob daily-stock-check -n agent-harness

# Vérifier les events
kubectl get events -n agent-harness --sort-by='.lastTimestamp'
```

### Job échoue

```bash
# Voir les logs du Pod
kubectl logs -l task=daily-stock-check -n agent-harness

# Décrire le Job pour voir les erreurs
kubectl describe job <job-name> -n agent-harness
```

### Suspendre un CronJob

```bash
kubectl patch cronjob daily-stock-check -n agent-harness -p '{"spec":{"suspend":true}}'
```

### Réactiver un CronJob

```bash
kubectl patch cronjob daily-stock-check -n agent-harness -p '{"spec":{"suspend":false}}'
```

## Modification d'un CronJob

```bash
# Éditer le YAML
vim cronjobs/daily-stock-check.yaml

# Appliquer les changements
kubectl apply -f cronjobs/daily-stock-check.yaml
```

## Suppression

```bash
# Supprimer un CronJob spécifique
kubectl delete cronjob daily-stock-check -n agent-harness

# Supprimer tous les CronJobs
kubectl delete cronjobs --all -n agent-harness

# Supprimer le namespace (attention : supprime tout !)
kubectl delete namespace agent-harness
```

## Monitoring en production

### Ajouter des alertes

Utilise Prometheus + Alertmanager pour être notifié des échecs :

```yaml
# prometheus-rules.yaml
- alert: CronJobFailed
  expr: kube_job_status_failed{namespace="agent-harness"} > 0
  for: 5m
  annotations:
    summary: "CronJob {{ $labels.job_name }} failed"
```

### Dashboard Grafana

Importe le dashboard Kubernetes CronJobs pour visualiser :
- Succès/Échecs
- Durée d'exécution
- Dernière exécution

## Best Practices

1. **Timeouts** : Toujours définir `activeDeadlineSeconds`
2. **Resources** : Définir `requests` et `limits`
3. **Retry** : Configurer `backoffLimit` (2-3 max)
4. **History** : Garder quelques jobs pour le debugging
5. **Monitoring** : Logger vers stdout/stderr
6. **Secrets** : Jamais en clair dans les YAML
7. **Idempotence** : Les tâches doivent être rejouables sans problème

## Exemples de tâches

```bash
# Alerte stock bas
python run_scheduled_task.py inventory-agent system \
  "Vérifie le stock et alerte si < 10 unités"

# Traiter les devis
python run_scheduled_task.py inventory-agent system \
  "Traite tous les devis bruts en attente"

# Rapport hebdomadaire
python run_scheduled_task.py inventory-agent system \
  "Génère un rapport hebdomadaire complet"
```
