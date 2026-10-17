class Singleton(type):
    """Metaclasse que faz uma classe ter uma instância só.

    HOJE NINGUÉM A USA. Confira com

        grep -rn Singleton tests/ src/

    e as únicas ocorrências são este arquivo. Ela vive aqui porque é o
    utilitário padrão dos projetos da QI e faz parte do andaime; não
    procure quem a chama.

    Se quiser entender: "metaclasse" é a classe de uma classe. O
    `__call__` abaixo roda quando alguém escreve `MinhaClasse()` — e,
    em vez de construir um objeto novo toda vez, ele guarda o primeiro
    num dicionário e devolve sempre o mesmo. É Python avançado, e não
    saber isso não te atrapalha em nada no resto do projeto.
    """

    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]
