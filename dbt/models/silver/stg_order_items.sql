with source as (
    select
        order_sn,
        raw_data,
        extraction_date,
        loaded_at
    from {{ source('bronze', 'get_order_detail') }}
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

),

-- Explode a lista de itens: 1 linha de pedido vira N linhas, 1 por item
items_exploded as (

{% if target.type == 'bigquery' %}

    -- No BigQuery o unnest vai no FROM (cross join), nao no SELECT.
    -- json_query_array devolve um array de STRING, um por item.
    select
        order_sn,
        item,
        extraction_date,
        loaded_at
    from deduped,
         unnest(json_query_array(raw_data, '$.item_list')) as item

{% else %}

    select
        order_sn,
        jsonb_array_elements(raw_data -> 'item_list') as item,
        extraction_date,
        loaded_at
    from deduped

{% endif %}

)

select
    order_sn,

{% if target.type == 'bigquery' %}

    cast(json_value(item, '$.item_id') as int64)                    as item_id,
    json_value(item, '$.item_sku')                                  as item_sku,
    json_value(item, '$.item_name')                                 as item_name,
    cast(json_value(item, '$.model_id') as int64)                   as model_id,
    nullif(json_value(item, '$.model_sku'), '')                     as model_sku,
    nullif(json_value(item, '$.model_name'), '')                    as model_name,
    coalesce(
        nullif(json_value(item, '$.model_sku'), ''),
        nullif(json_value(item, '$.item_sku'), '')
    )                                                               as sku_custo,
    cast(json_value(item, '$.model_quantity_purchased') as int64)   as quantity_purchased,
    cast(json_value(item, '$.model_original_price') as numeric)     as preco_tabela,
    cast(json_value(item, '$.model_discounted_price') as numeric)   as discounted_price,

{% else %}

    (item ->> 'item_id')::bigint as item_id,
    item ->> 'item_sku' as item_sku,
    item ->> 'item_name' as item_name,
    (item ->> 'model_id')::bigint as model_id,
    nullif(item ->> 'model_sku', '') as model_sku,
    nullif(item ->> 'model_name', '') as model_name,
    coalesce(
        nullif(item ->> 'model_sku', ''),
        nullif(item ->> 'item_sku', '')
    ) as sku_custo,
    (item ->> 'model_quantity_purchased')::int as quantity_purchased,
    (item ->> 'model_original_price')::numeric as preco_tabela,
    (item ->> 'model_discounted_price')::numeric as discounted_price,

{% endif %}

    extraction_date,

    -- loaded_at: quando o bronze recebeu ESTE pedido pela ultima vez.
    -- Sobrevive ao explode de item_list de proposito -- o master_orders
    -- precisa dela para ter coluna de carga, e sem carregar aqui o valor
    -- morre no unnest. Vem de `deduped`, que ja escolheu a carga mais
    -- recente por order_sn, entao todos os itens de um pedido compartilham
    -- o mesmo loaded_at. Isso e correto: a Shopee entrega o pedido inteiro
    -- numa chamada so.
    loaded_at
from items_exploded