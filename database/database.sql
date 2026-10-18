-- ─────────────────────────────────────────────────────────────────────
-- Antifraude Pix: o banco é um grafo.
--   nó     = account_node        (uma conta transacional: ISPB + agência + conta)
--   aresta = transaction_history (um Pix de uma conta para outra, com risk_score 0..1)
-- O veredito de cada Pix fica em status_result_history e o porquê em metadata.
-- ─────────────────────────────────────────────────────────────────────

CREATE TYPE enum_status_result AS ENUM ('approved', 'rejected', 'two_factor_required');

-- Nó do grafo. Agência + conta sozinhas colidem entre bancos, por isso a
-- identidade inclui o participante (ISPB).
CREATE TABLE account_node (
    id_account      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    participant     CHAR(8)      NOT NULL,                -- ISPB
    branch          VARCHAR(4)   NOT NULL,                -- normalizada com zeros à esquerda: '0001'
    account_number  VARCHAR(20)  NOT NULL,                -- só dígitos, sem zeros à esquerda
    document_number VARCHAR(14)  NOT NULL,                -- CPF (11) ou CNPJ (14), só dígitos/letras
    -- true quando a conta já foi ORIGEM (conta nossa): o documento é o do
    -- nosso cadastro. Destino nunca verifica nem altera o documento (R3, C2).
    document_verified BOOLEAN    NOT NULL DEFAULT false,
    person_type     CHAR(2)      NOT NULL CHECK (person_type IN ('PF', 'PJ')),
    opening_date    TIMESTAMPTZ,                          -- vem do DICT (Account.OpeningDate)
    -- Fato: o que o DICT diz do titular (1.0 marcado, 0.6 em análise, 0.3 sinal fraco). Não decai.
    external_risk   NUMERIC(5, 4) NOT NULL DEFAULT 0 CHECK (external_risk BETWEEN 0 AND 1),
    -- Estimativa: risco aprendido com os Pix da conta. Decai com o tempo a
    -- partir de risk_updated_at (o decaimento é calculado na leitura).
    -- No grafo, R(u) = max(external_risk, risk_score decaído).
    risk_score      NUMERIC(5, 4) NOT NULL DEFAULT 0 CHECK (risk_score BETWEEN 0 AND 1),
    risk_updated_at TIMESTAMPTZ,
    degree          INT          NOT NULL DEFAULT 0 CHECK (degree >= 0),                     -- nº de contrapartes distintas
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_account_node_identity UNIQUE (participant, branch, account_number)
);

CREATE INDEX ix_account_node_document_number ON account_node (document_number);

-- Vínculo CPF <-> CNPJ (regra 4). Não vem do DICT: vem do quadro societário
-- da Receita / KYC (mockado).
CREATE TABLE person_link (
    cpf        CHAR(11)    NOT NULL,
    cnpj       CHAR(14)    NOT NULL,
    relation   VARCHAR(20) NOT NULL CHECK (relation IN ('PARTNER', 'SOLE_PROPRIETOR', 'ADMINISTRATOR')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (cpf, cnpj)
);

CREATE INDEX ix_person_link_cnpj ON person_link (cnpj);

-- Dispositivos cadastrados do cliente. Alimentada por POST /device.
-- A R1 NÃO lê mais esta tabela: pergunta à API externa de dispositivo (S2).
CREATE TABLE registered_device (
    document_number VARCHAR(14) NOT NULL,
    device_id       VARCHAR(50) NOT NULL,
    registered_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (document_number, device_id)
);

CREATE TABLE geolocation (
    id_geolocation UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    longitude      NUMERIC(11, 8) NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    latitude       NUMERIC(10, 8) NOT NULL CHECK (latitude BETWEEN -90 AND 90)
);

-- Aresta do grafo.
CREATE TABLE transaction_history (
    key_pix                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    transaction_id         VARCHAR(64) NOT NULL,          -- "id" recebido no POST (idempotência)
    amount                 BIGINT      NOT NULL CHECK (amount > 0),  -- centavos
    source_account_id      UUID        NOT NULL REFERENCES account_node (id_account),
    destination_account_id UUID        NOT NULL REFERENCES account_node (id_account),
    source_device_id       VARCHAR(50) NOT NULL,
    source_device_channel  VARCHAR(50) NOT NULL,
    source_ip              INET        NOT NULL,          -- aceita IPv4 e IPv6
    source_geolocation     UUID REFERENCES geolocation (id_geolocation),
    risk_score             NUMERIC(5, 4) CHECK (risk_score BETWEEN 0 AND 1),  -- peso da aresta
    -- SHA-256 do payload normalizado: mesmo "id" com outro corpo -> 409 (C4).
    -- NULL só em linhas gravadas antes da v2.
    payload_sha256         CHAR(64),
    -- Resposta da API de dispositivo no momento do Pix (S2): true/false, ou
    -- NULL quando ela estava indisponível. Base da soma diária da R1.
    device_registered      BOOLEAN,
    transaction_date       TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_transaction_history_transaction_id UNIQUE (transaction_id)
);

-- Janelas de tempo por conta (velocity, limite diário, padrão noturno) e
-- travessia do grafo nos dois sentidos.
CREATE INDEX ix_transaction_history_source_account_date
    ON transaction_history (source_account_id, transaction_date DESC);
CREATE INDEX ix_transaction_history_destination_account_date
    ON transaction_history (destination_account_id, transaction_date DESC);
CREATE INDEX ix_transaction_history_device_date
    ON transaction_history (source_device_id, transaction_date DESC);

-- O porquê do veredito (explicabilidade).
CREATE TABLE metadata (
    key_metadata            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    risk_score              NUMERIC(5, 4) CHECK (risk_score BETWEEN 0 AND 1),
    rules_score             NUMERIC(5, 4) CHECK (rules_score BETWEEN 0 AND 1),
    graph_source_score      NUMERIC(5, 4) CHECK (graph_source_score BETWEEN 0 AND 1),
    graph_destination_score NUMERIC(5, 4) CHECK (graph_destination_score BETWEEN 0 AND 1),
    rule_hits               JSONB NOT NULL DEFAULT '[]',  -- [{rule, action, weight, reason}]
    graph_evidence          JSONB NOT NULL DEFAULT '[]',  -- [{account, distance, risk}]
    engine_version          VARCHAR(20),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Histórico de vereditos de um Pix (ex.: two_factor_required -> approved).
CREATE TABLE status_result_history (
    key          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_pix      BIGINT NOT NULL REFERENCES transaction_history (key_pix),
    status       enum_status_result NOT NULL,
    date         TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata_key UUID REFERENCES metadata (key_metadata)
);

CREATE INDEX ix_status_result_history_key_pix_date
    ON status_result_history (key_pix, date DESC);
