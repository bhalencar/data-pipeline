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

## Campanha sem produto

`item_id` é o que liga gasto de mídia a um SKU. Ele vem **nulo** quando a campanha não aparece mais na listagem da Shopee.

Campanha encerrada some, e o gasto histórico dela continua na tabela sem produto associado. **Nulo aqui é esperado, não defeito** — a alternativa seria perder a linha de gasto, o que é pior.

---

## Uma premissa que pode expirar

Hoje cada campanha anuncia **um produto só**. Foram 24 campanhas verificadas em 02/09/2026, todas com um item.

É isso que permite guardar `item_id` como uma coluna simples e dizer "esta campanha é do produto X".

Se a loja passar a criar campanha com vários produtos, o gasto deixa de ser atribuível a um SKU sem rateio arbitrário — e rateio arbitrário produz número que parece exato e não é. O teste `assert_ads_campanha_um_item` avisa quando isso acontecer, e nesse dia o modelo precisa mudar de formato.

**Se esse teste falhar, não aumente o limite.** Ele está fazendo o trabalho dele.

---

## O que esta tabela não responde

**De onde veio a visita.** Atribuição de origem de tráfego por pedido não existe na API pública da Shopee — confirmado pelo suporte. Não é lacuna a preencher, é teto da plataforma.

**Quanto custou cada produto dentro de uma campanha com vários.** Enquanto cada campanha tiver um produto a pergunta não existe; quando passar a ter, a resposta honesta é "a Shopee não reparte".

**Histórico de configuração.** `status_campanha`, `orcamento_campanha` e `meta_roas` são o estado de **agora**, não o do dia da linha. Se o orçamento mudou em julho, isso não está aqui e não há como recuperar.

---

## Quando os números mudam sozinhos

A extração relê os últimos 30 dias todo dia, de propósito. A Shopee ajusta métrica de atribuição depois do fato — a janela de sete dias do "amplo" faz uma venda de hoje mudar o número de cinco dias atrás.

Por isso um relatório tirado hoje e outro tirado semana que vem, do mesmo período, podem divergir um pouco. **O mais recente é o correto.**
