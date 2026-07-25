with source as (
    select
        order_sn,
        raw_data,
        extraction_date,
        loaded_at
    from {{ source('bronze', 'get_escrow_detail') }}
),

deduped as (
    select distinct on (order_sn)
        order_sn,
        raw_data,
        extraction_date,
        loaded_at
    from source
    order by order_sn, loaded_at desc
)

select
    order_sn,
    (raw_data -> 'order_income' ->> 'commission_fee')::numeric as commission_fee,
    (raw_data -> 'order_income' ->> 'net_commission_fee')::numeric as net_commission_fee,
    (raw_data -> 'order_income' ->> 'actual_shipping_fee')::numeric as frete_custo_real,
    (raw_data -> 'order_income' ->> 'buyer_paid_shipping_fee')::numeric as frete_pago_comprador,
    (raw_data -> 'order_income' ->> 'cost_of_goods_sold')::numeric as valor_pago_produto,
    (raw_data -> 'order_income' ->> 'escrow_amount')::numeric as escrow_amount,
    extraction_date
from deduped