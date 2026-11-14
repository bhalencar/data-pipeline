# Mapeamento de Fontes — Casa e Patas Data Pipeline

Documento de referência da arquitetura de dados do projeto. Cobre as fontes extraídas,
os campos reais confirmados na API, as decisões de modelagem e as limitações conhecidas.

## Arquitetura geral

- **Bronze**: dado bruto, 1 tabela por endpoint, JSON preservado em coluna `JSONB`
- **Silver**: dado limpo e normalizado, 1 modelo por entidade/grão
- **Gold**: `master_orders`, o produto de dados final — 1 linha por item/SKU por pedido

## Bronze — endpoints extraídos

| Tabela | Endpoint | Frequência | Observações |
|---|---|---|---|
| `bronze.get_order_list` | `Order.get_order_list` | Diária (D-1) | Índice de controle: só `order_sn` + status, usado para descobrir o que buscar em detalhe |
| `bronze.get_order_detail` | `Order.get_order_detail` | Diária (D-1) | Pedido completo, incluindo `item_list` aninhado |
| `bronze.get_escrow_detail` | `Payment.get_escrow_detail` | Diária (D-1) | Financeiro do pedido (comissão, frete real, valor pago). Chamada 1 `order_sn` por vez (endpoint não suporta lote) |

Todas seguem o mesmo padrão de carga incremental: arquivo JSON extraído → carregado no Postgres →
movido para uma subpasta `loaded/` (evita reprocessamento).

## Silver — modelos e campos confirmados

### `stg_orders` (grão: pedido)
Campos: `order_sn`, `order_status`, `create_time`, `pay_time`, `payment_method`,
`buyer_username`, `total_amount`, `actual_shipping_fee`, `shipping_carrier`.

### `stg_order_items` (grão: item/SKU dentro do pedido)
Explode `item_list` via `jsonb_array_elements`. Campos confirmados na API real (prefixo `model_`
mesmo em produtos sem variação):
- `item_sku` — chave de cruzamento com a planilha de custo
- `model_name` — nome da variação (vazio quando não há variação)
- `model_original_price` → mapeado como `preco_tabela`
- `model_discounted_price` → mapeado como `discounted_price`
- `model_quantity_purchased` → mapeado como `quantity_purchased`

### `stg_customer_orders` (grão: pedido, por comprador)
Classifica cada pedido de um `buyer_username` em ordem cronológica via `row_number()`.
O 1º pedido de cada pessoa vira `'Novo'`, os seguintes `'Recorrente'` (campo `customer_type`).

### `stg_escrow` (grão: pedido)
Extraído de dentro do objeto aninhado `order_income` do JSON de escrow:
- `commission_fee` / `net_commission_fee` (líquida, específica de vendedores BR local)
- `frete_custo_real` (= `actual_shipping_fee`)
- `frete_pago_comprador` (= `buyer_paid_shipping_fee`)
- `valor_pago_produto` (= `cost_of_goods_sold` — nome de campo enganoso; é o valor pago pelo
  comprador pelos itens, não custo de mercadoria)
- `escrow_amount` — valor líquido final repassado pela Shopee

## Gold — `master_orders`

**Grão: 1 linha por item/SKU por pedido** (decisão deliberada, para permitir margem por produto).
Consequência: campos de nível de pedido — `order_status`, `pay_time`, `customer_type`, os campos
de escrow — se repetem em cada linha de item do mesmo pedido. Contagem de pedidos exige
`COUNT(DISTINCT order_sn)`.

Localização física: schema **`gold`** no Postgres (materializado como tabela).

Colunas: `order_sn`, `item_id`, `order_status`, `create_time`, `pay_time`, `customer_type`,
`item_sku`, `item_name`, `model_name`, `quantity_purchased`, `preco_tabela`, `discounted_price`,
`cmv_unitario`, `receita_item`, `cmv_total`, `margem_item`, `commission_fee`, `net_commission_fee`,
`frete_custo_real`, `frete_pago_comprador`, `valor_pago_produto`, `escrow_amount`.

### Lógica de custo com histórico (point-in-time)

O custo de cada item é o **mais recente vigente na data do pedido** (não o custo atual) —
via `row_number()` sobre custos com `data_vigencia_inicio <= create_time`, mantendo só `rn = 1`.
Isso garante que pedidos antigos sempre usem o custo que valia na época.

## Fonte de custo (`config.custo_produtos`)

`cp-pipeline-503623.config.custo_produtos` — tabela lida em tempo de execução pelo
`master_orders`. Histórico append-only: **nunca editar linha antiga**; custo que mudou entra
como linha nova com `data_vigencia_inicio` nova, porque o modelo escolhe a vigência mais
recente anterior à data do pedido e reescrever linha velha reescreveria margem de pedido já
fechado.

Workflow de atualização — um passo, sem deploy:

```sql
insert into `cp-pipeline-503623.config.custo_produtos`
  (sku, nome_produto, custo_unitario, data_vigencia_inicio, observacao, origem, alterado_em)
values ('SKU-01', 'Nome do produto', 12.34, date '2026-11-01',
        'de onde veio o custo', 'manual', current_timestamp());
```

A linha vale na rodada seguinte. Para valer **agora**, `dbt run --select master_orders`.

### O que era antes, e por que mudou (14/11/2026)

Era o seed `dbt/seeds/custo_produtos.csv`, gerado de `custo_produtos.xlsx` pelo
`export_custo_csv.py`. Seed viaja dentro da imagem do Cloud Run, então cadastrar produto
exigia commit, `builds submit` e `run jobs update`. Em 11/11/2026 quatro presépios de Natal
começaram a vender, o cadastro ficou sem deploy, e o teste `not_null` do `cmv_unitario`
derrubou o build por três dias.

O `export_custo_csv.py` está **desativado** — a xlsx local parou em 01/08/2026 e rodá-lo
sobrescreveria o seed inteiro, apagando em silêncio tudo que entrou desde agosto. A planilha
de precificação continua sendo de onde saem os custos novos; o que morreu foi o caminho
automático planilha → seed.

A mesma mudança valeu para `config.campanhas_extras`, lida pelo `get_ads.py`.

## Limitações conhecidas

- **Nome do cupom**: não existe na API da Shopee. Só há `seller_voucher_code` (código, só de
  cupons próprios do vendedor). Cupons da própria Shopee só aparecem como valor agregado
  (`voucher_from_shopee`), sem identificação. Fechado como limitação de plataforma, não do pipeline.
- **Fontes de tráfego** (canal de origem da venda): não confirmado se existe endpoint público
  equivalente — parece exclusivo do painel "Central de Dados" do Seller Center.
- **Validação financeira pendente**: os 3 pedidos de teste do Sandbox cancelaram automaticamente
  (prazo de envio expirado) antes de conseguirmos validar `get_escrow_detail` com um pedido
  `COMPLETED`. A estrutura está testada e correta, mas os valores reais (comissão, escrow_amount
  etc.) ainda não foram vistos diferentes de zero. Deve resolver naturalmente em produção.

## Ambiente Sandbox vs. Produção

| Item | Sandbox (atual) | Produção |
|---|---|---|
| Host de autorização | `open.test-stable.shopee.com.br/auth` | `open.shopee.com.br/auth` |
| Host da API | `openplatform.sandbox.test-stable.shopee.sg` | `partner.shopeemobile.com` |
| IP Whitelist | Não obrigatório | Obrigatório |

Migração deliberadamente adiada para a Fase 7, junto com o backfill histórico
(Janeiro/2026 em diante, em janelas de 15 dias).

## ⚠️ Manutenção recorrente — Renovação da Live API Partner Key

**Data de expiração atual: 23/01/2027 12:59**

A Live API Partner Key da Shopee tem validade limitada. Quando expirar, a autenticação
para de funcionar e o pipeline falha silenciosamente (o launchd continua rodando às 6h,
mas a extração retorna erro de autenticação).

**Como renovar:** Shopee Open Platform → App Management → App List →
app "data pipeline casa e patas" → renovar/regerar a Live API Partner Key,
depois atualizar o valor no `.env` local.

**Recomendação:** criar um lembrete no calendário para dezembro/2026,
com ~1 mês de folga antes do vencimento.

### Credenciais de produção (Go-Live aprovado em 29/07/2026)
| Campo | Valor |
|---|---|
| Live Partner_id | 2039225 |
| Test Partner_id (Sandbox, ainda ativo) | 1238362 |
| Status do app | Online |

---
_Última atualização: 29/07/2026_