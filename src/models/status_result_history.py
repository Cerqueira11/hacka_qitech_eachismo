import uuid
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import relationship

from models.base import Base


class StatusResultHistory(Base):
    """Representa a tabela status_result_history com os vereditos de antifraude."""

    __tablename__ = "status_result_history"

    key = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key_pix = Column(BigInteger, ForeignKey("transaction_history.key_pix"), nullable=False)
    status = Column(
        ENUM("approved", "rejected", "two_factor_required", name="enum_status_result", create_type=False),
        nullable=False,
    )
    date = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    metadata_key = Column(UUID(as_uuid=True), ForeignKey("metadata.key_metadata"), nullable=True)

    transaction = relationship("TransactionHistory", back_populates="status_history")
    metadata_item = relationship("Metadata")
