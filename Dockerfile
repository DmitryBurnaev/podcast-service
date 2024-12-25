# download and extract ffmpeg
FROM alpine:3.20 AS download-ffmpeg
WORKDIR /ffmpeg
ARG FFMPEG_VERSION=6.1

RUN apk add wget unzip \
    && wget "https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v${FFMPEG_VERSION}/ffmpeg-${FFMPEG_VERSION}-linux-64.zip" -q -O /tmp/ffmpeg-linux-64.zip \
    && unzip /tmp/ffmpeg-linux-64.zip -d /ffmpeg \
    && chmod u+x /ffmpeg/ffmpeg \
    && rm /tmp/ffmpeg-linux-64.zip \
    && rm -rf /var/cache/apk/*

# copy source code
FROM alpine:3.20 AS code-layer
WORKDIR /podcast

COPY src ./src
COPY alembic ./alembic
COPY etc/deploy.sh ./deploy.sh
COPY etc/migrate_db.sh ./migrate_db.sh
COPY etc/entrypoint.sh .
COPY pytest.ini .
COPY alembic.ini .
COPY .coveragerc .
COPY .pylintrc .

# build running version
FROM python:3.13-slim-bookworm AS runtime
ARG DEV_DEPS
WORKDIR /podcast

RUN groupadd -r podcast && useradd -r -g podcast podcast

COPY --from=download-ffmpeg --chown=podcast:podcast /ffmpeg/ffmpeg /usr/bin/ffmpeg

COPY Pipfile /podcast
COPY Pipfile.lock /podcast

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
		libpq-dev \
    build-essential \
		python3-dev \
    python3-psycopg2 \
        grep  \
        procps \
	&& pip install pipenv==2024.4.0 \
	&& if [ "${DEV_DEPS}" = "true" ]; then \
	     echo "=== Install DEV dependencies ===" && \
	     pipenv install --dev --system; \
       else \
         echo "=== Install PROD dependencies ===" && \
	     pipenv install --system; \
       fi \
    && pip uninstall -y pipenv \
    && pip cache remove "*" \
	&& apt-get purge -y --auto-remove libpq-dev python3-dev build-essential \
	&& apt-get -y autoremove \
	&& apt-get clean \
	&& rm -rf /var/lib/apt/lists/*

COPY --from=code-layer --chown=podcast:podcast /podcast /podcast

ENTRYPOINT ["/bin/sh", "/podcast/entrypoint.sh"]
