from sqlalchemy import Column, DateTime, String, func

from models.base import Base


class PersonLink(Base):
    """Vínculo CPF <-> CNPJ (sócio, MEI/EI, administrador). Fonte: Receita/KYC, não o DICT."""

    __tablename__ = "person_link"

    cpf = Column(String(11), primary_key=True)
    cnpj = Column(String(14), primary_key=True, index=True)
    relation = Column(String(20), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
