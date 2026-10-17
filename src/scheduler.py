"""Agendador dos jobs (decisão 4.2: o projeto agenda, não a IF).

Roda num container próprio (serviço `scheduler` do docker-compose, ligado
só com `--profile scheduler`), reaproveitando o `jobs.runner`: cada job
abre e fecha o próprio contexto de banco, como na linha de comando.

    cd src && python scheduler.py

Horário de Brasília fixo em UTC−3 (o Brasil não tem horário de verão desde
2019). Não depende do fuso do container — a API também não: ela lê a hora
do Postgres (`now() AT TIME ZONE 'America/Sao_Paulo'`).

A rota `POST /job/{nome}` continua existindo para reprocessar na mão.
Todos os jobs são idempotentes, então rodar a mais nunca move dinheiro
duas vezes.
"""

import logging
import time
from datetime import datetime, timedelta, timezone

from jobs.runner import run

BRASILIA = timezone(timedelta(hours=-3))

# Diários, no horário de Brasília (HH, MM). A ordem importa: cobra as
# parcelas, fecha faturas, faz o débito automático (autopay) e só então
# marca o que sobrou como atrasado (overdue). Por fim, solta HOLDs.
DAILY = (
    ((0, 30), "collect_installments"),
    ((1, 0), "close_invoices"),
    ((1, 30), "run_invoice_autopay"),
    ((2, 0), "mark_overdue_invoices"),
    ((3, 0), "expire_authorizations"),
    # Abertura da janela do STR (6h30). O job só executa em dia útil.
    ((6, 30), "run_scheduled_teds"),
)

# Periódicos, em minutos.
EVERY_MINUTES = (
    (1, "dispatch_outbox_events"),
    (10, "reconcile_spi_str"),
)

logger = logging.getLogger("scheduler")


def safe_run(job_name: str) -> None:
    """Um job que falha não derruba o agendador: loga e segue."""
    try:
        result = run(job_name)
        logger.info(f"job {job_name}: {result}")
    except Exception as error:  # noqa: BLE001
        logger.error(f"job {job_name} failed: {error!r}")


def due_jobs(now: datetime, last_minute: datetime) -> list:
    """Jobs que devem rodar no minuto `now` (já truncado), uma vez só por minuto."""
    if now == last_minute:
        return []
    jobs = [name for (hour, minute), name in DAILY if (now.hour, now.minute) == (hour, minute)]
    minute_of_day = now.hour * 60 + now.minute
    jobs += [name for every, name in EVERY_MINUTES if minute_of_day % every == 0]
    return jobs


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logger.info("scheduler started (America/Sao_Paulo = UTC-3)")

    last_minute = None
    while True:
        now = datetime.now(BRASILIA).replace(second=0, microsecond=0)
        for job_name in due_jobs(now, last_minute):
            safe_run(job_name)
        last_minute = now
        time.sleep(5)


if __name__ == "__main__":
    main()
