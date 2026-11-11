COLLECTOR_IMAGE := otel/opentelemetry-collector-contrib:0.120.0

.PHONY: up down logs test validate

up: ## Start the stack
	docker compose up -d --build
	@echo "Grafana: http://localhost:$${GRAFANA_PORT:-3000}  (admin / $${GRAFANA_ADMIN_PASSWORD:-change-me})"

down: ## Stop and delete all data
	docker compose down -v

logs: ## Follow the gateway logs
	docker compose logs -f otel-gateway

validate: ## Check the compose file and the collector config
	docker compose config -q
	docker run --rm -v "$(CURDIR)/otel:/cfg:ro" $(COLLECTOR_IMAGE) validate --config=/cfg/gateway.yaml

test: ## End-to-end smoke test against a running stack
	./scripts/smoke-test.sh
