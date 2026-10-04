FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH"

RUN python -m venv /opt/venv
COPY requirements.txt /tmp/requirements.txt
RUN pip install --disable-pip-version-check -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt \
    && groupadd --gid 10001 assistant \
    && useradd --uid 10001 --gid assistant --create-home --home-dir /home/assistant assistant

WORKDIR /app
COPY --chown=assistant:assistant app ./app
COPY --chown=assistant:assistant scripts ./scripts
RUN mkdir -p /data /secrets && chown assistant:assistant /data /secrets

USER assistant
CMD ["python", "-m", "app.bot"]
