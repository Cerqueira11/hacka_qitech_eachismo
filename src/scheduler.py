"""Agendador dos jobs.

Roda num container próprio (serviço `scheduler` do docker-compose, ligado
só com `--profile scheduler`).

Horário de Brasília fixo em UTC−3 (o Brasil não tem horário de verão desde
2019).
"""

import logging
import time
from datetime import datetime, timedelta, timezone

BRASILIA = timezone(timedelta(hours=-3))

# Jobs diários e periódicos (podem ser definidos conforme novas necessidades)
DAILY = ()
EVERY_MINUTES = ()

logger = logging.getLogger("scheduler")


def safe_run(job_name: str) -> None:
    """Executa um job de forma segura sem derrubar o agendador."""
    try:
        logger.info(f"Executando job: {job_name}")
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
