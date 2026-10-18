# Antifraude Pix — pendências para o serviço completo

Oct 18, 2026 · @Raff

## Resumo executivo

O motor já roda ponta a ponta na `main` (commit `22e8661`, 18/10 00:48): portaria, R1 a R8, grafo, score, decisão e gravação, com C2, C3, C4 e S2 no código e 84 testes. Para o serviço ficar completo faltam **12 decisões** e **10 ajustes de regra**, além de **6 regras novas** possíveis com o payload fixo. Confiança: 88%.

Três pontos bloqueiam a demo:

1. **Contrato de resposta (D1).** O campo `reasons` devolve à IF o motivo interno de cada regra (`destino_marcado`, `vinculado_marcado`). Isso ensina o fraudador quais contas estão queimadas.
2. **Volta do 2FA (D2).** Não existe rota para gravar o resultado do 2FA. Todo `two_factor_required` fica pendente para sempre e continua somando na R1, na R2 e no histórico da R6.
3. **Fraude confirmada (D3).** Sem entrada de fraude confirmada, o grafo só aprende com o próprio score. É circular, e é justamente a peça que o pitch vende.

O modelo de risco (pesos, limiares, grafo e calibração) fica para depois, como combinado. Ele aparece nas tabelas abaixo marcado como "Modelo de risco", só para o inventário ficar completo.

## Decisões em aberto: produto e arquitetura

Doze decisões separam o código atual de um serviço completo. As três primeiras mudam o contrato com a IF e fecham primeiro.

| # | Decisão | Hoje no código | Recomendação | Bloqueia |
| --- | --- | --- | --- | --- |
| D1 | Motivo exposto à IF | `reasons` traz o motivo interno de cada regra | Poucos códigos públicos genéricos (ex.: `RISK_DECLINED`, `STEP_UP_REQUIRED`, `LIMIT_EXCEEDED`); motivo completo só no `metadata` | Demo |
| D2 | Resultado do 2FA | "Fora do fluxo"; o pendente nunca fecha | Rota interna para gravar `approved`/`rejected` como novo status, mais um TTL que tira o pendente vencido das somas | Demo |
| D3 | Fraude confirmada | "Fora do fluxo" | Rota interna por Pix: aresta vai a 1,0 e o destino recebe `external_risk` 1,0 | Pitch do grafo |
| D4 | Limites da R1 | R$ 200 por Pix e R$ 1.000 por dia, aplicados pelo motor | Manter e registrar como decidido: é exigência do BC para dispositivo novo, e só o motor sabe se o device é cadastrado. O doc v1→v2 ainda lista como aberto | Não |
| D5 | API de dispositivo | Mock `GET /devices/{doc}/{device}`; o cache `registered_device` nunca expira | Formato real quando existir; TTL do cache via `registered_at` (sugestão: 90 dias) | Não |
| D6 | DICT | Mock por arquivo, sem timeout nem cache | Cliente real como subclasse do `RestConnector`, timeout curto e cache por documento (E1). Na demo, segue o mock | Produção |
| D7 | Orçamento de latência | Nenhum SLO | p99 do POST ≤ 500 ms (sugestão), com timeout de cada externo dentro dele | Produção |
| D8 | Escopo do motor | PSP único, implícito | Declarar PSP único no README; consórcio entre tenants fica como roadmap | Não |
| D9 | Métrica de sucesso | Nenhuma | Taxa de 2FA e de reject por persona do mock como números do pitch; perda em bps fica para produção | Pitch |
| D10 | Auditoria de parâmetros | `engine_version` fixo em 2.0.0; metadata sem os parâmetros usados | Gravar um hash do `config.py` em cada veredito | Não |
| D11 | Higiene do repositório | README com 2 linhas; `BANKSLIP_*` e `IF_WEBHOOK_*` herdados do BaaS no compose e no `.env.example`; `scheduler.py` vazio; dois `.patch` na raiz | Limpar e escrever o README (payload, rotas, personas do mock, como rodar) | Demo |
| D12 | Documentação de decisão | Doc v1→v2 ainda traz A1 (held/expired, fora do escopo de 3 status), itens de E2 sem fonte e C1 sem o d = 0 que já entrou; draw.io da R3 desatualizado | Reconciliar o doc com o código e fechar o draw.io | Demo |

## Regras existentes: o que falta em cada uma

As oito regras, os sinais extras e o grafo estão implementados e rodam. Faltam 10 ajustes de regra; tudo marcado "(a calibrar)" no `config.py` continua sendo ponto de partida, não número validado.

| Regra | O que falta definir | Tipo |
| --- | --- | --- |
| R1 · Dispositivo | TTL do cache e formato real da API (D5); limites (D4). Pix feito com a API fora do ar não entra na soma diária: aceitar a brecha ou contar como não cadastrado | Regra |
| R2 · Desvio noturno | Faixas 3× e 5×; mínimo de 3 noites. Cliente novo nunca recebe peso noturno (a R6 cobre só valor alto) | Modelo de risco |
| R3 · Vínculo | Documento vinculado conta como igual? Um MEI que recebe com o CPF do dono num nó verificado com o CNPJ hoje é rejeitado; o `person_link` já resolve isso | Regra |
| R4 · Fraude na pessoa | Rejeição por score sobre "destino em análise": manter ou limitar a 0,84 (aberto no doc v1→v2). Corte de R$ 500 igual para PF e PJ | Regra e modelo |
| R5 · Localização | "Sem geolocalização": manter peso 0,10 ou virar limite, já que a IN BCB 669 permite reduzir o limite a zero com o geolocalizador desligado | Regra |
| R6 · Valor | k = 3 e desvio mínimo de 0,2 | Modelo de risco |
| R7 · Recorrência | **Bug barato:** o desconto incide sobre o `rules_score` inteiro, inclusive `destino_em_analise` e `vinculado_marcado`. Deve descontar só a família de desvio de valor (A3, teste T8) | Regra |
| R8 · Velocity | Limiares de origem, fan-in e device. O fan-in só pega destino com menos de 30 dias, então a mula antiga passa | Modelo de risco |
| Transversal · 2FA pendente | Pendente conta para sempre nas somas e históricos (`not_rejected`). Depende de D2 | Regra |
| Transversal · IP e canal | `ip` e `channel` são validados e gravados, mas nenhuma regra lê. Ver N1 e N2 | Regra |
| Grafo, score e decisão | Resto da C1 (R9: risco próprio do destino como ação), A2 (grafo direcional e anti-envenenamento), limiares 0,85 e 0,50, taxas de aprendizado | Modelo de risco (deferido) |

## Regras que ainda não existem

Seis regras novas cabem no payload fixo, usando só o histórico que já gravamos; N1 e N2 aproveitam `ip` e `channel`, hoje ignorados. Os pesos sugeridos seguem a escala das regras atuais e entram como "(a calibrar)". Confiança: 75%.

| ID | Regra proposta | Dado usado | Ação sugerida | Prioridade |
| --- | --- | --- | --- | --- |
| N1 | IP compartilhado: mesmo IP em 3 ou mais contas de origem em 24 h (fazenda de contas, anel de mulas) | `source_ip`; pede índice por IP e data | Peso 0,30 | Alta |
| N2 | Combinação de tomada de conta: device não cadastrado, IP nunca visto na origem e destino desconhecido no mesmo Pix | `source_ip`, `channel`, R1 e extras | 2FA | Alta |
| N3 | Fracionamento abaixo da R1: vários Pix logo abaixo de R$ 200 em device novo para destinos distintos no mesmo dia | histórico da origem | Peso 0,30 | Média |
| N4 | Conta de passagem (S3): a origem recebeu valor parecido nas últimas 2 h e repassa. Só enxerga recebimentos que passaram pelo motor | arestas de entrada | Peso 0,30 | Média |
| N5 | Conta dormente reativada: origem sem Pix há mais de 90 dias faz Pix alto | histórico da origem | Peso 0,20 | Média |
| N6 | Mesmo titular: origem e destino com o mesmo documento ou documento vinculado | payload e `person_link` | Alívio de peso | Baixa |

Descartados: idade da chave Pix (o payload não traz chave) e ciclo A→B→A (fica com o grafo, na A2).

## Não-funcionais

O serviço não tem SLO, métrica por regra nem política de retenção. Nada disso trava a demo, mas trava produção; o único item de demo aqui é cobrir T1 e T10 com teste.

| Tema | O que falta | Sugestão |
| --- | --- | --- |
| Latência | Cada POST faz duas chamadas externas (device e DICT) e uma busca de até 3 níveis no grafo; não há SLO (D7) | Teste de carga simples com as personas do mock e meta de p99 |
| Testes | Dos cenários da matriz do doc v1→v2, T1 (`destino_risco_interno`) e T10 (origem que pagou mula) não têm teste; T9 (2FA vencido) depende de D2 | Escrever T1 e T10; T9 entra junto com D2 |
| Observabilidade | Só log por linha | Contagem por status e por motivo, latência por etapa e taxa de API externa indisponível |
| Segurança | Um `INTERNAL-TOKEN` único para todas as rotas; `reasons` vaza inteligência (D1) | Fechar D1; token por chamador fica para produção |
| LGPD | Documento, IP e geolocalização ficam guardados sem prazo | Definir prazo de retenção e registrar a base legal de prevenção à fraude no README |
| Operação | Serviço `scheduler` sem nenhum job; o decaimento já é calculado na leitura | Dar a ele o TTL do 2FA (D2) ou tirar do compose |

## Plano de ataque

A ordem vai do que muda o contrato com a IF para o que só muda número. O modelo de risco fica por último, como combinado.

1. **Contrato (antes da demo):** D1, D2 e D3. As três mexem em rota ou resposta, e o resto se apoia nelas.
2. **Correções baratas de regra:** desconto da R7 (T8), documento vinculado na R3, formalizar D4 e escrever T1 e T10.
3. **Apresentação:** D11 (README e limpeza do repo), D12 (doc v1→v2 e draw.io) e D9 (os números do pitch).
4. **Regras novas:** N1 e N2 primeiro, porque usam campos que já gravamos.
5. **Produção:** D5, D6, D7, D10 e os não-funcionais.
6. **Modelo de risco:** C1 restante, A2, limiares e calibração.

## Insight Visionário

O motor hoje só aprende com o próprio veredito: o score gera a aresta, e a aresta alimenta o score. Sem D3, o grafo é um relógio que acerta a hora pelo próprio ponteiro. Com a rota de fraude confirmada, cada caso do MED vira rótulo, e o grafo passa a ser o único ativo que melhora com o uso, o que nenhum concorrente copia lendo o `regras_antifraude.txt`. Esse é o argumento de pitch: as regras são commodity; o histórico rotulado não é.

## Resumo

- O código já roda o fluxo inteiro; faltam 12 decisões, das quais três (contrato de resposta, volta do 2FA e fraude confirmada) bloqueiam a demo.
- Nas regras, o ajuste mais barato e mais urgente é o desconto da R7; as melhores regras novas usam IP e canal, que já gravamos e ninguém lê.
- Modelo de risco e calibração seguem deferidos e inventariados.

## Fontes

- [regras\_antifraude.txt](https://github.com/Cerqueira11/hacka_qitech_eachismo/blob/main/regras_antifraude.txt): o spec atual, com o que ficou "fora deste fluxo" (2FA e fraude confirmada).
- [config.py](https://github.com/Cerqueira11/hacka_qitech_eachismo/blob/main/src/antifraud/config.py) e [engine.py](https://github.com/Cerqueira11/hacka_qitech_eachismo/blob/main/src/antifraud/engine.py): parâmetros "a calibrar" e o desconto da R7 aplicado ao score inteiro.
- [pix\_transaction\_dto.py](https://github.com/Cerqueira11/hacka_qitech_eachismo/blob/main/src/dtos/pix_transaction_dto.py): `reasons` com os motivos internos na resposta.
- [app.py](https://github.com/Cerqueira11/hacka_qitech_eachismo/blob/main/src/app.py), [docker-compose.yml](https://github.com/Cerqueira11/hacka_qitech_eachismo/blob/main/docker-compose.yml) e [scheduler.py](https://github.com/Cerqueira11/hacka_qitech_eachismo/blob/main/src/scheduler.py): rotas existentes, variáveis herdadas do BaaS e agendador vazio.
- [Antifraude Pix — o que mudar da v1 para a v2](https://claude.ai/code/artifact/659f6bb7-d537-4c0d-a3b6-fe60a4d60324): decisões em aberto, matriz T1–T12 e itens C1, A1–A3, S3 e E1–E3.
