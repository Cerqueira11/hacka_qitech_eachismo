import random


class RandomGenerator:
    @staticmethod
    def generate_isbn():
        """Um ISBN-13 com o formato certo: 978 e mais dez dígitos.

        Só o formato — os treze dígitos que o schema cobra. O dígito
        verificador não é calculado, porque esta API não confere a conta:
        quem diz se o ISBN existe é o catálogo.
        """
        digits = "".join(str(random.randrange(10)) for _ in range(10))
        return f"978{digits}"

    @staticmethod
    def generate_cpf():
        """Um CPF que existe, já com a máscara 000.000.000-00.

        Nove dígitos sorteados e os dois verificadores calculados pela
        mesma conta que a API confere: cada dígito anterior vezes um peso
        que decresce, a soma, o resto por 11; resto menor que 2 vira 0, e
        nos outros casos o dígito é 11 menos o resto. A conta está escrita
        aqui de novo, e não importada: o teste não enxerga o `src/`.

        Nove dígitos iguais são sorteados de novo: a Receita não emite
        CPF de dígitos todos iguais, e a API recusa esses números.
        """
        all_digits_are_equal = True
        while all_digits_are_equal:
            digits = []
            for _position in range(9):
                digits.append(random.randrange(10))

            all_digits_are_equal = True
            for digit in digits:
                if digit != digits[0]:
                    all_digits_are_equal = False
                    break

        for position in [9, 10]:
            total = 0
            first_weight = position + 1

            for index in range(position):
                total = total + digits[index] * (first_weight - index)

            remainder = total % 11

            if remainder < 2:
                digits.append(0)
            else:
                digits.append(11 - remainder)

        cpf_number = ""
        for digit in digits:
            cpf_number = cpf_number + str(digit)

        return f"{cpf_number[0:3]}.{cpf_number[3:6]}.{cpf_number[6:9]}-{cpf_number[9:11]}"

    @staticmethod
    def generate_cnpj():
        cnpj = [random.randrange(10) for _ in range(8)] + [0, 0, 0, 1]

        for _ in range(2):
            value = sum(v * (i % 8 + 2) for i, v in enumerate(reversed(cnpj)))
            digit = 11 - value % 11
            cnpj.append(digit if digit < 10 else 0)

        cnpj_number = "".join(str(x) for x in cnpj)

        cnpj_number = (
            f"{cnpj_number[0:2]}.{cnpj_number[2:5]}.{cnpj_number[5:8]}/{cnpj_number[8:12]}-{cnpj_number[12:14]}"
        )

        return cnpj_number
