from fastapi import FastAPI

from constants import check_variables
from errors import register_error_handlers
from errors.base_error import error_verification
from middlewares import (
    register_internal_token_middleware,
    register_request_context_middleware,
    register_request_logger_middleware,
    register_session_manager_middleware,
)
from resources import (
    AccountResource,
    CardAuthorizationResource,
    CardResource,
    CreditWalletResource,
    CustomerResource,
    HealthCheckResource,
    InvoiceResource,
    JobResource,
    LoanResource,
    PixResource,
    TedResource,
    TransferResource,
    WebhookResource,
)
from utils.logger import setup_logging


def create_app() -> FastAPI:
    """Monta a aplicação, peça por peça.

    Os três blocos abaixo seguem a ordem em que a requisição encontra
    cada um — de fora pra dentro:
      1. os middlewares    — o que acontece com TODA requisição
      2. as rotas          — o que a API sabe responder
      3. os error handlers — como cada erro vira uma resposta

    Essa ordem serve pra leitura, não é exigência: o FastAPI monta a
    pilha de middlewares na primeira requisição que chega, então
    registrar rota antes ou depois de middleware dá no mesmo. Só a
    ordem DENTRO do bloco de middlewares tem consequência, e ela está
    explicada logo abaixo.
    """
    # Os três None desligam a documentação automática: o FastAPI sabe
    # gerar sozinho umas páginas descrevendo a API, e aqui elas não
    # existem. Pra ver o que cada rota responde, mande uma requisição —
    # tem exemplo pronto de cada uma no README.
    application = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    # ────────────────────────────────────────────────────────────────
    # Os middlewares — e a ordem deles, que é regra e não gosto
    # ────────────────────────────────────────────────────────────────
    # Middleware é uma camada por fora da aplicação: toda requisição
    # atravessa todas elas na ida, e todas de novo na volta. São como
    # cascas de cebola, e o ÚLTIMO registrado é a casca de FORA.
    #
    # Ou seja: destas quatro linhas, a de BAIXO é a primeira que a
    # requisição encontra, e a de CIMA é a última. Lendo de fora para
    # dentro, acontece isto:
    #
    #     requisição chega
    #           ↓
    #     request_context   dá um identificador único a esta requisição
    #           ↓
    #     request_logger    escreve "ENTROU" e, na volta, "SAIU"
    #           ↓
    #     internal_token    confere o INTERNAL-TOKEN. Sem ele, para aqui
    #           ↓
    #     session_manager   cuida da sessão de banco: desfaz se deu
    #           ↓           errado, fecha sempre — e nunca salva
    #           ↓
    #     as rotas
    #
    # Cada posição tem um porquê, e trocar duas linhas muda o que a API
    # faz:
    #
    # • O identificador vem ANTES do log: se viesse depois, as linhas de
    #   log da requisição sairiam sem o nome dela, e o middleware
    #   existiria para nada.
    # • O log vem ANTES do token: assim a tentativa recusada com 403
    #   também aparece no log — e essa é justamente a que você quer ver,
    #   porque mil delas seguidas é alguém tentando adivinhar o token.
    # • A sessão de banco fica por DENTRO do token, encostada nas
    #   rotas: quem não passou na porta leva 403 na camada de cima e não
    #   chega a ter uma sessão. É o mais interno de propósito — banco é
    #   o recurso mais caro desta lista, e o último que se empresta.
    #
    # Nada disso é teoria, e dá pra ver com os olhos. Troque as duas
    # últimas linhas de lugar (o identificador passa a ser registrado
    # antes do log, ou seja, a executar DEPOIS dele), chame qualquer
    # rota e olhe o log:
    #
    #     docker compose logs api | grep request_logger | tail -2
    #
    # (O grep é necessário: sem ele o tail pega a linha de acesso do
    # uvicorn, que é outra coisa e não passa por este middleware.)
    #
    # As duas linhas saem com [-] no lugar do identificador: o log
    # aconteceu antes de existir um nome para aquela requisição. Desfaça
    # a troca e o nome volta.
    #
    # Repare no que essa experiência tem de incômodo: a suíte continua
    # TODA VERDE com a ordem trocada. Nenhum teste aqui guarda esta
    # ordem — o preço aparece no dia do incidente, quando o log não
    # servir pra achar a requisição. Teste que não existe não avisa
    # nada, e é por isso que este comentário existe.
    #
    # ATENÇÃO, e é aqui que quase todo mundo tropeça: as quatro linhas
    # abaixo são o DIAGRAMA ACIMA DE TRÁS PRA FRENTE. O FastAPI embrulha
    # a aplicação de dentro pra fora, então o ÚLTIMO registrado é o
    # PRIMEIRO a executar. Leia de baixo pra cima e o diagrama volta.
    register_session_manager_middleware(application)
    register_internal_token_middleware(application)
    register_request_logger_middleware(application)
    register_request_context_middleware(application)

    # ────────────────────────────────────────────────────────────────
    # As rotas — o endereço, o verbo, e quem atende
    # ────────────────────────────────────────────────────────────────
    # Cada linha liga um endereço a um método de um resource. É a lista
    # COMPLETA do que esta API atende: rota que não está aqui não
    # existe, e não há um segundo lugar para procurar.
    #
    # Nos serviços da QI o framework é o Falcon, que descobre o método
    # pelo nome — chegou um POST, ele procura um `on_post`, e o registro
    # é uma linha por ENDEREÇO. O FastAPI não faz essa descoberta, então
    # aqui é uma linha por endereço E verbo. Custa mais linhas; em troca,
    # não existe rota que atenda sem estar escrita nesta lista.
    #
    # Repare no que NÃO está escrito aqui: o status de cada resposta.
    # 201, 202, 204 — todos saem de dentro do resource, que é quem sabe
    # se a coisa foi criada, agendada ou concluída. Esta lista diz QUEM
    # atende cada endereço, e mais nada.
    health_check_resource = HealthCheckResource()

    application.add_api_route("/", health_check_resource.on_get_home, methods=["GET"])
    application.add_api_route(
        "/health_check",
        health_check_resource.on_get_health_check,
        methods=["GET"]
    )

    # ────────────────────────────────────────────────────────────────
    # Conta digital + microcrédito — contrato em docs/api-contract.md
    # ────────────────────────────────────────────────────────────────
    customer_resource = CustomerResource()
    account_resource = AccountResource()
    transfer_resource = TransferResource()
    webhook_resource = WebhookResource()
    pix_resource = PixResource()
    ted_resource = TedResource()
    wallet_resource = CreditWalletResource()
    card_resource = CardResource()
    authorization_resource = CardAuthorizationResource()
    loan_resource = LoanResource()
    invoice_resource = InvoiceResource()
    job_resource = JobResource()

    # A · Clientes e contas
    application.add_api_route("/customer", customer_resource.on_post, methods=["POST"])
    application.add_api_route("/customer/{customer_key}", customer_resource.on_get_by_id, methods=["GET"])
    application.add_api_route("/customer/{customer_key}", customer_resource.on_patch_by_id, methods=["PATCH"])
    application.add_api_route(
        "/customer/{customer_key}/account", customer_resource.on_post_account, methods=["POST"]
    )
    application.add_api_route(
        "/customer/{customer_key}/account", customer_resource.on_get_accounts, methods=["GET"]
    )
    application.add_api_route(
        "/customer/{customer_key}/relationship", customer_resource.on_post_relationship, methods=["POST"]
    )
    application.add_api_route("/account/{account_key}", account_resource.on_get_by_id, methods=["GET"])
    application.add_api_route("/account/{account_key}/status", account_resource.on_patch_status, methods=["PATCH"])
    application.add_api_route("/account/{account_key}/statement", account_resource.on_get_statement, methods=["GET"])

    # B · Microcrédito — linha do patrimônio, contratação e pagamento
    application.add_api_route(
        "/customer/{customer_key}/credit_line", customer_resource.on_put_credit_line, methods=["PUT"]
    )
    application.add_api_route(
        "/customer/{customer_key}/credit_line", customer_resource.on_get_credit_line, methods=["GET"]
    )
    application.add_api_route(
        "/account/{account_key}/loan/simulation", loan_resource.on_post_simulation, methods=["POST"]
    )
    application.add_api_route("/account/{account_key}/loan", loan_resource.on_post, methods=["POST"])
    application.add_api_route("/account/{account_key}/loan", loan_resource.on_get_by_account, methods=["GET"])
    application.add_api_route("/loan/{loan_key}", loan_resource.on_get_by_id, methods=["GET"])
    application.add_api_route("/loan/{loan_key}/payment", loan_resource.on_post_payment, methods=["POST"])

    # C · Transferências
    application.add_api_route("/transfer", transfer_resource.on_post, methods=["POST"])
    application.add_api_route("/transfer/{transfer_key}", transfer_resource.on_get_by_id, methods=["GET"])
    application.add_api_route("/account/{account_key}/transfer", account_resource.on_get_transfers, methods=["GET"])
    application.add_api_route("/transfer/{transfer_key}/cancel", transfer_resource.on_patch_cancel, methods=["PATCH"])
    application.add_api_route("/webhook/spi", webhook_resource.on_post_spi, methods=["POST"])
    application.add_api_route("/webhook/str", webhook_resource.on_post_str, methods=["POST"])

    # C2 · Pix e TED — rotas por trilho, aninhadas na conta, como na QI
    # (/account/{key}/pix_transfer, /account/{key}/ted). A tabela é uma só.
    application.add_api_route("/account/{account_key}/pix_key", pix_resource.on_post_key, methods=["POST"])
    application.add_api_route("/account/{account_key}/pix_key", pix_resource.on_get_keys, methods=["GET"])
    application.add_api_route(
        "/account/{account_key}/pix_key/{pix_key_key}", pix_resource.on_delete_key, methods=["DELETE"]
    )
    application.add_api_route("/pix_key/{pix_key}", pix_resource.on_get_lookup, methods=["GET"])
    application.add_api_route("/account/{account_key}/pix_transfer", pix_resource.on_post_transfer, methods=["POST"])
    application.add_api_route(
        "/account/{account_key}/incoming_transfer/{incoming_transfer_key}/reversal",
        pix_resource.on_post_reversal,
        methods=["POST"],
    )
    application.add_api_route("/account/{account_key}/ted_transfer", ted_resource.on_post, methods=["POST"])

    # D · Cartões e faturas — carteira (QI wallet) separada do cartão
    application.add_api_route("/account/{account_key}/credit_wallet", wallet_resource.on_post, methods=["POST"])
    application.add_api_route("/credit_wallet/{wallet_key}", wallet_resource.on_get_by_id, methods=["GET"])
    application.add_api_route("/credit_wallet/{wallet_key}/limit", wallet_resource.on_patch_limit, methods=["PATCH"])
    application.add_api_route("/credit_wallet/{wallet_key}/status", wallet_resource.on_patch_status, methods=["PATCH"])
    application.add_api_route("/credit_wallet/{wallet_key}/invoice", wallet_resource.on_get_invoices, methods=["GET"])
    application.add_api_route("/invoice/{invoice_key}", wallet_resource.on_get_invoice, methods=["GET"])
    application.add_api_route("/invoice/{invoice_key}/payment", invoice_resource.on_post_payment, methods=["POST"])
    application.add_api_route("/invoice/{invoice_key}/charge", invoice_resource.on_post_charge, methods=["POST"])
    application.add_api_route("/account/{account_key}/card", card_resource.on_post, methods=["POST"])
    application.add_api_route("/account/{account_key}/card", card_resource.on_get_by_account, methods=["GET"])
    application.add_api_route("/card/{card_key}", card_resource.on_get_by_id, methods=["GET"])
    application.add_api_route("/card/{card_key}/activate", card_resource.on_patch_activate, methods=["PATCH"])
    application.add_api_route("/card/{card_key}/status", card_resource.on_patch_status, methods=["PATCH"])

    # D2 · Rede de cartão (papel da processadora). Autorização: 200 sempre.
    application.add_api_route("/card/authorization", authorization_resource.on_post, methods=["POST"])
    application.add_api_route(
        "/card/authorization/{authorization_key}", authorization_resource.on_get, methods=["GET"]
    )
    application.add_api_route(
        "/card/authorization/{authorization_key}/increment",
        authorization_resource.on_post_increment,
        methods=["POST"],
    )
    application.add_api_route(
        "/card/authorization/{authorization_key}/reversal",
        authorization_resource.on_post_reversal,
        methods=["POST"],
    )
    application.add_api_route("/card/captures", authorization_resource.on_post_capture, methods=["POST"])
    application.add_api_route("/card/refunds", authorization_resource.on_post_refund, methods=["POST"])

    # E · Jobs agendados. Quem agenda é o src/scheduler.py (serviço
    # `scheduler` do compose); esta rota fica para reprocessar na mão.
    # Pela linha de comando: `python -m jobs.<nome>`.
    application.add_api_route("/job/{job_name}", job_resource.on_post, methods=["POST"])

    register_error_handlers(application)

    return application


def main() -> FastAPI:
    # Não deixa a API subir com configuração faltando: é melhor falhar
    # agora, na hora de ligar, do que na cara do cliente mais tarde.
    check_variables()
    error_verification()
    setup_logging()

    return create_app()


app = main()
