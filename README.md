# EACHISMO — Motor de Decisão Antifraude Pix em Tempo Real

**Bootcamp QI Tech 2026 · Hackathon Risk Solutions**  
**Integrantes:** Gustavo Cerqueira, Nicolas, Gabriel

---

## 1. Como o motor de decisão funciona

Estamos projetando um motor antifraude transacional as a Service projetado para uma instituição financeira que tem como principais clientes pessoas físicas mas que também atende a PJ's (em sua maioria pequenos empresários e empreendedores individuais) . Ele envolve: **decisão em tempo real (< 500 ms)**, **visão de rede e histórico relacional** e **fricção cirúrgica com falso-positivo mínimo**.

O caminho de cada `POST /pix/transaction` segue um pipeline determinístico e auditável em **7 etapas**:

```
POST /pix/transaction
 │
 ├── ETAPA 0: Portaria & Segurança
 │     • Validação de INTERNAL-TOKEN, schema estrito e integridade semântica (CPF/CNPJ, fuso, datas, IP).
 │     • Consultas externas (Device API e DICT) executadas FORA do lock de banco (evita contenção de fila).
 │     • Lock transacional no Postgres (pg_advisory_xact_lock) ancorado na conta de origem: impede race-conditions em rajadas simultâneas.
 │     • Idempotência Canônica: hash SHA-256 sobre payload normalizado (espaços, zeros à esquerda e máscaras).
 │     • Upsert atômico dos nós de origem e destino no grafo relacional.
 │
 ├── ETAPA 1: Enriquecimento de Contexto
 │     • Carrega antes da gravação: histórico de 90 dias, estatísticas noturnas, geolocalizações,
 │       vínculos societários Receita (person_link CPF <-> CNPJ), personas/fraudes do DICT e
 │       fan-in, fan-out e volumes acumulados (entrada/saída) de origem e destino em 90 dias (R9).
 │
 ├── ETAPA 2: Motor de Regras Especializadas (R1 a R9 + N1, N2 e Sinais Extras)
 │     • Todas as regras rodam, mesmo depois de um REJECT: o metadata guarda todos os motivos.
 │     • Cada regra devolve {ação: NENHUMA | 2FA | REJECT, peso: 0..1, piso, desconto, motivo}.
 │
 ├── ETAPA 3: Inteligência de Grafos (A Vizinhança Suja)
 │     • Busca em largura (BFS) até K=3 saltos nos nós vizinhos no PostgreSQL.
 │     • Decaimento exponencial temporal (τ = 30 dias) e por salto (λ = 0.5).
 │     • Penalidade logarítmica de Hubs para evitar falso-positivo em contas com alto grau (ex: varejo, folha).
 │
 ├── ETAPA 4: Fusão de Risco Probabilística (Noisy-OR)
 │     • Combinação independente dos pesos via Noisy-OR: rules_score = 1 - Π(1 - w_i).
 │     • Família "desvio_valor" (R2 e R6): seleciona apenas o maior desvio (evita dupla contagem).
 │     • Desconto da R7 (Recorrência) aplicado exclusivamente sobre a família de desvio de valor.
 │     • Ponderação Assimétrica: Destino pesa 0.8 e Origem pesa 0.5 (o dinheiro do golpe vai para o destino).
 │
 ├── ETAPA 5: Decisão Explicável
 │     • 1. Ação REJECT explícita ou risk_score >= 0.85 ──> rejected
 │     • 2. Ação 2FA explícita ou risk_score >= 0.50 ──────> two_factor_required
 │     • 3. Caso contrário ─────────────────────────────────> approved
 │
 └── ETAPA 6: Gravação Atômica & Feedback Loop
       • Grava aresta (transaction_history) com peso real, metadados de explicabilidade e status.
       • Atualiza risco aprendido do nó destino (taxa 0.30) e origem (taxa 0.15) de forma atômica.
       • Commit da transação (libera o advisory lock) e retorna 201 Created
         (ou 200 com o mesmo veredito quando o mesmo "id" é reenviado com o mesmo conteúdo).
```

---

## 2. Regras Antifraude

| Regra | Lógica | Parâmetros | Por quê |
| :--- | :--- | :--- | :--- |
| **R1 · Limite de Dispositivo Novo** | Consulta cache local `registered_device` ou Device API externa. Se não cadastrado, limita valor e soma diária. | Max R$ 200/Pix (`20000`) e Max R$ 1.000/dia (`100000`): acima disso REJECT (sem piso). Dentro do limite: peso 0.15 (`dispositivo_nao_cadastrado`). Se API indisponível: 2FA + peso 0.30. | Regulamentação do Banco Central para aparelhos novos. Impede drenagem de conta por dispositivo recém-instalado sem prejudicar transações pequenas. |
| **R2 · Desvio do Padrão Noturno** | Compara a soma da noite atual (20h às 06h, ancorada no início) com a média noturna dos últimos 90 dias do próprio cliente. | Mínimo 3 noites com histórico. 3x a 5x a média: peso 0.20; > 5x a média: peso 0.40. Nunca rejeita por si só. | Respeita a autonomia do cliente que tem rotina noturna. Só adiciona peso se o valor fugir drasticamente do hábito pessoal daquela conta. |
| **R3 · Vínculo Conta x Documento** | Compara CPF/CNPJ do payload com o documento já verificado do nó no banco (sem depender de busca por conta no DICT). Só um nó verificado (que já foi origem) pode divergir, então a primeira transação de uma conta nunca cai aqui. | Divergência na Origem: REJECT (piso 0.80). Divergência no Destino verificado: REJECT sem piso (pode ser erro de digitação de quem paga). | Conta invadida ou envenenamento de payload. A origem é nossa cliente (titular garantido). |
| **R4 · Fraude na Pessoa (DICT & Societário)** | Consulta marcações no DICT (`MULE_ACCOUNT`, `SCAMMER_ACCOUNT`, `APPLICATION_FRAUD`) e infrações abertas (`SCAM`, `ACCOUNT_TAKEOVER`, `FRAUDULENT_ACCESS`, `COERCION`), expandindo para CPFs/CNPJs vinculados via `person_link`. | Titular (origem ou destino) marcado: REJECT (piso 1.0). Origem com infração `SCAM` aberta: REJECT. Origem com conta roubada/coagida: 2FA + peso 0.40. Destino em análise: 2FA + peso 0.40 (≤ R$ 500) ou 0.70 (> R$ 500). Vinculado marcado: 2FA + peso 0.60. Marcação `OTHER`/`UNKNOWN`: peso 0.30. DICT indisponível: 2FA + peso 0.30. | Barra fraudadores contumazes e protege vítimas sob sequestro/coerção, cascateando risco para o quadro societário. |
| **R5 · Localização Física Atípica** | Calcula velocidade geográfica em relação ao último Pix e distância do centróide das últimas 10 transações. | Distância > 50 km e velocidade > 900 km/h: 2FA + peso 0.30 (viagem impossível). Distância do centróide habitual > 100 km: 2FA + peso 0.30. Sem geo: peso 0.10. | Física inquestionável: um dispositivo não pode transacionar em São Paulo e 30 minutos depois em Recife. |
| **R6 · Valor Fora do Padrão (Estatística)** | $Z\text{-score}$ sobre o logaritmo dos valores transacionados nos últimos 90 dias ($z = \frac{\ln(amount) - \mu}{\sigma}$). | Mínimo 5 transações, piso de desvio padrão 0.2. $z > 3$: peso $\min(0.40, 0.10 \cdot (z - 2))$. Sem histórico e valor > R$ 5.000: peso 0.10. | A distribuição de valores bancários é log-normal. O $z\text{-score}$ logarítmico detecta outliers reais em ordens de grandeza sem penalizar pequenas variações. |
| **R7 · Pagamento Periódico / Recorrência** | Detecta pagamentos regulares e previsíveis para a mesma contraparte (aluguel, condomínio, mensalidade). | Só avalia se a R6 acionou. $\ge 3$ Pix aprovados em 180 dias, o primeiro há mais de 60 dias, periodicidade regular (7, 15 ou 30 dias $\pm 3$), valor $\pm 20\%$ da mediana. Desconto de 0.30 (teto total 0.50). | **Regra redutora de atrito e anti falso-positivo:** evita travar clientes bons no pagamento de contas recorrentes, amortizando o peso da família de valor. |
| **R8 · Velocity & Rajada** | Monitora frequência de disparos na origem, dispersão de aparelhos e atração de fundos no destino. | Origem: $\ge 5$ tentativas em 10 min ou $\ge 10$ em 1h $\rightarrow$ 2FA + peso 0.35. Destino: fan-in $\ge 10$ origens em 1h para conta < 30 dias (peso 0.30). Device em $\ge 3$ contas em 24h (peso 0.30). | Ataques automatizados, contas sequestradas esvaziadas em rajada, aparelhos emulados de quadrilha e funis receptores de laranjas. |
| **R9 · Conta de Passagem (Mula / Pass-through)** | Olha o comportamento acumulado da conta em 90 dias (só Pix não rejeitados), dos dois lados do Pix: a mula pode ser a origem (repassando agora) ou o destino (recebendo para repassar). | Fan-in $\ge 8$ origens distintas, fan-out $\le 3$ destinos distintos e razão saída/entrada $\ge 0.80$, os três juntos $\rightarrow$ 2FA + peso 0.40 (`origem_conta_passagem` / `destino_conta_passagem`). | Conta laranja recebe de muitos, repassa para poucos e não retém o dinheiro. A razão saída/entrada separa a mula do varejista legítimo, que recebe de muitos mas acumula. 2FA e não REJECT porque intermediadores legítimos existem. |
| **N1 · IP Compartilhado** | Mapeia múltiplos CPFs/CNPJs distintos operando a partir do mesmo endereço IP em janela curta. | $\ge 3$ contas de origem distintas no mesmo IP em 24h $\rightarrow$ peso 0.30 (`ip_compartilhado`). | Fazendas de contas, VPNs de quadrilhas e anéis de mulas operando no mesmo local físico ou rede comprometida. |
| **N2 · Combo de Tomada de Conta (ATO)** | Combina sinais periféricos: aparelho não cadastrado + IP nunca visto na origem (com histórico prévio) + destinatário inédito. | Presença simultânea dos 3 sinais $\rightarrow$ 2FA + peso 0.40 (`combo_tomada_conta`). | Padrão clássico de Account Takeover: invasor troca o aparelho, usa rede externa e tenta transferir para conta terceira. |
| **Sinais Extras** | Idade da conta de destino e ineditismo de contraparte. | Destino aberto há < 30 dias: peso 0.20. Primeiro Pix entre o par: peso 0.10. | Contas recém-criadas são o destino estatístico da maioria dos golpes de engenharia social. |

---

## 3. Como as regras viram decisão

A decisão final é obtida através de uma hierarquia rígida de avaliação:

1. **Ações Fixas Mandatórias:**
   * Se qualquer regra retornou **REJECT** (ex.: R1 limite de aparelho estourado, R3 divergência de titular, R4 titular com marcação de golpista/mula no DICT ou origem com infração `SCAM` aberta) $\rightarrow$ **`rejected`**.
2. **Limiar Crítico de Risco (Noisy-OR + Grafo):**
   * Se $risk\_score \ge 0.85$ $\rightarrow$ **`rejected`**.
3. **Fricção Cirúrgica (2FA):**
   * Se qualquer regra retornou **2FA** (ex.: R4 conta roubada, R5 viagem impossível, R8 rajada de velocity, R9 conta de passagem, N2 combo ATO, ou DICT/Device API indisponíveis) OU se $risk\_score \ge 0.50$ $\rightarrow$ **`two_factor_required`**.
4. **Fluidez Total:**
   * Caso contrário $\rightarrow$ **`approved`**.

### O Ciclo Completo de 2FA e Fraude Confirmada (D2 e D3)
* **`POST /pix/transaction/{id}/2fa`**: Registra o retorno do cliente (`approved` ou `rejected`). Pix pendentes contam no limite temporariamente com TTL de 15 minutos; se aprovados, consolidam a movimentação e aprendizado no grafo.
* **`POST /pix/transaction/{id}/fraud`**: Notificação de fraude confirmada (MED/contestação). Grava o status `rejected`, eleva a aresta transacional para peso $1.0$ e marca a conta receptora com `external_risk = 1.0`, permitindo que o grafo aprenda com fraudes reais rotuladas.

---

## 4. O Grafo de Contas & Propagação Temporal

* **Nó (`account_node`)**: Identificado por ISPB + Agência + Conta. Armazena risco factual (`external_risk` do DICT) e risco dinâmico (`risk_score`).
* **Decaimento Exponencial:** $R_{aprendido}(t) = risk\_score \cdot e^{-\Delta t / \tau}$, com $\tau = 30$ dias. O risco de nós suspeitos dissipa naturalmente na leitura, eliminando custos de jobs em lote.
* **Penalidade de Hubs:** A contribuição de nós vizinhos é atenuada por $\log_2(2 + degree)$, evitando falsos-positivos em grandes recebedores legítimos (marketplaces, concessionárias, folhas de pagamento).
* **Auditabilidade e Explicabilidade:** A tabela `metadata` grava `rules_score`, scores do grafo, pesos de cada regra (`rule_hits`), `engine_version` e o `graph_evidence` (as 3 contas a até 3 saltos que mais contribuíram para o score). A resposta da API expõe só `risk_score` e `reasons`: expor o peso de cada regra ensinaria o fraudador a ficar logo abaixo do limiar.

---

## 5. API

Todas as rotas exigem o header `INTERNAL-TOKEN` (padrão local: `default_token`), exceto `GET /` e `GET /health_check`. Valores sempre em centavos.

| Método | Rota | O que faz | Respostas |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | Nome do serviço e PID. | 200 |
| `GET` | `/health_check` | Liveness (usado pelo healthcheck do Docker). | 204 |
| `POST` | `/pix/transaction` | Analisa um Pix e devolve o veredito. | 201 analisado agora · 200 reenvio idempotente · 400 schema · 403 token · 409 mesmo `id` com outro conteúdo · 422 validação semântica |
| `GET` | `/pix/transaction/{id}` | Veredito mais recente do Pix pelo `id` do payload. | 200 · 404 |
| `POST` | `/pix/transaction/{id}/2fa` | Resultado do 2FA: `{"status": "approved" \| "rejected"}`. | 200 · 404 |
| `POST` | `/pix/transaction/{id}/fraud` | Fraude confirmada (MED/contestação). | 200 · 404 |
| `POST` | `/person_link` | Vínculo CPF <-> CNPJ usado pela R4: `{"cpf", "cnpj", "relation": "PARTNER" \| "SOLE_PROPRIETOR" \| "ADMINISTRATOR"}`. | 201 criado · 200 já existia |

Não existe rota de cadastro de dispositivo: `registered_device` é cache interno, gravado só quando a Device API externa confirma o aparelho (R1).

### Exemplo: `POST /pix/transaction`
```bash
curl -X POST http://localhost:3000/pix/transaction \
  -H "Content-Type: application/json" \
  -H "INTERNAL-TOKEN: default_token" \
  -d '{
    "id": "pix-000123",
    "amount": 150000,
    "transaction_date": "2026-10-17T22:15:00-03:00",
    "source_account": {
      "branch": "0001",
      "account_number": "123456",
      "opening_date": "2025-03-02T10:00:00-03:00",
      "owner": {"document_number": "529.982.247-25"}
    },
    "destination_account": {
      "participant": "60701190",
      "branch": "3675",
      "account_number": "987654",
      "opening_date": "2026-10-10T09:00:00-03:00",
      "owner": {"document_number": "11.222.333/0001-81"}
    },
    "source": {
      "device_id": "dvc-9f2c71a8",
      "channel": "app",
      "ip": "10.0.0.1",
      "geolocation": {"latitude": -23.56, "longitude": -46.65}
    }
  }'
```

`source_account.participant` é opcional: a origem é sempre desta instituição (`INSTITUTION_ISPB`). `geolocation` também é opcional (sem ela a R5 soma peso 0.10).

Resposta:
```json
{
  "key": "<uuid do veredito>",
  "status": "approved | two_factor_required | rejected",
  "metadata": {
    "risk_score": 0.28,
    "reasons": ["limite_dispositivo_novo", "destino_conta_nova", "destino_desconhecido"]
  }
}
```

---

## 6. Como rodar e testar

### Pré-requisitos
* Docker & Docker Compose
* Python 3.11+ (só para rodar os testes na sua máquina)

### Subindo o ambiente
```bash
# Sobe a API (porta 3000), o PostgreSQL (5432) e o MockServer (1080),
# que simula a Device API (R1) e o DICT (R4).
docker compose up -d --build
```

O `.env` é opcional: todas as variáveis têm valor padrão no `docker-compose.yml`. Crie um (`cp .env.example .env`) só para trocar porta, token ou host. O código em `src/` é montado no container com `--reload`, então salvar um arquivo reinicia a API.

Antes de rodar os testes, espere a API ficar `healthy`:
```bash
docker compose ps
```

### Executando a suíte de testes
```bash
pip install -r requirements-dev.txt

# Na raiz do repositório: o pytest descobre todos os test_*.py de todas as pastas em tests/
pytest -v
```

Os testes são black box: falam com a API de pé por HTTP (e cadastram respostas no MockServer) e conferem só status e corpo. Nenhum teste importa o `src/` nem lê o banco. Cada sessão começa com o MockServer zerado, e cada teste sorteia ids, contas, documentos e dispositivos, então a suíte pode rodar várias vezes sobre o mesmo banco.

| Pasta | Cobre |
| :--- | :--- |
| `tests/integration/test_healthcheck.py` | `/` e `/health_check` |
| `tests/integration/pix_transaction/` | Contrato do `POST /pix/transaction` e `GET /pix/transaction/{id}`, token, schema, validações de CPF/CNPJ/datas/IP e idempotência (200 e 409) |
| `tests/integration/antifraud/` | Regras R1 a R9, N1, N2, sinais extras, rajada concorrente da mesma origem e propagação no grafo |
| `tests/integration/registration/` | `POST /person_link` e ausência de rota de cadastro de dispositivo |
| `tests/utils/` | Geradores de payload e mocks da Device API e do DICT (não são testes) |

Os testes leem `SERVER_LOCALHOST`, `API_PORT`, `MOCK_HOST` e `MOCK_PORT` do `.env` (se existir). No Windows, se aparecer erro de conexão com `0.0.0.0`, defina `SERVER_LOCALHOST=localhost` no `.env`.


