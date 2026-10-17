from errors.base_error import QIException


class NotFoundPixTransaction(QIException):
    code = "QIT001015"

    def __init__(self, key_pix) -> None:
        title = "Pix Transaction not Found"
        http_status = 404
        description = f"Pix transaction with key {key_pix} was not found."
        translation = f"A transação PIX com identificador {key_pix} não foi encontrada."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidTransactionDate(QIException):
    code = "QIT001007"

    def __init__(self, message: str = "Invalid transaction date.") -> None:
        title = "Invalid Transaction Date"
        http_status = 422
        description = message
        translation = "A data da transação é inválida."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidDocumentNumber(QIException):
    code = "QIT001008"

    def __init__(self, field: str) -> None:
        title = "Invalid Document Number"
        http_status = 422
        description = f"The document number in '{field}' is not a valid CPF or CNPJ."
        translation = f"O documento em '{field}' não é um CPF ou CNPJ válido."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidOpeningDate(QIException):
    code = "QIT001009"

    def __init__(self, field: str) -> None:
        title = "Invalid Opening Date"
        http_status = 422
        description = f"The date in '{field}' must be ISO-8601 with timezone and not after transaction_date."
        translation = f"A data em '{field}' deve ser ISO-8601 com fuso horário e não pode ser posterior à transaction_date."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidIpAddress(QIException):
    code = "QIT001010"

    def __init__(self, ip: str) -> None:
        title = "Invalid IP Address"
        http_status = 422
        description = f"'{ip}' is not a valid IPv4 or IPv6 address."
        translation = f"'{ip}' não é um endereço IPv4 ou IPv6 válido."
        super().__init__(title, self.code, http_status, description, translation)
