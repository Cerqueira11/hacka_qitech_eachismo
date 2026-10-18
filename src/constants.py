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

# DICT (R4): estatísticas de fraude por documento em
# GET /persons/{TaxIdNumber}/statistics. Sem URL configurada o DICT conta
# como indisponível: a R4 pede 2FA, nunca aprova às cegas. No docker
# compose ele aponta para o mockserver.
DICT_API_URL = os.environ.get("DICT_API_URL", "").rstrip("/")
DICT_API_INTERNAL_TOKEN = os.environ.get("DICT_API_INTERNAL_TOKEN", "default_token")
# Timeout por consulta (segundos). Roda antes do lock, como a de dispositivo.
DICT_API_TIMEOUT = float(os.environ.get("DICT_API_TIMEOUT", "0.5"))

# API externa de dispositivo cadastrado (R1). Só é chamada quando o device
# não está em registered_device; o 200 é gravado lá. O motor lê só o
# campo booleano "registered" de GET /devices/{document_number}/{device_id}.
# Sem URL configurada a API conta como indisponível: a R1 pede 2FA, nunca
# aprova às cegas. No docker compose ela aponta para o mockserver.
DEVICE_API_URL = os.environ.get("DEVICE_API_URL", "").rstrip("/")
DEVICE_API_INTERNAL_TOKEN = os.environ.get("DEVICE_API_INTERNAL_TOKEN", "default_token")
# Timeout curto (segundos): a chamada roda antes do lock, mas ainda dentro
# do tempo de resposta que a IF espera da gente.
DEVICE_API_TIMEOUT = float(os.environ.get("DEVICE_API_TIMEOUT", "0.2"))

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
