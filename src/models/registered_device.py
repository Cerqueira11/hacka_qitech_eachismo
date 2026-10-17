from sqlalchemy import Column, DateTime, String, func

from models.base import Base


class RegisteredDevice(Base):
    """Dispositivo cadastrado por um cliente (CPF/CNPJ). Usado pela regra de dispositivo novo."""

    __tablename__ = "registered_device"

    document_number = Column(String(14), primary_key=True)
    device_id = Column(String(50), primary_key=True)
    registered_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
