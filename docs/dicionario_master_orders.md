# Dicionário de campos — `gold.master_orders`

Guia de consulta rápida: o que cada coluna significa, em linguagem de negócio.

> **Para quem é este arquivo.** É a versão para pessoa de negócio, com exemplos e explicação
> do porquê. A versão de engenharia está em `dbt/models/gold/schema.yml`, e a versão que os
> agentes consultam está na tabela `silver.dicionario_campos`, gerada de
> `dbt/seeds/dicionario_campos.csv`.
>
> As três descrevem os mesmos 31 campos, para leitores diferentes. **Campo novo ou
> descrição corrigida precisa entrar nas três** — a divergência entre elas foi o que
> escondeu a armadilha do fuso horário até 09/08/2026.

## O que é esta tabela

É a tabela final com todas as vendas da Casa e Patas na Shopee, pronta para análise.

**Cada linha é um produto dentro de um pedido.** Se um cliente comprou 3 itens diferentes
no mesmo pedido, isso vira 3 linhas. Se ele comprou 2 variações do mesmo produto (por
exemplo, o comedouro marrom e o branco), também vira 2 linhas — uma para cada variação.

Isso é importante na hora de contar: para saber **quantos pedidos** você teve, conte
`order_sn` distintos, não o número de linhas.

---

## Identificação do pedido e do produto

| Campo | O que é |
|---|---|
| `canal` | O marketplace de onde veio o pedido. Hoje sempre `shopee`. |
| `order_sn` | O número do pedido na Shopee. É o mesmo código que aparece no painel do vendedor. |
| `item_id` | Código interno da Shopee para o produto (o "produto pai"). |
| `model_id` | Código interno da Shopee para a variação (cor, tamanho). Fica vazio em produtos sem variação. |
| `item_sku` | Seu código de produto, quando cadastrado no nível do produto pai. |

> **Sobre o `canal`.** Ele é constante hoje, e por isso não separa nada — a loja só
> vende na Shopee. Ele existe desde já porque a `despesa_operacional` também tem canal,
> e um DRE por canal precisa dos dois lados. Quando o Mercado Livre entrar, só muda a
> origem do valor e nenhuma query precisa ser reescrita.
>
> Coluna constante não dispensa o rótulo: **continue dizendo "Shopee", nunca "total"**.
| `sku_custo` | **Use este.** É o código que realmente identifica o que foi vendido — pega a variação quando existe, senão o produto pai. É por ele que a tabela busca o custo na planilha. |
| `item_name` | Nome do produto como aparece no anúncio. |
| `model_name` | Nome da variação vendida. Ex: "Marrom-Escuro \| Potes-Preto". |

---

## Quando e em que situação

| Campo | O que é |
|---|---|
| `create_time` | Data e hora em que o pedido foi feito. **É a data que você deve usar** para análises por período. Vem em **UTC**, 3 horas à frente de São Paulo — veja o aviso abaixo. |
| `pay_time` | Data e hora do pagamento, também em UTC. Costuma ser igual ou poucos minutos depois da criação. |

> **Atenção ao fuso horário.** As datas são gravadas em UTC, que está 3 horas à frente
> de São Paulo. Um pedido feito às 22h de terça aparece como quarta-feira se você não
> converter. Cerca de 16% dos pedidos caem em outro dia por causa disso.
>
> Em SQL, use `date(create_time, 'America/Sao_Paulo')` em vez de `date(create_time)`.
> Em Looker ou planilha, confira se a ferramenta está convertendo para o horário de Brasília.
>
> **A referência certa é o painel da Shopee**, que mostra horário de Brasília. Verificado
> em 09/08/2026 com o pedido `260130CHJ981HS`: o painel exibe 29/01 às 21:13, e é essa
> a data comercial correta.

> **Não tire a data do número do pedido.** Os seis primeiros dígitos do `order_sn`
> parecem uma data — `260130...` — mas seguem o relógio de Singapura, onde fica o
> servidor da Shopee. Nos 95 pedidos da base, todos os 95 batem com Singapura e apenas
> 28 batem com Brasília. O pedido acima tem `260130` no número e foi feito no dia 29.
| `order_status` | Situação atual do pedido na Shopee. Oito valores já vistos, do mais cru ao final: `UNPAID` (criado e nunca pago), `READY_TO_SHIP` (pago, aguardando envio), `PROCESSED` (em preparação), `SHIPPED` (enviado), `TO_CONFIRM_RECEIVE` (aguardando confirmação do cliente), `TO_RETURN` (em devolução), `CANCELLED` (cancelado), `COMPLETED` (concluído). |

> **Status muda com o tempo.** A extração relê os pedidos dos últimos 30 dias a cada
> rodada, então pedido mais novo que isso ainda está em movimento. Pedido que não
> chegou em `COMPLETED` ou `CANCELLED` e já passou de 30 dias não muda mais sozinho:
> isso é sinal de que algo travou, não de que o pedido está mesmo em trânsito.
| `customer_type` | Se foi a primeira compra daquele cliente (`Novo`) ou se ele já havia comprado antes (`Recorrente`). |

---

## Quantidade e preços

| Campo | O que é |
|---|---|
| `quantity_purchased` | Quantas unidades daquele item o cliente levou. |
| `preco_tabela` | Preço cheio, sem desconto — o valor "de" do anúncio. |
| `discounted_price` | Preço de venda **por unidade**, já com as promoções aplicadas. |
| `preco_desconto_linha` | Preço de venda **da linha inteira** (preço × quantidade). Vem do relatório financeiro da Shopee. |

> **Atenção:** `discounted_price` é por unidade, `preco_desconto_linha` é o total.
> Não some os dois nem os compare diretamente.

---

## Custo e margem de produto

| Campo | O que é |
|---|---|
| `cmv_unitario` | Quanto custa uma unidade daquele produto para você. Vem da planilha de custos. |
| `cmv_total` | Custo total daquela linha (custo unitário × quantidade). |
| `receita_item` | Valor de venda da linha (preço unitário × quantidade). |
| `margem_item` | Quanto sobrou naquela linha, considerando só o custo do produto: `receita_item − cmv_total`. |

> **O que a margem NÃO considera:** comissão da Shopee, frete, impostos e cupons.
> Ela responde "quanto ganhei acima do custo do produto", não "quanto entrou no bolso".
> Para isso, use `receita_bruta` e `receita_liquida` mais abaixo.

---

## GMV — o faturamento

| Campo | O que é |
|---|---|
| `cupom_vendedor` | Desconto de cupom que saiu do **seu** bolso, já dividido por item. |
| `cupom_shopee` | Desconto de cupom bancado pela **Shopee**. Não reduz seu faturamento. |
| `gmv_item` | **O faturamento daquela linha.** É o preço de venda menos o seu cupom. |

O GMV segue a definição oficial da Shopee (2026): preço do item menos desconto do vendedor.
Cupons da Shopee não são descontados, taxas do comprador não entram, e **pedidos cancelados
e devolvidos continuam contando**.

> **Por que cancelado conta?** Porque GMV mede volume de vendas geradas, não dinheiro
> recebido. Para dinheiro de verdade, use `receita_bruta`.

> **Cuidado ao comparar com o painel da Shopee.** O `gmv_item` fica **vazio** enquanto
> a Shopee não libera o escrow do pedido — e vazio não vira zero: o pedido simplesmente
> some da soma, sem aviso nenhum. Antes de comparar, conte quantas linhas do período
> estão com `gmv_item` vazio.
>
> O painel conta **pedidos pagos**. Aqui, `order_status <> 'CANCELLED'` entrega isso:
> pedido não pago é cancelado automaticamente pela Shopee e cai fora do filtro sozinho.
> A única exceção é o pedido criado há poucos dias que ainda não foi pago nem cancelado —
> ele fica em `UNPAID` e entra na conta. Em recorte que inclua os últimos dias, e onde
> essa diferença importe, use `pay_time is not null`.

**Exemplo real** (pedido `260728S8J8BE78`):

| Etapa | Valor |
|---|---|
| Preço cheio | R$ 113,61 |
| − promoção (flash sale) | − R$ 56,81 |
| = preço de venda | R$ 56,80 |
| − cupom do vendedor (CASAEF2) | − R$ 1,14 |
| **= GMV** | **R$ 55,66** |

---

## Receita — o que realmente entra

| Campo | O que é |
|---|---|
| `receita_bruta` | Quanto a Shopee efetivamente repassa para você naquela linha, depois de reter tudo o que ela cobra. Em pedido cancelado, é zero. |
| `receita_liquida` | A receita bruta menos 6% de imposto. |
| `comissao_shopee` | A fatia do faturamento que ficou com a Shopee, em decimal (0,3565 = 35,65%). |

No mesmo pedido do exemplo: GMV de R$ 55,66, receita bruta de R$ 40,53 — ou seja,
a Shopee ficou com 27% daquela venda.

> **Cuidados ao usar estes campos:**
>
> - `comissao_shopee` inclui **tudo** que a Shopee retém: comissão, taxa de serviço,
>   taxa de transação e o efeito do frete. Não é apenas a comissão contratual.
> - Em pedidos **cancelados** este campo mostra 100%, porque o repasse foi zero.
>   Sempre filtre por `order_status` ao analisar.
> - Para calcular a comissão média de um período, **não tire a média da coluna**.
>   Use `1 − soma(receita_bruta) ÷ soma(gmv_item)`, senão um pedido de R$ 20 pesa
>   o mesmo que um de R$ 200.

---

## Fretes e detalhamento financeiro

| Campo | O que é |
|---|---|
| `frete_pago_comprador` | Quanto o cliente pagou de frete. |
| `frete_custo_real` | Quanto o frete custou de verdade. Se for maior que o pago pelo cliente, a diferença saiu de algum lugar — subsídio da Shopee ou do seu bolso. |
| `commission_fee` | A comissão da Shopee em valor absoluto, isolada das demais taxas. |
| `net_commission_fee` | A comissão após ajustes e rebates. |
| `valor_pago_produto` | Valor dos produtos conforme o relatório financeiro da Shopee. |
| `escrow_amount` | O repasse **do pedido inteiro**. Em pedidos com vários itens, este valor se repete em cada linha. |

> **Nunca some `escrow_amount`** em análises. Como ele se repete nas linhas do mesmo
> pedido, a soma fica inflada. Para somar repasse, use `receita_bruta`, que já vem
> dividido corretamente por item.

---

## Coisas que valem saber antes de analisar

**1. Pedidos antes de junho/2026 não têm custo.**
São produtos que saíram de linha e não estão na planilha de custos. Nesses casos,
`cmv_unitario`, `cmv_total` e `margem_item` ficam vazios. É proposital, não é erro.

**2. Contagem de pedidos ≠ contagem de linhas.**
Use `count(distinct order_sn)` para número de pedidos.

**3. GMV e receita contam histórias diferentes, de propósito.**
GMV mede volume de vendas (inclui cancelado e devolvido). Receita mede dinheiro
que entrou. Os dois estão certos, respondem perguntas diferentes.

**4. Devolução pode gerar repasse negativo.**
Se você pagou o frete de retorno, o `escrow_amount` daquele pedido fica negativo.
É o comportamento correto — você realmente pagou para vender.

**5. Ao filtrar vendas "de verdade", exclua cancelados.**
`where order_status <> 'CANCELLED'` resolve a maioria dos casos.

**6. Preço unitário zerado não é venda com defeito.**
Existe um pedido (21/07/2026) em que `discounted_price` veio **0**. A venda
aconteceu normalmente: `preco_desconto_linha` R$ 56,16, `valor_pago_produto`
R$ 56,16 e `gmv_item` R$ 55,03 estão todos corretos.

A Shopee às vezes não preenche o campo de preço unitário com desconto, mas o
valor da linha chega íntegro por outros campos. **Para somar dinheiro, use
`gmv_item` ou `receita_bruta`** — nunca `discounted_price × quantidade`.

**7. `loaded_at` diz respeito ao pedido, não à tabela.**
A coluna marca quando a Shopee mandou notícia **daquele pedido** pela última vez,
e não quando a tabela foi construída. Como o `master_orders` é reconstruído todo
dia, um carimbo de construção seria igual em todas as linhas e não serviria para
nada.

Pedido antigo com `loaded_at` antigo é normal: significa que nada mudou nele.
Todos os itens de um mesmo pedido têm o mesmo valor, porque a Shopee entrega o
pedido inteiro numa chamada só.
