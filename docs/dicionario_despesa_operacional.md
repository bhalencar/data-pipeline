# Despesa operacional — dicionário de negócio

Tabela `gold.despesa_operacional`. É a fonte de tudo que fica **abaixo da margem de contribuição** no DRE.

O dado é lançado à mão pelo Bruno, numa planilha, e entra no warehouse por `dbt seed`. Mesmo padrão do custo de produto.

---

## O que é uma linha

Uma linha = **um item de despesa, num mês**.

Grão: `competencia` × `canal` × `categoria` × `descricao`.

| Campo | O que é |
|---|---|
| `competencia` | O mês a que a despesa se refere, sempre no dia 1º. |
| `canal` | A que canal a despesa pertence: `shopee`, `mercado_livre` ou `comum`. |
| `categoria` | O tipo: `assinaturas`, `agencia_marketing`, `consultoria`, `pro_labore`, `midia_manual`. |
| `descricao` | O item dentro da categoria — Canva, Avantpro, Shopee Ads. |
| `valor` | Quanto foi naquele mês, em reais. |
| `observacao` | Rateio aplicado, motivo, ou registro de que o gasto conferido foi zero. |

---

## Canal, e por que `comum` não vem rateado

Três valores: `shopee`, `mercado_livre` e `comum`.

Use o canal **só quando a despesa existe por causa dele**. Mídia da Shopee é `shopee`. A agência de marketing de março a julho é `shopee`, porque trabalhava a loja da Shopee.

Canva, Avantpro e a consultoria são `comum`: são despesa do **negócio**, não de um canal. Isso vale **mesmo hoje**, que só existe um canal.

> **Por que não marcar tudo como `shopee`, já que só existe Shopee?** Porque no dia em que o Mercado Livre entrar, toda a estrutura de custo do negócio estaria pendurada na Shopee — e a comparação entre canais nasceria errada, justamente quando ela passa a importar. Classificar certo agora custa nada; corrigir depois exige reescrever o histórico.

**A despesa `comum` não vem rateada, de propósito.** Quem monta o DRE decide o critério: ratear por faturamento do canal, mostrar em bloco separado, ou os dois. Se o rateio fosse feito na planilha, o critério ficaria escondido na digitação e ninguém conseguiria auditar depois por que foi 60/40.

Consequência prática: **somar só a despesa de um canal subestima o custo daquele canal.** Um DRE por canal precisa dizer o que fez com a `comum`.

Hoje, jan/2026 a jul/2027: R$ 6.389,16 em `shopee` e R$ 14.014,38 em `comum` — a maior parte do custo do negócio não pertence a canal nenhum.

---

## Competência, não caixa

O contrato de consultoria custou **R$ 13.374,38 por 12 meses**, pago de uma vez em agosto. Na tabela ele aparece como **R$ 1.114,53 por mês**, de agosto/2026 a julho/2027.

> **Por que assim?** Se os R$ 13 mil entrassem inteiros em agosto, agosto ficaria artificialmente péssimo e os outros onze artificialmente bons — e nenhum mês seria comparável com o outro. O ponto de um DRE mensal é comparar meses.
>
> **Consequência:** esta tabela **não diz quando o dinheiro saiu.** Para fluxo de caixa ela não serve, e não existe outra fonte no warehouse que sirva.

O último mês do rateio leva os centavos que sobram (R$ 1.114,55), para o contrato fechar exato.

---

## Mês sem linha não é mês sem despesa

Esta é a regra mais importante da tabela, e ela é deliberada.

**Despesa recorrente não se propaga sozinha.** Assinatura precisa de uma linha nova a cada mês. Se ninguém lançar setembro, setembro não tem despesa registrada — e o DRE deve **parar na margem de contribuição e declarar que parou**, nunca assumir que o valor de agosto continua valendo.

A alternativa (uma linha valendo "daqui em diante") economizaria digitação, mas faria o modelo afirmar despesa em meses que ninguém apurou. Deixaria de distinguir *"conferi e é isso"* de *"ninguém olhou"*.

**Zero explícito é diferente de ausência.** Abril e maio de 2026 têm `midia_manual` com valor `0.00` e a observação "verificado: sem veiculação no mês". Isso é informação: alguém conferiu. Um mês sem a linha não afirma nada.

---

## Três armadilhas ao montar o DRE

**1. Antes de junho/2026 não existe margem de contribuição.**
Produtos descontinuados não têm custo cadastrado, então `cmv_unitario` é nulo em janeiro, fevereiro e março — de propósito. Como a margem depende do CMV, ela não é calculável nesses meses. Só que a **despesa está lançada** (R$ 80 em jan e fev, R$ 1.281,87 em março). Subtrair despesa de uma margem que não existe produz um "resultado" que não é resultado. Nesses meses o DRE precisa mostrar a despesa e declarar que a margem é indisponível.

**2. Mês sem venda tem margem zero, não margem nula.**
Abril e maio não tiveram nenhum pedido, mas tiveram R$ 1.077 de despesa cada. Um `join` ingênuo devolve `null` e some com o mês. O correto é margem zero e resultado −1.077.

**3. Existem linhas no futuro.**
A consultoria está lançada até julho/2027. Um DRE que não filtre por mês corrente vai exibir meses que ainda não aconteceram, com despesa e sem receita. Filtrar é decisão de quem monta o relatório.

---

## `pro_labore` é categoria válida e não tem nenhum lançamento

A categoria existe na lista permitida, mas **nenhuma linha usa ela**. Houve um lançamento de R$ 10.000 em ago/2026 que foi removido em 24/08: o Bruno confirmou que **não houve pró-labore em nenhum mês de 2026**.

Isso é exatamente a distinção que a tabela existe para preservar. Ausência de linha **não** significa que o pró-labore foi zero — significa que ninguém apurou. Se em algum mês houver retirada, ela entra como linha nova, canal `comum`.

> Enquanto não houver lançamento, **o DRE não deve exibir linha de pró-labore**, nem com valor zero. Zero afirma que se conferiu e não houve; ausência não afirma nada.

---

## `midia_manual` é provisória — e tem data para sair

A categoria `midia_manual` cobre o gasto com Shopee Ads de **março a agosto/2026**, digitado à mão porque o `master_ads` ainda não existe.

**Quando o `master_ads` entrar, estas linhas precisam ser removidas.** Se ficarem, o gasto com anúncio conta duas vezes: uma pela planilha, outra pela API.

Estado em 21/08/2026: a mídia está **pausada**. Agosto tem R$ 88,91, que é o gasto de **01 a 04/08** — não o mês fechado.

---

## O que não entra aqui

| Não entra | Onde já está |
|---|---|
| Imposto | Dentro de `receita_liquida` — 6% sobre o GMV |
| Custo do produto | `cmv_total` no `master_orders` |
| Embalagem e mão de obra | Embutidos no custo do produto — a loja opera sem estoque próprio |
| Mídia, a partir do `master_ads` | `master_ads`, quando existir |

Lançar qualquer um deles aqui conta o mesmo dinheiro duas vezes.

---

## Como atualizar

1. Abrir `extraction/planilhas/despesa_operacional.xlsx`, aba `despesa_operacional`.
2. Acrescentar as linhas do mês. **Nunca editar linha antiga** — se um valor estava errado, a correção é uma linha nova com observação dizendo o que ela substitui.
3. Exportar e carregar:

```bash
source ~/.venvs/cp-bigquery/bin/activate
cd ~/Documents/"Casa e Patas"/data-pipeline
python extraction/planilhas/export_despesa_csv.py
cd dbt && dbt build --select despesa_operacional_manual+ --target bigquery
```

O `+` no `--select` faz o dbt rodar o seed **e** o modelo que depende dele. Sem o `+`, só o seed é carregado.

> **O export exige `openpyxl`.** Ele não vem com o `dbt-bigquery`. Se der `ModuleNotFoundError: No module named 'openpyxl'`, rode `pip install openpyxl` com o venv `~/.venvs/cp-bigquery` ativo. Sem ele o export falha, o CSV **não é regenerado**, e o `dbt seed` carrega a versão anterior sem reclamar — a planilha muda e o warehouse não.

> **Os comandos acima param no seu computador.** Os CSVs de seed são copiados para **dentro da imagem** do Cloud Run (`COPY dbt/ ./dbt/` no Dockerfile). O `dbt seed` local atualiza o BigQuery na hora, mas o job que roda todo dia às 06:00 continua carregando a versão que estava na imagem — e recria a tabela por cima da sua.
>
> Ou seja: **lançamento novo só é permanente depois de um novo build.**
>
> ```bash
> gcloud builds submit \
>   --tag southamerica-east1-docker.pkg.dev/cp-pipeline-503623/cp-pipeline/pipeline:latest
> gcloud run jobs update pipeline-casa-e-patas \
>   --region southamerica-east1 \
>   --image southamerica-east1-docker.pkg.dev/cp-pipeline-503623/cp-pipeline/pipeline:latest
> ```
>
> O `run jobs update` não é opcional: o Cloud Run resolve a tag para um digest fixo quando a revisão é criada, e não relê o `:latest` a cada execução. Sem ele, a imagem nova sobe e o job continua na antiga, em silêncio. Foi o que aconteceu entre 21 e 24/08 — quatro dias de gold recriado com código velho.

O script recusa a exportação se alguma competência não estiver no dia 1º — data no meio do mês costuma significar que alguém preencheu pensando em data de pagamento.
