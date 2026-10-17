import functools
import json
import os

from jsonschema import RefResolver, ValidationError, validate

from constants import SCHEMA_PATH
from errors import InvalidSchema


class SchemaCache:
    """Guarda os schemas já lidos do disco, pra não reler a cada requisição.

    Um schema é um arquivo .json que não muda enquanto a API está no ar.
    Ler o disco a cada POST seria trabalho repetido — então a primeira
    requisição lê e guarda, e as próximas pegam daqui.

    O dicionário é de CLASSE, não de instância: existe um só, e ninguém
    precisa passar o cache adiante.
    """

    schemas = {}

    @staticmethod
    def get_schema(schema_file_name: str) -> dict:
        schema_path = os.path.join(SCHEMA_PATH, schema_file_name)

        if schema_path in SchemaCache.schemas:
            return SchemaCache.schemas[schema_path]

        if not os.path.isfile(schema_path):
            raise Exception(
                f"Nao encontrei o schema '{schema_file_name}' em {SCHEMA_PATH}. "
                + "Ou o arquivo nao existe, ou o nome escrito na rota esta diferente."
            )

        with open(schema_path, "r", encoding="utf-8") as arquivo:
            schema = json.loads(arquivo.read())

        SchemaCache.schemas[schema_path] = schema

        return schema


class SchemaHandler:
    """Confere o corpo da requisição contra um arquivo de schema.

    ────────────────────────────────────────────────────────────────
    POR QUE O CONTRATO DE ENTRADA É UM ARQUIVO JSON SCHEMA
    ────────────────────────────────────────────────────────────────
    O que esta API aceita no corpo de uma requisição está escrito em
    `src/schemas/*.json`, fora do código Python. O arquivo é
    DECLARATIVO: diz quais campos existem, de que tipo e quais são
    obrigatórios, sem nenhuma linha de execução no meio — dá pra ler o
    contrato inteiro sem saber o que o servidor faz com ele.

    Morar num arquivo à parte rende três coisas. Ele é VERSIONÁVEL: o
    diff mostra qual campo entrou, saiu ou mudou de tipo, então
    mudança de contrato aparece na revisão de código em vez de se
    esconder no meio da lógica. Ele é LEGÍVEL por quem não programa
    Python — produto, QA e quem integra leem o mesmo arquivo que o
    servidor cobra. E ele é PUBLICÁVEL: JSON Schema é um padrão que
    existe fora do Python, então este mesmo .json pode ser entregue a
    quem vai consumir a API, sem que a pessoa abra o repositório.

    Nos serviços da QI Tech o contrato de entrada é escrito assim, e a
    semelhança aqui é de propósito: o formato que você lê neste
    projeto é o que você vai encontrar lá.

    ────────────────────────────────────────────────────────────────
    O QUE ISSO CUSTA
    ────────────────────────────────────────────────────────────────
    O corpo chega como um dicionário cru, e não como um objeto com
    campos. Onde um objeto daria `payload.isbn`, aqui se escreve
    `payload["isbn"]` — e o editor não completa o nome do campo nem
    avisa se você digitar errado. O contrato mora fora do código:
    melhor pra quem integra, um pouco pior pra quem digita.
    """

    @staticmethod
    def validate(schema_file_name: str):
        """Decorator que valida o `payload` antes de o resource rodar.

        Usa-se assim, no método do resource que recebe corpo:

            class BookResource:
                @SchemaHandler.validate("post_book.json")
                def on_post(self, payload: dict) -> dict:

        O nome do arquivo é o único argumento, e ele aponta pra dentro
        de src/schemas/.

        Método que não recebe corpo não usa ESTE decorator — não há
        corpo a conferir. Mas pode usar o irmão dele, logo abaixo: o
        on_get_list é um GET sem corpo e leva
        @SchemaHandler.validate_query_params, que aplica a mesma ideia
        aos parâmetros do endereço.

        Repare que o endereço HTTP não aparece aqui. Quem liga
        "/book" a este método é o src/app.py, e é de propósito:
        o resource cuida do CONTEÚDO da requisição, o app.py cuida do
        ENDEREÇO dela.
        """

        # As três funções aninhadas abaixo são o que faz um DECORATOR.
        # Decorator é o `@alguma_coisa` escrito em cima de uma função:
        # ele embrulha a função original noutra, que roda ANTES dela.
        # É por isso que são três camadas e não uma:
        #
        #   validate(...)          recebe o nome do arquivo de schema
        #     decorator_validate   recebe a função da rota
        #       wrapper_validate   é quem de fato roda na requisição,
        #                          valida, e só então chama a rota
        #
        # O @functools.wraps copia nome e assinatura da função original
        # pro embrulho. Sem ele, toda rota decorada passaria a se
        # chamar "wrapper_validate" — e o FastAPI, que descobre os
        # parâmetros da rota lendo a assinatura, deixaria de enxergar
        # o `request`.
        def decorator_validate(func):
            @functools.wraps(func)
            def wrapper_validate(*args, **kwargs):
                if "payload" not in kwargs:
                    raise Exception(
                        f"A rota '{func.__name__}' foi decorada com o SchemaHandler, mas nao "
                        + "tem um parametro chamado 'payload'. E de la que sai o corpo a validar."
                    )

                schema = SchemaCache.get_schema(schema_file_name)
                resolver = RefResolver(f"file://{SCHEMA_PATH}/", None)

                try:
                    validate(kwargs["payload"], schema, resolver=resolver)
                except ValidationError as error:
                    raise InvalidSchema(describe_schema_error(error))

                return func(*args, **kwargs)

            return wrapper_validate

        return decorator_validate

    @staticmethod
    def validate_query_params(schema_file_name: str):
        """Decorator que valida a QUERY STRING antes de o resource rodar.

        Usa-se assim, num metodo que recebe a requisicao inteira:

            class BookResource:
                @SchemaHandler.validate_query_params("get_books.json")
                def on_get_list(self, request: Request) -> JSONResponse:

        Por que ler do `request` em vez dos argumentos da funcao: o
        FastAPI so entrega o que ele mesmo declarou. Um parametro com o
        nome errado — `?stauts=pending` — nunca chegaria aqui, e passaria
        batido como passa hoje em qualquer API que so declara o que
        conhece. Lendo a query string crua, o `additionalProperties:
        false` do schema pega o engano e responde dizendo o nome errado.

        O segundo detalhe e a LISTA. Na query string, `?status=a&status=b`
        e o mesmo campo repetido, e nada no texto diz se `?status=a`
        sozinho era pra ser lista de um ou valor unico. Quem sabe disso e
        o schema: o campo declarado como "type": "array" vem por
        `getlist`, o resto vem simples.
        """

        def decorator_validate(func):
            @functools.wraps(func)
            def wrapper_validate(*args, **kwargs):
                request = kwargs.get("request")
                if request is None:
                    raise Exception(
                        f"A rota '{func.__name__}' foi decorada com o validate_query_params, mas "
                        + "nao tem um parametro chamado 'request'. E de la que sai a query string."
                    )

                schema = SchemaCache.get_schema(schema_file_name)
                resolver = RefResolver(f"file://{SCHEMA_PATH}/", None)
                query_params = query_params_to_dict(request.query_params, schema)

                try:
                    validate(query_params, schema, resolver=resolver)
                except ValidationError as error:
                    raise InvalidSchema(describe_schema_error(error))

                return func(*args, **kwargs)

            return wrapper_validate

        return decorator_validate


def query_params_to_dict(query_params, schema: dict) -> dict:
    """A query string virada dicionario, com o schema dizendo o que e lista.

    Campo ausente nao entra: quem nao veio nao tem o que validar, e um
    None no lugar faria o schema reclamar de tipo por um filtro que a
    pessoa simplesmente nao usou.
    """
    properties = schema.get("properties", {})
    parsed_params = {}

    for param_name in query_params.keys():
        declared = properties.get(param_name, {})

        if declared.get("type") == "array":
            parsed_params[param_name] = query_params.getlist(param_name)
        else:
            parsed_params[param_name] = query_params[param_name]

    return parsed_params


def describe_schema_error(error: ValidationError) -> str:
    """Diz o que estava errado e ONDE, quando o campo é aninhado.

    O jsonschema já escreve uma boa mensagem ("'isbn' is a required
    property"), mas ela não diz em que parte do JSON o problema está.
    Para um campo na raiz isso não faz falta; para um campo dentro de
    uma lista dentro de um objeto, faz toda.
    """
    location = []
    for part in error.absolute_path:
        location.append(str(part))

    if location:
        return f"{error.message} in {'.'.join(location)}"

    return error.message
