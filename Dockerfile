FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git curl && rm -rf /var/lib/apt/lists/*
WORKDIR /work
COPY pyproject.toml ./
RUN pip install --no-cache-dir "pytest>=8,<9" "ruff>=0.5,<1"
COPY . .
ENV PYTHONPATH=/work PYTHONDONTWRITEBYTECODE=1
CMD ["./check"]
