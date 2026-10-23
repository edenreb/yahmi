# Deploying Yahmi on a server (Docker)

Status: built and tested on a Debian server (62 tests passed in the container); not yet exposed to the internet. Web app only.
- Each pilot business has a secret access code (`YAHMI_ACCESS_CODES` in `.env`). The server decides the business from the code; a business name sent by the browser is ignored.
- With no code, visitors get a demo: no history, nothing saved, 10 checks per hour per address (`YAHMI_DEMO=0` turns the demo off).
- Uploads are limited to 8 MB and to real PDF/JPG/PNG files; at most 2 checks run at once per worker, the rest wait up to 45 s.
- The WhatsApp routes are off unless `YAHMI_ENABLE_WHATSAPP=1` (the webhook does not verify Meta's signature, so leave it off).
- Still to do before a public launch: a privacy notice on the page, the HTTPS tunnel, backups. Limits are per worker (two workers: about double).

## 1. Get the code (public repo)
    git clone https://github.com/edenreb/yahmi.git && cd yahmi

## 2. Copy the private files from your own computer (never through the repo)
    mkdir -p private/models private/sanctions
    # from the computer that has them:
    scp models/bec_final.joblib models/bec_multi.joblib USER@SERVER:yahmi/private/models/
    # optional, for the sanctions check (python3 tools/update_sanctions.py makes it):
    scp data/sanctions/entries.json USER@SERVER:yahmi/private/sanctions/

## 3. Secret
    cp .env.example .env && nano .env      # set YAHMI_KEY and one access code per pilot business; chmod 600 .env

Generate each with `openssl rand -hex 32` (key) and `openssl rand -hex 8` (access codes). Keep `.env` private and back it up.

## 4. Build, test, run
    docker compose build
    docker compose run --rm -e YAHMI_DB=/tmp/test.db -e YAHMI_KEY=test-key yahmi python -m pytest -q tests
    docker compose up -d
    curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/        # 200

Always pass the two `-e` overrides when running the tests: otherwise the tests would write fake businesses into the real history database volume.

The first start downloads the embedding model into a volume (about 130 MB; more the first time Arabic is used).
The port is bound to 127.0.0.1 only: reach it from outside through the HTTPS tunnel, never by opening a router port.

## 5. Backups
The history database lives in the `yahmi-data` volume (it holds only keyed fingerprints). Back it up off the machine, and back up `.env`.

## What is stored

- Payment history and the shared network: keyed hashes only (see `yahmi/memory.py`).
- Check log (pilot access codes only, never demo): supplier name, invoice number, date, total and verdict, in plain text in the same database, at most 500 rows per business, shown only to that business's code. A business clears it from the History page. Tell each pilot business before you turn it on, put it in the privacy notice, and keep the server's disk encrypted and its backups private.
