# hacka_qitech_eachismo
Projeto de API pix antifraude

## Fixtures de simulação DICT e POST

Os cenários independentes para testes ficam em `tests/fixtures/`:

- `dict_responses.json` contém respostas no formato `ListFraudMarkersResponse`,
  indexadas pelo CPF/CNPJ consultado. As respostas cobrem consulta sem ocorrência,
  marcações registradas/canceladas e paginação. O simulador em
  `tests/utils/dict_response_simulator.py` aceita documentos com ou sem máscara;
  documentos sem resposta fixa recebem uma resposta aleatória que usa o documento
  consultado nos marcadores.
- `api_post/pix_transaction/` contém corpos JSON de exemplo para POST
  `/pix/transaction`, incluindo três requisições (`aleatoria_documentos_*.json`)
  com cinco CPFs/CNPJs não presentes em nenhum mock estático. O teste de fixtures
  envia os documentos ao simulador para exercitar a geração aleatória sem chamar
  a API em execução.

Esses dados são separados de `src/mocks/dict_mock.json` e não alteram o mock usado
pela API em execução. Os JSONs de POST são validados contra o schema da rota nos
testes de fixtures; para consultar uma resposta em outro teste, use
`DictResponseSimulator().query("52998224725")`. Para gerar uma resposta aleatória
no terminal, execute `python -m tests.utils.dict_response_simulator 12345678901`.

Para gerar transações sintéticas aleatórias e enviá-las via
`POST /pix/transaction`, veja as respostas do DICT simulado e os vereditos do
modelo antifraude no terminal e no arquivo de log:

```powershell
# Execute esta linha uma única vez para configurar a API para usar o fixture aleatório.
Add-Content .env "`nDICT_MOCK_FILE=/tests/logs/dict_random_generated_mock.json"
docker compose up -d --force-recreate api
python -m tests.run_dict_random_scenarios --count 100 --seed 42
```

O relatório é salvo em `tests/logs/dict_random_scenarios.log` (sobrescrito a
cada execução); o mock gerado para a API fica em
`tests/logs/dict_random_generated_mock.json`. O serviço precisa usar o caminho
`/tests/logs/dict_random_generated_mock.json` via `DICT_MOCK_FILE` para que as
marcações aleatórias geradas sejam as que o POST consulta. Os IDs dos Pix recebem
um identificador único por execução, evitando que a idempotência devolva um
veredito antigo. O padrão é 100 transações; `--count` permite alterar a quantidade.
As transações variam documentos CPF/CNPJ, contas, horários nos últimos 90 dias,
valores, dispositivos e geolocalizações. Contas, documentos e dispositivos
podem reaparecer aleatoriamente, para que o grafo e o histórico se formem pela
execução normal do modelo. Nenhuma regra ou sequência específica de decisão é
injetada pelo gerador: cada POST passa pelas regras já implementadas na API.

Para repetir as mesmas escolhas aleatórias, informe uma semente:

```powershell
python -m tests.run_dict_random_scenarios --seed 42
```

O comando não altera `src/mocks/dict_mock.json`. Ele grava um arquivo de mock
isolado, envia cada payload à API e registra status HTTP e corpo de resposta junto
às consultas simuladas. Se a API estiver indisponível ou não estiver configurada
para usar o mock gerado, o comando informa a falha e preserva o relatório.
