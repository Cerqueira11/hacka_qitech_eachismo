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
        """O score final e os motivos, sem os pesos de cada regra.

        Os pesos, os scores parciais e a evidência do grafo ficam gravados na
        tabela metadata para auditoria, mas não saem na resposta: expor quanto
        cada regra pesa ensina o fraudador a ficar logo abaixo do limiar.
        """
        dto = dict()
        if metadata is None:
            return dto
        if metadata.risk_score is not None:
            dto["risk_score"] = float(metadata.risk_score)
        # Sempre presente (lista vazia quando nenhuma regra acionou): quem
        # consome não precisa tratar a ausência do campo.
        reasons = []
        for hit in metadata.rule_hits or []:
            reason = hit.get("reason") or hit.get("rule")
            if reason not in reasons:
                reasons.append(reason)
        dto["reasons"] = reasons
        return dto
