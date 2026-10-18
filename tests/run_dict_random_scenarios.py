import argparse
from bisect import bisect_right
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import random
import uuid

from dotenv import load_dotenv
from tests.utils.device_api_mock import device_path
from tests.utils.dict_response_simulator import DictResponseSimulator
from tests.utils.excel_report import create_results_workbook, run_workbook_path
from tests.utils.mock_utils import BaseExpectation, Mock
from tests.utils.request_generator import RequestGenerator


TEST_ROOT = Path(__file__).resolve().parent
load_dotenv(TEST_ROOT.parent / ".env")
DEFAULT_LOG_PATH = TEST_ROOT / "logs" / "dict_random_scenarios.log"
DEFAULT_DICT_MOCK_PATH = TEST_ROOT / "logs" / "dict_random_generated_mock.json"
DEFAULT_SCENARIO_COUNT = 100
DEFAULT_CPF_COUNT = 50
COUNTER_BY_FRAUD_TYPE = {
    "APPLICATION_FRAUD": "ApplicationFrauds",
    "MULE_ACCOUNT": "MuleAccounts",
    "SCAMMER_ACCOUNT": "ScammerAccounts",
    "OTHER": "OtherFrauds",
    "UNKNOWN": "UnknownFrauds",
}
# Fração dos Pix feitos de um dispositivo cadastrado do titular da origem.
# O resto sai de um dispositivo do pool comum, que não é cadastrado na API (404).
REGISTERED_DEVICE_RATE = 0.85


def build_application_dict_mock(report: dict) -> dict:
    persons = {}
    for scenario in report["scenarios"]:
        for query in scenario["dict_queries"].values():
            document_number = query["document_number"]
            markers = query["response"]["ListFraudMarkersResponse"]["FraudMarkers"]["FraudMarker"]
            counters = {}
            for marker in markers:
                if marker["Status"] != "REGISTERED":
                    continue
                counter = COUNTER_BY_FRAUD_TYPE[marker["FraudType"]]
                counters.setdefault(counter, {"d90": 0, "m12": 0, "m60": 0})["m12"] += 1
            persons[document_number] = {"FraudMarkers": counters}

    return {"unavailable_documents": [], "entries": {}, "persons": persons}


def generate_cpf(rng: random.Random) -> str:
    digits = [rng.randrange(10) for _ in range(9)]
    while len(set(digits)) == 1:
        digits = [rng.randrange(10) for _ in range(9)]
    for position in (9, 10):
        remainder = sum(
            digit * (position + 1 - index) for index, digit in enumerate(digits)
        ) % 11
        digits.append(0 if remainder < 2 else 11 - remainder)
    return "".join(str(digit) for digit in digits)


def generate_cpf_pool(rng: random.Random, cpf_count: int) -> list:
    if cpf_count < 1:
        raise ValueError("A quantidade de CPFs deve ser maior que zero")

    documents = []
    seen = set()
    while len(documents) < cpf_count:
        document = generate_cpf(rng)
        if document not in seen:
            seen.add(document)
            documents.append(document)
    return documents


def random_timestamp(rng: random.Random, start: datetime, end: datetime) -> datetime:
    span_seconds = int((end - start).total_seconds())
    return start + timedelta(seconds=rng.randrange(span_seconds + 1))


def random_amount(rng: random.Random) -> int:
    if rng.random() < 0.08:
        return rng.randint(500_001, 2_000_000)
    if rng.random() < 0.2:
        return rng.randint(50_001, 500_000)
    return rng.randint(1_000, 50_000)


def random_location(rng: random.Random):
    if rng.random() < 0.08:
        return None
    latitude = rng.uniform(-23.8, -23.3)
    longitude = rng.uniform(-46.9, -46.3)
    if rng.random() < 0.04:
        latitude = rng.uniform(-33.0, 5.0)
        longitude = rng.uniform(-74.0, -34.0)
    return {"latitude": round(latitude, 6), "longitude": round(longitude, 6)}


def build_registered_devices(device_rng: random.Random, documents: list) -> dict:
    """Dispositivos cadastrados por titular: 1, às vezes 2 (celular + tablet)."""
    registered = {}
    for document in documents:
        quantity = 2 if device_rng.random() < 0.25 else 1
        registered[document] = [
            f"dvc-reg-{device_rng.getrandbits(48):012x}" for _ in range(quantity)
        ]
    return registered


def build_random_scenarios(
    simulator: DictResponseSimulator,
    rng: random.Random,
    run_id: str,
    count: int,
    documents: list,
    device_rng: random.Random = None,
) -> tuple:
    """Devolve (cenários, dispositivos cadastrados por documento)."""
    device_rng = device_rng or random.Random()
    if count < 1:
        raise ValueError("A quantidade de cenários deve ser maior que zero")
    dict_queries = {
        document: {"document_number": document, "response": simulator.query(document)}
        for document in documents
    }
    start = datetime(2026, 7, 19, tzinfo=timezone(timedelta(hours=-3)))
    end = datetime(2026, 10, 17, 23, 59, tzinfo=timezone(timedelta(hours=-3)))

    # Uma conta por CPF do pool (todos os CPFs entram no teste). Se o pool for
    # pequeno, completa com contas extras de CPFs sorteados, como antes.
    account_owners = list(documents)
    minimum_accounts = max(25, min(count, 100))
    while len(account_owners) < minimum_accounts:
        account_owners.append(rng.choice(documents))

    accounts = []
    used_account_numbers = set()
    for document_number in account_owners:
        account_number = str(rng.randrange(1_000_000, 99_999_999))
        while account_number in used_account_numbers:
            account_number = str(rng.randrange(1_000_000, 99_999_999))
        used_account_numbers.add(account_number)
        accounts.append({
            "account_number": account_number,
            "document_number": document_number,
            "opening_date": random_timestamp(
                rng,
                start - timedelta(days=365),
                start - timedelta(days=1),
            ),
        })
    accounts.sort(key=lambda account: account["opening_date"])
    opening_dates = [account["opening_date"] for account in accounts]

    # Pool comum: dispositivos que NÃO são cadastrados na API (404).
    devices = [f"dvc-{rng.getrandbits(48):012x}" for _ in range(max(10, count // 5))]
    registered_devices = build_registered_devices(device_rng, documents)
    transaction_times = sorted(random_timestamp(rng, start, end) for _ in range(count))
    institution_ispb = os.environ.get("INSTITUTION_ISPB", "00000000")
    scenarios = []

    for index, transaction_time in enumerate(transaction_times):
        # accounts está ordenado por abertura: as ativas são um prefixo.
        active_accounts = accounts[:bisect_right(opening_dates, transaction_time)]
        if len(active_accounts) < 2:
            active_accounts = accounts
        source = rng.choice(active_accounts)
        destination = rng.choice(active_accounts)
        if len(active_accounts) > 1 and destination is source:
            destination = rng.choice([account for account in active_accounts if account is not source])

        source_account = {
            "branch": "0001",
            "account_number": source["account_number"],
            "opening_date": source["opening_date"].isoformat(),
            "owner": {"document_number": source["document_number"]},
        }
        destination_account = {
            "participant": institution_ispb,
            "branch": "0001",
            "account_number": destination["account_number"],
            "opening_date": destination["opening_date"].isoformat(),
            "owner": {"document_number": destination["document_number"]},
        }

        # O device_rng (separado) decide se o Pix sai de um dispositivo
        # cadastrado do titular; senão usa o do pool comum (404 na API).
        amount = random_amount(rng)
        unregistered_device = rng.choice(devices)
        device_registered = device_rng.random() < REGISTERED_DEVICE_RATE
        device_id = (
            device_rng.choice(registered_devices[source["document_number"]])
            if device_registered else unregistered_device
        )

        payload = {
            "id": f"random-{run_id}-{index + 1:04d}",
            "amount": amount,
            "transaction_date": transaction_time.isoformat(timespec="seconds"),
            "source_account": source_account,
            "destination_account": destination_account,
            "source": {
                "device_id": device_id,
                "channel": rng.choice(("app", "internet_banking", "mobile")),
                "ip": f"198.51.100.{rng.randint(1, 254)}",
            },
        }
        geolocation = random_location(rng)
        if geolocation is not None:
            payload["source"]["geolocation"] = geolocation

        scenarios.append({
            "fixture": f"aleatorio_{index + 1:04d}",
            "post_payload": payload,
            "device_registered_expected": device_registered,
            "dict_queries": {
                "source_account": dict_queries[source["document_number"]],
                "destination_account": dict_queries[destination["document_number"]],
            },
        })
    return scenarios, registered_devices


def run_scenarios(seed=None, count=DEFAULT_SCENARIO_COUNT, cpf_count=DEFAULT_CPF_COUNT) -> dict:
    rng = random.Random(seed)
    simulator = DictResponseSimulator(rng=rng)
    run_id = uuid.uuid4().hex[:8]
    cpf_pool = generate_cpf_pool(rng, cpf_count)
    # RNG separado para os dispositivos, derivado da mesma seed.
    device_rng = random.Random(None if seed is None else f"{seed}-devices")
    scenarios, registered_devices = build_random_scenarios(
        simulator, rng, run_id, count, cpf_pool, device_rng=device_rng
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_id": run_id,
        "seed": seed,
        "cpf_count": cpf_count,
        "cpf_pool": cpf_pool,
        "scenario_count": len(scenarios),
        "registered_devices": registered_devices,
        "scenarios": scenarios,
    }


def register_devices_on_mock(registered_devices: dict) -> int:
    """Cadastra no mockserver (API de dispositivo) os dispositivos de cada titular.

    Limpa as expectativas antes: o que não for cadastrado aqui responde 404,
    que a R1 lê como "dispositivo não cadastrado".
    """
    mock = Mock()
    mock.clear()
    expectations = [
        BaseExpectation.generate_expectation(
            "GET",
            device_path(document, device_id),
            {"document_number": document, "device_id": device_id, "registered": True},
            200,
        )
        for document, device_ids in registered_devices.items()
        for device_id in device_ids
    ]
    # O mockserver aceita uma lista de expectativas num PUT só.
    mock.add_expectations(expectations)
    return len(expectations)


def submit_scenarios(report: dict) -> list:
    errors = []
    total = len(report["scenarios"])
    for position, scenario in enumerate(report["scenarios"], start=1):
        if position % 1000 == 0 or position == total:
            print(f"POSTs enviados: {position}/{total}", flush=True)
        try:
            status, response = RequestGenerator.POST_pix_transaction(scenario["post_payload"])
            scenario["post_result"] = {"http_status": status, "response": response}
            if status < 200 or status >= 300:
                errors.append(
                    f"{scenario['fixture']}: POST retornou HTTP {status}: {response}"
                )
        except RuntimeError as error:
            scenario["post_result"] = {"error": str(error)}
            errors.append(str(error))
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera respostas DICT aleatórias, envia os cenários por POST e grava os resultados."
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Semente para tornar as escolhas aleatórias reproduzíveis.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_SCENARIO_COUNT,
        help=f"Quantidade de transações aleatórias para enviar (padrão: {DEFAULT_SCENARIO_COUNT})",
    )
    parser.add_argument(
        "--cpf-count",
        type=int,
        default=DEFAULT_CPF_COUNT,
        help=f"Quantidade de CPFs únicos para reutilizar (padrão: {DEFAULT_CPF_COUNT})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help=f"Arquivo de log de saída (padrão: {DEFAULT_LOG_PATH})",
    )
    parser.add_argument(
        "--dict-mock-output",
        type=Path,
        default=DEFAULT_DICT_MOCK_PATH,
        help=f"Mock no formato interno da API (padrão: {DEFAULT_DICT_MOCK_PATH})",
    )
    parser.add_argument(
        "--excel-output",
        type=Path,
        help="Arquivo Excel de saída (padrão: mesmo nome do log com extensão .xlsx)",
    )
    arguments = parser.parse_args()

    report = run_scenarios(
        seed=arguments.seed,
        count=arguments.count,
        cpf_count=arguments.cpf_count,
    )
    arguments.dict_mock_output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.dict_mock_output.open("w", encoding="utf-8") as fixture:
        json.dump(build_application_dict_mock(report), fixture, indent=2, ensure_ascii=False)

    try:
        registered_count = register_devices_on_mock(report["registered_devices"])
    except Exception as error:
        raise RuntimeError(
            f"Não foi possível cadastrar os dispositivos no mockserver ({error}). "
            "Suba com `docker compose up -d mockserver`."
        ) from error
    print(f"Dispositivos cadastrados no mockserver: {registered_count}", flush=True)

    post_errors = submit_scenarios(report)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    excel_output = arguments.excel_output or run_workbook_path(
        report,
        arguments.output.parent,
    )
    create_results_workbook(report, excel_output)
    formatted_report = json.dumps(report, indent=2, ensure_ascii=False)

    logger = logging.getLogger("dict_random_scenarios")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(message)s")
    for handler in (
        logging.StreamHandler(),
        logging.FileHandler(arguments.output, mode="w", encoding="utf-8"),
    ):
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    logger.info(formatted_report)
    print(f"\nLog gravado em: {arguments.output.resolve()}")
    print(f"Planilha Excel: {excel_output.resolve()}")
    print(f"Mock DICT usado pela API: {arguments.dict_mock_output.resolve()}")
    print(f"Cenários POST executados: {len(report['scenarios'])}")
    if post_errors:
        raise RuntimeError(
            "Um ou mais POSTs falharam ou retornaram erro; confira o log e verifique se a API está "
            "no ar e configurada para usar o mock gerado."
        )


if __name__ == "__main__":
    main()
