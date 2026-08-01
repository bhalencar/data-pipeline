with source as (
    select
        order_sn,
        raw_data,
        extraction_date,
        loaded_at
    from {{ source('bronze', 'get_order_detail') }}
),

-- Garante 1 linha por pedido, mesmo que ele tenha sido carregado
-- mais de uma vez (mantem sempre a versao mais recente)
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

    json_value(raw_data, '$.order_status')                                  as order_status,
    timestamp_seconds(cast(json_value(raw_data, '$.create_time') as int64)) as create_time,
    timestamp_seconds(cast(json_value(raw_data, '$.pay_time') as int64))    as pay_time,
    json_value(raw_data, '$.payment_method')                                as payment_method,
    json_value(raw_data, '$.buyer_username')                                as buyer_username,
    cast(json_value(raw_data, '$.total_amount') as numeric)                 as total_amount,
    cast(json_value(raw_data, '$.actual_shipping_fee') as numeric)          as actual_shipping_fee,
    json_value(raw_data, '$.shipping_carrier')                              as shipping_carrier,

{% else %}

    raw_data ->> 'order_status' as order_status,
    to_timestamp((raw_data ->> 'create_time')::bigint) as create_time,
    to_timestamp((raw_data ->> 'pay_time')::bigint) as pay_time,
    raw_data ->> 'payment_method' as payment_method,
    raw_data ->> 'buyer_username' as buyer_username,
    (raw_data ->> 'total_amount')::numeric as total_amount,
    (raw_data ->> 'actual_shipping_fee')::numeric as actual_shipping_fee,
    raw_data ->> 'shipping_carrier' as shipping_carrier,

{% endif %}

    extraction_date
from deduped