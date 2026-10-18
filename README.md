# EACHISMO — Motor de Decisão Antifraude Pix em Tempo Real

**Bootcamp QI Tech 2026 · Hackathon Risk Solutions**  
**Integrantes:** Gustavo Cerqueira, Nicolas, Gabriel

---

## 1. Como o motor de decisão funciona

O **EACHISMO** é um motor antifraude transacional projetado para o ecossistema Pix da QI Tech. Ele resolve o trilema do Pix: **decisão em tempo real (< 500 ms)**, **visão de rede e histórico relacional** e **fricção cirúrgica com falso-positivo mínimo**.

O caminho de cada `POST /pix/transaction` segue um pipeline determinístico e auditável em **7 etapas**:

```
POST /pix/transaction
 │
 ├── ETAPA 0: Portaria & Segurança
 │     • Validação de INTERNAL-TOKEN, schema estrito e integridade semântica (CPF/CNPJ, fuso, datas).
 │     • Consultas externas (Device API e DICT) executadas FORA do lock de banco (evita contenção de fila).
 │     • Lock transacional no Postgres (pg_advisory_xact_lock) ancorado na conta de origem: impede race-conditions em rajadas simultâneas.
 │     • Idempotência Canônica: hash SHA-256 sobre payload normalizado (espaços, zeros à esquerda e máscaras).
 │     • Upsert atômico dos nós de origem e destino no grafo relacional.
 │
 ├── ETAPA 1: Enriquecimento de Contexto
 │     • Carrega antes da gravação: histórico de 90 dias, estatísticas noturnas, geolocalizações,
 │       vínculos societários Receita (person_link CPF <-> CNPJ) e personas/fraudes do DICT.
 │
 ├── ETAPA 2: Motor de Regras Especializadas (R1 a R8 + N1, N2 e Extras)
 │     • Avaliação simultânea de 10 dimensões de risco comportamentais, estatísticas e cadastrais.
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
       • Commit da transação (libera o advisory lock) e retorna 201 Created.
```

---

## 2. Regras Antifraude

| Regra | Lógica | Parâmetros | Por quê |
| :--- | :--- | :--- | :--- |
| **R1 · Limite de Dispositivo Novo** | Consulta cache local `registered_device` ou Device API externa. Se não cadastrado, limita valor e soma diária. | Max R$ 200/Pix (`20000`) e Max R$ 1.000/dia (`100000`). Se API indisponível: 2FA + peso 0.30. | Regulamentação do Banco Central para aparelhos novos. Impede drenagem de conta por dispositivo recém-instalado sem prejudicar transações pequenas. |
| **R2 · Desvio do Padrão Noturno** | Compara a soma da noite atual (20h às 06h, ancorada no início) com a média noturna dos últimos 90 dias do próprio cliente. | Mínimo 3 noites com histórico. 3x a 5x a média: peso 0.20; > 5x a média: peso 0.40. Nunca rejeita por si só. | Respeita a autonomia do cliente que tem rotina noturna. Só adiciona peso se o valor fugir drasticamente do hábito pessoal daquela conta. |
| **R3 · Vínculo Conta x Documento** | Compara CPF/CNPJ do payload com o documento já verificado do nó no banco (sem depender de busca por conta no DICT). Integração com `person_link`. | Divergência na Origem: REJECT (piso 0.80). Divergência no Destino: REJECT sem piso. Vínculo societário CPF<->CNPJ aceito. | Conta invadida ou envenenamento de payload. A origem é nossa cliente (titular garantido). Destino aceita MEI/sócios vinculados via `person_link`. |
| **R4 · Fraude na Pessoa (DICT & Societário)** | Consulta ocorrências no DICT (`MULE_ACCOUNT`, `SCAMMER_ACCOUNT`, `APPLICATION_FRAUD`) e infrações abertas (`ACCOUNT_TAKEOVER`, `COERCION`), expandindo para sócios. | Titular marcado: REJECT (piso 1.0). Infração aberta de roubo/coerção: 2FA + peso 0.40. Sócio/vinculado marcado: 2FA + peso 0.60. Destino em análise: 2FA + peso 0.40 (≤ R$ 500) ou 0.70 (> R$ 500). | Barra fraudadores contumazes e protege vítimas sob sequestro/coerção, cascateando risco para o quadro societário. |
| **R5 · Localização Física Atípica** | Calcula velocidade geográfica em relação ao último Pix e distância do centróide das últimas 10 transações. | Distância > 50 km e velocidade > 900 km/h: 2FA + peso 0.30 (viagem impossível). Distância do centróide habitual > 100 km: 2FA + peso 0.30. Sem geo: peso 0.10. | Física inquestionável: um dispositivo não pode transacionar em São Paulo e 30 minutos depois em Recife. |
| **R6 · Valor Fora do Padrão (Estatística)** | $Z\text{-score}$ sobre o logaritmo dos valores transacionados nos últimos 90 dias ($z = \frac{\ln(amount) - \mu}{\sigma}$). | Mínimo 5 transações, piso de desvio padrão 0.2. $z > 3$: peso $\min(0.40, 0.10 \cdot (z - 2))$. Sem histórico e valor > R$ 5.000: peso 0.10. | A distribuição de valores bancários é log-normal. O $z\text{-score}$ logarítmico detecta outliers reais em ordens de grandeza sem penalizar pequenas variações. |
| **R7 · Pagamento Periódico / Recorrência** | Detecta pagamentos regulares e previsíveis para a mesma contraparte (aluguel, condomínio, mensalidade). | $\ge 3$ Pix aprovados em 180 dias, periodicidade regular (7, 15 ou 30 dias $\pm 3$), valor $\pm 20\%$ da mediana. Desconto de até 0.30. | **Regra redutora de atrito e anti falso-positivo:** evita travar clientes bons no pagamento de contas recorrentes, amortizando o peso da família de valor. |
| **R8 · Velocity & Rajada** | Monitora frequência de disparos na origem, dispersão de aparelhos e atração de fundos no destino. | Origem: $\ge 5$ tentativas em 10 min ou $\ge 10$ em 1h $\rightarrow$ 2FA + peso 0.35. Destino: fan-in $\ge 10$ origens em 1h para conta < 30 dias (peso 0.30). Device em $\ge 3$ contas em 24h (peso 0.30). | Ataques automatizados, contas sequestradas esvaziadas em rajada, aparelhos emulados de quadrilha e funis receptores de laranjas. |
| **N1 · IP Compartilhado** | Mapeia múltiplos CPFs/CNPJs distintos operando a partir do mesmo endereço IP em janela curta. | $\ge 3$ contas de origem distintas no mesmo IP em 24h $\rightarrow$ peso 0.30 (`ip_compartilhado`). | Fazendas de contas, VPNs de quadrilhas e anéis de mulas operando no mesmo local físico ou rede comprometida. |
| **N2 · Combo de Tomada de Conta (ATO)** | Combina sinais periféricos: aparelho não cadastrado + IP nunca visto na origem (com histórico prévio) + destinatário inédito. | Presença simultânea dos 3 sinais $\rightarrow$ 2FA + peso 0.40 (`combo_tomada_conta`). | Padrão clássico de Account Takeover: invasor troca o aparelho, usa rede externa e tenta transferir para conta terceira. |
| **Sinais Extras** | Idade da conta de destino e ineditismo de contraparte. | Destino aberto há < 30 dias: peso 0.20. Primeiro Pix entre o par: peso 0.10. | Contas recém-criadas são o destino estatístico da maioria dos golpes de engenharia social. |

---

## 3. Como as regras viram decisão

A decisão final é obtida através de uma hierarquia rígida de avaliação:

1. **Ações Fixas Mandatórias:**
   * Se qualquer regra retornou **REJECT** (ex.: R1 limite de aparelho estourado, R3 divergência de titular, R4 titular com marcação de golpista/mula no DICT) $\rightarrow$ **`rejected`**.
2. **Limiar Crítico de Risco (Noisy-OR + Grafo):**
   * Se $risk\_score \ge 0.85$ $\rightarrow$ **`rejected`**.
3. **Fricção Cirúrgica (2FA):**
   * Se qualquer regra retornou **2FA** (ex.: R4 conta roubada, R5 viagem impossível, R8 rajada de velocity, N2 combo ATO, ou DICT/Device API indisponíveis) OU se $risk\_score \ge 0.50$ $\rightarrow$ **`two_factor_required`**.
4. **Fluidez Total:**
   * Caso contrário $\rightarrow$ **`approved`**.

### O Ciclo Completo de 2FA e Fraude Confirmada (D2 e D3)
* **`POST /pix/transaction/{id}/2fa`**: Registra o retorno do cliente (`approved` ou `rejected`). Pix pendentes contam no limite temporariamente com TTL de 15 minutos; se aprovados, consolidam a movimentação e aprendizado no grafo.
* **`POST /pix/transaction/{id}/fraud`**: Notificação de fraude confirmada (MED/contestação). Eleva a aresta transacional para peso $1.0$ e marca a conta receptora com `external_risk = 1.0`, permitindo que o grafo aprenda com fraudes reais rotuladas.

---

## 4. O Grafo de Contas & Propagação Temporal

* **Nó (`account_node`)**: Identificado por ISPB + Agência + Conta. Armazena risco factual (`external_risk` do DICT) e risco dinâmico (`risk_score`).
* **Decaimento Exponencial:** $R_{aprendido}(t) = risk\_score \cdot e^{-\Delta t / \tau}$, com $\tau = 30$ dias. O risco de nós suspeitos dissipa naturalmente na leitura, eliminando custos de jobs em lote.
* **Penalidade de Hubs:** A contribuição de nós vizinhos é atenuada por $\log_2(2 + degree)$, evitando falsos-positivos em grandes recebedores legítimos (marketplaces, concessionárias, folhas de pagamento).
* **Auditabilidade e Explicabilidade:** O metadata da resposta identifica exatamente quais nós e arestas a até 3 saltos motivaram o aumento do score.

---

## 5. Como rodar e testar

### Pré-requisitos
* Python 3.11+
* Docker & Docker Compose

### Subindo o ambiente completo
```bash
# 1. Copiar variáveis de ambiente
cp .env.example .env

# 2. Subir os serviços (PostgreSQL e MockServer)
docker compose up -d

# 3. Rodar a aplicação localmente (ou via container)
uvicorn app:app --host 0.0.0.0 --port 8000 --app-dir src
```

### Executando a Suíte de Testes
```bash
# Todos os testes são black box: falam com a API de pé por HTTP e conferem
# só status e corpo. Nenhum teste importa o src/ nem lê o banco.
# (regras R1-R9, N1/N2, idempotência, concorrência e grafo)
pytest tests/integration/ -v
```

### Simulação de Estresse com 50.000 Transações Sintéticas
Para validar a resiliência, latência e calibração estatística do motor sob carga massiva de produção:
```powershell
python -m tests.run_dict_random_scenarios --count 50000 --seed 42
```
Este comando gera transações variando CPFs/CNPJs, contas, horários ao longo de 90 dias, dispersão geográfica e personas do DICT, exportando os resultados consolidados e métricas em planilhas Excel em `tests/logs/`.
