"""As personas do DICT simulado (src/mocks/dict_mock.json), do ponto de vista do teste.

Os testes são caixa-preta: não leem o arquivo do mock, só conhecem os
documentos e contas que ele descreve. Se o mock mudar, mude aqui também.
"""

MULE = "10433218100"                     # MULE_ACCOUNT: Pix para ele -> rejected
SCAMMER = "96001338914"                  # SCAMMER_ACCOUNT: Pix dele -> rejected
UNDER_ANALYSIS = "08386379499"           # infração aberta SCAM: Pix para ele -> 2FA
ACCOUNT_TAKEOVER = "02654235114"         # infração aberta ACCOUNT_TAKEOVER: Pix dele -> 2FA
WEAK_SIGNAL = "16155940789"              # marcação OTHER: só peso
DICT_UNAVAILABLE = "81618495950"         # o DICT não responde para este documento
MULE_CNPJ = "92832764000161"             # CNPJ laranja, para vincular com POST /person_link

# Contas de destino com resposta fixa no DICT (participant 60701190, agência 0001).
ACCOUNT_NOT_IN_DICT = "99999"
ACCOUNT_WITH_OTHER_OWNER = "88888"
DICT_ACCOUNT_BRANCH = "0001"
