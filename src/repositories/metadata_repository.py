from typing import Optional

from database import Context
from models import Metadata


class MetadataRepository:
    """A camada que fala com a tabela metadata (o porquê de cada veredito)."""

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def create(
        self,
        risk_score: Optional[float] = None,
        rules_score: Optional[float] = None,
        graph_source_score: Optional[float] = None,
        graph_destination_score: Optional[float] = None,
        rule_hits: Optional[list] = None,
        graph_evidence: Optional[list] = None,
        engine_version: Optional[str] = None,
    ) -> Metadata:
        metadata = Metadata(
            risk_score=risk_score,
            rules_score=rules_score,
            graph_source_score=graph_source_score,
            graph_destination_score=graph_destination_score,
            rule_hits=rule_hits or [],
            graph_evidence=graph_evidence or [],
            engine_version=engine_version,
        )
        self.session.add(metadata)
        return metadata
