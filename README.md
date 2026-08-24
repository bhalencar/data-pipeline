# data-pipeline — Casa e Patas

Pipeline de dados da Casa e Patas, loja de casa & pet em marketplace. Extrai pedidos da Shopee, carrega no BigQuery e modela em bronze / silver / gold com dbt.

Esta é a porta de entrada técnica. A explicação narrativa do projeto — papéis, agentes, como ler os boards — vive no Drive, em `QG Casa e Patas > Metas e Planejamento`.

## Endereço dos dados

| Item | Valor |
|---|---|
| Projeto BigQuery | `cp-pipeline-503623` |
| Região | `southamerica-east1` |
| Datasets | `bronze`, `silver`, `gold` |
| Tabelas de consulta | `gold.master_orders`, `gold.despesa_operacional` |

**Consulte sempre o `gold`.** Silver e bronze existem para depurar o pipeline. Exceção: `silver.dicionario_campos`, que é metadado.

## Como roda

Cloud Run Job disparado pelo Cloud Scheduler, 1x/dia às 06:00 (America/Sao_Paulo).

A extração relê os pedidos criados nos **últimos 30 dias**, não só os de ontem. Pedido não é imutável: status e escrow mudam depois da criação, e sem releitura eles congelam na primeira leitura. A janela é fatiada em pedaços de 15 dias, limite da API `get_order_list`.

Entrada: `orchestration/run_pipeline_cloud.py`. O container está no `Dockerfile` (Python 3.12 slim); ele copia `extraction/`, `orchestration/` e `dbt/`, e aponta `DBT_PROFILES_DIR` para `/app/dbt`.

`orchestration/run_pipeline.py` é a versão local antiga, do tempo do Postgres. **Está parada.**

## Deploy — e a armadilha que já custou quatro dias

**Rodar `dbt` na sua máquina não muda o que a nuvem executa.** O job das 06:00 roda a imagem publicada, e ele recria o gold por cima do que você fez local.

Isso vale inclusive para os **CSVs de seed**: eles são copiados para dentro da imagem pelo `COPY dbt/ ./dbt/`. Lançamento novo de custo ou despesa só é permanente depois de novo build.

```bash
gcloud builds submit \
  --tag southamerica-east1-docker.pkg.dev/cp-pipeline-503623/cp-pipeline/pipeline:latest

gcloud run jobs update pipeline-casa-e-patas \
  --region southamerica-east1 \
  --image southamerica-east1-docker.pkg.dev/cp-pipeline-503623/cp-pipeline/pipeline:latest

gcloud run jobs execute pipeline-casa-e-patas --region southamerica-east1 --wait
```

**O `run jobs update` não é opcional.** O Cloud Run resolve a tag para um digest fixo quando a revisão é criada — ele não relê o `:latest` a cada execução. Sem esse comando, a imagem nova sobe para o Artifact Registry e o job continua rodando a antiga, em silêncio, sem erro nenhum.

Foi exatamente o que aconteceu entre 21 e 24/08/2026: quatro manhãs recriando o gold com código velho, desfazendo colunas que já estavam commitadas.

Cloud Build e não Docker local: o Mac é ARM e o Cloud Run precisa de x86.

**Mudança em modelo do gold só é dada como pronta depois de uma rodada da nuvem.** Verificar logo após o `dbt build` local prova que o código funciona, não que ele está em produção.

## Estrutura

```
extraction/shopee/      Extração da API da Shopee (auth, token, pedidos, escrow)
extraction/planilhas/   Planilhas manuais -> CSV para o dbt (custo e despesa)
dbt/models/silver/      Views de limpeza, uma por entidade
dbt/models/gold/        master_orders e despesa_operacional (tabelas materializadas)
dbt/seeds/              custo_produtos, dicionario_campos, despesa_operacional_manual
dbt/tests/              Testes singulares (grão das tabelas do gold)
orchestration/          Orquestradores (cloud e local)
docker/                 Compose e SQL da fase Postgres — histórico
docs/                   Dicionários de negócio, um por tabela do gold
consultas/              SQL avulso
```

## Rodar localmente — são três venvs, e eles não são intercambiáveis

Os venvs ficam **fora do repositório**, e a separação é proposital.

| Venv | Para quê |
|---|---|
| `~/.venvs/cp-bigquery` | **Rodar dbt no BigQuery.** É o que você usa em 90% das vezes. |
| `venv/` do projeto | Scripts de extração da Shopee (`requirements.txt`) |
| `~/.venvs/cp-postgres` | Postgres local, **congelado** — fase antiga do projeto |

```bash
source ~/.venvs/cp-bigquery/bin/activate
cd ~/Documents/"Casa e Patas"/data-pipeline/dbt
dbt build --target bigquery
```

**Por que não usar o `venv/` do projeto para dbt.** O `requirements.txt` instala `dbt-bigquery` junto com `google-cloud-bigquery` e `google-cloud-storage`. Essa combinação **trava qualquer comando dbt por até 13 minutos**, em espera de I/O. Já custou uma sessão inteira em 09/08/2026, com um `dbt seed` de 31 linhas aparentemente pendurado. Não estava travado; estava esperando.

**Duas variáveis que vivem fora do repositório:**

- `export DBT_VERSION_CHECK=false` — está no `~/.zshrc`. Sem ela, o dbt gasta tempo checando versão a cada comando.
- Credenciais em `.env` na raiz, não versionado. O `.gitignore` cobre `.env`, `credentials.json` e os caches de token da Shopee; verificado que nenhum deles está no histórico do git.

**`openpyxl` não vem com o `dbt-bigquery`.** Os scripts de export leem `.xlsx` via pandas e precisam dele:

```bash
source ~/.venvs/cp-bigquery/bin/activate
pip install openpyxl
```

Sem ele o export falha com `ModuleNotFoundError`, o CSV **não é regenerado**, e o `dbt seed` seguinte carrega a versão anterior sem reclamar. A planilha muda e o warehouse não.

## O dicionário de campos

Três superfícies de origem e uma de leitura. Não confunda:

| Onde | Papel |
|---|---|
| `dbt/seeds/dicionario_campos.csv` | **Onde se escreve.** Colunas: `tabela`, `campo`, `grupo`, `descricao`, `cuidados`. |
| `dbt/models/gold/schema.yml` | Descrição de coluna nativa do BigQuery, via `persist_docs`. Aparece no console. |
| `docs/dicionario_<tabela>.md` | **Versão de negócio**, uma por tabela do gold, para leitor não técnico. |
| `silver.dicionario_campos` | **Onde se lê.** Gerada do CSV por `dbt seed`. É o que os agentes consultam. |

A coluna `tabela` existe desde 21/08/2026, quando o gold ganhou a segunda tabela. Sem ela o dicionário fica ambíguo: `descricao` existe nas duas e significa coisas diferentes. **Toda junção com o dicionário precisa das duas chaves**, `tabela` e `campo`.

Campo novo no gold pede entrada nas **três** superfícies de origem, no mesmo commit.

## Planilhas manuais

Duas fontes entram à mão, pelo mesmo padrão: planilha `.xlsx` → script de export → CSV de seed → `dbt seed`.

**Custo dos produtos** (`custo_produtos.xlsx`). Custo point-in-time: aplica-se o vigente na data do pedido. É **append-only** — nunca editar linha antiga, sempre acrescentar com nova `data_vigencia_inicio`.

```bash
source ~/.venvs/cp-bigquery/bin/activate
python extraction/planilhas/export_custo_csv.py
cd dbt && dbt build --select custo_produtos+ --target bigquery
```

Pedidos anteriores a junho/2026 não têm custo cadastrado — `cmv_unitario`, `cmv_total` e `margem_item` ficam nulos de propósito.

**Despesa operacional** (`despesa_operacional.xlsx`). Uma linha por mês de competência. Detalhe em `docs/dicionario_despesa_operacional.md`.

```bash
source ~/.venvs/cp-bigquery/bin/activate
python extraction/planilhas/export_despesa_csv.py
cd dbt && dbt build --select despesa_operacional_manual+ --target bigquery
```

Nos dois casos, o `+` no `--select` roda o seed **e** o modelo que depende dele. E nos dois casos, **lembre do build** — ver a seção de deploy.

## Armadilhas que custam caro

1. **`create_time` é UTC — e o dia comercial é Brasília.** `date(create_time)` devolve a data UTC, 3h à frente. Cerca de 16% dos pedidos caem em outro dia. Use `date(create_time, 'America/Sao_Paulo')`, que é o que o painel da Shopee mostra (verificado em 09/08/2026).
2. **Não extraia data do `order_sn`.** Os seis primeiros dígitos parecem `AAMMDD` mas seguem o relógio de Singapura: dos 95 pedidos, 95 batem com Singapura e 28 com Brasília.
3. **Nunca some `escrow_amount`.** É o repasse do pedido inteiro, repetido em cada linha. Para somar dinheiro use `receita_bruta`.
4. **Conte pedidos com `count(distinct order_sn)`.** Cada linha é um item, não um pedido.
5. **Filtre `order_status <> 'CANCELLED'`** em qualquer análise financeira. Cancelado tem repasse zero e distorce média.
6. **Comissão média é ponderada:** `1 - sum(receita_bruta) / sum(gmv_item)`. Média da coluna faz pedido de R$ 20 pesar igual a um de R$ 200.
7. **`gmv_item` fica nulo enquanto o escrow não chega — e nulo não vira zero.** O pedido some da soma sem aviso. Antes de comparar com o painel da Shopee, conte quantas linhas do período estão com `gmv_item` vazio.
8. **`receita_bruta` e `receita_liquida` não formam par.** A bruta é o repasse da Shopee; a líquida parte do GMV menos 6% de imposto. Uma **nunca** se subtrai da outra, e `receita_liquida > receita_bruta` é o esperado, não um defeito.

A lista completa está em `silver.dicionario_campos`, coluna `cuidados`.

## Manutenção com data marcada

**A Live API Partner Key da Shopee expira em 23/01/2027.** Quando expirar, a extração retorna erro de autenticação e os dados param de atualizar **sem alarme** — o agendamento continua verde.

Renovação: Shopee Open Platform → App Management → App List → app "data pipeline casa e patas" → regerar a Live API Partner Key → atualizar a credencial.

## Limite estrutural conhecido

`gold.master_orders` é recriado inteiro a cada rodada (`CREATE OR REPLACE`). Consequência: **não há histórico de status de pedido**.

Desde a releitura de 30 dias, o status que se vê é o **atual** — antes era o da primeira extração, e ficava congelado. Mas continua não sendo possível responder "quantos pedidos estavam em trânsito na semana passada": a tabela guarda o estado de agora, não a série.

Com o volume de hoje a escolha é a certa, mas precisa ser revisitada antes de o volume crescer, não depois.
