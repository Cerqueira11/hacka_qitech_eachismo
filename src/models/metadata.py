import uuid

from sqlalchemy import Column, DateTime, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from models.base import Base


class Metadata(Base):
    """O porquê de um veredito: scores e regras acionadas."""

    __tablename__ = "metadata"

    key_metadata = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    risk_score = Column(Numeric(5, 4), nullable=True)
    rules_score = Column(Numeric(5, 4), nullable=True)
    graph_source_score = Column(Numeric(5, 4), nullable=True)
    graph_destination_score = Column(Numeric(5, 4), nullable=True)
    # default=list (callable) para não compartilhar a mesma lista entre instâncias
    rule_hits = Column(JSONB, nullable=False, default=list, server_default="[]")
    graph_evidence = Column(JSONB, nullable=False, default=list, server_default="[]")
    engine_version = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
