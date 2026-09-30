# syntax=docker/dockerfile:1
#
# Imaginea vedit: site (React, construit) + API FastAPI + toolkit (ffmpeg, OpenCV).
#
#   docker build -t vedit .
#   docker build -t vedit --build-arg INSTALL_WHISPER=1 .                        # + transcriere locală
#   docker build -t vedit --build-arg INSTALL_WHISPER=1 --build-arg INSTALL_DIARIZE=1 .   # + pyannote (torch CPU, imagine mare)
#
# Datele (proiecte, SQLite, cache de modele) stau în volumul /data.

ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------- 1. frontend
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---------------------------------------------------------------- 2. dependențe Python (într-un venv)
FROM python:${PYTHON_VERSION}-slim AS py
ARG INSTALL_WHISPER=0
ARG INSTALL_DIARIZE=0
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /src
# Întâi doar metadatele, ca stratul cu dependențe să rămână în cache când se schimbă doar codul.
# Pentru diarize instalăm întâi torch doar pentru CPU (de câteva ori mai mic decât varianta CUDA implicită).
COPY pyproject.toml README.md ./
RUN set -eux; \
    extras="server,reframe,tts"; \
    if [ "$INSTALL_WHISPER" = "1" ]; then extras="$extras,whisper"; fi; \
    if [ "$INSTALL_DIARIZE" = "1" ]; then \
        pip install --index-url https://download.pytorch.org/whl/cpu torch torchaudio; \
        extras="$extras,diarize"; \
    fi; \
    mkdir -p vedit && touch vedit/__init__.py; \
    pip install ".[${extras}]"; \
    pip uninstall -y vedit
COPY vedit/ ./vedit/
RUN pip install --no-deps . && rm -rf /src

# ---------------------------------------------------------------- 3. runtime
FROM python:${PYTHON_VERSION}-slim AS runtime
# ffmpeg din Debian are libass (subtitrări) și libx264; fonturile DejaVu pentru diacritice în fallback.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 vedit \
 && useradd --uid 1000 --gid vedit --home-dir /home/vedit --create-home --shell /usr/sbin/nologin vedit \
 && mkdir -p /data/projects /data/cache \
 && chown -R vedit:vedit /data

COPY --from=py /opt/venv /opt/venv
COPY skills/ /app/skills/
COPY --from=web /web/dist /app/web/dist

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VEDIT_HOST=0.0.0.0 \
    VEDIT_PORT=8000 \
    VEDIT_HOME=/data/projects \
    VEDIT_WEB_DIST=/app/web/dist \
    VEDIT_SKILLS_DIR=/app/skills \
    XDG_CACHE_HOME=/data/cache \
    HF_HOME=/data/cache/huggingface

WORKDIR /app
USER vedit
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

CMD ["vedit-server"]
