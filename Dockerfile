FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git make \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml ./
RUN python -m pip install --no-cache-dir --requirement requirements.txt

COPY . .

CMD ["make", "test", "PYTHON=python"]
