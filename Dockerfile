# download and extract ffmpeg
FROM alpine:3.17 as download-ffmpeg
WORKDIR /ffmpeg
ARG FFMPEG_VERSION=4.4.1

RUN apk add wget unzip \
    && wget "https://github.com/vot/ffbinaries-prebuilt/releases/download/v${FFMPEG_VERSION}/ffmpeg-${FFMPEG_VERSION}-linux-64.zip" -q -O /tmp/ffmpeg-linux-64.zip \
    && unzip /tmp/ffmpeg-linux-64.zip -d /ffmpeg \
    && rm /tmp/ffmpeg-linux-64.zip \
    && rm -rf /var/cache/apk/*


# copy source code
FROM alpine:3.17 as code-layer
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
FROM python:3.11-slim-buster
ARG DEV_DEPS
WORKDIR /podcast

RUN groupadd -r podcast && useradd -r -g podcast podcast

COPY --from=download-ffmpeg /ffmpeg/ffmpeg /usr/bin/ffmpeg
RUN chown podcast:podcast /usr/bin/ffmpeg && chmod u+x /usr/bin/ffmpeg

COPY Pipfile /podcast
COPY Pipfile.lock /podcast

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
		gcc \
		libpq-dev \
		python-dev \
		nano \
	&& pip install pipenv==2022.12.19 \
	&& if [ ${DEV_DEPS} = "true" ]; then \
	     echo "=== Install DEV dependencies ===" && \
	     pipenv install --dev --system; \
       else \
         echo "=== Install PROD dependencies ===" && \
	     pipenv install --system; \
       fi \
	&& apt-get purge -y --auto-remove gcc python-dev git \
	&& apt-get -y autoremove \
	&& apt-get clean \
	&& rm -rf /var/lib/apt/lists/*

COPY --from=code-layer /podcast /podcast
RUN chown -R podcast:podcast /podcast

ENTRYPOINT ["/bin/sh", "/podcast/entrypoint.sh"]
