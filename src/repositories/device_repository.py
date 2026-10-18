from sqlalchemy import exists
from sqlalchemy.dialects.postgresql import insert

from database import Context
from models import RegisteredDevice


class DeviceRepository:
    """registered_device: cache interno dos dispositivos que a API externa já confirmou (R1).

    Só o motor lê e grava aqui; não existe rota para o usuário consultar ou
    cadastrar. Quem põe um dispositivo nesta tabela é a resposta 200 da API
    de dispositivo, nunca o cliente.
    """

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def is_registered(self, document_number: str, device_id: str) -> bool:
        return self.session.query(
            exists().where(
                RegisteredDevice.document_number == document_number,
                RegisteredDevice.device_id == device_id,
            )
        ).scalar()

    def save(self, document_number: str, device_id: str) -> None:
        """Grava o dispositivo confirmado pela API. Já existir não é erro: dois
        Pix simultâneos do mesmo device podem confirmar ao mesmo tempo."""
        statement = (
            insert(RegisteredDevice)
            .values(document_number=document_number, device_id=device_id)
            .on_conflict_do_nothing()
        )
        self.session.execute(statement)
