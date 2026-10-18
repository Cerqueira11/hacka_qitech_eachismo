from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Identity, Numeric, String, func
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import relationship

from models.base import Base


class TransactionHistory(Base):
    """Aresta do grafo antifraude: um Pix da conta de origem para a conta de destino."""

    __tablename__ = "transaction_history"

    key_pix = Column(BigInteger, Identity(always=True), primary_key=True)
    transaction_id = Column(String(64), nullable=False, unique=True)
    amount = Column(BigInteger, nullable=False)
    source_account_id = Column(UUID(as_uuid=True), ForeignKey("account_node.id_account"), nullable=False)
    destination_account_id = Column(UUID(as_uuid=True), ForeignKey("account_node.id_account"), nullable=False)
    source_device_id = Column(String(50), nullable=False)
    source_device_channel = Column(String(50), nullable=False)
    source_ip = Column(INET, nullable=False)
    source_geolocation = Column(UUID(as_uuid=True), ForeignKey("geolocation.id_geolocation"), nullable=True)
    risk_score = Column(Numeric(5, 4), nullable=True)
    # SHA-256 do payload normalizado (C4). NULL só em linhas anteriores à v2.
    payload_sha256 = Column(String(64), nullable=True)
    # Resposta da API de dispositivo no momento do Pix (S2); NULL = indisponível.
    device_registered = Column(Boolean, nullable=True)
    transaction_date = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    source_account = relationship("AccountNode", foreign_keys=[source_account_id], lazy="selectin")
    destination_account = relationship("AccountNode", foreign_keys=[destination_account_id], lazy="selectin")
    geolocation = relationship("Geolocation", foreign_keys=[source_geolocation], lazy="selectin")
    status_history = relationship(
        "StatusResultHistory",
        back_populates="transaction",
        order_by="desc(StatusResultHistory.date)",
        lazy="selectin",
    )
