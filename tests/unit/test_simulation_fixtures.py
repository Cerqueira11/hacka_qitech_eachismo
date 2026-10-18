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

    assert report["scenario_count"] == 100
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
        assert scenario["dict_queries"]["source_account"]["document_number"] == (
            payload["source_account"]["owner"]["document_number"]
        )
        assert scenario["dict_queries"]["destination_account"]["document_number"] == (
            payload["destination_account"]["owner"]["document_number"]
        )
    assert timestamps == sorted(timestamps)


def test_random_payload_population_is_reproducible_by_seed():
    first = run_scenarios(seed=42, count=10)
    second = run_scenarios(seed=42, count=10)

    for first_scenario, second_scenario in zip(first["scenarios"], second["scenarios"]):
        first_payload = first_scenario["post_payload"]
        second_payload = second_scenario["post_payload"]
        first_payload["id"] = second_payload["id"] = ""
        assert first_payload == second_payload


def test_runner_rejects_nonpositive_scenario_count():
    with pytest.raises(ValueError, match="maior que zero"):
        run_scenarios(seed=42, count=0)


@pytest.mark.parametrize("fixture_path", sorted(POST_FIXTURE_DIRECTORY.glob("*.json")))
def test_post_pix_transaction_fixtures_match_api_schema(fixture_path):
    with fixture_path.open(encoding="utf-8") as fixture:
        payload = json.load(fixture)
    with PIX_TRANSACTION_SCHEMA.open(encoding="utf-8") as schema_file:
        schema = json.load(schema_file)

    validate(instance=payload, schema=schema)
