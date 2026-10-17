import uuid
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import UUID
from models.base import Base


class Metadata(Base):
    """Representa a tabela metadata associada aos resultados de status."""

    __tablename__ = "metadata"

    key_metadata = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
