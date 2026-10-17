CPF_LENGTH = 11

CHECK_DIGIT_POSITIONS = [9, 10]


def is_valid_cpf(document_number: str) -> bool:
    """Diz se um CPF existe de verdade — não se ele tem a cara certa.

    O schema (src/schemas/post_author.json ou post_member.json) já cobrou o formato:
    onze dígitos arrumados em 000.000.000-00 — dois pontos e um hífen.
    Isto aqui é outra pergunta, e a diferença entre as duas é a lição
    deste arquivo.

    Os dois últimos dígitos de um CPF não são escolhidos: eles são o
    RESULTADO de uma conta feita sobre os nove primeiros. Por isso um
    número pode ter o formato perfeito e não existir — "111.222.333-44"
    passa no schema e não passa aqui.

    É o mesmo motivo pelo qual a resposta dessa recusa é 422 e não 400:
    não é que a API não conseguiu ler o pedido; ela leu, entendeu, e o
    valor não pode existir.

    A conta, para cada um dos dois dígitos: multiplica cada dígito
    anterior por um peso que decresce, soma tudo, tira o resto da divisão
    por 11. Resto menor que 2 vira dígito 0; nos outros casos, o dígito é
    11 menos o resto.
    """
    digits = []
    for character in document_number:
        if character.isdigit():
            digits.append(int(character))

    if len(digits) != CPF_LENGTH:
        return False

    # Um CPF de dígitos todos iguais ("111.111.111-11") passa na conta
    # dos dígitos verificadores e mesmo assim não vale. São dez números
    # conhecidos (um por dígito, de 000... a 999...), e a Receita não
    # emite nenhum deles.
    all_digits_are_equal = True
    for digit in digits:
        if digit != digits[0]:
            all_digits_are_equal = False
            break

    if all_digits_are_equal:
        return False

    for position in CHECK_DIGIT_POSITIONS:
        total = 0
        first_weight = position + 1

        for index in range(position):
            total = total + digits[index] * (first_weight - index)

        remainder = total % 11

        if remainder < 2:
            expected_digit = 0
        else:
            expected_digit = 11 - remainder

        if digits[position] != expected_digit:
            return False

    return True


CNPJ_LENGTH = 14
CNPJ_FIRST_WEIGHTS = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
CNPJ_SECOND_WEIGHTS = [6] + CNPJ_FIRST_WEIGHTS
DOCUMENT_MASK_CHARACTERS = ".-/ "


def normalize_document_number(document_number: str) -> str:
    """Tira a máscara ('123.456.789-09' -> '12345678909') e põe letras em maiúsculo.

    Letras ficam porque o CNPJ alfanumérico (IN RFB 2.229/2024) pode ter
    letras nas 12 primeiras posições.
    """
    cleaned = ""
    for character in document_number:
        if character not in DOCUMENT_MASK_CHARACTERS:
            cleaned = cleaned + character.upper()
    return cleaned


def _cnpj_check_digit(characters: str, weights: list) -> int:
    # No CNPJ alfanumérico o valor de cada caractere é o código ASCII menos 48:
    # '0'..'9' continuam valendo 0..9, 'A' vale 17, 'B' 18 e assim por diante.
    total = 0
    for character, weight in zip(characters, weights):
        total = total + (ord(character) - 48) * weight
    remainder = total % 11
    if remainder < 2:
        return 0
    return 11 - remainder


def is_valid_cnpj(document_number: str) -> bool:
    """Diz se um CNPJ (numérico ou alfanumérico) tem os dígitos verificadores certos."""
    cnpj = normalize_document_number(document_number)
    if len(cnpj) != CNPJ_LENGTH:
        return False

    body = cnpj[:12]
    check_digits = cnpj[12:]
    if not body.isalnum() or not body.isascii() or not check_digits.isdigit():
        return False
    if cnpj == cnpj[0] * CNPJ_LENGTH:
        return False

    first = _cnpj_check_digit(body, CNPJ_FIRST_WEIGHTS)
    second = _cnpj_check_digit(body + str(first), CNPJ_SECOND_WEIGHTS)
    return check_digits == f"{first}{second}"


def person_type_of(document_number: str):
    """'PF' para CPF válido, 'PJ' para CNPJ válido, None se não for nenhum dos dois."""
    normalized = normalize_document_number(document_number)
    if len(normalized) == CPF_LENGTH and normalized.isdigit() and is_valid_cpf(normalized):
        return "PF"
    if len(normalized) == CNPJ_LENGTH and is_valid_cnpj(normalized):
        return "PJ"
    return None
