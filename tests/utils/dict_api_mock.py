"""O DICT (R4), do ponto de vista do teste.

Quem responde no docker compose é o mockserver: sem expectativa cadastrada
ele devolve 404, que a R4 lê como "documento sem histórico no DICT" (pessoa
limpa). Por isso só os documentos com marcação, infração aberta ou DICT fora
do ar precisam de expectativa. Cada teste sorteia o próprio documento e
cadastra aqui o roteiro do cenário.

Contrato combinado com a API (GET /persons/{documento}/statistics):
PersonStatistics do DICT (contadores d90/m12/m60 por FraudType) mais a lista
OpenInfractions das notificações de infração abertas.
"""
from urllib.parse import quote

from tests.utils.mock_utils import BaseExpectation, Mock

MASK_CHARACTERS = ".-/ "


def normalize(document_number: str) -> str:
    """Como a API manda o documento para o DICT: sem máscara, letras em maiúsculo
    (o CNPJ alfanumérico tem letras)."""
    return "".join(character.upper() for character in document_number if character not in MASK_CHARACTERS)


def statistics_path(document_number: str) -> str:
    return f"/persons/{quote(normalize(document_number), safe='')}/statistics"


def counter(m12: int, d90: int = 0) -> dict:
    return {"d90": d90, "m12": m12, "m60": m12}


class DictApiMock:
    @staticmethod
    def statistics(
        document_number: str,
        fraud_markers: dict = None,
        open_infractions: list = None,
        open_reports: int = None,
    ) -> None:
        """O DICT responde 200 com as estatísticas deste documento."""
        open_infractions = open_infractions or []
        if open_reports is None:
            open_reports = len(open_infractions)
        Mock().add_expectations(
            BaseExpectation.generate_expectation(
                "GET",
                statistics_path(document_number),
                {
                    "TaxIdNumber": normalize(document_number),
                    "FraudMarkers": fraud_markers or {},
                    "InfractionReports": {"OpenReports": open_reports},
                    "OpenInfractions": open_infractions,
                },
                200,
            )
        )

    # ── Personas ────────────────────────────────────────────────────────
    @staticmethod
    def mule(document_number: str) -> None:
        """MULE_ACCOUNT nos últimos 12 meses: Pix para ele é rejeitado."""
        DictApiMock.statistics(document_number, {"MuleAccounts": counter(m12=2, d90=1)})

    @staticmethod
    def scammer(document_number: str) -> None:
        """SCAMMER_ACCOUNT nos últimos 12 meses: Pix dele é rejeitado."""
        DictApiMock.statistics(document_number, {"ScammerAccounts": counter(m12=1)})

    @staticmethod
    def under_analysis(document_number: str) -> None:
        """Notificação de infração SCAM aberta: Pix para ele pede 2FA."""
        DictApiMock.statistics(document_number, open_infractions=[{"SituationType": "SCAM", "Status": "OPEN"}])

    @staticmethod
    def account_takeover(document_number: str) -> None:
        """Notificação ACCOUNT_TAKEOVER aberta: Pix dele pede 2FA."""
        DictApiMock.statistics(
            document_number, open_infractions=[{"SituationType": "ACCOUNT_TAKEOVER", "Status": "ACKNOWLEDGED"}]
        )

    @staticmethod
    def weak_signal(document_number: str) -> None:
        """Marcação OTHER: só soma peso."""
        DictApiMock.statistics(document_number, {"OtherFrauds": counter(m12=1)})

    # ── DICT fora do ar ─────────────────────────────────────────────────
    @staticmethod
    def unavailable(document_number: str, status_code: int = 503) -> None:
        Mock().add_expectations(
            BaseExpectation.generate_expectation(
                "GET", statistics_path(document_number), {"message": "Service Unavailable"}, status_code
            )
        )

    @staticmethod
    def slow(document_number: str, delay_ms: int = 2000) -> None:
        """Responde 200 limpo, mas depois do timeout da API: conta como fora do ar."""
        Mock().add_expectations(
            BaseExpectation.generate_expectation(
                "GET",
                statistics_path(document_number),
                {"TaxIdNumber": normalize(document_number), "FraudMarkers": {}, "InfractionReports": {"OpenReports": 0}},
                200,
                delay_ms=delay_ms,
            )
        )

    # ── Verificação ─────────────────────────────────────────────────────
    @staticmethod
    def calls(document_number: str) -> int:
        """Quantas vezes a API consultou o DICT para este documento."""
        return len(Mock().retrieve_requests(method="GET", path=statistics_path(document_number)))
