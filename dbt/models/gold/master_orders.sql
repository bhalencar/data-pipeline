with items as (
    select * from {{ ref('stg_order_items') }}
),

escrow_items as (
    select * from {{ ref('stg_escrow_items') }}
),

orders as (
    select
        order_sn,
        order_status,
        create_time,
        pay_time
    from {{ ref('stg_orders') }}
),

customer_flags as (
    select
        order_sn,
        customer_type
    from {{ ref('stg_customer_orders') }}
),

escrow as (
    select
        order_sn,
        commission_fee,
        net_commission_fee,
        frete_custo_real,
        frete_pago_comprador,
        valor_pago_produto,
        escrow_amount
    from {{ ref('stg_escrow') }}
),

costs as (

{% if target.type == 'bigquery' %}

    -- No BigQuery o seed ja chega com custo_unitario FLOAT64 e
    -- data_vigencia_inicio DATE, mas o cast para numeric mantem a
    -- precisao decimal igual a do Postgres nos calculos de margem.
    select
        sku,
        cast(custo_unitario as numeric) as custo_unitario,
        data_vigencia_inicio
    from {{ ref('custo_produtos') }}

{% else %}

    select
        sku,
        custo_unitario::numeric as custo_unitario,
        data_vigencia_inicio::date as data_vigencia_inicio
    from {{ ref('custo_produtos') }}

{% endif %}

),

items_orders as (
    select
        items.order_sn,
        items.item_id,
        items.model_id,
        orders.order_status,
        orders.create_time,
        orders.pay_time,
        customer_flags.customer_type,
        escrow.commission_fee,
        escrow.net_commission_fee,
        escrow.frete_custo_real,
        escrow.frete_pago_comprador,
        escrow.valor_pago_produto,
        escrow.escrow_amount,
        items.item_sku,
        items.sku_custo,
        items.item_name,
        items.model_name,
        items.quantity_purchased,
        items.preco_tabela,
        items.discounted_price,
        escrow_items.preco_desconto_linha,
        escrow_items.cupom_vendedor,
        escrow_items.cupom_shopee,
        escrow_items.gmv_item
    from items
    left join orders on items.order_sn = orders.order_sn
    left join customer_flags on items.order_sn = customer_flags.order_sn
    left join escrow on items.order_sn = escrow.order_sn
    -- coalesce(model_id, 0): escrow traz 0 para produto sem variacao
    left join escrow_items
        on  items.order_sn = escrow_items.order_sn
        and items.item_id  = escrow_items.item_id
        and coalesce(items.model_id, 0) = coalesce(escrow_items.model_id, 0)
),

cost_matches as (
    select
        io.*,
        c.custo_unitario,
        row_number() over (
            partition by io.order_sn, io.item_id, io.model_id
            order by c.data_vigencia_inicio desc
        ) as rn
    from items_orders io
    left join costs c
        on c.sku = io.sku_custo
        -- timestamp para data: BigQuery usa date(), Postgres usa ::date
        {% if target.type == 'bigquery' %}
        and c.data_vigencia_inicio <= date(io.create_time)
        {% else %}
        and c.data_vigencia_inicio <= io.create_time::date
        {% endif %}
),

deduplicated as (
    select * from cost_matches where rn = 1
),

rateio as (
    -- escrow_amount vem por PEDIDO. Aqui rateamos por item, proporcional ao GMV,
    -- para que SUM(receita_bruta) nao duplique em pedidos multi-item.
    select
        d.*,
        sum(d.gmv_item) over (partition by d.order_sn) as gmv_pedido,
        round(
            d.escrow_amount * d.gmv_item
            / nullif(sum(d.gmv_item) over (partition by d.order_sn), 0)
        , 2) as receita_bruta
    from deduplicated d
)

select
    order_sn,
    item_id,
    model_id,
    order_status,
    create_time,
    pay_time,
    customer_type,
    item_sku,
    sku_custo,
    item_name,
    model_name,
    quantity_purchased,
    preco_tabela,
    discounted_price,
    custo_unitario as cmv_unitario,
    round(discounted_price * quantity_purchased, 2) as receita_item,
    round(custo_unitario * quantity_purchased, 2) as cmv_total,
    round((discounted_price - custo_unitario) * quantity_purchased, 2) as margem_item,

    -- GMV (definicao Shopee 2026): preco apos desconto do vendedor menos cupom
    -- do vendedor. Cupom Shopee nao deduz. Inclui cancelados e devolvidos.
    preco_desconto_linha,
    cupom_vendedor,
    cupom_shopee,
    gmv_item,

    -- receita_bruta: escrow (repasse liquido da Shopee) rateado por item
    receita_bruta,

    -- receita_liquida: receita_bruta menos 6% de imposto.
    -- ATENCAO: base = repasse da Shopee, nao o GMV. Se o regime tributario exigir
    -- que a aliquota incida sobre o faturamento, trocar receita_bruta por gmv_item.
    {% if target.type == 'bigquery' %}
    -- cast do fator para numeric: sem isso o BigQuery promove a conta para
    -- FLOAT64 e o arredondamento pode divergir do Postgres nos centavos.
    round(receita_bruta * cast(0.94 as numeric), 2) as receita_liquida,
    {% else %}
    round(receita_bruta * (1 - 0.06), 2) as receita_liquida,
    {% endif %}

    -- comissao_shopee (take rate): fatia do GMV retida pela Shopee, somando
    -- comissao, taxa de servico, transacao e efeito de frete. Expressa em decimal
    -- (0.2718 = 27,18%). Em pedido cancelado o escrow e 0, entao da 1.0 (100%) --
    -- filtrar por order_status no dashboard.
    round(1 - receita_bruta / nullif(gmv_item, 0), 4) as comissao_shopee,

    commission_fee,
    net_commission_fee,
    frete_custo_real,
    frete_pago_comprador,
    valor_pago_produto,
    escrow_amount
from rateio
order by create_time, order_sn, sku_custo