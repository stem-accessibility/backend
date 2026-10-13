# Usage: make migrate | make migration m="add foo column" | make migration-status
export FLASK_APP := backend.app_factory:create_app
FLASK := .venv/bin/flask

migrate:            ## apply pending migrations to DATABASE_URL
	$(FLASK) db upgrade

migration:          ## autogenerate a migration from model changes (review it!)
	$(FLASK) db migrate -m "$(m)"

migration-status:   ## current revision and drift check
	$(FLASK) db current
	$(FLASK) db check

purge-job-images:   ## remove uploaded images stored in the jobs table (make purge-job-images DRY=1 to preview)
	$(FLASK) purge-job-images $(if $(DRY),--dry-run,)
