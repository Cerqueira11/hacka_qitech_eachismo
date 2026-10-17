CREATE TYPE enum_status_result AS ENUM ('approved', 'rejected', 'two_factor_required');

CREATE TABLE geolocation (
    id_geolocation UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    longitude      NUMERIC(11, 8) NOT NULL,  -- -180 a 180
    latitude       NUMERIC(10, 8) NOT NULL   -- -90 a 90
);

CREATE TABLE transaction_history (
    key_pix                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    amount                     BIGINT NOT NULL,
    source_document_number     CHAR(14) NOT NULL,
    destination_document_number CHAR(14) NOT NULL,
    source_account_branch      INT NOT NULL,
    source_account_number      INT NOT NULL,
    destination_account_branch INT NOT NULL,
    destination_account_number INT NOT NULL,
    source_device_id           VARCHAR(50) NOT NULL,
    source_device_channel      VARCHAR(50) NOT NULL,
    source_ip                  INET NOT NULL,  -- aceita IPv4 e IPv6
    source_geolocation         UUID REFERENCES geolocation (id_geolocation),
    transaction_date           TIMESTAMPTZ NOT NULL
);

-- Busca por valor exato da conta de origem / destino (agência + número)
CREATE INDEX ix_transaction_history_source_account
    ON transaction_history (source_account_branch, source_account_number);
CREATE INDEX ix_transaction_history_destination_account
    ON transaction_history (destination_account_branch, destination_account_number);
CREATE INDEX ix_transaction_history_source_document_number
    ON transaction_history (source_document_number);
CREATE INDEX ix_transaction_history_destination_document_number
    ON transaction_history (destination_document_number);

-- TODO: campos ainda não definidos
CREATE TABLE metadata (
    key_metadata UUID PRIMARY KEY DEFAULT gen_random_uuid()
);

CREATE TABLE status_result_history (
    key          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_pix      BIGINT REFERENCES transaction_history (key_pix),
    status       enum_status_result NOT NULL,
    date         TIMESTAMPTZ NOT NULL,
    metadata_key UUID REFERENCES metadata (key_metadata)
);
