"""Cliente do DICT (Diretório de Identificadores de Contas Transacionais do BCB).

O motor usa uma consulta só: as estatísticas de fraude de um CPF/CNPJ (R4).
O contrato abaixo segue o PersonStatistics da API DICT (contadores d90/m12/m60
por FraudType), em JSON:

    GET /persons/{TaxIdNumber}/statistics
      200 {
            "TaxIdNumber": "...",
            "FraudMarkers": {"MuleAccounts": {"d90": 1, "m12": 2, "m60": 2}, ...},
            "InfractionReports": {"OpenReports": 1},
            "OpenInfractions": [{"SituationType": "SCAM", "Status": "OPEN"}]
          }
      404 -> documento sem histórico no DICT (pessoa limpa)

OpenInfractions não faz parte do PersonStatistics: representa a listagem das
notificações de infração abertas contra o documento.

Qualquer outra coisa (timeout, erro de rede, 5xx, 429, corpo que não é objeto)
vira DictUnavailable: quem chama decide o que fazer (a R4 pede 2FA).

O vínculo conta x titular NÃO vem daqui (C2): o DICT é indexado por chave Pix
(GET /entries/{Key}) e não busca por conta. A R3 compara o payload com o
account_node verificado.

Localmente quem responde é o mockserver do docker compose. Se o formato real
for diferente, só este arquivo muda.
"""
from dataclasses import dataclass
from typing import Tuple
from urllib.parse import quote

import requests

from connectors.rest_connector import RestConnector
from constants import DICT_API_INTERNAL_TOKEN, DICT_API_TIMEOUT, DICT_API_URL

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
    """O DICT não respondeu de forma utilizável. Quem chama decide o que fazer."""


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


class DictApiClient(RestConnector):
    def __init__(
        self,
        base_url: str = DICT_API_URL,
        timeout: float = DICT_API_TIMEOUT,
        internal_token: str = DICT_API_INTERNAL_TOKEN,
    ) -> None:
        super().__init__(__name__, base_url, timeout, internal_token)

    def get_person_risk(self, document_number: str) -> DictPersonRisk:
        if not self.base_url:
            raise DictUnavailable("DICT_API_URL não configurada")
        endpoint = f"/persons/{quote(document_number, safe='')}/statistics"
        try:
            response = self.send(endpoint, "GET")
        except requests.RequestException as error:
            raise DictUnavailable(f"{type(error).__name__}: {error}") from error
        if response.status == 404:
            return CLEAN_PERSON
        if response.status == 200 and isinstance(response.json, dict):
            return _person_risk(response.json)
        if response.status == 200:
            raise DictUnavailable("200 sem PersonStatistics no corpo")
        raise DictUnavailable(f"HTTP {response.status}")


def _person_risk(statistics: dict) -> DictPersonRisk:
    fraud_types = set()
    for counter, values in (statistics.get("FraudMarkers") or {}).items():
        fraud_type = FRAUD_TYPE_BY_COUNTER.get(counter)
        # m12 já inclui os últimos 90 dias (d90).
        if fraud_type and isinstance(values, dict) and (values.get("m12") or 0) > 0:
            fraud_types.add(fraud_type)
    infractions = tuple(
        item["SituationType"]
        for item in (statistics.get("OpenInfractions") or [])
        if isinstance(item, dict) and item.get("SituationType")
    )
    open_reports = (statistics.get("InfractionReports") or {}).get("OpenReports") or 0
    if open_reports > 0 and not infractions:
        infractions = ("OTHER",)
    return DictPersonRisk(fraud_types=frozenset(fraud_types), open_infractions=infractions)
