-- Explode o array items de dentro de order_income no escrow.
-- ATENCAO: aqui discounted_price ja e o TOTAL DA LINHA (preco x quantidade),
-- diferente do stg_order_items (que vem do order_detail e e UNITARIO).
with source as (
    select order_sn, raw_data, loaded_at
    from {{ source('bronze', 'get_escrow_detail') }}
),

deduped as (

{% if target.type == 'bigquery' %}

    select order_sn, raw_data
    from source
    qualify row_number() over (
        partition by order_sn order by loaded_at desc
    ) = 1

{% else %}

    select distinct on (order_sn)
        order_sn, raw_data
    from source
    order by order_sn, loaded_at desc

{% endif %}

),

exploded as (

{% if target.type == 'bigquery' %}

    select
        order_sn,
        item
    from deduped,
         unnest(json_query_array(raw_data, '$.order_income.items')) as item

{% else %}

    select
        order_sn,
        jsonb_array_elements(raw_data -> 'order_income' -> 'items') as item
    from deduped

{% endif %}

)

select
    order_sn,

{% if target.type == 'bigquery' %}

    cast(json_value(item, '$.item_id') as int64)                            as item_id,
    cast(nullif(json_value(item, '$.model_id'), '0') as int64)              as model_id,
    nullif(json_value(item, '$.model_sku'), '')                             as model_sku,
    cast(json_value(item, '$.quantity_purchased') as int64)                 as quantity_purchased,
    cast(json_value(item, '$.original_price') as numeric)                   as preco_original_linha,
    cast(json_value(item, '$.discounted_price') as numeric)                 as preco_desconto_linha,
    cast(json_value(item, '$.seller_discount') as numeric)                  as desconto_vendedor,
    cast(json_value(item, '$.discount_from_voucher_seller') as numeric)     as cupom_vendedor,
    cast(json_value(item, '$.discount_from_voucher_shopee') as numeric)     as cupom_shopee,
    -- GMV Shopee: preco apos desconto do vendedor, menos o cupom do vendedor.
    -- Cupom Shopee NAO deduz (rebate de plataforma).
    round(
        cast(json_value(item, '$.discounted_price') as numeric)
        - cast(json_value(item, '$.discount_from_voucher_seller') as numeric)
    , 2)                                                                    as gmv_item

{% else %}

    (item ->> 'item_id')::bigint                          as item_id,
    nullif(item ->> 'model_id', '0')::bigint              as model_id,
    nullif(item ->> 'model_sku', '')                      as model_sku,
    (item ->> 'quantity_purchased')::int                  as quantity_purchased,
    (item ->> 'original_price')::numeric                  as preco_original_linha,
    (item ->> 'discounted_price')::numeric                as preco_desconto_linha,
    (item ->> 'seller_discount')::numeric                 as desconto_vendedor,
    (item ->> 'discount_from_voucher_seller')::numeric    as cupom_vendedor,
    (item ->> 'discount_from_voucher_shopee')::numeric    as cupom_shopee,
    round(
        (item ->> 'discounted_price')::numeric
        - (item ->> 'discount_from_voucher_seller')::numeric
    , 2)                                                  as gmv_item

{% endif %}

from exploded