FROM python:3.12-alpine AS build

ENV UV_INSTALL_DIR="/uv"

RUN apk update && \
    apk add --no-cache \
        bash \
        curl \
        g++ \
        gcc \
        libffi-dev \
        make \
        musl-dev && \
    curl -LsSf https://astral.sh/uv/install.sh | sh

SHELL ["/bin/bash", "-c"]

ENV PATH="$UV_INSTALL_DIR:$PATH"

WORKDIR /tmp

COPY pyproject.toml /tmp/pyproject.toml
COPY uv.lock /tmp/uv.lock
COPY install_unrar.sh /tmp/install_unrar.sh

RUN uv sync --no-cache --locked && \
    /tmp/install_unrar.sh

FROM python:3.12-alpine

ENV UV_INSTALL_DIR="/uv"
ARG VERSION="7.3.0"

LABEL org.opencontainers.image.authors="EDM115 <unzip@edm115.dev>"
LABEL org.opencontainers.image.base.name="python:3.12-alpine"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.source="https://github.com/EDM115/unzip-bot.git"
LABEL org.opencontainers.image.title="unzip-bot"
LABEL org.opencontainers.image.url="https://github.com/EDM115/unzip-bot"
LABEL org.opencontainers.image.version=${VERSION}

RUN apk update && \
    apk add --no-cache \
        bash \
        cgroup-tools \
        cpulimit \
        curl \
        ffmpeg \
        git \
        tar \
        tzdata \
        util-linux \
        zstd && \
    apk add --no-cache 7zip --repository=https://dl-cdn.alpinelinux.org/alpine/edge/main && \
    curl -LsSf https://astral.sh/uv/install.sh | sh && \
    ln -sf /usr/share/zoneinfo/Europe/Paris /etc/localtime

SHELL ["/bin/bash", "-c"]

ENV PATH="$UV_INSTALL_DIR:/venv/bin:$PATH"
ENV TZ=Europe/Paris

WORKDIR /app

COPY --from=build /tmp/.venv /venv
COPY --from=build /usr/local/bin/unrar /tmp/unrar

RUN git clone -b v7 https://github.com/EDM115/unzip-bot.git /app && \
    install -m 755 /tmp/unrar /usr/local/bin && \
    rm -rf /tmp/unrar && \
    source /venv/bin/activate

COPY .env /app/.env

ENTRYPOINT ["/bin/bash", "/app/start.sh"]
