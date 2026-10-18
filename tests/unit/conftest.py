"""Testes de unidade: importam o código de src/ direto, sem API nem banco."""

import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# database.py cria o engine ao ser importado (criar não conecta). Sem
# DATABASE_URL no ambiente, importa com um endereço de mentira e devolve o
# ambiente como estava: os testes de integração da mesma rodada não podem
# herdar esse endereço.
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "postgresql+psycopg2://unit:unit@localhost:5432/unit"
    try:
        import database  # noqa: F401
    finally:
        del os.environ["DATABASE_URL"]
