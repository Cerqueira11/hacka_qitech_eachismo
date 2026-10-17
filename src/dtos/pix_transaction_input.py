import ipaddress
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from constants import INSTITUTION_ISPB
from errors import InvalidDocumentNumber, InvalidIpAddress, InvalidOpeningDate, InvalidTransactionDate
from utils.document_number import normalize_document_number, person_type_of


@dataclass(frozen=True)
class AccountInput:
    participant: str
    branch: str
    account_number: str
    document_number: str
    person_type: str
    opening_date: datetime


@dataclass(frozen=True)
class GeolocationInput:
    latitude: float
    longitude: float


@dataclass(frozen=True)
class PixTransactionInput:
    """O corpo do POST já validado pelo schema, normalizado e com os tipos certos.

    O schema cobra o FORMATO; aqui ficam as checagens que dependem de conta
    (dígito verificador, data com fuso, IP real) e que respondem 422.
    """

    transaction_id: str
    amount: int
    transaction_date: datetime
    source_account: AccountInput
    destination_account: AccountInput
    device_id: str
    channel: str
    ip: str
    geolocation: Optional[GeolocationInput]

    @staticmethod
    def from_payload(payload: dict) -> "PixTransactionInput":
        transaction_date = _parse_aware_datetime(payload["transaction_date"])
        if transaction_date is None:
            raise InvalidTransactionDate(
                "transaction_date must be an ISO-8601 date-time with timezone, e.g. 2026-10-17T22:15:00-03:00."
            )

        source = payload["source"]
        geolocation = None
        if source.get("geolocation"):
            geolocation = GeolocationInput(
                latitude=source["geolocation"]["latitude"],
                longitude=source["geolocation"]["longitude"],
            )

        return PixTransactionInput(
            transaction_id=payload["id"],
            amount=payload["amount"],
            transaction_date=transaction_date,
            source_account=_parse_account(payload["source_account"], "source_account", transaction_date),
            destination_account=_parse_account(
                payload["destination_account"], "destination_account", transaction_date
            ),
            device_id=source["device_id"],
            channel=source["channel"],
            ip=_parse_ip(source["ip"]),
            geolocation=geolocation,
        )


def _parse_aware_datetime(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # Sem fuso não dá para saber se 22:15 é horário noturno em Brasília.
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _parse_account(account: dict, field: str, transaction_date: datetime) -> AccountInput:
    document_number = normalize_document_number(account["owner"]["document_number"])
    person_type = person_type_of(document_number)
    if person_type is None:
        raise InvalidDocumentNumber(f"{field}.owner.document_number")

    opening_date = _parse_aware_datetime(account["opening_date"])
    if opening_date is None or opening_date > transaction_date:
        raise InvalidOpeningDate(f"{field}.opening_date")

    # A origem é sempre conta desta instituição; o destino diz o próprio ISPB.
    participant = account.get("participant") or INSTITUTION_ISPB

    return AccountInput(
        participant=participant,
        # Identidade canônica do nó: '1' e '0001' são a mesma agência,
        # '010442' e '10442' a mesma conta.
        branch=account["branch"].zfill(4),
        account_number=account["account_number"].lstrip("0") or "0",
        document_number=document_number,
        person_type=person_type,
        opening_date=opening_date,
    )


def _parse_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        raise InvalidIpAddress(value)
