# master_ads — desempenho de mídia paga

**Para quem lê número, não código.** A versão técnica está em `silver.dicionario_campos` e em `dbt/models/gold/schema.yml`.

Fonte: Shopee Ads API. Uma linha por **campanha por dia**.

---

## A regra que evita o erro mais caro

**O gasto total com mídia não sai desta tabela.**

Sai de `silver.stg_ads_shop_daily`, que tem uma linha por dia com o total da loja.

Parece contraditório — as duas têm gasto, e os números batem. Em julho/2026 a loja marcou R$ 839,17 e a soma das campanhas R$ 839,20: três centavos de diferença em 744 linhas.

A razão é o futuro, não o presente: **campanha encerrada some da listagem da Shopee**, e quando some, o gasto dela sai junto. O total por campanha pode encolher meses depois sem nada ter mudado no passado. O nível loja não tem esse problema.

Use `master_ads` para saber **qual** campanha gastou. Use `stg_ads_shop_daily` para saber **quanto** se gastou.

---

## Direto e amplo: dois números para a mesma venda

Cada métrica de retorno aparece duas vezes.

**Direto** conta só a venda do produto anunciado: a pessoa clicou no anúncio da escada pet e comprou a escada pet.

**Amplo** conta qualquer venda depois do clique: clicou no anúncio da escada e comprou uma cama. A Shopee credita à campanha da escada.

O amplo é maior e mais bonito. Também é o que engana:

> **Não some as métricas amplas entre campanhas.** A mesma venda é creditada a mais de uma campanha ao mesmo tempo. Somar dez campanhas pode dar um faturamento maior do que a loja inteira vendeu.

É o mesmo defeito do `escrow_amount` no `master_orders`, que repete o valor do pedido em cada item.

**Na dúvida, use o direto.** Ele é conservador e não infla.

### Hoje os dois são idênticos — e isso é normal

Medido em 13/09/2026: nas 63 linhas com venda, `gmv_amplo` e `gmv_direto` têm
**exatamente o mesmo valor**. Sempre.

Não é defeito. A Shopee entrega os dois campos com o mesmo número, e o motivo é
a escala da loja: cada campanha anuncia **um produto só**, e a loja faz cerca de
10 pedidos por semana. Para os números divergirem, alguém precisaria clicar no
anúncio da escada e comprar a caminha na mesma semana — o que quase nunca
acontece com esse volume.

**O aviso de não somar continua valendo**, porque ele protege contra um problema
que aparece quando o volume cresce. Hoje o risco está dormindo, não resolvido.

---

## O campo que parece dinheiro e não é

> **`valor_pedidos_diretos` e `valor_pedidos_amplos` NÃO são valores em reais.
> São contagem de itens.**

O nome está errado, e a culpa é compartilhada: o campo da Shopee se chama
`direct_order_amount`, e ali *amount* significa **quantidade**, não montante.

Como dá para ver na prática: nas 63 linhas com venda, o campo varia de **1 a 4**,
com média 1,56 — enquanto o GMV médio dessas mesmas linhas é **R$ 57,21**. Nenhum
faturamento diário de campanha é R$ 2.

A prova definitiva é uma divisão. `gmv_direto ÷ valor_pedidos_diretos` devolve:

| campanha | resultado | preço real do produto |
|---|---|---|
| Esteira Porta Copos | 25,86 | R$ 25,49 a 26,41 |
| Trio de Mesas | 57,10 | R$ 58,19 |

Ou seja: a divisão devolve o **preço unitário**. Isso só acontece se o
denominador for quantidade de itens.

**O erro que isso causa:** somar `valor_pedidos_diretos` achando que é receita
devolve **R$ 98** no período inteiro, onde o GMV real foi **R$ 3.604,08**. Um
erro de 37 vezes para baixo, num número que parece plausível à primeira vista.

**Para dinheiro, use `gmv_direto`.** Para saber quantos itens saíram, aí sim use
este campo — ele responde isso corretamente.

---

## Por que o GMV daqui nunca bate com o das vendas

A Shopee credita a venda ao **dia do clique**, com janela de sete dias.

Alguém clica no anúncio na terça e compra no sábado: o `master_orders` registra a venda no sábado, o `master_ads` credita à terça.

**Isso não é erro de ninguém.** São duas perguntas diferentes:

- *"Quanto vendemos na terça?"* → `master_orders`
- *"Quanto o anúncio de terça gerou?"* → `master_ads`

Comparar os dois no mesmo dia e concluir que um está errado é o engano mais fácil desta tabela.

---

## Números que já vêm calculados — e não se somam

`ctr`, `roi_direto`, `roi_amplo`, `cir_direto`, `cir_amplo`, `custo_por_clique`, `taxa_conversao` e `custo_por_conversao_direta` são **razões prontas**, calculadas pela Shopee dia a dia.

Para consolidar um período, **não tire média da coluna** — média de razão não é razão da média. Um dia com R$ 2 de gasto pesaria igual a um dia com R$ 200.

Recalcule a partir dos totais:

```sql
-- ROI do período, do jeito certo
select sum(gmv_direto) / nullif(sum(gasto), 0) as roi_periodo
from `cp-pipeline-503623.gold.master_ads`
where data between '2026-07-01' and '2026-07-31';
```

É a mesma regra da comissão média no `master_orders`.

---

## Cinco colunas que vêm nulas — e isso não é defeito

Em **anúncio em grupo** (campanha com vários produtos), cinco colunas vêm sempre nulas:

`item_id` · `qtd_itens` · `status_campanha` · `orcamento_campanha` · `meta_roas`

Medido em 05/11/2026: 150 de 150 linhas das cinco campanhas em grupo. Nas 25 individuais, 6.021 linhas, nenhum nulo.

**Por que todas juntas.** As cinco vêm do mesmo lugar — a configuração da campanha — e a Shopee recusa esses ids ali, com a mensagem *"auto & manual product ad types only"*. Sem linha de configuração, as cinco colunas ficam vazias de uma vez.

**O que nunca é nulo:** `gasto` e `nome_anuncio`. O que importa para o dinheiro está sempre lá.

A segunda causa possível de `item_id` nulo é campanha encerrada, que some da listagem e deixa o gasto histórico sem produto. Hoje esse caso não ocorre — todos os nulos são de anúncio em grupo.

**Consequência que incomoda:** com `status_campanha` nulo, nessas campanhas não dá para distinguir queda de venda por anúncio pausado de queda por ruptura. O status existe só na tela do Seller Centre.

---

## Como identificar uma campanha

**Para precisão, use `campaign_id`.** É o único campo estável.

**Para ler, extraia o colchete do `nome_anuncio`:**

```sql
regexp_extract(nome_anuncio, r'\[([^\]]+)\]$') as campanha
```

O formato do campo é `<título de um produto> [rótulo]`. Em campanha em grupo o colchete traz o nome que o vendedor deu — `[Lançamentos 2]`. Em campanha individual traz um número de desambiguação — `[2]`, `[4]` — ou não existe.

⚠️ **O título antes do colchete engana numa campanha em grupo.** Ele nomeia **um** item do grupo, escolhido pela Shopee, sem relação com o gasto. A campanha "Lançamentos 2" aparece rotulada com o *Suporte para Doces*, que gastou R$ 0,85 dos R$ 18,87 da campanha — sexto de sete produtos. Ler a linha como gasto daquele produto erra por vinte vezes.

⚠️ **E o campo muda sozinho.** Ele vem da performance e reflete o título vigente no momento da consulta. Reescrever o anúncio renomeia a campanha inclusive no histórico: seis das vinte e cinco campanhas antigas já aparecem na tabela com dois nomes diferentes. Nunca filtre por `nome_anuncio` com `LIKE` no título.

**Para separar os dois mundos, use `qtd_itens is null`** — hoje devolve exatamente as campanhas em grupo, sem falso positivo. Mas o marcador vai sujar: campanha encerrada que sai da listagem também perde a configuração e cai no mesmo filtro.

---

## A premissa que expirou

Até outubro de 2026 cada campanha anunciava **um produto só** — 24 campanhas verificadas em 02/09, todas com um item. É isso que permite guardar `item_id` como coluna simples e dizer "esta campanha é do produto X".

**Isso deixou de ser verdade em 30/10/2026**, quando a loja passou a criar anúncio em grupo. Para essas campanhas o gasto não é atribuível a um SKU, e a tabela não tenta: deixa `item_id` nulo em vez de ratear. Rateio arbitrário produz número que parece exato e não é.

**O teste `assert_ads_campanha_um_item` continua valendo, mas não cobre esse caso** — e vale entender por quê. Ele lê da configuração, que só contém as campanhas que a Shopee devolve na listagem. Por construção, um teste que lê só o que foi coletado não detecta o que não foi. Quem pega campanha ausente é o `assert_ads_conciliacao_loja_campanha`, que compara contra o nível loja.

**Se o teste do um-item falhar, não aumente o limite.** Ele passou a guardar uma premissa menor — "entre as campanhas que a listagem devolve, cada uma tem um item" — e continua fazendo o trabalho dele.

---

## O que esta tabela não responde

**De onde veio a visita.** Atribuição de origem de tráfego por pedido não existe na API pública da Shopee — confirmado pelo suporte. Não é lacuna a preencher, é teto da plataforma.

**Quanto custou cada produto dentro de uma campanha em grupo.** A tela "Desempenho do Produto" do Seller Centre mostra essa quebra; a API não devolve. Testado em 04 e 05/11/2026: o endpoint de performance entrega só o total da campanha, o de configuração recusa esses ids, a família GMS não conhece as campanhas, e a varredura dos 25 endpoints do módulo Ads não achou outro caminho. **É teto da plataforma, não lacuna a preencher.** Para decidir qual anúncio pausar dentro de uma campanha, a tela é a fonte.

**Histórico de configuração.** `status_campanha`, `orcamento_campanha` e `meta_roas` são o estado de **agora**, não o do dia da linha. Se o orçamento mudou em julho, isso não está aqui e não há como recuperar.

---

## Quando os números mudam sozinhos

A extração relê os últimos 30 dias todo dia, de propósito. A Shopee ajusta métrica de atribuição depois do fato — a janela de sete dias do "amplo" faz uma venda de hoje mudar o número de cinco dias atrás.

Por isso um relatório tirado hoje e outro tirado semana que vem, do mesmo período, podem divergir um pouco. **O mais recente é o correto.**
