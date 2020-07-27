deploy:
	git pull
	docker build -t podcast .
	supervisorctl stop podcast:
	docker-compose down
	supervisorctl start podcast:
	echo y | docker image prune -a

run_web:
	cd src && pipenv run python -m app

run_rq:
	cd src && pipenv run python -m rq_worker youtube_downloads

migrations_upgrade:
	. ./.env && echo "Upgrade migrations for: $$DATABASE_NAME" && \
	PIPENV_DONT_LOAD_ENV=1 DATABASE_NAME=$$DATABASE_NAME \
	pipenv run alembic upgrade head

migrations_downgrade:
	. ./.env && echo "Downgrade migration for: $$DATABASE_NAME" && \
	PIPENV_DONT_LOAD_ENV=1 DATABASE_NAME=$$DATABASE_NAME \
	pipenv run alembic downgrade "${revision}"

migrations_history:
	pipenv run alembic history

migrations_create_auto:
	pipenv run alembic revision --autogenerate -m "${message}"

migrations_create_manual:
	pipenv run alembic revision -m "${message}"

lint:
	pipenv run black . --exclude migrations --line-length 100
	pipenv run flake8
