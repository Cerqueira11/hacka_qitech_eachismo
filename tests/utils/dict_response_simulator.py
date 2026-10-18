import argparse
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import random
import uuid
from typing import Optional


DICT_RESPONSE_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "dict_responses.json"
FRAUD_TYPES = (
    "APPLICATION_FRAUD",
    "MULE_ACCOUNT",
    "SCAMMER_ACCOUNT",
    "OTHER",
    "UNKNOWN",
)
STATUSES = ("REGISTERED", "CANCELLED")
FRAUD_RESPONSE_PROBABILITY = 0.05


class DictResponseSimulator:
    """Devolve fixture conhecida ou resposta aleatória para CPF/CNPJ não mockado."""

    def __init__(
        self,
        fixture_path: Path = DICT_RESPONSE_FIXTURE,
        rng: Optional[random.Random] = None,
    ) -> None:
        with fixture_path.open(encoding="utf-8") as fixture:
            self._responses = json.load(fixture)
        self._rng = rng or random.Random()
        self._generated_responses = {}

    def query(self, document_number: str) -> dict:
        digits = "".join(character for character in document_number if character.isdigit())
        if len(digits) not in (11, 14):
            raise ValueError("A consulta ao DICT exige um CPF com 11 dígitos ou CNPJ com 14 dígitos")
        if digits in self._responses:
            return deepcopy(self._responses[digits])
        if digits not in self._generated_responses:
            self._generated_responses[digits] = self._generate_response(digits)
        return deepcopy(self._generated_responses[digits])

    def _generate_response(self, document_number: str) -> dict:
        has_fraud_marker = self._rng.random() < FRAUD_RESPONSE_PROBABILITY
        total = self._rng.randint(1, 5) if has_fraud_marker else 0
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        markers = []
        if total:
            returned_count = min(total, self._rng.randint(1, 3))
            for index in range(returned_count):
                marker_id = str(uuid.uuid4())
                markers.append({
                    "Id": marker_id,
                    "Status": "REGISTERED" if index == 0 else self._rng.choice(STATUSES),
                    "TaxIdNumber": document_number,
                    "FraudType": self._rng.choice(FRAUD_TYPES),
                    "Key": f"{uuid.uuid4().hex[:12]}@example.test",
                    "CreationTime": now,
                    "LastModified": now,
                    "InfractionReport": {"Id": str(uuid.uuid4())},
                })

        return {
            "ListFraudMarkersResponse": {
                "Signature": "",
                "ResponseTime": now,
                "CorrelationId": uuid.uuid4().hex,
                "HasMoreElements": total > len(markers),
                "Total": total,
                "FraudMarkers": {"FraudMarker": markers},
            }
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera uma resposta DICT simulada.")
    parser.add_argument("document_number", help="CPF ou CNPJ consultado, com ou sem máscara")
    arguments = parser.parse_args()
    print(json.dumps(DictResponseSimulator().query(arguments.document_number), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
