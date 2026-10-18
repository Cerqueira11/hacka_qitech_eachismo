"""Valida e envia cenarios de demonstracao pela API local de antifraude."""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from jsonschema import validate


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = ROOT / "tests" / "scenarios" / "antifraud"
TRANSACTION_SCHEMA = ROOT / "src" / "schemas" / "post_pix_transaction.json"
DEVICE_SCHEMA = ROOT / "src" / "schemas" / "post_device.json"
DEVICE_REGISTRATION = {
    "document_number": "52998224725",
    "device_id": "demo-device-stable-001",
}
LOGGER = logging.getLogger("seed_antifraud")


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def validate_scenarios(payloads: list[tuple[Path, dict]]) -> None:
    LOGGER.info("Validando cadastro de dispositivo e %s payloads de transacao", len(payloads))
    transaction_schema = read_json(TRANSACTION_SCHEMA)
    device_schema = read_json(DEVICE_SCHEMA)
    validate(instance=DEVICE_REGISTRATION, schema=device_schema)
    LOGGER.info("Cadastro de dispositivo valido contra %s", DEVICE_SCHEMA.name)

    sys.path.insert(0, str(ROOT / "src"))
    from dtos.pix_transaction_input import PixTransactionInput

    for path, payload in payloads:
        LOGGER.info("Validando %s (id=%s)", path.name, payload.get("id"))
        validate(instance=payload, schema=transaction_schema)
        PixTransactionInput.from_payload(payload)
        LOGGER.info("Payload valido: %s", path.name)


def post_json(session, url: str, payload: dict, timeout: float):
    import requests

    LOGGER.info("Enviando POST %s", url)
    response = session.post(url, json=payload, timeout=timeout)
    if not response.ok:
        LOGGER.error("POST %s respondeu HTTP %s", url, response.status_code)
        raise RuntimeError(f"POST {url} retornou {response.status_code}: {response.text}")
    LOGGER.info("POST %s concluido: HTTP %s", url, response.status_code)
    return response


def seed(base_url: str, token: str, timeout: float, payloads: list[tuple[Path, dict]]) -> None:
    import requests

    base_url = base_url.rstrip("/")
    headers = {"INTERNAL-TOKEN": token}

    LOGGER.info("Checando disponibilidade da API em %s/health_check", base_url)
    health = requests.get(f"{base_url}/health_check", timeout=timeout)
    health.raise_for_status()
    LOGGER.info("API disponivel: HTTP %s", health.status_code)

    with requests.Session() as session:
        session.headers.update(headers)
        LOGGER.info("Registrando dispositivo conhecido para a conta de origem")
        registration = post_json(
            session,
            f"{base_url}/device",
            DEVICE_REGISTRATION,
            timeout,
        )
        LOGGER.info("Dispositivo registrado: HTTP %s", registration.status_code)

        for index, (path, payload) in enumerate(payloads, start=1):
            transaction_id = payload["id"]
            LOGGER.info("Cenario %s/%s: iniciando %s (id=%s)", index, len(payloads), path.name, transaction_id)
            response = post_json(session, f"{base_url}/pix/transaction", payload, timeout)
            result = response.json()

            LOGGER.info("Consultando transacao criada: GET /pix/transaction/%s", transaction_id)
            fetched = session.get(
                f"{base_url}/pix/transaction/{transaction_id}",
                timeout=timeout,
            )
            fetched.raise_for_status()
            if fetched.json() != result:
                raise RuntimeError(f"GET divergiu do POST para {transaction_id}")
            LOGGER.info("GET confirmado para %s: HTTP %s", transaction_id, fetched.status_code)

            LOGGER.info(
                "Cenario concluido: %s status=%s risk=%s",
                path.name,
                result["status"],
                result["metadata"]["risk_score"],
            )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("API_BASE_URL", "http://127.0.0.1:3000"),
        help="URL da API (padrao: API_BASE_URL ou http://127.0.0.1:3000)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("INTERNAL_TOKEN", "default_token"),
        help="Token interno (padrao: INTERNAL_TOKEN ou default_token)",
    )
    parser.add_argument("--timeout", type=float, default=10, help="Timeout HTTP em segundos")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Valida os JSONs localmente sem chamar a API",
    )
    args = parser.parse_args()

    LOGGER.info("Carregando arquivos de cenario de %s", SCENARIOS_DIR)
    payloads = [(path, read_json(path)) for path in sorted(SCENARIOS_DIR.glob("*.json"))]
    if not payloads:
        raise RuntimeError(f"Nenhum JSON encontrado em {SCENARIOS_DIR}")
    LOGGER.info("%s cenarios carregados", len(payloads))

    validate_scenarios(payloads)
    if args.validate_only:
        LOGGER.info("Validacao local concluida: %s transacoes", len(payloads))
        return 0

    LOGGER.info("Iniciando seed em %s", args.base_url)
    seed(args.base_url, args.token, args.timeout, payloads)
    LOGGER.info("Seed concluido: %s transacoes enviadas e consultadas", len(payloads))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())