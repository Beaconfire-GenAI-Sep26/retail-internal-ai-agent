COMPOSE ?= docker compose

.DEFAULT_GOAL := help
# Lifecycle operations must stay sequential, including when make is given -j.
.NOTPARALLEL:
.PHONY: help up start down stop reset status logs

help:
	@echo make up      - Build and start the entire stack without resetting data
	@echo make down    - Stop and remove containers while keeping database data
	@echo make reset   - Reseed demo data, clear Agent history, and start the stack
	@echo make status  - Show service status
	@echo make logs    - Follow stack logs
	@echo start and stop are aliases for up and down

up start:
	$(COMPOSE) config --quiet
	$(COMPOSE) build demo-reset
	$(COMPOSE) stop gateway agent domain
	$(COMPOSE) up -d --wait postgres
	$(COMPOSE) exec -T postgres sh /setup/provision.sh
# Upgrade existing volumes without reseeding or clearing Agent/Auth state.
	$(COMPOSE) run --rm --no-deps demo-reset python -m alembic -c domain/alembic.ini upgrade head
	$(COMPOSE) exec -T postgres sh /setup/provision.sh
	$(COMPOSE) up --build -d --wait

down stop:
	$(COMPOSE) down

reset:
	$(COMPOSE) config --quiet
# Prepare the maintenance image before taking running services offline.
	$(COMPOSE) build demo-reset
	$(COMPOSE) stop gateway agent domain
	$(COMPOSE) up -d --wait postgres
	$(COMPOSE) exec -T postgres sh /setup/provision.sh
	$(COMPOSE) run --rm --no-deps demo-reset
# Seeding recreates schemas and tables; restore ownership and runtime grants.
	$(COMPOSE) exec -T postgres sh /setup/provision.sh
	$(COMPOSE) up --build -d --wait

status:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs --follow --tail=100
