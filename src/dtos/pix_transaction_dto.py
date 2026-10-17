from typing import Optional

from models import Metadata, StatusResultHistory, TransactionHistory


class PixTransactionDTO:
    """Traduz o veredito de uma transação PIX para o contrato de saída.

    Saída: {"key": <uuid do veredito>, "status": <approved|rejected|two_factor_required>, "metadata": {...}}
    """

    @staticmethod
    def obj_to_dict(transaction: TransactionHistory) -> dict:
        # status_history vem ordenado do mais novo para o mais antigo.
        latest = transaction.status_history[0]
        return PixTransactionDTO.verdict_to_dict(latest)

    @staticmethod
    def verdict_to_dict(verdict: StatusResultHistory) -> dict:
        return {
            "key": str(verdict.key),
            "status": verdict.status,
            "metadata": PixTransactionDTO.metadata_to_dict(verdict.metadata_item),
        }

    @staticmethod
    def metadata_to_dict(metadata: Optional[Metadata]) -> dict:
        """Só entra no metadata o que a análise de fato preencheu.

        Enquanto as regras não estão ligadas, nada é preenchido e o
        metadata sai como {}.
        """
        dto = dict()
        if metadata is None:
            return dto
        if metadata.risk_score is not None:
            dto["risk_score"] = float(metadata.risk_score)
        if metadata.rule_hits:
            dto["reasons"] = [hit.get("reason") or hit.get("rule") for hit in metadata.rule_hits]
        return dto
