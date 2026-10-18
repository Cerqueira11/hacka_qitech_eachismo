"""Parâmetros do motor antifraude.

Todos os limiares e pesos das regras (README.md, seção 2) moram aqui:
ponto de partida a calibrar, não decisão final. Valores em centavos.
"""

from datetime import timedelta, timezone

ENGINE_VERSION = "2.0.0"

# Brasil sem horário de verão desde 2019: UTC-3 fixo.
BRASILIA = timezone(timedelta(hours=-3))
NIGHT_START_HOUR = 20  # 20h00 ...
NIGHT_END_HOUR = 6     # ... até 05h59

# Históricos
HISTORY_WINDOW_DAYS = 90
LOG_STD_FLOOR = 0.2  # desvio mínimo em ln(valor): evita z infinito para quem paga sempre o mesmo valor

# R1 — dispositivo não cadastrado (limite de dispositivo novo). O cadastro
# vem de registered_device ou, se não estiver lá, da API externa de dispositivo.
UNREGISTERED_DEVICE_TX_LIMIT = 20_000
UNREGISTERED_DEVICE_DAILY_LIMIT = 100_000
UNREGISTERED_DEVICE_WEIGHT = 0.15
DEVICE_API_UNAVAILABLE_WEIGHT = 0.30

# R2 — desvio do padrão noturno (só peso, nunca REJECT) (a calibrar)
NIGHT_LOOKBACK_DAYS = 90
NIGHT_MIN_NIGHTS = 3             # noites com Pix nos últimos 90 dias
NIGHT_MODERATE_MULTIPLIER = 3    # soma da noite + amount acima de 3x a média ...
NIGHT_MODERATE_WEIGHT = 0.20
NIGHT_HIGH_MULTIPLIER = 5        # ... e acima de 5x
NIGHT_HIGH_WEIGHT = 0.40

# R2 e R6 medem a mesma coisa (desvio de valor): no score vale o maior peso
# entre as duas, não os dois somados.
AMOUNT_DEVIATION_FAMILY = "desvio_valor"

# R3 — vínculo conta x documento (só contra nó verificado, sem DICT)
OWNER_MISMATCH_FLOOR = 0.80      # origem; o destino rejeita sem piso

# R4 — fraude na pessoa (DICT)
MARKED_FLOOR = 1.0
TAKEOVER_SITUATIONS = frozenset({"ACCOUNT_TAKEOVER", "FRAUDULENT_ACCESS", "COERCION"})
SOURCE_TAKEOVER_WEIGHT = 0.40
LINKED_MARKED_WEIGHT = 0.60
WEAK_SIGNAL_WEIGHT = 0.30
DESTINATION_UNDER_ANALYSIS_LIMIT = 50_000
DESTINATION_UNDER_ANALYSIS_LOW_WEIGHT = 0.40
DESTINATION_UNDER_ANALYSIS_HIGH_WEIGHT = 0.70
DICT_UNAVAILABLE_WEIGHT = 0.30

# R5 — localização
NO_GEOLOCATION_WEIGHT = 0.10
IMPOSSIBLE_TRAVEL_MIN_KM = 50
IMPOSSIBLE_TRAVEL_KMH = 900
LOCATION_MIN_HISTORY = 3
LOCATION_MAX_KM_FROM_CENTROID = 100
LOCATION_WEIGHT = 0.30

# R6 — valor fora do padrão
AMOUNT_MIN_HISTORY = 5
AMOUNT_Z_THRESHOLD = 3.0
AMOUNT_WEIGHT_PER_Z = 0.10
AMOUNT_MAX_WEIGHT = 0.40
AMOUNT_NO_HISTORY_LIMIT = 500_000
AMOUNT_NO_HISTORY_WEIGHT = 0.10

# R7 — pagamento recorrente
RECURRING_WINDOW_DAYS = 180
RECURRING_MIN_PAYMENTS = 3
RECURRING_PERIODS_DAYS = (7, 15, 30)
RECURRING_PERIOD_TOLERANCE_DAYS = 3
RECURRING_AMOUNT_TOLERANCE = 0.20
RECURRING_MIN_AGE_DAYS = 60
RECURRING_DISCOUNT = 0.30
MAX_DISCOUNT = 0.50

# R8 — velocity
VELOCITY_SHORT_WINDOW = timedelta(minutes=10)
VELOCITY_SHORT_MAX = 5
VELOCITY_LONG_WINDOW = timedelta(hours=1)
VELOCITY_LONG_MAX = 10
VELOCITY_WEIGHT = 0.35
FAN_IN_WINDOW = timedelta(hours=1)
FAN_IN_MIN_SOURCES = 10
FAN_IN_WEIGHT = 0.30
DEVICE_SHARED_WINDOW = timedelta(hours=24)
DEVICE_SHARED_MIN_ACCOUNTS = 3
DEVICE_SHARED_WEIGHT = 0.30

# N1 — IP compartilhado (mesmo IP em >= 3 contas de origem em 24h)
IP_SHARED_WINDOW = timedelta(hours=24)
IP_SHARED_MIN_ACCOUNTS = 3
IP_SHARED_WEIGHT = 0.30

# N2 — Combo de tomada de conta (account takeover)
TAKEOVER_COMBO_WEIGHT = 0.40

# R9 — conta de passagem (pass-through / mula). Olha o comportamento ACUMULADO
# da conta na janela (90d), não uma rajada curta: recebe de muitas origens
# distintas (fan-in), repassa para poucos destinos (fan-out) e não retém o
# dinheiro (razão saída/entrada perto de 1). Avalia origem e destino do Pix.
# O pass_through_ratio é o que separa mula de varejista legítimo (que recebe de
# muitos mas acumula/saca em vez de repassar). Exigido nos dois lados (conservador).
R9_WINDOW_DAYS = 90
R9_FANIN_MIN = 8               # origens distintas que pagaram a conta
R9_FANOUT_MAX = 3              # destinos distintos que a conta pagou
R9_PASSTHROUGH_RATIO = 0.80    # (total que saiu) / (total que entrou) >= isto
R9_WEIGHT = 0.40

# 2FA pendente: conta nos históricos e somas por 15 minutos e depois expira,
# como um rejeitado. O resultado do 2FA não volta para o motor (fora do escopo).
TWO_FACTOR_TTL_MINUTES = 15

# Sinais extras
NEW_ACCOUNT_DAYS = 30
NEW_DESTINATION_ACCOUNT_WEIGHT = 0.20
UNKNOWN_DESTINATION_WEIGHT = 0.10

# Grafo
GRAPH_MAX_DEPTH = 3
GRAPH_WINDOW_DAYS = 90
GRAPH_HOP_DECAY = 0.5        # λ
GRAPH_TIME_DECAY_DAYS = 30   # τ
GRAPH_MAX_DEGREE = 200       # não expande por hubs
GRAPH_MAX_NODES_PER_LEVEL = 500
GRAPH_EVIDENCE_SIZE = 3
SOURCE_GRAPH_WEIGHT = 0.5
DESTINATION_GRAPH_WEIGHT = 0.8

# Atualização do risco aprendido dos nós
DESTINATION_LEARNING_RATE = 0.30
SOURCE_LEARNING_RATE = 0.15

# Decisão
REJECT_THRESHOLD = 0.85
TWO_FACTOR_THRESHOLD = 0.50
