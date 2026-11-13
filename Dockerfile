FROM python:3.12-slim

RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install --no-cache-dir .

USER 10001
EXPOSE 8000
CMD ["python", "-m", "healthcare_platform", "serve"]
