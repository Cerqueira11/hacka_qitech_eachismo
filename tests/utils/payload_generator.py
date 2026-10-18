import hashlib
import random
import uuid
from typing import Optional

from tests.utils.random_generator import RandomGenerator

# Datas de referência dos cenários (horário de Brasília).
NIGHT = "2026-10-17T22:15:00-03:00"
DAY = "2026-10-17T14:00:00-03:00"
OLD_ACCOUNT = "2024-01-01T09:00:00-03:00"
NEW_ACCOUNT = "2026-10-10T09:00:00-03:00"  # 7 dias antes de NIGHT/DAY: "destino_conta_nova"


def only_digits(document_number: str) -> str:
    return "".join(character for character in document_number if character.isdigit())


def source_ip(document_number: str, account_number: str) -> str:
    """IP padrão de uma origem: o mesmo para a mesma conta, outro para cada conta.

    Um IP fixo para todo payload faria a N1 (mesmo IP em 3+ contas em 24h)
    disparar em qualquer teste que rode depois de outros dois no mesmo dia.
    """
    # Zeros à esquerda não mudam a conta (a API normaliza): também não mudam o IP.
    account = account_number.lstrip("0") or "0"
    digest = hashlib.sha256(f"{only_digits(document_number)}|{account}".encode()).digest()
    return f"10.{digest[0]}.{digest[1]}.{digest[2] or 1}"


class PayloadGenerator:
    """Gera payloads prontos para os testes da API."""

    @staticmethod
    def random_account_number() -> str:
        return str(random.randrange(10_000, 99_999_999))

    @staticmethod
    def random_device_id() -> str:
        return f"dvc-{uuid.uuid4().hex[:12]}"

    @staticmethod
    def create_pix_transaction_payload(
        transaction_id: Optional[str] = None,
        amount: int = 150000,
        transaction_date: str = NIGHT,
        source_document_number: Optional[str] = None,
        destination_document_number: Optional[str] = None,
        source_participant: Optional[str] = None,
        source_branch: str = "0001",
        source_account_number: Optional[str] = None,
        source_opening_date: str = "2025-03-02T10:00:00-03:00",
        destination_participant: str = "60701190",
        destination_branch: str = "3675",
        destination_account_number: Optional[str] = None,
        destination_opening_date: str = NEW_ACCOUNT,
        device_id: Optional[str] = None,
        channel: str = "app",
        ip: Optional[str] = None,
        latitude: float = -23.56,
        longitude: float = -46.65,
        include_geolocation: bool = True,
    ) -> dict:
        # Ids, contas, documentos e dispositivos aleatórios: cada teste cria o
        # próprio pedaço do grafo, sem esbarrar na idempotência (mesmo "id")
        # nem no histórico de outro teste — e pode rodar quantas vezes quiser.
        if transaction_id is None:
            transaction_id = f"pix-{uuid.uuid4().hex[:16]}"
        if source_account_number is None:
            source_account_number = PayloadGenerator.random_account_number()
        if destination_account_number is None:
            destination_account_number = PayloadGenerator.random_account_number()
        if device_id is None:
            device_id = PayloadGenerator.random_device_id()
        if source_document_number is None:
            source_document_number = RandomGenerator.generate_cpf()
        if ip is None:
            ip = source_ip(source_document_number, source_account_number)

        source = {
            "device_id": device_id,
            "channel": channel,
            "ip": ip,
        }
        if include_geolocation:
            source["geolocation"] = {"latitude": latitude, "longitude": longitude}

        source_account = {
            "branch": source_branch,
            "account_number": source_account_number,
            "opening_date": source_opening_date,
            "owner": {"document_number": source_document_number or RandomGenerator.generate_cpf()},
        }
        if source_participant:
            source_account["participant"] = source_participant

        return {
            "id": transaction_id,
            "amount": amount,
            "transaction_date": transaction_date,
            "source_account": source_account,
            "destination_account": {
                "participant": destination_participant,
                "branch": destination_branch,
                "account_number": destination_account_number,
                "opening_date": destination_opening_date,
                "owner": {"document_number": destination_document_number or RandomGenerator.generate_cpf()},
            },
            "source": source,
        }

    @staticmethod
    def create_person_link_payload(cpf: str, cnpj: str, relation: str = "PARTNER") -> dict:
        return {"cpf": cpf, "cnpj": cnpj, "relation": relation}
