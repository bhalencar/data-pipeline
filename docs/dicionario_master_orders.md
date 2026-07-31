# Dicionário de campos — `gold.master_orders`

Guia de consulta rápida: o que cada coluna significa, em linguagem de negócio.

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
| `order_sn` | O número do pedido na Shopee. É o mesmo código que aparece no painel do vendedor. |
| `item_id` | Código interno da Shopee para o produto (o "produto pai"). |
| `model_id` | Código interno da Shopee para a variação (cor, tamanho). Fica vazio em produtos sem variação. |
| `item_sku` | Seu código de produto, quando cadastrado no nível do produto pai. |
| `sku_custo` | **Use este.** É o código que realmente identifica o que foi vendido — pega a variação quando existe, senão o produto pai. É por ele que a tabela busca o custo na planilha. |
| `item_name` | Nome do produto como aparece no anúncio. |
| `model_name` | Nome da variação vendida. Ex: "Marrom-Escuro \| Potes-Preto". |

---

## Quando e em que situação

| Campo | O que é |
|---|---|
| `create_time` | Data e hora em que o pedido foi feito. **É a data que você deve usar** para análises por período. |
| `pay_time` | Data e hora do pagamento. Costuma ser igual ou poucos minutos depois da criação. |
| `order_status` | Situação atual do pedido na Shopee. Valores possíveis: `COMPLETED` (concluído), `SHIPPED` (enviado), `TO_CONFIRM_RECEIVE` (aguardando confirmação do cliente), `CANCELLED` (cancelado), `TO_RETURN` (em devolução). |
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
