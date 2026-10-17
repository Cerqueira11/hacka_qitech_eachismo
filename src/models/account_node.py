import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from models.base import Base


class AccountNode(Base):
    """Nó do grafo antifraude: uma conta transacional (ISPB + agência + conta)."""

    __tablename__ = "account_node"
    __table_args__ = (
        UniqueConstraint("participant", "branch", "account_number", name="uq_account_node_identity"),
        CheckConstraint("person_type IN ('PF', 'PJ')"),
    )

    id_account = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    participant = Column(String(8), nullable=False)
    branch = Column(String(4), nullable=False)
    account_number = Column(String(20), nullable=False)
    document_number = Column(String(14), nullable=False, index=True)
    person_type = Column(String(2), nullable=False)
    opening_date = Column(DateTime(timezone=True), nullable=True)
    external_risk = Column(Numeric(5, 4), nullable=False, default=0, server_default="0")
    risk_score = Column(Numeric(5, 4), nullable=False, default=0, server_default="0")
    degree = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
