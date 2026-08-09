# data-pipeline — Casa e Patas

Pipeline de dados da Casa e Patas, loja de casa & pet em marketplace. Extrai pedidos da Shopee, carrega no BigQuery e modela em bronze / silver / gold com dbt.

Esta é a porta de entrada técnica. A explicação narrativa do projeto — papéis, agentes, como ler os boards — vive no Drive, em `QG Casa e Patas > Metas e Planejamento`.

## Endereço dos dados

| Item | Valor |
|---|---|
| Projeto BigQuery | `cp-pipeline-503623` |
| Região | `southamerica-east1` |
| Datasets | `bronze`, `silver`, `gold` |
| Tabela de consulta | `gold.master_orders` |

**Consulte sempre o `gold`.** Silver e bronze existem para depurar o pipeline. Exceção: `silver.dicionario_campos`, que é metadado.

## Como roda

Cloud Run Job disparado pelo Cloud Scheduler, 1x/dia às 06:00 (America/Sao_Paulo), carregando o dia anterior.

Entrada: `orchestration/run_pipeline_cloud.py`. O container está no `Dockerfile` (Python 3.12 slim); ele copia `extraction/`, `orchestration/` e `dbt/`, e aponta `DBT_PROFILES_DIR` para `/app/dbt`.

`orchestration/run_pipeline.py` é a versão local antiga, do tempo do Postgres. **Está parada.**

## Estrutura

```
extraction/shopee/      Extração da API da Shopee (auth, token, pedidos, escrow)
extraction/planilhas/   Custo de produtos: planilha manual -> CSV para o dbt
dbt/models/silver/      Views de limpeza, uma por entidade
dbt/models/gold/        master_orders (tabela materializada)
dbt/seeds/              custo_produtos.csv e dicionario_campos.csv
orchestration/          Orquestradores (cloud e local)
docker/                 Compose e SQL da fase Postgres — histórico
docs/                   Documentação de apoio
consultas/              SQL avulso
```

## O dicionário de campos

Duas superfícies, com papéis diferentes. Não confunda:

| Onde | Papel |
|---|---|
| `dbt/seeds/dicionario_campos.csv` | **Onde se escreve.** Fonte do dicionário: `campo`, `grupo`, `descricao`, `cuidados`. |
| `silver.dicionario_campos` | **Onde se lê.** Gerada do CSV por `dbt seed`. É o que os agentes consultam. |
| `dbt/models/gold/schema.yml` | Descrição de coluna nativa do BigQuery, via `persist_docs`. Aparece no console. |

Campo novo no gold pede linha no CSV **e** entrada no `schema.yml`. Quem adiciona campo adiciona as duas — é o mesmo commit.

> `docs/dicionario_master_orders.md` é uma cópia congelada de 31/07/2026. **Não é fonte e não deve ser usada para decidir nada.**

## Custo dos produtos

Custo point-in-time: aplica-se o vigente na data do pedido. A planilha é **append-only** — nunca editar linha antiga, sempre acrescentar linha nova com nova `data_vigencia_inicio`.

Para atualizar:

```bash
python3.12 extraction/planilhas/export_custo_csv.py
cd dbt && dbt seed && dbt run --select master_orders
```

Pedidos anteriores a junho/2026 não têm custo cadastrado — `cmv_unitario`, `cmv_total` e `margem_item` ficam nulos de propósito.

## Armadilhas que custam caro

1. **`create_time` é UTC — e o dia comercial é Brasília.** `date(create_time)` devolve a data UTC, 3h à frente. Cerca de 16% dos pedidos caem em outro dia. Use `date(create_time, 'America/Sao_Paulo')`, que é o que o painel da Shopee mostra (verificado em 09/08/2026).
2. **Não extraia data do `order_sn`.** Os seis primeiros dígitos parecem `AAMMDD` mas seguem o relógio de Singapura: dos 95 pedidos, 95 batem com Singapura e 28 com Brasília.
3. **Nunca some `escrow_amount`.** É o repasse do pedido inteiro, repetido em cada linha. Para somar dinheiro use `receita_bruta`.
4. **Conte pedidos com `count(distinct order_sn)`.** Cada linha é um item, não um pedido.
5. **Filtre `order_status <> 'CANCELLED'`** em qualquer análise financeira. Cancelado tem repasse zero e distorce média.
6. **Comissão média é ponderada:** `1 - sum(receita_bruta) / sum(gmv_item)`. Média da coluna faz pedido de R$ 20 pesar igual a um de R$ 200.

A lista completa está em `silver.dicionario_campos`, coluna `cuidados`.

## Rodar localmente

```bash
python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

Credenciais em `.env` na raiz — não versionado. O `.gitignore` cobre `.env`, `credentials.json` e os caches de token da Shopee; verificado que nenhum deles está no histórico do git.

## Manutenção com data marcada

**A Live API Partner Key da Shopee expira em 23/01/2027.** Quando expirar, a extração retorna erro de autenticação e os dados param de atualizar **sem alarme** — o agendamento continua verde.

Renovação: Shopee Open Platform → App Management → App List → app "data pipeline casa e patas" → regerar a Live API Partner Key → atualizar a credencial.

## Limite estrutural conhecido

`gold.master_orders` é recriado inteiro a cada rodada (`CREATE OR REPLACE`). Consequência: **não há histórico de status de pedido** — o que se vê é sempre o estado atual. Com o volume de hoje a escolha é a certa, mas precisa ser revisitada antes de o volume crescer, não depois.
