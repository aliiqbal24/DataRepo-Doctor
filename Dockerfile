FROM node:22-alpine AS web
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY demo_catalog ./demo_catalog
RUN pip install --no-cache-dir .
# DataRepo pins Polars 1.12. The LTS CPU wheel exposes the same public module
# without AVX2, which keeps the demo portable to conservative VM CPUs.
RUN pip install --no-cache-dir --force-reinstall polars-lts-cpu==1.12.0
COPY tests ./tests
COPY --from=web /web/dist /app/web/dist
RUN useradd --create-home --uid 10001 doctor && mkdir -p /data && chown doctor:doctor /data
USER doctor
EXPOSE 8000
CMD ["uvicorn", "datarepo_doctor.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS test
USER root
RUN pip install --no-cache-dir ".[dev]"
USER doctor
