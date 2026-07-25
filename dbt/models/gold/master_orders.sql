with items as (
    select * from {{ ref('stg_order_items') }}
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
    select
        sku,
        custo_unitario::numeric as custo_unitario,
        data_vigencia_inicio::date as data_vigencia_inicio
    from {{ ref('custo_produtos') }}
),

items_orders as (
    select
        items.order_sn,
        items.item_id,
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
        items.item_name,
        items.model_name,
        items.quantity_purchased,
        items.preco_tabela,
        items.discounted_price
    from items
    left join orders on items.order_sn = orders.order_sn
    left join customer_flags on items.order_sn = customer_flags.order_sn
    left join escrow on items.order_sn = escrow.order_sn
),

cost_matches as (
    select
        io.*,
        c.custo_unitario,
        row_number() over (
            partition by io.order_sn, io.item_sku, io.item_id
            order by c.data_vigencia_inicio desc
        ) as rn
    from items_orders io
    left join costs c
        on c.sku = io.item_sku
        and c.data_vigencia_inicio <= io.create_time::date
)

select
    order_sn,
    item_id,
    order_status,
    create_time,
    pay_time,
    customer_type,
    item_sku,
    item_name,
    model_name,
    quantity_purchased,
    preco_tabela,
    discounted_price,
    custo_unitario as cmv_unitario,
    round(discounted_price * quantity_purchased, 2) as receita_item,
    round(custo_unitario * quantity_purchased, 2) as cmv_total,
    round((discounted_price - custo_unitario) * quantity_purchased, 2) as margem_item,
    commission_fee,
    net_commission_fee,
    frete_custo_real,
    frete_pago_comprador,
    valor_pago_produto,
    escrow_amount
from cost_matches
where rn = 1
order by create_time, order_sn, item_sku