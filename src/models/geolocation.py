import uuid
from sqlalchemy import Column, Numeric
from sqlalchemy.dialects.postgresql import UUID
from models.base import Base


class Geolocation(Base):
    """Representa coordenadas geográficas registradas para a transação."""

    __tablename__ = "geolocation"

    id_geolocation = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    longitude = Column(Numeric(11, 8), nullable=False)
    latitude = Column(Numeric(10, 8), nullable=False)
