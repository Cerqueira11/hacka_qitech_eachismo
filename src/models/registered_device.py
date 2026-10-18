from sqlalchemy import Column, DateTime, String, func

from models.base import Base


class RegisteredDevice(Base):
    """Cache interno da R1: dispositivo que a API externa já confirmou para o titular (CPF/CNPJ).

    Gravado só pelo motor (resposta 200 da API). Não há rota para o usuário consultar ou cadastrar.
    """

    __tablename__ = "registered_device"

    document_number = Column(String(14), primary_key=True)
    device_id = Column(String(50), primary_key=True)
    registered_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
