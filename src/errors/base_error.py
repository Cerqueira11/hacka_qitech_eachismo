"""Os erros da API: o formato de toda resposta ruim, e a trava do start.

Este arquivo define UMA coisa e protege OUTRA.

A coisa que ele define é o `QIException`, lá embaixo: o formato de toda
resposta de erro que sai desta API. Qualquer erro — 400, 403, 404, 409,
422, 500 — sai com os mesmos cinco campos, sempre:

    title        o nome do erro, em inglês, pra quem programa
    description  o que aconteceu, com detalhe
    translation  a frase em português, pronta pra mostrar ao usuário
    code         o identificador estável (QIT000001, QIT001016, ...)
    http_status  o número do HTTP

Cinco campos e não um texto solto porque quem integra com a API precisa
programar em cima de ALGO. Se o combinado fosse a mensagem, mudar uma
palavra quebraria o cliente de alguém. O `code` existe pra ser o
contrato: ele nunca muda, e o texto pode melhorar à vontade.

Os erros genéricos (QIT000...) moram aqui — os que toda API tem. Os das
regras deste projeto (QIT001...) moram em custom_errors.py, ao lado.
"""
import sys
import inspect


def error_verification():
    """Derruba a aplicação no start se dois erros usarem o mesmo código.

    A coisa que este arquivo PROTEGE. Ela roda uma vez, na subida da
    API (veja src/app.py), e faz uma coisa incomum: olha o próprio
    código de dentro. O `inspect.getmembers` lista todas as classes já
    carregadas do pacote `errors`, separa as que herdam de QIException
    e confere se algum `code` aparece duas vezes. Se aparecer, levanta
    e a API NÃO SOBE.

    Parece exagero derrubar tudo por causa disso. Não é. Código
    repetido é o pior tipo de bug de contrato: nada quebra, nada
    reclama, e um cliente lá fora passa a tratar dois erros diferentes
    como se fossem o mesmo — descobrindo só quando o comportamento dele
    estiver errado em produção. Falhar no start é a forma mais barata
    de descobrir: custa trinta segundos de quem escreveu o código, em
    vez de uma investigação de quem nem sabia do problema.

    Experimente: dê a um erro de custom_errors.py um código que já
    existe e suba a API. Ela não sobe, e a mensagem diz quais duas
    classes brigaram.
    """
    clsmembers = inspect.getmembers(sys.modules["errors"], inspect.isclass)

    errors_dict = dict()
    for _class in clsmembers:
        class_name = _class[0]
        class_type = _class[1]
        is_custom_exception = False
        if issubclass(class_type, QIException) and class_name != "QIException":
            is_custom_exception = True

        if is_custom_exception:
            code = class_type.code
            if errors_dict.get(code) is not None:
                used_class_name = errors_dict[code]
                raise Exception(f"The code {code} is being used twice: In {class_name} and {used_class_name}")
            errors_dict[code] = class_name
    return


class QIException(Exception):
    """A mãe de todo erro desta API — o formato descrito lá em cima.

    Ninguém levanta esta classe direto. Cada erro concreto herda dela,
    fixa o próprio `code` como atributo de classe e preenche os outros
    quatro campos no __init__. Veja os exemplos aqui embaixo e, para os
    erros de negócio, o custom_errors.py.
    """

    def __init__(self, title, code, http_status, description, translation) -> None:
        self.title = title
        self.description = description
        self.translation = translation
        self.code = code
        self.http_status = http_status


class MethodNotAllowed(QIException):
    code = "QIT000405"

    def __init__(self) -> None:
        title = "Method not allowed"
        http_status = 405
        description = "The requested method is forbidden for this resource."
        translation = "O método desejado não foi encontrado para esse recurso."
        super().__init__(title, self.code, http_status, description, translation)


class InternalError(QIException):
    code = "QIT000500"

    def __init__(self) -> None:
        title = "Internal Error"
        http_status = 500
        description = "An internal error has occurred and its being investigated."
        translation = "Um erro interno aconteceu e está sendo investigado."
        super().__init__(title, self.code, http_status, description, translation)


class NotFoundResource(QIException):
    code = "QIT000404"

    def __init__(self) -> None:
        title = "Resource not Found"
        http_status = 404
        description = "The requested resource could not be found but may be available in the future. Subsequent requests by the client are permissible."
        translation = "O resource solicitado não pode ser encontrado, mas pode estar disponível no futuro. Requests subsequentes do cliente são permitidos."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidSchema(QIException):
    code = "QIT000001"

    def __init__(self, __description) -> None:
        title = "Bad Request"
        http_status = 400
        description = __description
        translation = "Payload Inválido"
        super().__init__(title, self.code, http_status, description, translation)


class ForbiddenNotInternal(QIException):
    code = "QIT000002"

    def __init__(self) -> None:
        title = "Forbidden"
        http_status = 403
        description = "Request must be internal"
        translation = "Requisição precisa ser interna"
        super().__init__(title, self.code, http_status, description, translation)


class InvalidParameter(QIException):
    code = "QIT000010"

    def __init__(self, description) -> None:
        title = "Invalid Parameter"
        http_status = 400
        translation = "Parâmetros inválidos foram fornecidos na requisição."
        super().__init__(title, self.code, http_status, description, translation)
