from pathlib import Path
from os import path, environ

root = Path(__file__).resolve().parents[1]

if not environ.get("APP_ENV") or environ.get("APP_ENV") == "local":
    from dotenv import load_dotenv

    load_dotenv(path.join(str(root), ".env"))

    if environ.get("SERVER_LOCALHOST") is None:
        environ["SERVER_LOCALHOST"] = "0.0.0.0"


import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def reset_mockserver():
    """Começa cada sessão com o mockserver vazio.

    Os testes sorteiam documentos e devices, então não dependem disso para
    passar. Mas sem o reset as expectativas se acumulam a cada `pytest`, e
    toda requisição sem expectativa (o 404 de "pessoa limpa" no DICT) é
    comparada com todas elas.
    """
    # Importado aqui: o Mock lê MOCK_HOST/MOCK_PORT do ambiente, que o
    # load_dotenv acima já preencheu.
    from tests.utils.mock_utils import Mock

    Mock().clear()
    yield
