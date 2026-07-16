.PHONY: help install start stop logs test clean

help:
	@echo "Agent Harness Platform - Commands:"
	@echo ""
	@echo "  make install    - Install dependencies"
	@echo "  make start      - Start platform (Docker)"
	@echo "  make stop       - Stop platform"
	@echo "  make logs       - View logs"
	@echo "  make restart    - Restart platform"
	@echo "  make test       - Test API endpoints"
	@echo "  make clean      - Clean containers and data"
	@echo ""

install:
	pip install -r requirements.txt

start:
	@./start.sh

stop:
	docker-compose down

restart: stop start

logs:
	docker-compose logs -f platform

test:
	@echo "Testing API..."
	@curl -s http://localhost:8000/health | python -m json.tool
	@echo ""
	@echo "Agents:"
	@curl -s http://localhost:8000/admin/agents | python -m json.tool
	@echo ""
	@echo "Tools:"
	@curl -s http://localhost:8000/admin/tools/categories | python -m json.tool

clean:
	docker-compose down -v
	rm -rf __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
