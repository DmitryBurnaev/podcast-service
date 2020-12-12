deploy:
	git pull
	docker build -t podcast_service .
	supervisorctl stop podcast_service:
	docker-compose down
	supervisorctl start podcast_service:
	echo y | docker image prune -a

run_web:
	cd src && pipenv run uvicorn asgi:app --host dev.podcast --port 8081 --reload --reload-dir .

run_rq:
	cd src && pipenv run python -m worker youtube_downloads

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

clean-pyc:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -fr {} +
	find . -name '.pytest_cache' -exec rm -fr {} +
	find . -name '.coverage' -exec rm -fr {} +

lint:
	pipenv run black . --exclude migrations --line-length 100
	pipenv run flake8
	make clean-pyc
