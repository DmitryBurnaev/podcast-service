run_web:
	cd src && pipenv run uvicorn asgi:app --host dev.podcast --port 8001 --reload --reload-dir .

run_rq:
	cd src && pipenv run python -m worker youtube_downloads

migrate:
	. ./.env && echo "Upgrade migrations for: $$DB_NAME" && \
	PIPENV_DONT_LOAD_ENV=1 DATABASE_NAME=$$DB_NAME \
	pipenv run alembic upgrade head

downgrade:
	. ./.env && echo "Downgrade migration for: $$DB_NAME" && \
	PIPENV_DONT_LOAD_ENV=1 DATABASE_NAME=$$DB_NAME \
	pipenv run alembic downgrade "${revision}"

migrations:
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
	PYTHONPATH=./src pipenv run pylint src/
	make clean-pyc

test:
	PYTHONPATH=./src pipenv run coverage run -m pytest && \
	PYTHONPATH=./src pipenv run coverage report
