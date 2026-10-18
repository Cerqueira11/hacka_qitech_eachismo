import os


SERVICE_ROOT = os.path.abspath(os.path.dirname(__file__))

# Onde moram os arquivos de schema — os .json que descrevem o formato
# que cada requisicao precisa ter. Quem le essa pasta e o
# src/utils/schema_handler.py.
SCHEMA_PATH = os.path.join(SERVICE_ROOT, "schemas")

APP_ENV = os.environ.get("APP_ENV", "local")
SERVICE_NAME = os.environ.get("SERVICE_NAME", "bootcamp-api")

DATABASE_URL = os.environ.get("DATABASE_URL")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN")

# ISPB desta instituição. A conta de origem de todo Pix analisado aqui é
# nossa, então o payload não manda o participante dela: ele vem daqui.
# É parte da identidade do nó no grafo (ISPB + agência + conta). O padrão
# "00000000" é só para rodar localmente; configure o ISPB real no ambiente.
INSTITUTION_ISPB = os.environ.get("INSTITUTION_ISPB", "00000000")

# Arquivo com as respostas do DICT simulado (personas de demonstração).
# É lido a cada consulta, então editar o arquivo vale na hora, sem reiniciar.
DICT_MOCK_FILE = os.environ.get("DICT_MOCK_FILE", os.path.join(SERVICE_ROOT, "mocks", "dict_mock.json"))

# Liga a impressao de TODO SQL que o SQLAlchemy emite. Serve pra
# responder "que consulta esse repository virou, afinal?" sem abrir o
# banco do lado. Quem lê isto é o src/utils/logger.py, e o porquê de
# nao ser o `echo=True` do create_engine esta explicado la.
#
# Padrao desligado: em producao isso escreveria uma linha de log por
# comando, incluindo os valores enviados.
DATABASE_ECHO = os.environ.get("DATABASE_ECHO", "false").lower() == "true"

# Rotas públicas: não exigem o header INTERNAL-TOKEN. São as duas que
# precisam responder pra quem ainda não tem token nenhum: a raiz, que
# diz quem é este serviço, e o health check, que o Docker consulta pra
# saber se a API já está de pé.
BYPASS_ENDPOINTS = [
    "/",
    "/health_check",
]

REQUIRED_VARIABLES = ["DATABASE_URL", "INTERNAL_TOKEN"]


def check_variables():
    missing = []
    for name in REQUIRED_VARIABLES:
        if not globals().get(name):
            missing.append(name)

    if missing:
        raise EnvironmentError(
            f"Faltam variáveis de ambiente: {', '.join(missing)}. "
            "Rodando com 'docker compose up' elas já vêm preenchidas. "
            "Fora do Docker, copie o .env.example para .env."
        )
