"""Cliente do DICT (Diretório de Identificadores de Contas Transacionais do BCB).

Só existe a versão simulada, e ela responde uma coisa só: as estatísticas de
fraude de um CPF/CNPJ (GET /persons/{TaxIdNumber}/statistics), usadas pela R4.

O vínculo conta x titular NÃO vem daqui (C2): o DICT é indexado por chave Pix
(GET /entries/{Key}) e não busca por conta, e o payload deste serviço não traz
chave. A R3 compara o payload com o account_node verificado.

Um cliente real (subclasse de RestConnector) entra no lugar do mock com o
mesmo método get_person_risk.
"""

import json
import os
import threading
from dataclasses import dataclass
from typing import Tuple

from constants import DICT_MOCK_FILE

# Contadores do PersonStatistics.FraudMarkers -> FraudType da API DICT.
FRAUD_TYPE_BY_COUNTER = {
    "ApplicationFrauds": "APPLICATION_FRAUD",
    "MuleAccounts": "MULE_ACCOUNT",
    "ScammerAccounts": "SCAMMER_ACCOUNT",
    "OtherFrauds": "OTHER",
    "UnknownFrauds": "UNKNOWN",
}
STRONG_FRAUD_TYPES = frozenset({"MULE_ACCOUNT", "SCAMMER_ACCOUNT", "APPLICATION_FRAUD"})
WEAK_FRAUD_TYPES = frozenset({"OTHER", "UNKNOWN"})


class DictUnavailable(Exception):
    """O DICT não respondeu (timeout, erro). Quem chama decide o que fazer."""


@dataclass(frozen=True)
class DictPersonRisk:
    """O que o DICT sabe de um CPF/CNPJ nos últimos 12 meses."""

    fraud_types: frozenset = frozenset()   # FraudType com marcação nos últimos 12 meses
    open_infractions: Tuple[str, ...] = ()  # SituationType das notificações abertas

    @property
    def has_strong_marker(self) -> bool:
        return bool(self.fraud_types & STRONG_FRAUD_TYPES)

    @property
    def has_weak_marker(self) -> bool:
        return bool(self.fraud_types & WEAK_FRAUD_TYPES)

    @property
    def external_risk(self) -> float:
        """O risco "de fato" que vai para account_node.external_risk."""
        if self.has_strong_marker:
            return 1.0
        if self.open_infractions:
            return 0.6
        if self.has_weak_marker:
            return 0.3
        return 0.0


CLEAN_PERSON = DictPersonRisk()


class DictMockClient:
    """DICT simulado a partir de src/mocks/dict_mock.json."""

    _lock = threading.Lock()
    _cache = {}  # caminho do arquivo -> (mtime, conteúdo)

    def __init__(self, fixture_path: str = DICT_MOCK_FILE) -> None:
        self.fixture_path = fixture_path

    def get_person_risk(self, document_number: str) -> DictPersonRisk:
        self._raise_if_unavailable(document_number)
        person = self._data().get("persons", {}).get(document_number)
        if person is None:
            return CLEAN_PERSON

        fraud_types = set()
        for counter, values in person.get("FraudMarkers", {}).items():
            fraud_type = FRAUD_TYPE_BY_COUNTER.get(counter)
            # m12 já inclui os últimos 90 dias (d90).
            if fraud_type and (values or {}).get("m12", 0) > 0:
                fraud_types.add(fraud_type)

        infractions = tuple(item["SituationType"] for item in person.get("OpenInfractions", []))
        open_reports = person.get("InfractionReports", {}).get("OpenReports", 0)
        if open_reports > 0 and not infractions:
            infractions = ("OTHER",)

        return DictPersonRisk(fraud_types=frozenset(fraud_types), open_infractions=infractions)

    def _raise_if_unavailable(self, document_number: str) -> None:
        if document_number in self._data().get("unavailable_documents", []):
            raise DictUnavailable(f"DICT simulado indisponível para {document_number}")

    def _data(self) -> dict:
        # Relê o arquivo só quando ele muda: editar o mock vale sem reiniciar a API.
        try:
            mtime = os.path.getmtime(self.fixture_path)
        except OSError as error:
            raise DictUnavailable(f"Arquivo do DICT simulado não encontrado: {self.fixture_path}") from error

        with DictMockClient._lock:
            cached = DictMockClient._cache.get(self.fixture_path)
            if cached is None or cached[0] != mtime:
                with open(self.fixture_path, "r", encoding="utf-8") as fixture:
                    cached = (mtime, json.load(fixture))
                DictMockClient._cache[self.fixture_path] = cached
            return cached[1]
