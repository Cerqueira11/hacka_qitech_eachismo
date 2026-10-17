from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import relationship

from models.base import Base


class TransactionHistory(Base):
    """Representa a tabela transaction_history descrita no banco."""

    __tablename__ = "transaction_history"

    key_pix = Column(BigInteger, primary_key=True, autoincrement=True)
    amount = Column(BigInteger, nullable=False)
    source_account_branch = Column(Integer, nullable=False)
    source_account_number = Column(Integer, nullable=False)
    destination_account_branch = Column(Integer, nullable=False)
    destination_account_number = Column(Integer, nullable=False)
    source_device_id = Column(String(50), nullable=False)
    source_device_channel = Column(String(50), nullable=False)
    source_ip = Column(INET, nullable=False)
    source_geolocation = Column(UUID(as_uuid=True), ForeignKey("geolocation.id_geolocation"), nullable=True)
    transaction_date = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    geolocation = relationship("Geolocation", foreign_keys=[source_geolocation], lazy="selectin")
    status_history = relationship(
        "StatusResultHistory",
        back_populates="transaction",
        order_by="desc(StatusResultHistory.date)",
        lazy="selectin",
    )
