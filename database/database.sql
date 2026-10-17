-- =====================================================================
-- Infra de conta digital + microcrédito — Esquema PostgreSQL (fluxos v7)
-- Bootcamp QI Tech · single-tenant (uma única IF por instalação)
--
-- Convenções
--   • Identificadores em inglês; comentários em pt-BR.
--   • Termos regulatórios brasileiros mantidos como nome próprio:
--     CPF, CNPJ, MEI, PIX, TED, TEF, SPI, STR, ISPB, KYC, PEP.
--   • Dinheiro em centavos (BIGINT). Taxas como fração (0.035 = 3,5 por cento a.m.).
--   • Timestamps em TIMESTAMPTZ; regras de negócio em America/Sao_Paulo.
--   • Identidade: id BIGINT (PK, alvo das FKs, nunca sai do banco) e
--     key UUID (identificador público, o que a API recebe e devolve).
--   • Valores fixos de coluna como tipos enum_* nativos; status em
--     tabela enumeradora (seção 0b), com histórico *_status_event.
--   • Ledger imutável e em partidas dobradas (triggers no fim do arquivo).
--   • Ordem global de lock: account(s) por id → credit_line → loan
--     → installment; nos cartões account → credit_wallet
--     → card_authorization (a fatura vai protegida pelo lock da carteira).
--   • Titular (customer) = tomador: um CPF ou um CNPJ. Uma pessoa tem N
--     titulares (a PF e cada CNPJ) e cada titular tem N contas. Os tetos
--     de microcrédito agregam por PATRIMÔNIO (exposure_customer_id).
--
-- ATENÇÃO: este arquivo NÃO pode conter o caractere de porcentagem.
-- O tests/utils/db_utils.py roda o arquivo pelo psycopg2, que trata esse
-- caractere como marcador de parâmetro — inclusive dentro de comentário.
-- =====================================================================

SET TIME ZONE 'America/Sao_Paulo';




-- ENUMs para métodos
CREATE TYPE enum_transfer_method AS ENUM ('TEF', 'PIX', 'TED');
CREATE TYPE enum_ledger_method AS ENUM ('TEF', 'PIX', 'TED', 'CARD');

-- ENUMs para tipos (Types)
CREATE TYPE enum_person_type AS ENUM ('NATURAL', 'LEGAL');
CREATE TYPE enum_account_type AS ENUM ('CUSTOMER', 'INTERNAL');
CREATE TYPE enum_pix_key_type AS ENUM ('CPF', 'CNPJ', 'EMAIL', 'PHONE', 'EVP');
CREATE TYPE enum_external_account_type AS ENUM ('CHECKING', 'SALARY', 'SAVINGS', 'PAYMENT');
CREATE TYPE enum_pix_transfer_type AS ENUM ('KEY', 'MANUAL', 'STATIC_QR_CODE', 'DYNAMIC_QR_CODE', 'REVERSAL');
CREATE TYPE enum_card_type AS ENUM ('VIRTUAL', 'PLASTIC');
CREATE TYPE enum_invoice_item_type AS ENUM ('PURCHASE', 'PURCHASE_REFUND', 'REVOLVING_CHARGE');
CREATE TYPE enum_customer_segment AS ENUM ('INDIVIDUAL', 'BUSINESS');
CREATE TYPE enum_legal_nature AS ENUM ('EI', 'SLU' ,'LTDA');
-- ENUMs para tipos complexos (Ledger e Eventos)
CREATE TYPE enum_ledger_entry_type AS ENUM (
    'DISBURSEMENT','ORIGINATION_FEE',
    'TEF_SENT','TEF_RECEIVED',
    'PIX_SENT','PIX_RECEIVED',
    'PIX_REVERSAL_SENT','PIX_REVERSAL_RECEIVED',
    'TED_SENT','TED_RECEIVED',
    'TRANSFER_FEE',
    'INSTALLMENT_PAYMENT',
    'DEBIT_PURCHASE','PURCHASE_REFUND',
    'INVOICE_PAYMENT',
    'REVERSAL'
);

CREATE TYPE enum_reference_type AS ENUM (
    'TRANSFER', 'INCOMING_TRANSFER', 'LOAN', 
    'LOAN_PAYMENT', 'CARD_AUTHORIZATION', 'INVOICE_PAYMENT'
);

CREATE TYPE enum_card_auth_event_type AS ENUM (
    'AUTHORIZATION', 'INCREMENTAL_AUTHORIZATION', 'REVERSAL', 
    'PARTIAL_REVERSAL', 'EXPIRATION', 'CAPTURE', 'REFUND', 'PARTIAL_REFUND'
);

-- Papel do relacionamento
CREATE TYPE enum_relationship_role AS ENUM ('PARTNER', 'ADMINISTRATOR', 'ATTORNEY');

-- Pagamentos de Empréstimo e Fatura
CREATE TYPE enum_loan_payment_source AS ENUM ('MANUAL', 'AUTO_COLLECTION');
CREATE TYPE enum_invoice_payment_source AS ENUM ('MANUAL', 'AUTOPAY');
CREATE TYPE enum_loan_payment_mode AS ENUM ('REDUCE_TERM', 'REDUCE_INSTALLMENT');

-- Trilhos e Devoluções
CREATE TYPE enum_transfer_rail AS ENUM ('SPI', 'STR');
CREATE TYPE enum_reversal_reason AS ENUM ('CLIENT_REQUEST', 'RECONCILIATION');

-- Cartões e Autorizações
CREATE TYPE enum_card_brand AS ENUM ('VISA', 'MASTERCARD');
CREATE TYPE enum_card_functions AS ENUM ('DEBIT', 'CREDIT', 'MULTIPLE'); -- Capacidades do plástico
CREATE TYPE enum_card_function AS ENUM ('DEBIT', 'CREDIT');              -- A operação de fato
CREATE TYPE enum_denial_reason AS ENUM (
    'INSUFFICIENT_FUNDS', 'INSUFFICIENT_LIMIT', 'CARD_NOT_ACTIVE',
    'ACCOUNT_NOT_ACTIVE', 'WALLET_NOT_ACTIVE', 'FUNCTION_NOT_SUPPORTED',
    'FRAUD_SUSPICION'
);

-- ---------------------------------------------------------------------
-- 0. Apoio: calendário bancário e tabela de tarifas
-- ---------------------------------------------------------------------
CREATE TABLE holiday (
    date         DATE PRIMARY KEY,
    description  TEXT NOT NULL
);
-- Dia útil = não é sábado/domingo e não está em holiday.

-- Segmento de tarifa = customer.fee_segment (coluna gerada).
CREATE TABLE fee (
    method            enum_transfer_method NOT NULL,
    customer_segment  enum_customer_segment   NOT NULL,
    amount            BIGINT NOT NULL CHECK (amount >= 0),
    effective_from    DATE   NOT NULL DEFAULT CURRENT_DATE,
    PRIMARY KEY (method, customer_segment, effective_from)
);


-- Uma tabela por entidade. Estado que não está aqui o banco recusa, sem
-- precisar de código. O código lê pelo `enumerator`, nunca pelo id; o id
-- só aparece neste arquivo, nos CHECKs e índices parciais.
CREATE TABLE kyc_status (
    id          SMALLINT    PRIMARY KEY,
    enumerator  VARCHAR(30) NOT NULL UNIQUE
);
INSERT INTO kyc_status (id, enumerator) VALUES
    (1, 'PENDING'), (2, 'APPROVED'), (3, 'REJECTED');
 
CREATE TABLE account_status (
    id          SMALLINT    PRIMARY KEY,
    enumerator  VARCHAR(30) NOT NULL UNIQUE
);
INSERT INTO account_status (id, enumerator) VALUES
    (1, 'REQUESTED'), (2, 'PENDING'), (3, 'ACTIVE'),
    (4, 'BLOCKED'),   (5, 'REJECTED'), (6, 'CLOSED');
 
CREATE TABLE loan_status (
    id          SMALLINT    PRIMARY KEY,
    enumerator  VARCHAR(30) NOT NULL UNIQUE
);
INSERT INTO loan_status (id, enumerator) VALUES
    (1, 'ACTIVE'), (2, 'PAID_OFF');
 
CREATE TABLE installment_status (
    id          SMALLINT    PRIMARY KEY,
    enumerator  VARCHAR(30) NOT NULL UNIQUE
);
INSERT INTO installment_status (id, enumerator) VALUES
    (1, 'OPEN'), (2, 'PARTIAL'), (3, 'OVERDUE'), (4, 'PAID');
 
CREATE TABLE transfer_status (
    id          SMALLINT    PRIMARY KEY,
    enumerator  VARCHAR(30) NOT NULL UNIQUE
);
INSERT INTO transfer_status (id, enumerator) VALUES
    (1, 'CREATED'),  (2, 'SCHEDULED'), (3, 'SENT'), (4, 'COMPLETED'),
    (5, 'REJECTED'), (6, 'RETURNED'),  (7, 'FAILED'),
    (8, 'CANCELED');   -- agendamento cancelado pelo cliente (QI: pix_schedule "cancelled")
 
CREATE TABLE incoming_transfer_status (
    id          SMALLINT    PRIMARY KEY,
    enumerator  VARCHAR(30) NOT NULL UNIQUE
);
INSERT INTO incoming_transfer_status (id, enumerator) VALUES
    (1, 'CREDITED'), (2, 'RETURNED');
 
CREATE TABLE card_status (
    id          SMALLINT    PRIMARY KEY,
    enumerator  VARCHAR(30) NOT NULL UNIQUE
);
INSERT INTO card_status (id, enumerator) VALUES
    (1, 'ACTIVE'),    (2, 'BLOCKED'), (3, 'CANCELED'),
    (4, 'EMBOSSING'), (5, 'LOST'),    (6, 'STOLEN'),   (7, 'FRAUD');
 
CREATE TABLE card_authorization_status (
    id          SMALLINT    PRIMARY KEY,
    enumerator  VARCHAR(30) NOT NULL UNIQUE
);
-- REFUNDED (6) fica na lista (enumerador é append-only), mas deixou de
-- ser destino: estorno é EVENTO (card_authorization_event) e a autorização
-- segue CAPTURED, como o "completed" da QI. Quanto voltou diz o refunded_amount.
INSERT INTO card_authorization_status (id, enumerator) VALUES
    (1, 'APPROVED'), (2, 'DECLINED'), (3, 'CAPTURED'),
    (4, 'EXPIRED'),  (5, 'REVERSED'), (6, 'REFUNDED');
 
CREATE TABLE invoice_status (
    id          SMALLINT    PRIMARY KEY,
    enumerator  VARCHAR(30) NOT NULL UNIQUE
);
-- FUTURE: fatura de mês seguinte que já recebe parcelas de compra
-- parcelada. Vira OPEN quando a anterior fecha (job close_invoices).
INSERT INTO invoice_status (id, enumerator) VALUES
    (1, 'OPEN'), (2, 'CLOSED'), (3, 'PARTIALLY_PAID'), (4, 'PAID'), (5, 'OVERDUE'),
    (6, 'FUTURE');
 
CREATE TABLE pix_key_status (
    id          SMALLINT    PRIMARY KEY,
    enumerator  VARCHAR(30) NOT NULL UNIQUE
);
INSERT INTO pix_key_status (id, enumerator) VALUES
    (1, 'ACTIVE'), (2, 'DELETED');
 
CREATE TABLE credit_wallet_status (
    id          SMALLINT    PRIMARY KEY,
    enumerator  VARCHAR(30) NOT NULL UNIQUE
);
INSERT INTO credit_wallet_status (id, enumerator) VALUES
    (1, 'ACTIVE'), (2, 'BLOCKED'), (3, 'CLOSED');


CREATE TABLE outbox_event_status (
    id          SMALLINT    PRIMARY KEY,
    enumerator  VARCHAR(30) NOT NULL UNIQUE
);
INSERT INTO outbox_event_status (id, enumerator) VALUES
    (1, 'PENDING'), (2, 'SENT'), (3, 'FAILED');



-- ---------------------------------------------------------------------
-- 1. Cliente e conta
-- ---------------------------------------------------------------------
-- Titular de conta = o "tomador" da Res. CMN 4.854: um CPF OU um CNPJ.
-- A pessoa natural e cada CNPJ dela são linhas distintas. Porte (MEI, ME,
-- EPP) NÃO é modelado: muda por lei e é derivado do faturamento. O que
-- importa para as regras é a natureza jurídica (quem responde pela dívida)
-- e o faturamento (quem é elegível).
CREATE TABLE customer (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- GUID público para a API
    key                   UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    person_type            enum_person_type NOT NULL,  -- vocabulário do DICT
    document               VARCHAR(14) NOT NULL UNIQUE,   -- CPF (11) ou CNPJ (14), só dígitos
    name                   TEXT NOT NULL,                 -- nome civil ou razão social
    birth_date             DATE,                          -- só NATURAL
    -- Só LEGAL. EI = empresário individual, INCLUI o MEI (MEI é EI no SIMEI).
    -- SLU e LTDA são sociedades: patrimônio próprio. Ampliar por migração.
    legal_nature           enum_legal_nature,
    -- Só EI: a pessoa natural que É este CNPJ. EI/MEI não tem personalidade
    -- jurídica distinta; patrimônio único com a PF (jurisprudência do STJ).
    owner_customer_id      BIGINT,
    owner_person_type      enum_person_type CHECK (owner_person_type = 'NATURAL'::enum_person_type), -- alvo fixo da FK composta
    -- Quem responde pela dívida com o próprio patrimônio: a PF para ela
    -- mesma e para o EI/MEI dela; a sociedade para si. Tetos agregam aqui.
    exposure_customer_id   BIGINT GENERATED ALWAYS AS (COALESCE(owner_customer_id, id)) STORED,
    -- Pix gratuito para pessoa natural, inclusive empresário individual
    -- (Res. BCB 19/2020): EI/MEI tarifa como PF; sociedade tarifa como PJ.
    fee_segment enum_customer_segment GENERATED ALWAYS AS ( CASE WHEN person_type = 'NATURAL' OR legal_nature = 'EI' 
                                                            THEN 'INDIVIDUAL'::enum_customer_segment 
                                                            ELSE 'BUSINESS'::enum_customer_segment END) STORED,
    annual_revenue         BIGINT NOT NULL CHECK (annual_revenue >= 0),  -- renda (PF) ou receita bruta (PJ)
    revenue_reference_date DATE NOT NULL DEFAULT CURRENT_DATE,
    -- Res. CMN 4.854 art. 2º: renda ou receita bruta até o teto de
    -- microempresa (LC 123/2006: R$ 360.000,00). Vale para PF e PJ.
    microcredit_eligible   BOOLEAN GENERATED ALWAYS AS (annual_revenue <= 36000000) STORED,
    kyc_status_id          SMALLINT NOT NULL REFERENCES kyc_status(id),
    is_pep                 BOOLEAN NOT NULL DEFAULT FALSE,  -- só NATURAL; PJ herda dos sócios
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ux_customer_person_type UNIQUE (id, person_type),         -- alvo das FKs compostas
    CONSTRAINT ux_customer_exposure    UNIQUE (id, exposure_customer_id),
    CONSTRAINT ck_document CHECK (
        (person_type = 'NATURAL'::enum_person_type AND document ~ '^[0-9]{11}$')
     OR (person_type = 'LEGAL'::enum_person_type   AND document ~ '^[0-9]{14}$')),
     
    CONSTRAINT ck_fields_by_person_type CHECK (
        (person_type = 'NATURAL'::enum_person_type) = (birth_date IS NOT NULL)
        AND (person_type = 'LEGAL'::enum_person_type) = (legal_nature IS NOT NULL)),
        
    CONSTRAINT ck_pep_natural CHECK (NOT is_pep OR person_type = 'NATURAL'::enum_person_type),
    
    CONSTRAINT ck_ei_owner CHECK (
        (legal_nature IS NOT DISTINCT FROM 'EI'::enum_legal_nature) = (owner_customer_id IS NOT NULL)
        AND (owner_customer_id IS NULL) = (owner_person_type IS NULL)),
    -- o dono do EI é sempre uma pessoa natural
    CONSTRAINT fk_ei_owner FOREIGN KEY (owner_customer_id, owner_person_type)
        REFERENCES customer (id, person_type)
);
CREATE INDEX ix_customer_owner ON customer (owner_customer_id) WHERE owner_customer_id IS NOT NULL;

-- Quem opera a conta PJ além do titular do EI: sócios e administradores
-- de sociedade, procuradores de qualquer PJ. Liga PJ → PF.
CREATE TABLE customer_relationship (
    legal_customer_id     BIGINT NOT NULL,
    legal_person_type     enum_person_type NOT NULL DEFAULT 'LEGAL'::enum_person_type   CHECK (legal_person_type = 'LEGAL'::enum_person_type),
    natural_customer_id   BIGINT NOT NULL,
    natural_person_type   enum_person_type NOT NULL DEFAULT 'NATURAL'::enum_person_type CHECK (natural_person_type = 'NATURAL'::enum_person_type),
    role enum_relationship_role NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (legal_customer_id, natural_customer_id, role),
    CONSTRAINT fk_relationship_legal FOREIGN KEY (legal_customer_id, legal_person_type)
        REFERENCES customer (id, person_type),
    CONSTRAINT fk_relationship_natural FOREIGN KEY (natural_customer_id, natural_person_type)
        REFERENCES customer (id, person_type)
);
CREATE INDEX ix_customer_relationship_natural ON customer_relationship (natural_customer_id);

-- Número de conta sequencial (8 dígitos), agência fixa 0001
CREATE SEQUENCE account_number_seq START 1;

CREATE TABLE account (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- GUID público para a API
    key              UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    type             enum_account_type NOT NULL,
    customer_id      BIGINT REFERENCES customer(id),  -- NULL só em INTERNAL; N contas por titular
    internal_code    TEXT UNIQUE,  -- só para contas INTERNAL
    branch           CHAR(4),
    number           TEXT UNIQUE,
    status_id        SMALLINT NOT NULL REFERENCES account_status(id),
    status_reason    TEXT,     -- motivo do status ATUAL; o histórico está em account_status_event
    -- saldo contábil materializado: só contas CUSTOMER (atualizado sob FOR UPDATE).
    -- Contas INTERNAL não são travadas (evita hotspot); saldo = SUM do ledger.
    balance          BIGINT,
    held_balance     BIGINT,   -- soma dos HOLDs de débito ativos
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_account_type CHECK (
        (type = 'CUSTOMER'::enum_account_type AND customer_id IS NOT NULL AND internal_code IS NULL
             AND balance IS NOT NULL AND held_balance IS NOT NULL
             AND held_balance >= 0 AND number IS NOT NULL)
        OR (type = 'INTERNAL'::enum_account_type AND customer_id IS NULL AND internal_code IS NOT NULL
             AND balance IS NULL AND held_balance IS NULL)),
    CONSTRAINT ux_account_customer UNIQUE (id, customer_id)  -- alvo da FK composta do loan
    -- Sem CHECK balance >= 0: captura mandatória de débito pode negativar (regra da IF).
);
CREATE INDEX ix_account_customer ON account (customer_id) WHERE customer_id IS NOT NULL;

CREATE TABLE account_status_event (
    id              BIGINT   GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id      BIGINT     NOT NULL REFERENCES account(id),
    from_status_id  SMALLINT REFERENCES account_status(id),            -- nulo ao nascer
    to_status_id    SMALLINT NOT NULL REFERENCES account_status(id),
    reason          VARCHAR(255),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_account_status_event_changed CHECK (from_status_id IS DISTINCT FROM to_status_id)
);
CREATE INDEX ix_account_status_event ON account_status_event (account_id, id);
 
-- ---------------------------------------------------------------------
-- 2. Ledger (partidas dobradas, imutável)
-- ---------------------------------------------------------------------
CREATE TABLE ledger_entry (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    operation_id     UUID   NOT NULL,          -- agrupa as pernas; SUM(amount) = 0
    account_id       BIGINT   NOT NULL REFERENCES account(id),
    amount           BIGINT NOT NULL CHECK (amount <> 0),  -- + crédito / − débito
    type             enum_ledger_entry_type NOT NULL,
    method           enum_ledger_method,
    balance_after    BIGINT,                   -- preenchido só em conta CUSTOMER
    reference_type   enum_reference_type,
    reference_id     BIGINT,
    external_id      TEXT,                     -- endToEndId / nº de controle STR
    reversal_of_id   BIGINT REFERENCES ledger_entry(id),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Extrato keyset: WHERE account_id = $1 AND (created_at, id) < ($2, $3) ORDER BY created_at DESC, id DESC
CREATE INDEX ix_ledger_statement ON ledger_entry (account_id, created_at DESC, id DESC);
CREATE INDEX ix_ledger_operation ON ledger_entry (operation_id);
CREATE INDEX ix_ledger_reference ON ledger_entry (reference_type, reference_id);

-- ---------------------------------------------------------------------
-- 3. Microcrédito
-- ---------------------------------------------------------------------
-- Linha vigente: 1 por PATRIMÔNIO (não por conta, não por CNPJ), mutável
-- sob FOR UPDATE. A PF e o EI/MEI dela dividem a mesma linha; sociedade
-- tem a sua. Como total_limit ≤ R$ 21 mil e available_limit só cai na
-- contratação, o teto do art. 3º V (saldo do tomador na mesma IF) sai do
-- próprio lock: contratações concorrentes do mesmo patrimônio disputam
-- esta linha, mesmo vindo de contas ou CNPJs diferentes.
CREATE TABLE credit_line (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key                     UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    customer_id             BIGINT NOT NULL UNIQUE,   -- raiz do patrimônio (id = exposure_customer_id)
    version                 INT  NOT NULL DEFAULT 1 CHECK (version >= 1),
    total_limit             BIGINT NOT NULL CHECK (total_limit > 0 AND total_limit <= 2100000),
    available_limit         BIGINT NOT NULL CHECK (available_limit >= 0),
    monthly_interest_rate   NUMERIC(9,6) NOT NULL CHECK (monthly_interest_rate > 0 AND monthly_interest_rate <= 0.04),
    origination_fee_rate    NUMERIC(9,6) NOT NULL CHECK (origination_fee_rate >= 0 AND origination_fee_rate <= 0.03),  -- TAC
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_limit CHECK (available_limit <= total_limit),
    CONSTRAINT ux_credit_line_customer UNIQUE (id, customer_id),  -- alvo da FK composta do loan
    -- só a raiz do patrimônio tem linha: EI/MEI usa a linha do dono
    CONSTRAINT fk_credit_line_root FOREIGN KEY (customer_id, customer_id)
        REFERENCES customer (id, exposure_customer_id)
);

-- Histórico append-only de cada PUT da IF (auditoria)
CREATE TABLE credit_line_version (
    credit_line_id          BIGINT NOT NULL REFERENCES credit_line(id),
    version                 INT  NOT NULL,
    total_limit             BIGINT NOT NULL,
    monthly_interest_rate   NUMERIC(9,6) NOT NULL,
    origination_fee_rate    NUMERIC(9,6) NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (credit_line_id, version)
);

-- Contrato de microcrédito
-- Três papéis, três colunas:
--   • customer_id          tomador: o CPF ou CNPJ que assina (é o que vai ao SCR)
--   • account_id           conta do tomador que recebe o desembolso e paga
--   • exposure_customer_id patrimônio que responde (= dono da credit_line)
CREATE TABLE loan (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key                         UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    account_id                  BIGINT NOT NULL,
    customer_id                 BIGINT NOT NULL,
    exposure_customer_id        BIGINT NOT NULL,
    credit_line_id              BIGINT NOT NULL,
    credit_line_version         INT  NOT NULL,
    idempotency_key             TEXT NOT NULL UNIQUE,
    request_hash                CHAR(64) NOT NULL,       -- SHA-256 do payload
    principal_amount            BIGINT NOT NULL CHECK (principal_amount > 0 AND principal_amount <= 2100000),
    installment_count           SMALLINT NOT NULL CHECK (installment_count BETWEEN 2 AND 24),
    term_days                   SMALLINT NOT NULL CHECK (term_days BETWEEN 60 AND 720),
    monthly_interest_rate       NUMERIC(9,6) NOT NULL CHECK (monthly_interest_rate <= 0.04),
    effective_fee_rate          NUMERIC(9,6) NOT NULL CHECK (effective_fee_rate <= 0.03),  -- TAC proporcional
    origination_fee_amount      BIGINT NOT NULL CHECK (origination_fee_amount >= 0),
    net_amount                  BIGINT NOT NULL,
    effective_cost_monthly      NUMERIC(9,6) NOT NULL,   -- CET a.m.
    effective_cost_annual       NUMERIC(9,6) NOT NULL,   -- CET a.a.
    purpose                     TEXT NOT NULL,
    sfn_debt_declaration        BOOLEAN NOT NULL CHECK (sfn_debt_declaration),  -- teto R$ 80k no SFN
    outstanding_principal       BIGINT NOT NULL CHECK (outstanding_principal >= 0),
    status_id                   SMALLINT NOT NULL REFERENCES loan_status(id),
    contracted_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    paid_off_at                 TIMESTAMPTZ,
    FOREIGN KEY (credit_line_id, credit_line_version)
        REFERENCES credit_line_version (credit_line_id, version),
    -- a conta é do tomador
    CONSTRAINT fk_loan_account FOREIGN KEY (account_id, customer_id)
        REFERENCES account (id, customer_id),
    -- o patrimônio é o do tomador (PF → ela; EI/MEI → o dono; sociedade → ela)
    CONSTRAINT fk_loan_exposure FOREIGN KEY (customer_id, exposure_customer_id)
        REFERENCES customer (id, exposure_customer_id),
    -- a linha é a desse patrimônio
    CONSTRAINT fk_loan_credit_line FOREIGN KEY (credit_line_id, exposure_customer_id)
        REFERENCES credit_line (id, customer_id),
    CONSTRAINT ck_net_amount CHECK (net_amount = principal_amount - origination_fee_amount),
    CONSTRAINT ck_paid_off CHECK ((status_id = 2) = (paid_off_at IS NOT NULL))  -- 2 = PAID_OFF
);
CREATE INDEX ix_loan_account_active  ON loan (account_id)           WHERE status_id = 1;  -- 1 = ACTIVE
CREATE INDEX ix_loan_exposure_active ON loan (exposure_customer_id) WHERE status_id = 1;  -- 1 = ACTIVE

CREATE TABLE loan_status_event (
    id              BIGINT   GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    loan_id         BIGINT     NOT NULL REFERENCES loan(id),
    from_status_id  SMALLINT REFERENCES loan_status(id),            -- nulo ao nascer
    to_status_id    SMALLINT NOT NULL REFERENCES loan_status(id),
    reason          VARCHAR(255),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_loan_status_event_changed CHECK (from_status_id IS DISTINCT FROM to_status_id)
);
CREATE INDEX ix_loan_status_event ON loan_status_event (loan_id, id);

CREATE TABLE installment (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key                 UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    loan_id             BIGINT NOT NULL REFERENCES loan(id),
    number              SMALLINT NOT NULL CHECK (number >= 1),
    due_date            DATE NOT NULL,                -- já ajustado a dia útil
    principal_amount    BIGINT NOT NULL CHECK (principal_amount >= 0),
    interest_amount     BIGINT NOT NULL CHECK (interest_amount >= 0),
    total_amount        BIGINT GENERATED ALWAYS AS (principal_amount + interest_amount) STORED,
    paid_amount         BIGINT NOT NULL DEFAULT 0 CHECK (paid_amount >= 0),
    status_id           SMALLINT NOT NULL REFERENCES installment_status(id),
    days_overdue        INT NOT NULL DEFAULT 0 CHECK (days_overdue >= 0),
    paid_at             TIMESTAMPTZ,
    UNIQUE (loan_id, number),
    CONSTRAINT ck_paid CHECK ((status_id = 4) = (paid_at IS NOT NULL))  -- 4 = PAID
);
-- Filtro do job de cobrança (v6: OPEN, PARTIAL e OVERDUE)
CREATE INDEX ix_installment_collection ON installment (due_date)
    WHERE status_id IN (1, 2, 3);  -- OPEN, PARTIAL, OVERDUE

CREATE TABLE installment_status_event (
    id              BIGINT   GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    installment_id  BIGINT     NOT NULL REFERENCES installment(id),
    from_status_id  SMALLINT REFERENCES installment_status(id),            -- nulo ao nascer
    to_status_id    SMALLINT NOT NULL REFERENCES installment_status(id),
    reason          VARCHAR(255),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_installment_status_event_changed CHECK (from_status_id IS DISTINCT FROM to_status_id)
);
CREATE INDEX ix_installment_status_event ON installment_status_event (installment_id, id);


CREATE TABLE loan_payment (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key              UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    loan_id          BIGINT NOT NULL REFERENCES loan(id),
    idempotency_key  TEXT UNIQUE,         -- NULL quando source = AUTO_COLLECTION
    request_hash     CHAR(64),
    source           enum_loan_payment_source NOT NULL,
    mode             enum_loan_payment_mode,
    amount           BIGINT NOT NULL CHECK (amount > 0),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_manual CHECK (
        (source = 'MANUAL'::enum_loan_payment_source AND idempotency_key IS NOT NULL AND mode IS NOT NULL)
     OR (source = 'AUTO_COLLECTION'::enum_loan_payment_source))
);

-- Como cada pagamento foi alocado nas parcelas (antecipação a valor presente)
CREATE TABLE payment_allocation (
    payment_id          BIGINT NOT NULL REFERENCES loan_payment(id),
    installment_id      BIGINT NOT NULL REFERENCES installment(id),
    principal_amount    BIGINT NOT NULL CHECK (principal_amount >= 0),
    interest_amount     BIGINT NOT NULL CHECK (interest_amount >= 0),
    prepayment_discount BIGINT NOT NULL DEFAULT 0 CHECK (prepayment_discount >= 0),  -- CDC art. 52 §2º
    PRIMARY KEY (payment_id, installment_id)
);

-- ---------------------------------------------------------------------
-- 4. Transferências (TEF · PIX · TED)
-- ---------------------------------------------------------------------
-- 4a. Chaves Pix dos NOSSOS clientes. É o registro que o DICT mock lê
--     para resolver um Pix entre contas da casa. Limite por conta
--     (PF 5, PJ 20) fica no PixKeyController.
CREATE TABLE pix_key (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key         UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    account_id  BIGINT NOT NULL REFERENCES account(id),
    key_type    enum_pix_key_type NOT NULL,
    key_value   VARCHAR(77) NOT NULL,
    status_id   SMALLINT NOT NULL REFERENCES pix_key_status(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- A mesma chave só vive em uma conta; apagada, pode renascer em outra.
CREATE UNIQUE INDEX ux_pix_key_active ON pix_key (key_value) WHERE status_id = 1;  -- ACTIVE
CREATE INDEX ix_pix_key_account ON pix_key (account_id) WHERE status_id = 1;       -- ACTIVE
 
CREATE TABLE pix_key_status_event (
    id              BIGINT   GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pix_key_id      BIGINT     NOT NULL REFERENCES pix_key(id),
    from_status_id  SMALLINT REFERENCES pix_key_status(id),            -- nulo ao nascer
    to_status_id    SMALLINT NOT NULL REFERENCES pix_key_status(id),
    reason          VARCHAR(255),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_pix_key_status_event_changed CHECK (from_status_id IS DISTINCT FROM to_status_id)
);
CREATE INDEX ix_pix_key_status_event ON pix_key_status_event (pix_key_id, id);
 
-- 4b. Consulta ao DICT (QI: GET /pix_key/{key}?account_key=). Devolve o
--     end_to_end_id que o Pix por chave TEM de usar. Duas regras da QI
--     viram integridade:
--       • o e2e vale só para a conta que consultou  → FK composta em transfer
--       • o e2e vale para UMA transferência          → UNIQUE em transfer
--     Registro de fato, append-only. "Foi usada" não é estado da consulta:
--     é existir uma transferência apontando para ela.
CREATE TABLE pix_key_inquiry (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key                     UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    account_id              BIGINT NOT NULL REFERENCES account(id),     -- quem consultou
    pix_key                 VARCHAR(77) NOT NULL,
    key_type                enum_pix_key_type NOT NULL,
    end_to_end_id           CHAR(32) NOT NULL UNIQUE
                            CHECK (end_to_end_id ~ '^E[0-9]{8}[0-9]{12}[A-Za-z0-9]{11}$'),
    -- resposta do DICT (documento sempre mascarado, como o BCB devolve)
    ispb                    CHAR(8) NOT NULL,
    account_branch          VARCHAR(4) NOT NULL,
    account_number          VARCHAR(20) NOT NULL,
    account_digit           CHAR(1),
    account_type            enum_external_account_type NOT NULL,
    owner_name              VARCHAR(120) NOT NULL,
    owner_masked_document   VARCHAR(18) NOT NULL,
    owner_person_type       enum_person_type NOT NULL,
    destination_account_id  BIGINT REFERENCES account(id),              -- preenchido se a chave é nossa
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at              TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_inquiry_window CHECK (expires_at > created_at),
    CONSTRAINT ux_inquiry_ref UNIQUE (id, account_id, end_to_end_id)  -- alvo da FK composta
);
CREATE INDEX ix_pix_key_inquiry_account ON pix_key_inquiry (account_id, created_at DESC);
 
-- 4c. Transferência de saída. Uma tabela para os três meios; as rotas da
--     API é que são separadas por trilho, como na QI.
CREATE TABLE transfer (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key                     UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    idempotency_key         TEXT NOT NULL UNIQUE,
    request_hash            CHAR(64) NOT NULL,
    source_account_id       BIGINT NOT NULL REFERENCES account(id),
    method                  enum_transfer_method NOT NULL,
    pix_transfer_type       enum_pix_transfer_type,
    amount                  BIGINT NOT NULL CHECK (amount > 0),
    fee                     BIGINT NOT NULL DEFAULT 0 CHECK (fee >= 0),
    status_id               SMALLINT NOT NULL REFERENCES transfer_status(id),
    on_us                   BOOLEAN NOT NULL DEFAULT FALSE,
    -- destino interno (TEF e PIX on-us)
    destination_account_id  BIGINT REFERENCES account(id),
    -- destino externo (QI target_account)
    pix_key                 TEXT,
    pix_key_inquiry_id      BIGINT UNIQUE,               -- e2e da consulta: uso único
    destination_ispb        CHAR(8),
    destination_branch      TEXT,
    destination_account     TEXT,
    destination_account_digit CHAR(1),
    destination_account_type enum_external_account_type,    
    destination_document    TEXT,
    destination_name        TEXT,
    pix_message             VARCHAR(140),                -- QI: até 140, sem emoji (controller)
    -- devolução de Pix RECEBIDO (QI: POST .../pix_transfer/{key}/reversal)
    original_incoming_transfer_id BIGINT,                -- FK no fim da seção (tabela circular)
    reversal_reason enum_reversal_reason,
    -- trilho
    end_to_end_id           TEXT UNIQUE,                 -- E… no Pix; D… na devolução
    str_control_number      TEXT UNIQUE,
    scheduled_for           DATE,
    failure_code            VARCHAR(20),                 -- código do trilho (ex. PXT000132)
    failure_reason          TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at            TIMESTAMPTZ,
    CONSTRAINT ck_same_account CHECK (destination_account_id IS DISTINCT FROM source_account_id),
    CONSTRAINT ck_destination_by_method CHECK (
        (method = 'TEF'::enum_transfer_method AND destination_account_id IS NOT NULL AND on_us)
     OR (method = 'PIX'::enum_transfer_method AND pix_transfer_type = 'KEY'::enum_pix_transfer_type
            AND pix_key IS NOT NULL AND pix_key_inquiry_id IS NOT NULL AND end_to_end_id IS NOT NULL
            AND on_us = (destination_account_id IS NOT NULL))
     OR (method = 'PIX'::enum_transfer_method AND pix_transfer_type = 'MANUAL'::enum_pix_transfer_type
            AND destination_ispb IS NOT NULL AND destination_branch IS NOT NULL
            AND destination_account IS NOT NULL AND destination_document IS NOT NULL
            AND destination_name IS NOT NULL AND destination_account_type IS NOT NULL
            AND on_us = (destination_account_id IS NOT NULL))
     OR (method = 'PIX'::enum_transfer_method AND pix_transfer_type = 'REVERSAL'::enum_pix_transfer_type AND NOT on_us
            AND destination_ispb IS NOT NULL)
     OR (method = 'TED'::enum_transfer_method AND destination_ispb IS NOT NULL AND destination_branch IS NOT NULL
            AND destination_account IS NOT NULL AND destination_document IS NOT NULL
            AND destination_name IS NOT NULL AND destination_account_type IS NOT NULL
            AND NOT on_us)),
    CONSTRAINT ck_pix_type_by_method CHECK ((method = 'PIX'::enum_transfer_method) = (pix_transfer_type IS NOT NULL)),
    CONSTRAINT ck_pix_message_only_pix CHECK (pix_message IS NULL OR method = 'PIX'::enum_transfer_method),
    CONSTRAINT ck_e2e_format CHECK (
        end_to_end_id IS NULL OR end_to_end_id ~ '^[ED][0-9]{8}[0-9]{12}[A-Za-z0-9]{11}$'),
    CONSTRAINT ck_reversal_link CHECK (
        COALESCE(pix_transfer_type = 'REVERSAL'::enum_pix_transfer_type, FALSE) = (original_incoming_transfer_id IS NOT NULL)
        AND (original_incoming_transfer_id IS NOT NULL) = (reversal_reason IS NOT NULL)),
    CONSTRAINT ck_scheduled CHECK ((status_id = 2) <= (scheduled_for IS NOT NULL)),
    CONSTRAINT fk_transfer_inquiry FOREIGN KEY (pix_key_inquiry_id, source_account_id, end_to_end_id)
        REFERENCES pix_key_inquiry (id, account_id, end_to_end_id)
);
-- Limite noturno: soma das saídas da conta na janela 20h–6h
CREATE INDEX ix_transfer_source_date ON transfer (source_account_id, created_at);
-- Jobs: TED agendada e reconciliação SPI/STR
CREATE INDEX ix_transfer_scheduled ON transfer (scheduled_for) WHERE status_id = 2;  -- SCHEDULED
CREATE INDEX ix_transfer_sent      ON transfer (updated_at)    WHERE status_id = 3;  -- SENT
-- Soma das devoluções ≤ valor recebido (QI PXT000017)
CREATE INDEX ix_transfer_reversal ON transfer (original_incoming_transfer_id)
    WHERE original_incoming_transfer_id IS NOT NULL;
 
-- Histórico de status: uma linha por transição, append-only (trigger na seção 7).
-- A coluna transfer.status_id é a verdade do agora; esta tabela é a verdade do que aconteceu.
CREATE TABLE transfer_status_event (
    id              BIGINT   GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    transfer_id     BIGINT     NOT NULL REFERENCES transfer(id),
    from_status_id  SMALLINT REFERENCES transfer_status(id),            -- nulo ao nascer
    to_status_id    SMALLINT NOT NULL REFERENCES transfer_status(id),
    reason          VARCHAR(255),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_transfer_status_event_changed CHECK (from_status_id IS DISTINCT FROM to_status_id)
);
CREATE INDEX ix_transfer_status_event ON transfer_status_event (transfer_id, id);
 
-- 4d. Entradas via webhook SPI/STR (idempotência por id externo).
--     QI incoming_pix: o tipo inclui "reversal", que aponta para o NOSSO
--     Pix de saída que está sendo devolvido (original_outgoing_pix_transfer).
CREATE TABLE incoming_transfer (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key                     UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    rail enum_transfer_rail NOT NULL,
    pix_transfer_type       enum_pix_transfer_type,
    external_id             TEXT NOT NULL,
    destination_account_id  BIGINT REFERENCES account(id),
    amount                  BIGINT NOT NULL CHECK (amount > 0),
    sender_name             TEXT,
    sender_document         TEXT,
    sender_ispb             CHAR(8),
    receiver_pix_key        VARCHAR(77),
    pix_message             VARCHAR(140),
    original_transfer_id    BIGINT REFERENCES transfer(id),
    status_id               SMALLINT NOT NULL REFERENCES incoming_transfer_status(id),  -- nasce final: sem eventos
    received_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (rail, external_id),
    CONSTRAINT ck_incoming_pix_type CHECK ((rail = 'SPI'::enum_transfer_rail) = (pix_transfer_type IS NOT NULL)),
    CONSTRAINT ck_incoming_reversal CHECK (
        COALESCE(pix_transfer_type = 'REVERSAL'::enum_pix_transfer_type, FALSE) = (original_transfer_id IS NOT NULL))
);
CREATE INDEX ix_incoming_original ON incoming_transfer (original_transfer_id)
    WHERE original_transfer_id IS NOT NULL;
 
ALTER TABLE transfer ADD CONSTRAINT fk_transfer_original_incoming
    FOREIGN KEY (original_incoming_transfer_id) REFERENCES incoming_transfer(id);
 
-- ---------------------------------------------------------------------
-- 5. Cartões (débito e crédito)
-- ---------------------------------------------------------------------
-- 5a. Carteira de crédito (QI: wallet). "Uma carteira = uma fatura":
--     limite, ciclo e encargos moram AQUI, não no cartão. O virtual, o
--     físico e a reemissão consomem o MESMO limite e caem na MESMA fatura.
--     Cartão só de débito não tem carteira: debita a conta, como o
--     pré-pago da QI.
CREATE TABLE credit_wallet (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key                    UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    account_id             BIGINT NOT NULL REFERENCES account(id), -- BIGINT
    status_id              SMALLINT NOT NULL REFERENCES credit_wallet_status(id),
    total_limit            BIGINT NOT NULL CHECK (total_limit >= 0),   -- informado pela IF
    used_limit             BIGINT NOT NULL DEFAULT 0 CHECK (used_limit >= 0),
    closing_day            SMALLINT NOT NULL CHECK (closing_day BETWEEN 1 AND 28),
    due_day                SMALLINT NOT NULL CHECK (due_day BETWEEN 1 AND 28),
    monthly_interest_rate  NUMERIC(7,6) NOT NULL CHECK (monthly_interest_rate >= 0),     -- rotativo
    fine_rate              NUMERIC(5,4) NOT NULL CHECK (fine_rate BETWEEN 0 AND 0.02),   -- multa: teto CDC art. 52
    autopay                BOOLEAN NOT NULL DEFAULT FALSE,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ux_wallet_account UNIQUE (id, account_id)               -- alvo da FK composta do cartão
    -- Sem CHECK used_limit <= total_limit: encargo do rotativo pode passar
    -- do limite. "Novo limite >= usado" (QI CIN000110) é regra do controller.
);
-- Uma carteira viva por conta (QI CIN000043 "Active wallet found" → 409)
CREATE UNIQUE INDEX ux_credit_wallet_live ON credit_wallet (account_id) WHERE status_id IN (1, 2);  -- ACTIVE, BLOCKED
 
CREATE TABLE credit_wallet_status_event (
    id                BIGINT   GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    credit_wallet_id  BIGINT     NOT NULL REFERENCES credit_wallet(id),
    from_status_id    SMALLINT REFERENCES credit_wallet_status(id),       -- nulo ao nascer
    to_status_id      SMALLINT NOT NULL REFERENCES credit_wallet_status(id),
    reason            VARCHAR(255),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_credit_wallet_status_event_changed CHECK (from_status_id IS DISTINCT FROM to_status_id)
);
CREATE INDEX ix_credit_wallet_status_event ON credit_wallet_status_event (credit_wallet_id, id);
 
-- 5b. O cartão é só o instrumento.
CREATE TABLE card (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key                   UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    account_id            BIGINT NOT NULL REFERENCES account(id), -- BIGINT
    wallet_id             BIGINT, -- BIGINT
    type                  enum_card_type NOT NULL,
    pan_token             TEXT NOT NULL UNIQUE,                 -- nunca o PAN em claro (PCI DSS)
    last4                 CHAR(4) NOT NULL,
    brand       enum_card_brand NOT NULL,
    functions   enum_card_functions NOT NULL,
    card_name             VARCHAR(15),                          -- apelido (QI card_name)
    printed_name          VARCHAR(26) NOT NULL,                 -- QI printed_name
    contactless_enabled   BOOLEAN,                              -- só físico
    activation_code_hash  CHAR(64),                             -- só físico; nunca o código em claro
    status_id             SMALLINT NOT NULL REFERENCES card_status(id),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- a carteira é da MESMA conta do cartão
    CONSTRAINT fk_card_wallet FOREIGN KEY (wallet_id, account_id) REFERENCES credit_wallet (id, account_id),
    CONSTRAINT ck_card_wallet CHECK ((functions = 'DEBIT'::enum_card_functions) = (wallet_id IS NULL)),
    CONSTRAINT ck_card_plastic CHECK (
        (type = 'PLASTIC'::enum_card_type) = (contactless_enabled IS NOT NULL)
        AND (type = 'PLASTIC'::enum_card_type) = (activation_code_hash IS NOT NULL))
);

CREATE INDEX ix_card_account ON card (account_id);
CREATE INDEX ix_card_wallet ON card (wallet_id) WHERE wallet_id IS NOT NULL;
 
CREATE TABLE card_status_event (
    id              BIGINT   GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    card_id         BIGINT     NOT NULL REFERENCES card(id),
    from_status_id  SMALLINT REFERENCES card_status(id),            -- nulo ao nascer
    to_status_id    SMALLINT NOT NULL REFERENCES card_status(id),
    reason          VARCHAR(255),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_card_status_event_changed CHECK (from_status_id IS DISTINCT FROM to_status_id)
);
CREATE INDEX ix_card_status_event ON card_status_event (card_id, id);
 
-- 5c. Autorização = HOLD (débito) ou reserva de limite (crédito).
--     O agregado guarda os totais correntes; cada movimento financeiro é
--     uma linha em card_authorization_event (enumerador da QI, 1 para 1).
CREATE TABLE card_authorization (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key                  UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    authorization_id     TEXT NOT NULL UNIQUE,     -- id da rede: idempotência
    card_id              BIGINT NOT NULL REFERENCES card(id),
    account_id           BIGINT NOT NULL REFERENCES account(id),
    function             enum_card_function NOT NULL,
    amount               BIGINT NOT NULL CHECK (amount > 0),          -- valor ORIGINAL pedido
    authorized_amount    BIGINT NOT NULL CHECK (authorized_amount >= 0),  -- após incrementais e reversões
    captured_amount      BIGINT NOT NULL DEFAULT 0 CHECK (captured_amount >= 0),
    refunded_amount      BIGINT NOT NULL DEFAULT 0 CHECK (refunded_amount >= 0),
    installment_count    SMALLINT NOT NULL DEFAULT 1 CHECK (installment_count BETWEEN 1 AND 24),
    merchant_name        TEXT,
    mcc                  CHAR(4),
    status_id            SMALLINT NOT NULL REFERENCES card_authorization_status(id),
    response_code        CHAR(2) NOT NULL,         -- ISO 8583: '00' aprovada · '51' saldo/limite …
    denial_reason  enum_denial_reason,
    approval_code        CHAR(6),
    expires_at           TIMESTAMPTZ,
    response_payload     JSONB NOT NULL,           -- replay idêntico em reenvio
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_refund_le_capture CHECK (refunded_amount <= captured_amount),
    CONSTRAINT ck_declined_reason CHECK ((status_id = 2) = (denial_reason IS NOT NULL)),
    CONSTRAINT ck_installments_credit CHECK (installment_count = 1 OR function = 'CREDIT'::enum_card_function)
);
-- Job de expiração de HOLD/reserva
CREATE INDEX ix_card_auth_expiry ON card_authorization (expires_at) WHERE status_id = 1;  -- APPROVED
CREATE INDEX ix_card_auth_card ON card_authorization (card_id, created_at);
 
CREATE TABLE card_authorization_status_event (
    id                     BIGINT   GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    card_authorization_id  BIGINT     NOT NULL REFERENCES card_authorization(id),
    from_status_id         SMALLINT REFERENCES card_authorization_status(id),   -- nulo ao nascer
    to_status_id           SMALLINT NOT NULL REFERENCES card_authorization_status(id),
    reason                 VARCHAR(255),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_card_authorization_status_event_changed CHECK (from_status_id IS DISTINCT FROM to_status_id)
);
CREATE INDEX ix_card_authorization_status_event ON card_authorization_status_event (card_authorization_id, id);
 
-- Movimentos financeiros da autorização. Substitui card_capture e
-- card_refund: captura e estorno viraram TIPOS de evento, ao lado de
-- incremental, reversão parcial e expiração, que antes não existiam.
CREATE TABLE card_authorization_event (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    card_authorization_id  BIGINT   NOT NULL REFERENCES card_authorization(id),
    type                   enum_card_auth_event_type NOT NULL,
    amount                 BIGINT NOT NULL CHECK (amount > 0),
    external_id            TEXT,      -- id da rede (capture_id, refund_id…): idempotência
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ux_card_auth_event_external ON card_authorization_event (type, external_id)
    WHERE external_id IS NOT NULL;
CREATE INDEX ix_card_auth_event ON card_authorization_event (card_authorization_id, id);
 
-- 5d. Fatura: da CARTEIRA, não do cartão.
CREATE TABLE invoice (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key                     UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    wallet_id               BIGINT NOT NULL REFERENCES credit_wallet(id),
    reference_month         DATE NOT NULL,              -- 1º dia do mês do fechamento
    status_id               SMALLINT NOT NULL REFERENCES invoice_status(id),
    closing_date            DATE NOT NULL,
    due_date                DATE NOT NULL,              -- ajustada a dia útil
    total_amount            BIGINT NOT NULL DEFAULT 0,
    paid_amount             BIGINT NOT NULL DEFAULT 0 CHECK (paid_amount >= 0),
    original_debt_amount    BIGINT,                     -- base do teto do rotativo
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ux_invoice_wallet_month UNIQUE (wallet_id, reference_month),
    CONSTRAINT ck_dates CHECK (due_date > closing_date)
);
CREATE UNIQUE INDEX ux_invoice_open ON invoice (wallet_id) WHERE status_id = 1;          -- OPEN
CREATE INDEX ix_invoice_closing ON invoice (closing_date) WHERE status_id = 1;           -- OPEN
CREATE INDEX ix_invoice_due     ON invoice (due_date)     WHERE status_id IN (2, 3);     -- CLOSED, PARTIALLY_PAID
 
CREATE TABLE invoice_status_event (
    id              BIGINT   GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_id      BIGINT   NOT NULL REFERENCES invoice(id),
    from_status_id  SMALLINT REFERENCES invoice_status(id),            -- nulo ao nascer
    to_status_id    SMALLINT NOT NULL REFERENCES invoice_status(id),
    reason          VARCHAR(255),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_invoice_status_event_changed CHECK (from_status_id IS DISTINCT FROM to_status_id)
);
CREATE INDEX ix_invoice_status_event ON invoice_status_event (invoice_id, id);
 
CREATE TABLE invoice_item (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key                    UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    invoice_id             BIGINT NOT NULL REFERENCES invoice(id),
    card_authorization_id  BIGINT REFERENCES card_authorization(id),
    type                   enum_invoice_item_type NOT NULL,
    amount                 BIGINT NOT NULL CHECK (amount <> 0),   -- estorno negativo
    installment_number     SMALLINT NOT NULL DEFAULT 1,
    installment_total      SMALLINT NOT NULL DEFAULT 1,
    description            TEXT,
    -- Encargo lançado pela IF (POST /invoice/{key}/charge): move dinheiro,
    -- então tem Idempotency-Key. Compra e estorno vêm da rede, sem chave.
    idempotency_key        TEXT UNIQUE,
    request_hash           CHAR(64),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_installment_range CHECK (installment_number BETWEEN 1 AND installment_total),
    CONSTRAINT ck_charge_idempotency CHECK (
        (type = 'REVOLVING_CHARGE'::enum_invoice_item_type) = (idempotency_key IS NOT NULL)
        AND (idempotency_key IS NULL) = (request_hash IS NULL))
);
CREATE INDEX ix_invoice_item ON invoice_item (invoice_id);
 
CREATE TABLE invoice_payment (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key              UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    invoice_id       BIGINT NOT NULL REFERENCES invoice(id),
    idempotency_key  TEXT UNIQUE,         -- NULL no débito automático
    request_hash     CHAR(64),
    source           enum_invoice_payment_source NOT NULL,
    amount           BIGINT NOT NULL CHECK (amount > 0),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_invoice_payment_manual CHECK (source = 'AUTOPAY'::enum_invoice_payment_source OR idempotency_key IS NOT NULL)
);
-- Débito automático: no máximo um por fatura
CREATE UNIQUE INDEX ux_invoice_payment_autopay ON invoice_payment (invoice_id) WHERE source = 'AUTOPAY'::enum_invoice_payment_source;

-- ---------------------------------------------------------------------
-- 6. Eventos para a IF (transactional outbox)
-- ---------------------------------------------------------------------
CREATE TABLE outbox_event (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    type            TEXT NOT NULL,   -- webhook_type no padrão QI: baas.pix_transfer.outgoing_pix, baas.card.status_change, ...
    aggregate_type  TEXT NOT NULL,
    aggregate_id    UUID NOT NULL,
    payload         JSONB NOT NULL,
    status_id       SMALLINT NOT NULL REFERENCES outbox_event_status(id),  -- técnico: sem eventos
    attempts        INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at         TIMESTAMPTZ
);
CREATE INDEX ix_outbox_pending ON outbox_event (id) WHERE status_id = 1;  -- PENDING
 
-- ---------------------------------------------------------------------
-- 7. Integridade do ledger
-- ---------------------------------------------------------------------
-- 7a. Imutável: nunca UPDATE/DELETE; estorno = novo lançamento.
CREATE FUNCTION fn_immutable_ledger() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION USING
        MESSAGE = 'ledger_entry is immutable (post a reversal entry instead)',
        ERRCODE = 'restrict_violation';
END $$;
 
CREATE TRIGGER tg_immutable_ledger
    BEFORE UPDATE OR DELETE ON ledger_entry
    FOR EACH ROW EXECUTE FUNCTION fn_immutable_ledger();
 
-- 7b. Partidas dobradas: no COMMIT, cada operation_id soma zero.
CREATE FUNCTION fn_double_entry() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE s BIGINT;
BEGIN
    SELECT COALESCE(SUM(amount), 0) INTO s FROM ledger_entry WHERE operation_id = NEW.operation_id;
    IF s <> 0 THEN
        RAISE EXCEPTION USING
            MESSAGE = 'operation ' || NEW.operation_id || ' is unbalanced (sum = ' || s || ')',
            ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END $$;
 
CREATE CONSTRAINT TRIGGER tg_double_entry
    AFTER INSERT ON ledger_entry
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION fn_double_entry();
 
-- 7c. Enumeradores e históricos de status: só INSERT.
--     • Enumerador: o id está citado em CHECKs e índices parciais; editar
--       ou apagar uma linha mudaria o significado deles em silêncio.
--       Estado novo entra por INSERT, com id novo.
--     • Evento: histórico que pode ser editado não é histórico.
CREATE FUNCTION fn_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION USING
        MESSAGE = TG_TABLE_NAME || ' is append-only (UPDATE and DELETE are refused)',
        ERRCODE = 'restrict_violation';
END $$;
 
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'kyc_status', 'account_status', 'loan_status', 'installment_status',
        'transfer_status', 'incoming_transfer_status', 'card_status',
        'card_authorization_status', 'invoice_status', 'outbox_event_status',
        'account_status_event', 'loan_status_event', 'installment_status_event',
        'transfer_status_event', 'card_status_event',
        'card_authorization_status_event', 'invoice_status_event',
        'pix_key_status', 'pix_key_status_event', 'pix_key_inquiry',
        'credit_wallet_status', 'credit_wallet_status_event',
        'card_authorization_event']
    LOOP
        EXECUTE 'CREATE TRIGGER ' || quote_ident('tg_' || t || '_append_only')
             || ' BEFORE UPDATE OR DELETE ON ' || quote_ident(t)
             || ' FOR EACH ROW EXECUTE FUNCTION fn_append_only()';
    END LOOP;
END $$;
 
 
-- ---------------------------------------------------------------------
-- 8. Views de apoio
-- ---------------------------------------------------------------------
-- Posição das contas internas (conciliação contra SPI, STR e bandeira)
CREATE VIEW vw_internal_account_balance AS
SELECT a.internal_code, COALESCE(SUM(l.amount), 0) AS balance
FROM account a LEFT JOIN ledger_entry l ON l.account_id = a.id
WHERE a.type = 'INTERNAL'::enum_account_type
GROUP BY a.internal_code;
 
-- Saldo de microcrédito por PATRIMÔNIO (Res. CMN 4.854 art. 3º V: teto
-- R$ 21 mil do tomador na mesma IF). Soma PF + EI/MEI do mesmo CPF e
-- todas as contas de cada um; sociedade fica sozinha.
CREATE VIEW vw_microcredit_balance AS
SELECT l.exposure_customer_id, SUM(l.outstanding_principal) AS microcredit_balance
FROM loan l JOIN loan_status s ON s.id = l.status_id
WHERE s.enumerator = 'ACTIVE'
GROUP BY l.exposure_customer_id;
 
-- ---------------------------------------------------------------------
-- 9. Seeds
-- ---------------------------------------------------------------------
INSERT INTO account (type, internal_code, status_id)
SELECT 'INTERNAL'::enum_account_type, v.code, s.id
FROM (VALUES
    ('LOAN_PORTFOLIO'), ('ORIGINATION_FEE_REVENUE'), ('INTEREST_REVENUE'),
    ('FEE_REVENUE'), ('SPI_SETTLEMENT'), ('STR_SETTLEMENT'), ('CARD_SETTLEMENT')
) AS v(code) CROSS JOIN account_status s WHERE s.enumerator = 'ACTIVE';

-- Toda conta nasce com um evento (null → status inicial), inclusive as internas.
INSERT INTO account_status_event (account_id, from_status_id, to_status_id, reason)
SELECT id, NULL, status_id, 'SEED' FROM account WHERE type = 'INTERNAL';
 
-- Tarifas — PREMISSAS DO TIME, ajustar antes da banca:
--   • TEF R$ 1,00: o bootcamp exige tarifa na transferência; sem ela o
--     requisito não aparece na demo.
--   • PIX zero: gratuito para pessoa natural, inclusive empresário
--     individual e MEI (Res. BCB 19/2020). Para sociedade (BUSINESS) a IF
--     PODE cobrar; zero aqui é premissa do time.
--   • TED R$ 10,00.
INSERT INTO fee (method, customer_segment, amount) VALUES
    ('TEF'::enum_transfer_method, 'INDIVIDUAL'::enum_customer_segment, 100),
    ('TEF'::enum_transfer_method, 'BUSINESS'::enum_customer_segment, 100),
    ('PIX'::enum_transfer_method, 'INDIVIDUAL'::enum_customer_segment, 0),
    ('PIX'::enum_transfer_method, 'BUSINESS'::enum_customer_segment, 0),
    ('TED'::enum_transfer_method, 'INDIVIDUAL'::enum_customer_segment, 1000),
    ('TED'::enum_transfer_method, 'BUSINESS'::enum_customer_segment, 1000);


-- Feriados nacionais (Lei 662/1949, Lei 6.802/1980 e Lei 14.759/2023, que
-- tornou 20/11 feriado nacional). Fixos e moveis (Carnaval, Sexta-feira
-- Santa e Corpus Christi) de 2026 e 2027. Feriados estaduais e municipais
-- ficam fora: a IF, que conhece a praca, informaria se preciso.
-- Dia util = nao e sabado/domingo e nao esta aqui.
INSERT INTO holiday (date, description) VALUES
    -- 2026
    ('2026-01-01', 'Confraternizacao Universal'),
    ('2026-02-16', 'Carnaval'),
    ('2026-02-17', 'Carnaval'),
    ('2026-04-03', 'Sexta-feira Santa'),
    ('2026-04-21', 'Tiradentes'),
    ('2026-05-01', 'Dia do Trabalho'),
    ('2026-06-04', 'Corpus Christi'),
    ('2026-09-07', 'Independencia do Brasil'),
    ('2026-10-12', 'Nossa Senhora Aparecida'),
    ('2026-11-02', 'Finados'),
    ('2026-11-15', 'Proclamacao da Republica'),
    ('2026-11-20', 'Dia da Consciencia Negra'),
    ('2026-12-25', 'Natal'),
    -- 2027
    ('2027-01-01', 'Confraternizacao Universal'),
    ('2027-02-08', 'Carnaval'),
    ('2027-02-09', 'Carnaval'),
    ('2027-03-26', 'Sexta-feira Santa'),
    ('2027-04-21', 'Tiradentes'),
    ('2027-05-01', 'Dia do Trabalho'),
    ('2027-05-27', 'Corpus Christi'),
    ('2027-09-07', 'Independencia do Brasil'),
    ('2027-10-12', 'Nossa Senhora Aparecida'),
    ('2027-11-02', 'Finados'),
    ('2027-11-15', 'Proclamacao da Republica'),
    ('2027-11-20', 'Dia da Consciencia Negra'),
    ('2027-12-25', 'Natal'),
    -- 2028 (contrato de ate 720 dias assinado hoje vence em 2028)
    ('2028-01-01', 'Confraternizacao Universal'),
    ('2028-02-28', 'Carnaval'),
    ('2028-02-29', 'Carnaval'),
    ('2028-04-14', 'Sexta-feira Santa'),
    ('2028-04-21', 'Tiradentes'),
    ('2028-05-01', 'Dia do Trabalho'),
    ('2028-06-15', 'Corpus Christi'),
    ('2028-09-07', 'Independencia do Brasil'),
    ('2028-10-12', 'Nossa Senhora Aparecida'),
    ('2028-11-02', 'Finados'),
    ('2028-11-15', 'Proclamacao da Republica'),
    ('2028-11-20', 'Dia da Consciencia Negra'),
    ('2028-12-25', 'Natal');
