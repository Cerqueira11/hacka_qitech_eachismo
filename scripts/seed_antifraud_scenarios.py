"""Valida e envia cenarios de demonstracao pela API local de antifraude."""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from jsonschema import validate


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = ROOT / "tests" / "scenarios" / "antifraud"
HISTORY_DIR = SCENARIOS_DIR / "history"
TRANSACTION_SCHEMA = ROOT / "src" / "schemas" / "post_pix_transaction.json"
DEVICE_SCHEMA = ROOT / "src" / "schemas" / "post_device.json"
DEVICE_REGISTRATION = {
    "document_number": "52998224725",
    "device_id": "demo-device-stable-001",
}
LOGGER = logging.getLogger("seed_antifraud")


def transaction_date(payload: dict) -> datetime:
    return datetime.fromisoformat(payload["transaction_date"])


def order_payloads(payloads: list[tuple[Path, dict]], group: str) -> list[tuple[Path, dict]]:
    ordered = sorted(payloads, key=lambda item: transaction_date(item[1]))
    for previous, current in zip(ordered, ordered[1:]):
        if transaction_date(current[1]) < transaction_date(previous[1]):
            raise RuntimeError(
                f"Ordem cronologica invalida em {group}: {current[0].name} vem depois de "
                f"{previous[0].name}, mas tem data anterior"
            )
    return ordered


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


def send_transactions(session, base_url: str, timeout: float, label: str, payloads: list[tuple[Path, dict]]) -> None:
    previous_date = None
    for index, (path, payload) in enumerate(payloads, start=1):
        transaction_id = payload["id"]
        current_date = transaction_date(payload)
        if previous_date is not None and current_date < previous_date:
            raise RuntimeError(
                f"Envio cronologico interrompido: {path.name} tem data anterior ao registro precedente"
            )
        previous_date = current_date
        LOGGER.info("%s %s/%s: iniciando %s (id=%s)", label, index, len(payloads), path.name, transaction_id)
        response = post_json(session, f"{base_url}/pix/transaction", payload, timeout)
        result = response.json()
        response_body = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        LOGGER.info("========== [POST RESULT BEGIN] ==========")
        LOGGER.info("[POST RESULT] HTTP_STATUS=%s TRANSACTION_ID=%s", response.status_code, transaction_id)
        for line in response_body.splitlines():
            LOGGER.info("[POST BODY] %s", line)
        LOGGER.info("========== [POST RESULT END] ==========")

        LOGGER.info("[GET VERIFY START] TRANSACTION_ID=%s", transaction_id)
        fetched = session.get(
            f"{base_url}/pix/transaction/{transaction_id}",
            timeout=timeout,
        )
        fetched.raise_for_status()
        if fetched.json() != result:
            raise RuntimeError(f"GET divergiu do POST para {transaction_id}")
        LOGGER.info("[GET VERIFY OK] HTTP_STATUS=%s TRANSACTION_ID=%s", fetched.status_code, transaction_id)
        LOGGER.info(
            "[FINAL RESULT] GROUP=%s FILE=%s STATUS=%s RISK_SCORE=%s",
            label.upper(),
            path.name,
            result["status"],
            result["metadata"]["risk_score"],
        )


def seed(
    base_url: str,
    token: str,
    timeout: float,
    history_payloads: list[tuple[Path, dict]],
    scenario_payloads: list[tuple[Path, dict]],
    seed_only: bool = False,
) -> None:
    import requests

    base_url = base_url.rstrip("/")
    headers = {"INTERNAL-TOKEN": token}

    requests.get(f"{base_url}/health_check", timeout=timeout).raise_for_status()

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

        LOGGER.info("Iniciando carga historica antes dos cenarios")
        send_transactions(session, base_url, timeout, "Historico", history_payloads)

        if seed_only:
            LOGGER.info("Carga historica concluida; cenarios de teste nao foram enviados (--seed-only)")
            return

        LOGGER.info("[HISTORY COMPLETE] Historico pronto; iniciando cenarios antifraude")
        send_transactions(session, base_url, timeout, "Cenario", scenario_payloads)


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
    parser.add_argument(
        "--seed-only",
        action="store_true",
        help="Carrega apenas o historico inicial; nao envia os cenarios de teste",
    )
    args = parser.parse_args()

    LOGGER.info("Carregando historico inicial de %s", HISTORY_DIR)
    history_payloads = [(path, read_json(path)) for path in HISTORY_DIR.glob("*.json")]
    LOGGER.info("Carregando cenarios de teste de %s", SCENARIOS_DIR)
    scenario_payloads = [(path, read_json(path)) for path in SCENARIOS_DIR.glob("*.json")]
    if not history_payloads:
        raise RuntimeError(f"Nenhum JSON historico encontrado em {HISTORY_DIR}")
    if not scenario_payloads:
        raise RuntimeError(f"Nenhum JSON encontrado em {SCENARIOS_DIR}")
    history_payloads = order_payloads(history_payloads, "historico")
    scenario_payloads = order_payloads(scenario_payloads, "cenarios")
    if transaction_date(history_payloads[-1][1]) > transaction_date(scenario_payloads[0][1]):
        raise RuntimeError(
            "O historico termina depois do primeiro cenario; ajuste as datas para nao cadastrar "
            "transacoes antigas apos transacoes mais recentes"
        )

    ids = [payload["id"] for _, payload in history_payloads + scenario_payloads]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Ha IDs de transacao repetidos entre o historico e os cenarios")
    LOGGER.info("%s transacoes historicas e %s cenarios carregados", len(history_payloads), len(scenario_payloads))
    LOGGER.info(
        "Ordem cronologica validada: historico %s -> %s; cenarios %s -> %s",
        transaction_date(history_payloads[0][1]).isoformat(),
        transaction_date(history_payloads[-1][1]).isoformat(),
        transaction_date(scenario_payloads[0][1]).isoformat(),
        transaction_date(scenario_payloads[-1][1]).isoformat(),
    )

    payloads = history_payloads + scenario_payloads
    validate_scenarios(payloads)
    if args.validate_only:
        LOGGER.info("Validacao local concluida: %s transacoes historicas e %s cenarios", len(history_payloads), len(scenario_payloads))
        return 0

    LOGGER.info("Iniciando seed em %s", args.base_url)
    seed(args.base_url, args.token, args.timeout, history_payloads, scenario_payloads, args.seed_only)
    LOGGER.info("Seed concluido: historico carregado e %s cenarios processados", 0 if args.seed_only else len(scenario_payloads))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())