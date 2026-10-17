# Decisões do time — revisão das pendências (09/10/2026)

Registro do que foi decidido sobre o relatório de pendências. A RFC está sujeita a
alteração; quando ela mudar, este arquivo diz o que o código assume hoje.

| # | Item | Decisão | Onde está no código |
| --- | --- | --- | --- |
| 3.1 | Limite volta acima da linha após redução | **Corrigido.** Disponível = `max(total_limit − saldo do patrimônio, 0)`, recalculado depois da quitação | `LoanController._apply`; teste `test_payment_after_lowering_does_not_reopen_limit_above_the_new_line` |
| 3.2 | Feriados | **Opção (a):** feriados nacionais (fixos + Carnaval, Sexta-feira Santa, Corpus Christi) no seed, 2026–2028. Estaduais e municipais ficam fora | `database/database.sql` (fim do arquivo) |
| 3.3 | `IF_WEBHOOK_*` | **Corrigido.** Repassadas no compose e documentadas no `.env.example`. Sem URL = modo mock | `docker-compose.yml`, `.env.example` |
| 3.4 | Helpers de teste escrevem data no banco | **Mantém a exceção.** Não criar `?today=` na API (seria uma porta para mexer no relógio em produção). Nenhuma asserção lê o banco | `tests/utils/object_generator.py` |
| 3.5 | Lint | **Limpeza pontual**, sem lint obrigatório/CI nesta entrega | — |
| 4.1 | D1, D2, D3 | **Mantidas** como na RFC (ver abaixo) | testes citados na RFC |
| 4.2 | Quem agenda os jobs | **O projeto agenda** (`src/scheduler.py`). A rota `POST /job/{nome}` fica para reprocessar na mão | `src/scheduler.py`, serviço `scheduler` do compose |
| 4.3 | Serviços externos | **Todos seguem mock** nesta entrega (KYC, DICT, SPI/STR, webhook da IF) | `src/utils/*_mock.py`, `IfWebhookConnector` |
| 4.4 | QIT001058 inalcançável | **Mantém como segunda defesa** (defesa em profundidade), sem teste black box possível hoje | `LoanController` |

## 4.1 — Premissas D1, D2 e D3

- **D1 — o teto de R$ 21 mil conta só o principal em aberto.** A Res. CMN 4.854/2020 limita o
  saldo devedor do tomador; juros pagos não são saldo. Ponto para o Jurídico confirmar: se
  juros *vencidos e não pagos* devem entrar no saldo (hoje não entram).
- **D2 — sociedade (LTDA/SLU) tem teto próprio; PF + EI/MEI somam.** EI/MEI não têm patrimônio
  separado da pessoa natural; sociedade tem.
- **D3 — base dos 100% do rotativo = `original_debt_amount`** (saldo da fatura no vencimento),
  conforme Lei 14.690/2023, art. 28.

## 4.2 — Agendamento (horário de Brasília, UTC−3)

| Horário | Job |
| --- | --- |
| 00:30 | `collect_installments` |
| 01:00 | `close_invoices` |
| 01:30 | `run_invoice_autopay` |
| 02:00 | `mark_overdue_invoices` |
| 03:00 | `expire_authorizations` |
| 06:30 | `run_scheduled_teds` (abertura do STR; só executa em dia útil) |
| a cada 1 min | `dispatch_outbox_events` |
| a cada 10 min | `reconcile_spi_str` |

O serviço fica num *profile* do compose: `docker compose up` (o de rodar os testes) **não** liga
o agendador, porque ele disputaria os itens que os testes de job contam. Para ligar:
`docker compose --profile scheduler up`.

## Pendências que seguem abertas

- **Teste instável (não reproduziu):** `tests/integration/job/test_jobs.py::TestDispatchOutbox::test_pending_events_are_delivered_once`
  foi relatado como falhando na suíte inteira. Em 10/10/2026 passou em duas suítes completas
  seguidas (191 passed, 3 skipped), com banco limpo e com banco já usado. A suíte roda um teste
  por vez, então "outros testes gerando eventos" não explica a falha. Se voltar a falhar,
  procurar `job item ... failed` no log da API: um evento que dá exceção no despacho fica
  `PENDING` sem somar tentativa e reaparece em toda execução. Com o agendador ligado
  (`--profile scheduler`), o teste pode falhar, porque o agendador também despacha. Desligue o
  agendador antes de rodar a suíte.
- **Windows:** o `tests/conftest.py` usa `0.0.0.0` como host da API, e no Windows isso não
  conecta. Rode com `SERVER_LOCALHOST=localhost` (no `.env` ou no terminal).
- **Documentação manual:** fluxos do draw.io (`fluxo-v8`, caminhos no plural) e a RFC
  (trecho "O agendamento é da IF" muda com a decisão 4.2).
