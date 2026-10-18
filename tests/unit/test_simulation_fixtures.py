import json
from pathlib import Path
import random

import pytest
from jsonschema import validate

from tests.run_dict_random_scenarios import (
    build_application_dict_mock,
    run_scenarios,
)
from tests.utils.dict_response_simulator import DICT_RESPONSE_FIXTURE, DictResponseSimulator
from tests.utils.excel_report import create_results_workbook, run_workbook_path


TEST_ROOT = Path(__file__).resolve().parents[1]
POST_FIXTURE_DIRECTORY = TEST_ROOT / "fixtures" / "api_post" / "pix_transaction"
PIX_TRANSACTION_SCHEMA = (
    TEST_ROOT.parent / "src" / "schemas" / "post_pix_transaction.json"
)
FRAUD_TYPES = {
    "APPLICATION_FRAUD",
    "MULE_ACCOUNT",
    "SCAMMER_ACCOUNT",
    "OTHER",
    "UNKNOWN",
}


def test_dict_simulator_queries_cpf_and_cnpj_independently():
    simulator = DictResponseSimulator()

    no_marker = simulator.query("529.982.247-25")["ListFraudMarkersResponse"]
    cnpj_marker = simulator.query("11.222.333/0001-81")["ListFraudMarkersResponse"]

    assert no_marker["HasMoreElements"] is False
    assert no_marker["Total"] == 0
    assert no_marker["FraudMarkers"]["FraudMarker"] == []
    assert cnpj_marker["FraudMarkers"]["FraudMarker"][0]["TaxIdNumber"] == "11222333000181"
    assert cnpj_marker["FraudMarkers"]["FraudMarker"][0]["FraudType"] == "UNKNOWN"


def test_dict_simulator_covers_marker_statuses_types_and_pagination():
    with DICT_RESPONSE_FIXTURE.open(encoding="utf-8") as fixture:
        responses = json.load(fixture)

    statuses = set()
    fraud_types = set()
    paginated = False
    for response in responses.values():
        result = response["ListFraudMarkersResponse"]
        markers = result["FraudMarkers"]["FraudMarker"]
        assert result["Total"] >= len(markers)
        if result["HasMoreElements"]:
            paginated = True
            assert result["Total"] > len(markers)
        statuses.update(marker["Status"] for marker in markers)
        fraud_types.update(marker["FraudType"] for marker in markers)

    assert statuses == {"REGISTERED", "CANCELLED"}
    assert fraud_types == FRAUD_TYPES
    assert paginated


@pytest.mark.parametrize("document_number, expected_digits", [
    ("123.456.789-01", "12345678901"),
    ("12.345.678/0001-90", "12345678000190"),
])
def test_dict_simulator_generates_response_for_unmocked_documents(document_number, expected_digits):
    simulator = DictResponseSimulator(rng=random.Random(7))

    response = simulator.query(document_number)["ListFraudMarkersResponse"]
    assert simulator.query(document_number) == {
        "ListFraudMarkersResponse": response
    }

    assert response["CorrelationId"]
    assert response["Total"] >= len(response["FraudMarkers"]["FraudMarker"])
    assert response["HasMoreElements"] is (
        response["Total"] > len(response["FraudMarkers"]["FraudMarker"])
    )
    assert all(
        marker["TaxIdNumber"] == expected_digits
        and marker["Status"] in {"REGISTERED", "CANCELLED"}
        and marker["FraudType"] in FRAUD_TYPES
        for marker in response["FraudMarkers"]["FraudMarker"]
    )


def test_random_dict_responses_convert_to_application_mock_format():
    report = {
        "scenarios": [
            {
                "dict_queries": {
                    "source_account": {
                        "document_number": "12345678901",
                        "response": {
                            "ListFraudMarkersResponse": {
                                "FraudMarkers": {
                                    "FraudMarker": [
                                        {"Status": "REGISTERED", "FraudType": "MULE_ACCOUNT"},
                                        {"Status": "REGISTERED", "FraudType": "MULE_ACCOUNT"},
                                        {"Status": "REGISTERED", "FraudType": "OTHER"},
                                        {"Status": "CANCELLED", "FraudType": "SCAMMER_ACCOUNT"},
                                    ]
                                }
                            }
                        },
                    }
                }
            }
        ]
    }

    dict_mock = build_application_dict_mock(report)

    assert dict_mock["persons"]["12345678901"]["FraudMarkers"] == {
        "MuleAccounts": {"d90": 0, "m12": 2, "m60": 0},
        "OtherFrauds": {"d90": 0, "m12": 1, "m60": 0},
    }


def test_dict_simulator_rejects_invalid_queries():
    simulator = DictResponseSimulator()

    with pytest.raises(ValueError, match="CPF com 11 dígitos ou CNPJ com 14"):
        simulator.query("documento-invalido")


def test_random_dict_response_is_clean_95_percent_and_marked_5_percent():
    simulator = DictResponseSimulator(rng=random.Random(20261018))
    responses = [
        simulator.query(f"{index:011d}")["ListFraudMarkersResponse"]
        for index in range(1, 2001)
    ]

    marked = sum(
        any(
            marker["Status"] == "REGISTERED"
            for marker in response["FraudMarkers"]["FraudMarker"]
        )
        for response in responses
    )
    marked_rate = marked / len(responses)

    assert 0.03 <= marked_rate <= 0.07
    assert all(
        response["Total"] == 0 and response["FraudMarkers"]["FraudMarker"] == []
        for response in responses
        if not response["FraudMarkers"]["FraudMarker"]
    )


def test_post_pix_transaction_fixtures_have_matching_dict_responses():
    simulator = DictResponseSimulator()

    for fixture_path in sorted(POST_FIXTURE_DIRECTORY.glob("*.json")):
        with fixture_path.open(encoding="utf-8") as fixture:
            payload = json.load(fixture)
        document_number = payload["destination_account"]["owner"]["document_number"]
        response = simulator.query(document_number)["ListFraudMarkersResponse"]

        assert all(
            marker["TaxIdNumber"] == document_number
            for marker in response["FraudMarkers"]["FraudMarker"]
        )


def test_random_post_fixtures_use_unmocked_documents_and_generate_dict_responses():
    dict_mock_path = TEST_ROOT.parent / "src" / "mocks" / "dict_mock.json"
    with dict_mock_path.open(encoding="utf-8") as fixture:
        dict_mock = json.load(fixture)

    mock_documents = set(dict_mock["unavailable_documents"])
    mock_documents.update(dict_mock["persons"])
    mock_documents.update(
        entry["Owner"]["TaxIdNumber"]
        for entry in dict_mock["entries"].values()
        if entry is not None
    )
    response_fixture_documents = set(json.loads(DICT_RESPONSE_FIXTURE.read_text(encoding="utf-8")))
    random_fixture_paths = sorted(POST_FIXTURE_DIRECTORY.glob("aleatoria_documentos_*.json"))
    simulator = DictResponseSimulator(rng=random.Random(42))
    consulted_documents = set()

    assert len(random_fixture_paths) == 3
    for fixture_path in random_fixture_paths:
        with fixture_path.open(encoding="utf-8") as fixture:
            payload = json.load(fixture)
        for account in (payload["source_account"], payload["destination_account"]):
            document = account["owner"]["document_number"]
            assert document not in mock_documents
            assert document not in response_fixture_documents
            consulted_documents.add(document)

            result = simulator.query(document)["ListFraudMarkersResponse"]
            markers = result["FraudMarkers"]["FraudMarker"]
            assert result["Total"] >= len(markers)
            assert result["HasMoreElements"] is (result["Total"] > len(markers))
            assert all(marker["TaxIdNumber"] == document for marker in markers)

    assert len(consulted_documents) == 5


def test_runner_generates_random_production_payloads_for_existing_api_schema():
    report = run_scenarios(seed=42, count=100)
    schema = json.loads(PIX_TRANSACTION_SCHEMA.read_text(encoding="utf-8"))
    scenarios = report["scenarios"]
    payloads = [scenario["post_payload"] for scenario in scenarios]
    cpf_pool = set(report["cpf_pool"])

    assert report["scenario_count"] == 100
    assert report["cpf_count"] == 50
    assert len(cpf_pool) == report["cpf_count"]
    assert all(len(document) == 11 and document.isdigit() for document in cpf_pool)
    assert len({payload["id"] for payload in payloads}) == 100
    assert len({
        payload["source_account"]["account_number"]
        for payload in payloads
    }) > 1
    assert len({
        payload["destination_account"]["account_number"]
        for payload in payloads
    }) > 1
    assert len({
        payload["source"]["device_id"]
        for payload in payloads
    }) > 1
    assert len({
        payload["source_account"]["owner"]["document_number"]
        for payload in payloads
    }) > 1
    assert len({
        payload["destination_account"]["owner"]["document_number"]
        for payload in payloads
    }) > 1

    timestamps = []
    for scenario in scenarios:
        payload = scenario["post_payload"]
        validate(instance=payload, schema=schema)
        timestamps.append(payload["transaction_date"])
        assert payload["source_account"]["owner"]["document_number"] in cpf_pool
        assert payload["destination_account"]["owner"]["document_number"] in cpf_pool
        assert scenario["dict_queries"]["source_account"]["document_number"] == (
            payload["source_account"]["owner"]["document_number"]
        )
        assert scenario["dict_queries"]["destination_account"]["document_number"] == (
            payload["destination_account"]["owner"]["document_number"]
        )
    assert timestamps == sorted(timestamps)


def test_random_payload_population_is_reproducible_by_seed():
    first = run_scenarios(seed=42, count=10, cpf_count=7)
    second = run_scenarios(seed=42, count=10, cpf_count=7)

    assert first["cpf_count"] == 7
    assert first["cpf_pool"] == second["cpf_pool"]
    for first_scenario, second_scenario in zip(first["scenarios"], second["scenarios"]):
        first_payload = first_scenario["post_payload"]
        second_payload = second_scenario["post_payload"]
        first_payload["id"] = second_payload["id"] = ""
        assert first_payload == second_payload


def test_runner_rejects_nonpositive_scenario_count():
    with pytest.raises(ValueError, match="maior que zero"):
        run_scenarios(seed=42, count=0)


def test_runner_rejects_nonpositive_cpf_count():
    with pytest.raises(ValueError, match="quantidade de CPFs deve ser maior que zero"):
        run_scenarios(seed=42, count=10, cpf_count=0)


def test_excel_export_includes_api_verdict_and_marks_missing_post_results(tmp_path):
    report = {
        "generated_at": "2026-10-17T23:00:00-03:00",
        "scenario_count": 1,
        "scenarios": [
            {
                "fixture": "exemplo",
                "post_payload": {
                    "id": "pix-exemplo",
                    "amount": 1500,
                    "transaction_date": "2026-10-17T14:00:00-03:00",
                    "source_account": {
                        "owner": {"document_number": "12345678909"},
                        "account_number": "1001",
                    },
                    "destination_account": {
                        "owner": {"document_number": "98765432100"},
                        "account_number": "2002",
                    },
                },
                "dict_queries": {},
                "post_result": {
                    "http_status": 201,
                    "response": {
                        "status": "approved",
                        "metadata": {"risk_score": 0.12, "reasons": ["destino_desconhecido"]},
                    },
                },
            },
            {
                "fixture": "sem-post",
                "post_payload": {},
                "dict_queries": {},
            },
        ],
    }
    output_path = create_results_workbook(report, tmp_path / "resultados.xlsx")

    from openpyxl import load_workbook

    workbook = load_workbook(output_path, data_only=True)
    summary = workbook["Resumo"]
    transactions = workbook["Transações"]
    assert summary["B6"].value == 1
    assert summary["B8"].value == 1
    assert transactions["L2"].value == 201
    assert transactions["M2"].value == "approved"
    assert transactions["N2"].value == 0.12
    assert transactions["M3"].value == "Não registrado"


def test_default_excel_path_is_unique_for_each_runner_execution(tmp_path):
    first = run_workbook_path({"run_id": "a1b2c3d4"}, tmp_path)
    second = run_workbook_path({"run_id": "e5f6a7b8"}, tmp_path)

    assert first.parent == tmp_path
    assert first.suffix == ".xlsx"
    assert first.name.startswith("dict_random_results_")
    assert first != second


@pytest.mark.parametrize("fixture_path", sorted(POST_FIXTURE_DIRECTORY.glob("*.json")))
def test_post_pix_transaction_fixtures_match_api_schema(fixture_path):
    with fixture_path.open(encoding="utf-8") as fixture:
        payload = json.load(fixture)
    with PIX_TRANSACTION_SCHEMA.open(encoding="utf-8") as schema_file:
        schema = json.load(schema_file)

    validate(instance=payload, schema=schema)
