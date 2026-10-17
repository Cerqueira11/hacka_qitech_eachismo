# Contrato de API — Conta digital + microcrédito (schema v7)

Fonte da verdade das rotas do time. Quando o código e este arquivo
discordarem, um dos dois está errado — conserte no mesmo PR.

Stack e camadas: as do projeto base (`docs/como-o-projeto-e-organizado.md`).
Identificadores em inglês; descrições em pt-BR. Termos regulatórios
mantidos: CPF, CNPJ, MEI, PIX, TED, TEF, SPI, STR, ISPB, KYC, PEP.

As 51 rotas abaixo estão no `src/app.py` e cobertas pelos testes black box de `tests/integration/`.
Identificadores no caminho (`{customer_key}`, `{account_key}`…) e os `*_id` dos corpos são a
`key` UUID pública da entidade; o `id` numérico do banco nunca sai da API.

---

## Convenções transversais

| Tema | Regra |
|---|---|
| Autenticação | Header `INTERNAL-TOKEN` em todas as rotas (padrão do projeto base). Sem ele: 403 `QIT000002` |
| Rastreio | `X-Request-ID` em toda resposta (middleware do projeto base) |
| Formato do erro | `{"title", "description", "translation", "code"}` — o envelope do projeto base |
| Validação | Formato errado (JSON Schema): **400** `QIT000001`. Valor impossível ou regra de negócio: **422**. Conflito com o estado atual: **409** |
| Idempotência | `Idempotency-Key` obrigatório em todo POST que move dinheiro, no formato **UUID v4** (como o `request_control_key` da QI). Ausente/malformado → 400 `QIT001015`. A resposta ecoa o valor em `request_control_key`. Mesma key + mesmo corpo (SHA-256 canônico) → **200** com a resposta original. Mesma key + corpo diferente → 409 `QIT001016` |
| Dinheiro | Inteiro em **centavos** (`150000` = R$ 1.500,00). Float é recusado pelo schema. Taxas em fração (`0.035`) |
| Documentos | Só dígitos: CPF 11, CNPJ 14. Dígito verificador conferido (422 se não bater) |
| Datas | ISO-8601 com fuso (`2026-09-30T23:18:09-03:00`) |
| Paginação | Keyset: `?limit=1..100&cursor=<opaco>` → `next_cursor` (`null` na última página). Cursor adulterado → 400 `QIT000010` |
| Concorrência | Ordem global de lock: conta(s) em ordem crescente de id (`AccountRepository.lock_customer_accounts`) → linha de crédito do patrimônio → contrato → parcelas; nos cartões, conta → carteira → fatura ou autorização. Deadlock/serialização (`40P01`/`40001`) → retry automático com backoff, máx. 3 (`utils/db_retry.py`) |
| Ledger | Partidas dobradas, imutável. O banco recusa UPDATE/DELETE e operação que não soma zero |

---

## A · Titulares e contas

O cliente é o **titular**: um CPF (`NATURAL`) ou um CNPJ (`LEGAL`), cada um com N contas. O EI/MEI é um titular `LEGAL` com `legal_nature = EI` e `owner_customer_id` apontando para a PF dona; os dois formam um **patrimônio** (`exposure_customer_id`), que é a unidade do teto do microcrédito. Sociedade (`SLU`, `LTDA`) é patrimônio próprio.

| Método | Rota | Corpo / params | Sucesso | Erros |
|---|---|---|---|---|
| POST | `/customer` | `person_type (NATURAL\|LEGAL), document (CPF 11 \| CNPJ 14), name, annual_revenue`; NATURAL: `birth_date, is_pep?`; LEGAL: `legal_nature (EI\|SLU\|LTDA)`; EI: `owner_customer_id` | 201 `customer_id, account_id, branch, account_number, status, status_reason, microcredit_eligible` | 400 · 422 `QIT001003` CPF · `QIT001011` CNPJ · `QIT001007` data · `QIT001050` dono do EI inexistente ou não PF · 409 `QIT001010` documento já cadastrado |
| GET | `/customer/{customer_key}` | — | 200 titular (`person_type, document, legal_nature, owner_customer_id, annual_revenue, microcredit_eligible, kyc_status, account_id`…) | 404 `QIT001008` |
| PATCH | `/customer/{customer_key}` | `annual_revenue` | 200 titular com `microcredit_eligible` recalculado | 400 · 404 |
| POST | `/customer/{customer_key}/account` | — | 201 conta adicional, `ACTIVE` | 404 · 422 `QIT001051` KYC do titular não aprovado |
| GET | `/customer/{customer_key}/account` | — | 200 `items` (da mais antiga para a mais nova) | 404 |
| POST | `/customer/{customer_key}/relationship` | `natural_customer_id, role (PARTNER\|ADMINISTRATOR\|ATTORNEY)` | 201 `legal_customer_id, natural_customer_id, role, created_at` | 404 · 422 `QIT001052` não é PJ → PF, ou repetido |
| GET | `/account/{account_key}` | — | 200 `status, status_reason, status_events, balance, held_balance, available_balance, microcredit_eligible` | 404 `QIT001009` (inclui conta interna) |
| PATCH | `/account/{account_key}/status` | `status (ACTIVE\|REJECTED\|BLOCKED\|CLOSED), reason` | 200 conta | 404 · 409 `QIT001012` transição · 409 `QIT001014` encerramento |
| GET | `/account/{account_key}/statement` | `?limit&cursor` | 200 `items[entry_id, type, method, amount, balance_after, reference_type, reference_id, external_id, created_at], balance, held_balance, available_balance, next_cursor` | 400 · 404 |

**Status inicial** (ordem de avaliação): KYC reprovado → `REJECTED/KYC_REJECTED` · PF com idade < 18 → `REJECTED/UNDERAGE` · PEP → `PENDING/PEP_REVIEW` · PF com idade ≥ 80 → `PENDING/SENIOR_REVIEW` · demais → `ACTIVE`. Todos respondem **201**: a tentativa fica registrada (trilha de PLD). KYC é mock (`src/utils/kyc_mock.py`: o CPF `52998224725` é reprovado).

**Transições**: `PENDING → ACTIVE|REJECTED` · `ACTIVE ↔ BLOCKED` · `ACTIVE|BLOCKED → CLOSED`. `REJECTED` e `CLOSED` são finais. Encerrar exige `balance = 0`, `held_balance = 0` e nenhum contrato `ACTIVE` na conta.

**Elegibilidade e tarifa** (colunas geradas pelo banco): `microcredit_eligible = annual_revenue ≤ 36000000` (R$ 360 mil). `fee_segment` = `INDIVIDUAL` para PF e EI/MEI, `BUSINESS` para sociedade.

## B · Microcrédito

| Método | Rota | Corpo / params | Sucesso | Erros |
|---|---|---|---|---|
| PUT | `/customer/{customer_key}/credit_line` | `total_limit, monthly_interest_rate, origination_fee_rate` | 200 linha (`version` nova só se os termos mudaram; mesmo corpo, mesmo estado) | 400 · 404 `QIT001008` · 422 `QIT001053` titular é EI/MEI · 422 `QIT001055` fora da regra MPO |
| GET | `/customer/{customer_key}/credit_line` | — | 200 `credit_line_id, customer_id (raiz), version, total_limit, available_limit, microcredit_balance, monthly_interest_rate, origination_fee_rate` (para EI/MEI, a linha do dono) | 404 `QIT001008` · 404 `QIT001065` sem linha |
| POST | `/account/{account_key}/loan/simulation` | `amount, installment_count (2–24)` | 200 `term_days, effective_fee_rate, origination_fee_amount, net_amount, effective_cost_monthly, effective_cost_annual, installments[]` — nada é gravado | 400 · 404 · 422 `QIT001054` inelegível · `QIT001056` sem linha |
| POST | `/account/{account_key}/loan` | **Idempotency-Key** · `amount, installment_count (2–24), purpose, sfn_debt_declaration = true` | 201 contrato com `installments[]` (200 no replay) | 400 `QIT001015` · 404 · 409 `QIT001013` · `QIT001016` · 422 `QIT001054` · `QIT001056` · `QIT001057` limite · `QIT001058` teto de R$ 21 mil |
| GET | `/account/{account_key}/loan` | `?status (ACTIVE\|PAID_OFF)&limit&cursor` | 200 `items` (sem parcelas), `next_cursor` | 400 · 404 |
| GET | `/loan/{loan_key}` | — | 200 contrato + `installments[]` (`status OPEN\|PARTIAL\|OVERDUE\|PAID, paid_amount, remaining_amount, days_overdue`) | 404 `QIT001062` |
| POST | `/loan/{loan_key}/payment` | **Idempotency-Key** · `amount, mode (REDUCE_TERM\|REDUCE_INSTALLMENT)` | 201 `payment_id, allocations[number, principal_amount, interest_amount, prepayment_discount], loan` (200 no replay) | 400 `QIT001015` · 404 · 409 `QIT001063` quitado · `QIT001016` · 422 `QIT001059` acima do devido · `QIT001017` saldo |

**Guardrails MPO** (Res. CMN 4.854/2020), também em CHECK no banco: limite ≤ R$ 21 mil · juros ≤ 4% a.m. · TAC ≤ 3% · prazo de 60 a 720 dias (parcelas a cada 30 dias) · declaração de dívida no SFN (≤ R$ 80 mil) obrigatória.

**A conta do contrato** (`src/utils/loan_math.py`): Price (parcela fixa, juros sobre o saldo, a última absorve o arredondamento) · vencimento ajustado ao próximo dia útil · TAC proporcional abaixo de 120 dias (`taxa × prazo / 120`) · CET mensal = TIR dos fluxos (recebe o líquido, paga as parcelas), CET anual = `(1 + CET mensal)^12 − 1`.

**Teto por patrimônio.** O tomador é o titular da conta; o limite e o teto são do patrimônio dele. A PF e o EI/MEI dela disputam a **mesma** linha: o lock da linha serializa contratações simultâneas pelas duas contas. Premissas da RFC aplicadas (D1/D2): o teto conta só o **principal em aberto**, e sócio PF e sociedade têm tetos separados.

**Lançamentos.** Contratação: `DISBURSEMENT +amount` na conta contra `LOAN_PORTFOLIO`, e `ORIGINATION_FEE −TAC` contra `ORIGINATION_FEE_REVENUE`. Pagamento: `INSTALLMENT_PAYMENT −cash` na conta; o principal volta a `LOAN_PORTFOLIO` e os juros vão a `INTEREST_REVENUE`.

**Pagamento.** Parcelas vencidas primeiro, da mais antiga para a mais nova, pelo valor cheio; o que sobra antecipa as futuras **a valor presente** (CDC art. 52 §2º; o desconto nunca passa dos juros em aberto da parcela). `REDUCE_TERM` antecipa da última para a primeira (o prazo encurta); `REDUCE_INSTALLMENT` reparte na mesma proporção entre as futuras (o prazo fica). Só o **principal** amortizado volta ao `available_limit` da linha. Parcela toda paga vira `PAID`; todas pagas, o contrato vira `PAID_OFF`.

## C · Transferências

Pix e TED seguem o padrão da API da QI Tech (docs.qitech.com.br), **sem integrar**: rotas por trilho aninhadas na conta, `pix_transfer_type`, `target_account` com dígito e tipo de conta, consulta ao DICT antes do Pix por chave, devolução de Pix recebido, 201 para o que já liquidou e 202 para o que espera o trilho. A tabela `transfer` é uma só para os três meios.

| Método | Rota | Corpo / params | Sucesso | Erros |
|---|---|---|---|---|
| POST | `/transfer` | **Idempotency-Key** · `source_account_id, method (TEF), amount, destination{account_id}` | **201** `COMPLETED` (200 no replay) | 400 · 404 `QIT001009` · 409 `QIT001013` · 409 `QIT001016` · 422 `QIT001017` · 422 `QIT001018` · 422 `QIT001019` |
| GET | `/transfer/{transfer_key}` | — | 200 | 404 `QIT001020` |
| GET | `/account/{account_key}/transfer` | `?status&limit&cursor` (origem OU destino) | 200 `items, next_cursor` | 400 · 404 |
| PATCH | `/transfer/{transfer_key}/cancel` | — | 200 `CANCELED` | 404 · 409 `QIT001028` (só `SCHEDULED`) |
| POST | `/account/{account_key}/pix_key` | `key_type (CPF\|CNPJ\|EMAIL\|PHONE\|EVP), key_value?` (EVP é gerada pela API) | 201 | 404 · 409 `QIT001013` · 409 `QIT001029` já registrada · 409 `QIT001040` teto (NATURAL 5, LEGAL 20) · 422 `QIT001041` CPF/CNPJ de outro titular |
| GET · DELETE | `/account/{account_key}/pix_key` · `/account/{account_key}/pix_key/{pix_key_key}` | — | 200 (DELETE: a chave com `status = DELETED`) | 404 `QIT001009` · `QIT001021` |
| GET | `/pix_key/{pix_key}` | `?account_id` (quem consulta) | 200 `end_to_end_id, ispb, account_*, owner_name, owner_masked_document, owner_person_type, on_us, expires_at` | 400 · 404 `QIT001021` |
| POST | `/account/{account_key}/pix_transfer` | **Idempotency-Key** · `pix_transfer_type`. `KEY`: `pix_key, end_to_end_id, amount, pix_message?`. `MANUAL`: `target_account{ispb, branch, number, digit?, document, name, account_type}, amount, pix_message?` | on-us **201** `COMPLETED` · externo **202** `SENT` · 200 replay | 404 `QIT001036` consulta de outra conta · 409 `QIT001022` e2e já usado · 422 `QIT001023` consulta expirada · `QIT001024` emoji · `QIT001037` chave ≠ consulta · `QIT001042` destino inválido · `QIT001017` · `QIT001019` |
| POST | `/account/{account_key}/incoming_transfer/{incoming_transfer_key}/reversal` | **Idempotency-Key** · `amount, reversal_reason (CLIENT_REQUEST\|RECONCILIATION), pix_message?` | **202** `SENT` (id começa com `D`) | 404 `QIT001038` · 409 `QIT001013` · 422 `QIT001026` soma > recebido · `QIT001027` > 90 dias · `QIT001039` não devolvível · `QIT001017` saldo |
| POST | `/account/{account_key}/ted_transfer` | **Idempotency-Key** · `target_account{…}, amount, schedule_date?` | **202** `SENT` ou `SCHEDULED` | 422 `QIT001025` fora da janela sem data · `QIT001049` data inválida · `QIT001042` TED para esta IF |
| POST | `/webhook/spi` | `event`: `RECEIVED` (`external_id, amount, destination_account, sender, pix_transfer_type?, receiver_pix_key?, pix_message?, original_end_to_end_id` se `REVERSAL`) · `SETTLED` (`end_to_end_id`) · `REJECTED` (`end_to_end_id, error_code, error_description?`) | **200 sempre** | 400 · 403 |
| POST | `/webhook/str` | `event`: `RECEIVED` (como o SPI) · `SETTLED` · `RETURNED` (`str_control_number, reason?`) | **200 sempre** | 400 · 403 |

**Regras que o banco garante** (provadas pela API em `tests/integration/rules/test_guarantees.py`): o `end_to_end_id` do Pix por chave tem de vir de uma consulta da **mesma conta** (FK composta) e vale para **uma** transferência (UNIQUE); formato BCB `E|D + ISPB + yyyyMMddHHmm + 11`; devolução sempre com entrada original e motivo.

**Lançamentos.** Pix externo: `PIX_SENT −amount cliente / +amount SPI_SETTLEMENT`. Pix on-us: `PIX_SENT / PIX_RECEIVED` entre as contas. Devolução: `PIX_REVERSAL_SENT` e `PIX_REVERSAL_RECEIVED`. TED: `TED_SENT` contra `STR_SETTLEMENT`. Pix rejeitado devolve valor e tarifa (`REVERSAL`). TED devolvida devolve só o valor: a TED foi executada.

**Decisões do time.** TED fora da janela (dia útil, 6h30–17h) com `schedule_date` ausente recebe 422 — a API não reagenda sozinha (QI `TED000011`). Agendada não debita na criação: saldo e limite são conferidos na execução. Consulta ao DICT vale 15 min (premissa: a QI não publica). Devolução não conta no limite noturno. DICT de chaves externas é um mock (`src/utils/dict_mock.py`: `fornecedor@externo.com`, `+5511988887777`).

## D · Cartões e faturas

A **carteira de crédito** (`credit_wallet`, o "wallet" da QI) tem o limite, o ciclo e os encargos. Os cartões (virtual, físico, reemissão) são instrumentos que consomem o MESMO limite e caem na MESMA fatura. Cartão só de débito não tem carteira e debita a conta.

| Método | Rota | Corpo / params | Sucesso | Erros |
|---|---|---|---|---|
| POST | `/account/{account_key}/credit_wallet` | `total_limit, closing_day, due_day (1–28), monthly_interest_rate, fine_rate (≤ 0.02), autopay?` | 201 `ACTIVE` | 404 · 409 `QIT001013` · 409 `QIT001030` já existe carteira viva |
| GET | `/credit_wallet/{wallet_key}` | — | 200 com `available_limit` e `status_events` | 404 `QIT001044` |
| PATCH | `/credit_wallet/{wallet_key}/limit` | `total_limit` | 200 | 422 `QIT001031` abaixo do usado |
| PATCH | `/credit_wallet/{wallet_key}/status` | `status (ACTIVE\|BLOCKED\|CLOSED), reason` | 200 | 409 `QIT001032` (fechar exige `used_limit = 0`) |
| GET | `/credit_wallet/{wallet_key}/invoice` · `/invoice/{invoice_key}` | `?status` | 200 (detalhe com itens) | 404 `QIT001044` · `QIT001048` |
| POST | `/invoice/{invoice_key}/payment` | **Idempotency-Key** · `amount` | 201 `payment_id, status, paid_amount, remaining_amount` (200 no replay) | 400 `QIT001015` · 404 `QIT001048` · 409 `QIT001064` fatura paga · `QIT001016` · 409 `QIT001013` · 422 `QIT001060` acima da fatura · `QIT001017` saldo |
| POST | `/invoice/{invoice_key}/charge` | **Idempotency-Key** · `type (REVOLVING\|INSTALLMENT_PLAN), amount` | 201 fatura com itens + `charge` (200 no replay) | 400 `QIT001015` · 404 · 409 `QIT001066` fatura não está `OVERDUE` · `QIT001016` · 422 `QIT001061` teto do rotativo |
| POST | `/account/{account_key}/card` | `type (VIRTUAL\|PLASTIC), functions (DEBIT\|CREDIT\|MULTIPLE), printed_name, card_name?, brand?, contactless_enabled?` (só físico) | 201: virtual `ACTIVE`, físico `EMBOSSING` (+ `activation_code` fora de produção) | 409 `QIT001013` · 422 `QIT001045` crédito sem carteira ativa |
| GET | `/account/{account_key}/card` · `/card/{card_key}` | — | 200 com `status_events` (a QI expõe o mesmo) | 404 `QIT001043` |
| PATCH | `/card/{card_key}/activate` | `code` (6 dígitos) | 200 `ACTIVE` | 409 `QIT001032` · 422 `QIT001033` código · 422 `QIT001034` não é físico |
| PATCH | `/card/{card_key}/status` | `status (ACTIVE\|BLOCKED\|CANCELED\|LOST\|STOLEN\|FRAUD), reason` | 200 | 409 `QIT001032` |
| POST | `/card/authorization` | `authorization_id, card_id, function, amount, installment_count? (só crédito), merchant_name?, mcc?` | **200 sempre** `APPROVED` (`00`) ou `DECLINED` + `denial_reason` (`51` saldo/limite · `62` cartão · `57` conta/carteira/função · `14` cartão inexistente) | 400 · 403 |
| GET | `/card/authorization/{authorization_key}` | — | 200 com `events` | 404 `QIT001046` |
| POST | `/card/authorization/{authorization_key}/increment` | `request_id, amount` | 200 com `decision` | 404 · 409 `QIT001047` |
| POST | `/card/authorization/{authorization_key}/reversal` | `request_id, amount?` (sem amount = total) | 200 | 400 · 404 · 409 `QIT001047` |
| POST | `/card/captures` · `/card/refunds` | `capture_id\|refund_id, authorization_id, amount` | 200 (idempotente pelo id da rede) | 404 · 409 `QIT001047` · 422 `QIT001035` estorno > captura |

**Transições.** Cartão: `EMBOSSING → ACTIVE` só pelo código; `EMBOSSING → CANCELED|LOST|STOLEN`; `ACTIVE ↔ BLOCKED`; `ACTIVE|BLOCKED → CANCELED|LOST|STOLEN|FRAUD`. Terminais: `CANCELED, LOST, STOLEN, FRAUD`. Carteira: `ACTIVE ↔ BLOCKED`, `ACTIVE|BLOCKED → CLOSED`.

**Dinheiro da autorização** (`card_authorization_event`, enumerador da QI 1 para 1). `AUTHORIZATION`/`INCREMENTAL_AUTHORIZATION` criam HOLD (débito, `held_balance`) ou reserva (crédito, `used_limit`). `REVERSAL`/`PARTIAL_REVERSAL` soltam. A primeira `CAPTURE` troca o HOLD pelo valor capturado (pode ser maior ou menor): débito lança `DEBIT_PURCHASE` contra `CARD_SETTLEMENT`; crédito lança as parcelas nas faturas. `REFUND`/`PARTIAL_REFUND` são eventos: a autorização segue `CAPTURED` (o "completed" da QI). `REFUNDED` fica no enumerador, mas deixou de ser destino.

**Faturas.** Compra antes do dia de fechamento cai na fatura que fecha neste mês; no dia ou depois, na do mês seguinte. Vencimento: o primeiro `due_day` depois do fechamento, ajustado a dia útil. Parcela *k* cai *k−1* meses depois; faturas de meses seguintes nascem `FUTURE` (id 6) e viram `OPEN` quando a anterior fechar. Compra no crédito não gera lançamento no ledger: até o pagamento, o registro é a fatura.

**Pagamento da fatura.** Debita a conta (`INVOICE_PAYMENT` contra `CARD_SETTLEMENT`) e devolve o valor ao limite da carteira. Fatura ainda `OPEN`/`FUTURE`: é antecipação e o status não muda. Fechada: `PARTIALLY_PAID` enquanto falta, `PAID` quando quita.

**Rotativo** (Lei 14.690/2023). Ao vencer sem quitar, a fatura vira `OVERDUE` e grava `original_debt_amount` (job `mark_overdue_invoices`). A IF lança o encargo (`REVOLVING` ou `INSTALLMENT_PLAN`) na própria fatura vencida, como item `REVOLVING_CHARGE`, que soma no total e consome limite da carteira. A soma dos encargos não passa de 100% da `original_debt_amount` (premissa D3 da RFC).

## E · Jobs

| Método | Rota | Corpo / params | Sucesso | Erros |
|---|---|---|---|---|
| POST | `/job/{job_name}` | — | 200 `{job, result: {processed, outcomes}}` | 404 `QIT000404` job inexistente |

Os mesmos jobs rodam pela linha de comando (`cd src && python -m jobs.<nome>`; no container, `docker compose exec api python -m jobs.<nome>`). Cada job lista os candidatos sem lock e processa um por um, na própria transação, pelo mesmo controller que a rota usaria. Item que falha conta como `ERROR` e não derruba o lote. **Todos são idempotentes**: rodar duas vezes no mesmo dia não move dinheiro de novo.

| Job | O que faz |
|---|---|
| `collect_installments` | Debita as parcelas vencidas até hoje, da mais antiga à mais nova, com o saldo disponível (conta `ACTIVE` ou `BLOCKED`). O que não couber fica `OVERDUE`, com `days_overdue`, e gera `baas.installment.overdue` |
| `run_scheduled_teds` | Só em dia útil, na janela do STR: TED `SCHEDULED` do dia vira `SENT` (ou `FAILED` sem saldo / conta fora de `ACTIVE`) |
| `reconcile_spi_str` | Pergunta ao trilho o desfecho do que está `SENT` há mais de 30 min. Sem resposta, não mexe (o trilho é mock: `src/utils/rail_mock.py`) |
| `expire_authorizations` | `APPROVED` com `expires_at` vencido → `EXPIRED` + evento `EXPIRATION`; solta HOLD ou reserva |
| `close_invoices` | `OPEN` → `CLOSED` no dia do fechamento (`PAID` se nada a pagar); a próxima `FUTURE` vira `OPEN` |
| `run_invoice_autopay` | Carteira com `autopay`: no vencimento, debita o que houver de saldo até o valor da fatura. No máximo um débito automático por fatura |
| `mark_overdue_invoices` | `CLOSED`/`PARTIALLY_PAID` vencida e não quitada → `OVERDUE`, gravando `original_debt_amount` |
| `dispatch_outbox_events` | Entrega à IF os eventos `PENDING`, do mais antigo ao mais novo, em lotes de 100, fora de transação: `{webhook_type, key, aggregate_type, event_id, data}`. Falha conta tentativa; depois de 5, `FAILED`. Sem `IF_WEBHOOK_URL`, roda em modo mock (registra no log e considera entregue) |

Tipos de evento do outbox (`webhook_type` no padrão da QI): `baas.account.*`, `baas.tef.*`, `baas.pix_transfer.*`, `baas.ted.*`, `baas.pix_key.*`, `baas.credit_wallet.*`, `baas.card.*`, `baas.credit_line.change`, `baas.loan.contracted|payment|paid_off`, `baas.installment.overdue`, `baas.invoice.status_change|payment|charge` (`src/models/outbox_event.py`).

---

## Códigos de erro do domínio

| Código | HTTP | Nome no contrato v6 | Quando |
|---|---|---|---|
| `QIT001003` | 422 | — | CPF com dígito verificador errado (herdado do projeto base) |
| `QIT001007` | 422 | — | data que não existe no calendário (herdado do projeto base) |
| `QIT001008` | 404 | — | cliente não encontrado |
| `QIT001009` | 404 | — | conta não encontrada (inclui conta interna e id que não é UUID) |
| `QIT001010` | 409 | `CUSTOMER_ALREADY_EXISTS` | CPF ou CNPJ já cadastrado |
| `QIT001011` | 422 | — | CNPJ com dígito verificador errado |
| `QIT001012` | 409 | `INVALID_STATUS_TRANSITION` | transição fora da máquina de estados |
| `QIT001013` | 409 | `ACCOUNT_NOT_ACTIVE` | origem ou destino não está ACTIVE |
| `QIT001014` | 409 | — | encerramento com saldo, bloqueio ou loan ativo |
| `QIT001015` | 400 | `IDEMPOTENCY_KEY_REQUIRED` | header ausente ou malformado |
| `QIT001016` | 409 | `IDEMPOTENCY_CONFLICT` | mesma key, corpo diferente |
| `QIT001017` | 422 | `INSUFFICIENT_BALANCE` | saldo disponível < valor + tarifa |
| `QIT001018` | 422 | `SAME_ACCOUNT` | origem = destino |
| `QIT001019` | 422 | `NIGHT_LIMIT_EXCEEDED` | teto noturno estourado |
| `QIT001020` | 404 | — | transferência não encontrada |
| `QIT001021` | 404 | QI `PIX000017` | chave Pix não encontrada no DICT |
| `QIT001022` | 409 | QI `PXT000061` | `end_to_end_id` já usado |
| `QIT001023` | 422 | — | consulta ao DICT expirada |
| `QIT001024` | 422 | QI `PXT000048` | emoji na `pix_message` |
| `QIT001025` | 422 | QI `TED000011` | TED fora da janela sem `schedule_date` |
| `QIT001026` | 422 | QI `PXT000017` | devoluções acima do recebido |
| `QIT001027` | 422 | QI `PXT000015` | devolução depois de 90 dias |
| `QIT001028` | 409 | QI `PSC000028` | cancelar transferência que não está `SCHEDULED` |
| `QIT001029` | 409 | — | chave Pix já registrada |
| `QIT001030` | 409 | QI `CIN000043` | carteira viva já existe |
| `QIT001031` | 422 | QI `CIN000110` | novo limite abaixo do usado |
| `QIT001032` | 409 | QI `CARD000013` | transição inválida de cartão ou carteira |
| `QIT001033` | 422 | QI `CARD000020` | código de ativação inválido |
| `QIT001034` | 422 | QI `CARD000023` | operação só para cartão físico |
| `QIT001035` | 422 | — | estorno acima do capturado |
| `QIT001036` | 404 | QI `PIX000056` | consulta ao DICT não encontrada para esta conta |
| `QIT001037` | 422 | QI `PXT000128` | chave enviada ≠ chave da consulta |
| `QIT001038` | 404 | — | entrada não encontrada (ou de outra conta) |
| `QIT001039` | 422 | — | entrada não devolvível (STR, devolvida, ou já é devolução) |
| `QIT001040` | 409 | Regulamento Pix | teto de chaves (PF 5, PJ 20) |
| `QIT001041` | 422 | — | chave CPF/CNPJ de outro titular |
| `QIT001042` | 422 | QI `PXT000132`/`PXT000141` | conta de destino inválida |
| `QIT001043` | 404 | QI `CARD000011` | cartão não encontrado |
| `QIT001044` | 404 | QI `CIN000007` | carteira não encontrada |
| `QIT001045` | 422 | — | cartão com crédito sem carteira ativa |
| `QIT001046` | 404 | — | autorização não encontrada |
| `QIT001047` | 409 | — | operação não aceita no status da autorização |
| `QIT001048` | 404 | — | fatura não encontrada |
| `QIT001049` | 422 | QI `PSC000008` | `schedule_date` não é dia útil futuro |
| `QIT001050` | 422 | — | dono do EI/MEI inexistente ou que não é pessoa natural |
| `QIT001051` | 422 | — | conta adicional para titular sem KYC aprovado |
| `QIT001052` | 422 | — | vínculo que não liga PJ → PF, ou repetido |
| `QIT001053` | 422 | — | linha de crédito pedida para EI/MEI (usa a do dono) |
| `QIT001054` | 422 | `CUSTOMER_NOT_ELIGIBLE` | renda ou receita anual acima de R$ 360 mil |
| `QIT001055` | 422 | `OUT_OF_MPO_RULE` | linha fora da regra MPO (limite, juros, TAC) ou prazo fora de 60–720 dias; a descrição traz o campo |
| `QIT001056` | 422 | `NO_CREDIT_LINE` | patrimônio do tomador sem linha |
| `QIT001057` | 422 | `INSUFFICIENT_LIMIT` | valor acima do limite disponível da linha |
| `QIT001058` | 422 | `REGULATORY_CAP_EXCEEDED` | saldo de microcrédito do patrimônio passaria de R$ 21 mil |
| `QIT001059` | 422 | `AMOUNT_ABOVE_DUE` | pagamento acima do que quita o contrato hoje (a descrição traz o valor) |
| `QIT001060` | 422 | `AMOUNT_ABOVE_INVOICE` | pagamento acima do saldo da fatura |
| `QIT001061` | 422 | `REVOLVING_CAP_EXCEEDED` | encargos passariam de 100% da dívida original |
| `QIT001062` | 404 | — | contrato não encontrado |
| `QIT001063` | 409 | — | contrato já quitado |
| `QIT001064` | 409 | — | fatura já paga |
| `QIT001065` | 404 | — | patrimônio sem linha de crédito (consulta) |
| `QIT001066` | 409 | — | encargo em fatura que não está `OVERDUE` |

Próximo livre: `QIT001067`. Aposentados, não reutilizar: `QIT001001`, `001002`, `001004`, `001005`, `001006` (eram do `sample_entity`, removido).

---

## Onde o código diverge do contrato v6 (e por quê)

| v6 dizia | Ficou | Motivo |
|---|---|---|
| `X-API-Key` por chamador · HMAC nos webhooks | `INTERNAL-TOKEN` | Padrão do projeto base: um token só para todas as rotas internas. HMAC volta quando houver trilho fora da nossa rede |
| `{"error": {"code": "INSUFFICIENT_BALANCE"}}` | Envelope `QIT0…` do projeto base | Um formato só na API inteira; a tabela acima faz a ponte |
| Validação 422 | 400 formato · 422 valor | Semântica do projeto base (README, seção 7) |
| Ledger `TED_FEE` | `TRANSFER_FEE` + coluna `method` | Tarifa existe em TEF também; o meio já está na linha |
| Tarifa TEF R$ 0 | **R$ 1,00 (premissa)** | O bootcamp exige tarifa na transferência; com zero, o requisito não aparece na demo. PIX segue gratuito |
| Resposta do POST /customers | + `branch`, `account_number`, `status_reason` | É o endereço que o SPI usa para creditar PIX |
| Item do extrato | + `entry_id`, `reference_type`, `reference_id` | Liga cada linha à transferência que a gerou |
| `Idempotency-Key` livre (8–64) | UUID v4 | Mesmo formato do `request_control_key` da QI; todo cliente já gera UUID v4 |
| `POST /transfers` para TEF, PIX e TED | Rotas por trilho para Pix e TED | Padrão da QI (`/account/{key}/pix_transfer`, `/account/{key}/ted_transfer`). A tabela segue única |
| Rotas no plural com `{id}` (`/customers/{id}`) | Singular com `{*_key}` (`/customer/{customer_key}`) | Padrão do `src/app.py`, igual ao da QI |
| Cliente = CPF, com `type INDIVIDUAL\|MEI` e `cnpj` opcional | Titular v7: `person_type NATURAL\|LEGAL` + `document`; o MEI é um titular `LEGAL/EI` com dono PF | A mesma pessoa tem uma conta PF e outra para cada CNPJ; o teto do microcrédito é do patrimônio |
| Id UUID é a PK | `id BIGINT` interno + `key UUID` público | O `id` nunca sai do banco; a API só recebe e devolve a `key` |
| Linha de crédito na conta (`/accounts/{id}/credit-line`) | Na raiz do patrimônio (`/customer/{customer_key}/credit_line`) | O teto de R$ 21 mil soma a PF e o EI/MEI dela |
| Limite e fatura no cartão | Carteira de crédito (`credit_wallet`) | Padrão da QI (wallet): um limite e uma fatura para todos os cartões do cliente |
| `card_capture` e `card_refund` | `card_authorization_event` | Enumerador de eventos da QI; ganha incremental, reversão parcial e expiração |
| Tipos do outbox `TRANSFER_COMPLETED`… | `baas.<recurso>.<evento>` | É o `webhook_type` da QI |