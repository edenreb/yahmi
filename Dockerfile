# Yahmi web app. Private files (models, sanctions lists) and the database are NOT in the image: they are mounted at run time (see docker-compose.yml).
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-ara tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Indra OCR model (about 76 MB) is downloaded once at build time so the running container needs no outside calls
ENV HF_HOME=/cache/hf
RUN mkdir -p /cache/hf && python -c "import indra_ocr; indra_ocr.load()"

COPY yahmi ./yahmi
COPY web ./web
COPY data/uae_banks.json ./data/uae_banks.json
COPY tools ./tools
COPY tests ./tests
COPY eval/pilot_report.py ./eval/pilot_report.py

# run as a normal user, not root
RUN useradd --create-home --uid 10001 yahmi && mkdir -p /var/lib/yahmi /cache/fastembed && chown -R yahmi /app /var/lib/yahmi /cache
USER yahmi

ENV FASTEMBED_CACHE_PATH=/cache/fastembed \
    YAHMI_DB=/var/lib/yahmi/yahmi.db \
    PYTHONUNBUFFERED=1

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/').status == 200 else 1)"
CMD ["uvicorn", "yahmi.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
