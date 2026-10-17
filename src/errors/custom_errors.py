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
