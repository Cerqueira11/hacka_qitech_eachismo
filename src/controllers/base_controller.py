from abc import ABCMeta

from database import get_context
from utils.logger import get_logger


class BaseController(metaclass=ABCMeta):
    """O que todo controller tem em comum: a conexão com o banco e o log.

    Sobre o `metaclass=ABCMeta`: ele marca esta classe como ABSTRATA —
    a ideia de "não me instancie, me herde". Honestidade sobre o que
    está aqui: a marcação só passa a IMPEDIR alguma coisa quando algum
    método é decorado com `@abstractmethod`, e não há nenhum. Do jeito
    que está, `BaseController()` funcionaria. O que sobra é a intenção
    declarada em voz alta pra quem lê — que é o motivo de ela estar
    aqui, e não um mecanismo que te protege.

    Nada chega por parâmetro: o controller pega o CONTEXTO da requisição
    em que está rodando. Quem preparou esse contexto foi o middleware.

    Guardar o `self.context`, e não só a sessão, é o que permite o
    repository receber `context` em vez de `db`: o contexto é a coisa que
    viaja entre as camadas, e a sessão é só o que ele carrega hoje.

    É aqui que a sessão nasce, no `get_or_create_session` — construir um
    controller é a mesma coisa que dizer "eu uso banco".
    """

    def __init__(self, class_name: str) -> None:
        self.context = get_context()
        self.session = self.context.get_or_create_session()
        self.logger = get_logger(class_name)
