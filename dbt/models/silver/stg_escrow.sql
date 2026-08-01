with source as (
    select
        order_sn,
        raw_data,
        extraction_date,
        loaded_at
    from {{ source('bronze', 'get_escrow_detail') }}
),

deduped as (

{% if target.type == 'bigquery' %}

    select
        order_sn,
        raw_data,
        extraction_date,
        loaded_at
    from source
    qualify row_number() over (
        partition by order_sn order by loaded_at desc
    ) = 1

{% else %}

    select distinct on (order_sn)
        order_sn,
        raw_data,
        extraction_date,
        loaded_at
    from source
    order by order_sn, loaded_at desc

{% endif %}

)

select
    order_sn,

{% if target.type == 'bigquery' %}

    -- Campos aninhados: o caminho JSON percorre order_income direto.
    cast(json_value(raw_data, '$.order_income.commission_fee') as numeric)          as commission_fee,
    cast(json_value(raw_data, '$.order_income.net_commission_fee') as numeric)      as net_commission_fee,
    cast(json_value(raw_data, '$.order_income.actual_shipping_fee') as numeric)     as frete_custo_real,
    cast(json_value(raw_data, '$.order_income.buyer_paid_shipping_fee') as numeric) as frete_pago_comprador,
    cast(json_value(raw_data, '$.order_income.cost_of_goods_sold') as numeric)      as valor_pago_produto,
    cast(json_value(raw_data, '$.order_income.escrow_amount') as numeric)           as escrow_amount,

{% else %}

    (raw_data -> 'order_income' ->> 'commission_fee')::numeric as commission_fee,
    (raw_data -> 'order_income' ->> 'net_commission_fee')::numeric as net_commission_fee,
    (raw_data -> 'order_income' ->> 'actual_shipping_fee')::numeric as frete_custo_real,
    (raw_data -> 'order_income' ->> 'buyer_paid_shipping_fee')::numeric as frete_pago_comprador,
    (raw_data -> 'order_income' ->> 'cost_of_goods_sold')::numeric as valor_pago_produto,
    (raw_data -> 'order_income' ->> 'escrow_amount')::numeric as escrow_amount,

{% endif %}

    extraction_date
from deduped