# Makefile for Kubernetes CronJobs management

NAMESPACE ?= agent-harness
REGISTRY ?= your-registry
IMAGE_NAME ?= agent-harness
TAG ?= latest

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.PHONY: build
build: ## Build Docker image for CronJobs
	docker build -f ../Dockerfile.cronjob -t $(REGISTRY)/$(IMAGE_NAME):$(TAG) ..

.PHONY: push
push: ## Push Docker image to registry
	docker push $(REGISTRY)/$(IMAGE_NAME):$(TAG)

.PHONY: build-push
build-push: build push ## Build and push Docker image

.PHONY: create-namespace
create-namespace: ## Create Kubernetes namespace
	kubectl create namespace $(NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -

.PHONY: create-secrets
create-secrets: ## Create secrets (will prompt for values)
	@echo "Creating secrets in namespace $(NAMESPACE)..."
	@read -p "Anthropic API Key: " api_key; \
	read -p "Database URL: " db_url; \
	kubectl create secret generic agent-secrets \
		--from-literal=anthropic-api-key="$$api_key" \
		--from-literal=database-url="$$db_url" \
		--namespace=$(NAMESPACE) \
		--dry-run=client -o yaml | kubectl apply -f -

.PHONY: deploy
deploy: ## Deploy all CronJobs
	kubectl apply -f cronjobs/ --namespace=$(NAMESPACE)

.PHONY: deploy-stock-check
deploy-stock-check: ## Deploy daily stock check CronJob
	kubectl apply -f cronjobs/daily-stock-check.yaml --namespace=$(NAMESPACE)

.PHONY: deploy-devis
deploy-devis: ## Deploy hourly devis processing CronJob
	kubectl apply -f cronjobs/hourly-devis-processing.yaml --namespace=$(NAMESPACE)

.PHONY: deploy-report
deploy-report: ## Deploy weekly report CronJob
	kubectl apply -f cronjobs/weekly-report.yaml --namespace=$(NAMESPACE)

.PHONY: list
list: ## List all CronJobs
	kubectl get cronjobs -n $(NAMESPACE)

.PHONY: list-jobs
list-jobs: ## List all Jobs
	kubectl get jobs -n $(NAMESPACE)

.PHONY: list-pods
list-pods: ## List all Pods
	kubectl get pods -n $(NAMESPACE)

.PHONY: logs
logs: ## Show logs of last job (usage: make logs JOB=daily-stock-check)
	@if [ -z "$(JOB)" ]; then \
		echo "Usage: make logs JOB=daily-stock-check"; \
		exit 1; \
	fi
	kubectl logs -l task=$(JOB) -n $(NAMESPACE) --tail=100

.PHONY: test
test: ## Create a manual test job (usage: make test JOB=daily-stock-check)
	@if [ -z "$(JOB)" ]; then \
		echo "Usage: make test JOB=daily-stock-check"; \
		exit 1; \
	fi
	kubectl create job --from=cronjob/$(JOB) manual-test-$(shell date +%s) -n $(NAMESPACE)

.PHONY: suspend
suspend: ## Suspend a CronJob (usage: make suspend JOB=daily-stock-check)
	@if [ -z "$(JOB)" ]; then \
		echo "Usage: make suspend JOB=daily-stock-check"; \
		exit 1; \
	fi
	kubectl patch cronjob $(JOB) -n $(NAMESPACE) -p '{"spec":{"suspend":true}}'

.PHONY: resume
resume: ## Resume a CronJob (usage: make resume JOB=daily-stock-check)
	@if [ -z "$(JOB)" ]; then \
		echo "Usage: make resume JOB=daily-stock-check"; \
		exit 1; \
	fi
	kubectl patch cronjob $(JOB) -n $(NAMESPACE) -p '{"spec":{"suspend":false}}'

.PHONY: delete
delete: ## Delete all CronJobs
	kubectl delete cronjobs --all -n $(NAMESPACE)

.PHONY: delete-jobs
delete-jobs: ## Delete all Jobs
	kubectl delete jobs --all -n $(NAMESPACE)

.PHONY: clean
clean: delete-jobs delete ## Clean everything (CronJobs and Jobs)

.PHONY: status
status: ## Show status of all CronJobs
	@echo "=== CronJobs ==="
	@kubectl get cronjobs -n $(NAMESPACE)
	@echo ""
	@echo "=== Recent Jobs ==="
	@kubectl get jobs -n $(NAMESPACE) --sort-by=.metadata.creationTimestamp | tail -10
	@echo ""
	@echo "=== Recent Events ==="
	@kubectl get events -n $(NAMESPACE) --sort-by='.lastTimestamp' | tail -5
