FROM python:3.10-slim-buster
WORKDIR /podcast
ARG DEV_DEPS

COPY Pipfile /podcast
COPY Pipfile.lock /podcast

RUN groupadd -r podcast && useradd -r -g podcast podcast
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
		gcc \
		libpq-dev \
		python-dev \
		wget \
		unzip \
		nano \
	&& wget https://github.com/DmitryBurnaev/webargs-starlette/archive/refs/tags/v2.1.0.zip -q -O /tmp/webargs-starlette-2.1.0.zip \
	&& wget https://github.com/vot/ffbinaries-prebuilt/releases/download/v4.2/ffmpeg-4.2-linux-64.zip -q -O /tmp/ffmpeg-4.2-linux-64.zip \
	&& unzip /tmp/ffmpeg-4.2-linux-64.zip -d /usr/bin \
	&& rm /tmp/ffmpeg-4.2-linux-64.zip \
	&& pip install pipenv==2022.9.2 \
	&& if [ ${DEV_DEPS} = "true" ]; then \
	     echo "=== Install DEV dependencies ===" && \
	     pipenv install --dev --system; \
       else \
         echo "=== Install PROD dependencies ===" && \
	     pipenv install --system; \
       fi \
	&& apt-get purge -y --auto-remove gcc python-dev \
	&& apt-get -y autoremove \
	&& apt-get clean \
	&& rm -rf /var/lib/apt/lists/*

COPY src ./src
COPY alembic ./alembic
COPY etc/deploy.sh ./deploy.sh
COPY etc/migrate_db.sh ./migrate_db.sh
COPY etc/entrypoint.sh .
COPY pytest.ini .
COPY alembic.ini .
COPY .coveragerc .
COPY .flake8 .

RUN chown -R podcast:podcast /podcast

ENTRYPOINT ["/bin/sh", "/podcast/entrypoint.sh"]
