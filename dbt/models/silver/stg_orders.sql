with source as (
    select
        order_sn,
        raw_data,
        extraction_date,
        loaded_at
    from {{ source('bronze', 'get_order_detail') }}
),

-- Garante 1 linha por pedido, mesmo que ele tenha sido carregado
-- mais de uma vez (mantém sempre a versão mais recente)
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
    raw_data ->> 'order_status' as order_status,
    to_timestamp((raw_data ->> 'create_time')::bigint) as create_time,
    to_timestamp((raw_data ->> 'pay_time')::bigint) as pay_time,
    raw_data ->> 'payment_method' as payment_method,
    raw_data ->> 'buyer_username' as buyer_username,
    (raw_data ->> 'total_amount')::numeric as total_amount,
    (raw_data ->> 'actual_shipping_fee')::numeric as actual_shipping_fee,
    raw_data ->> 'shipping_carrier' as shipping_carrier,
    extraction_date
from deduped