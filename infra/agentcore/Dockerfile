FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY agent agent
COPY apps/api apps/api
COPY packages packages
COPY services services

RUN pip install --no-cache-dir uv \
    && uv sync --frozen --all-packages --no-dev

ENV PYTHONUNBUFFERED=1

CMD ["uv", "run", "--directory", "apps/api", "python", "-m", "assistflow_api.runtime_entry"]
