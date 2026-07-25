with source as (
    select
        order_sn,
        raw_data,
        extraction_date,
        loaded_at
    from {{ source('bronze', 'get_order_detail') }}
),

deduped as (
    select distinct on (order_sn)
        order_sn,
        raw_data,
        extraction_date,
        loaded_at
    from source
    order by order_sn, loaded_at desc
),

-- Explode a lista de itens: 1 linha de pedido vira N linhas, 1 por item
items_exploded as (
    select
        order_sn,
        jsonb_array_elements(raw_data -> 'item_list') as item,
        extraction_date
    from deduped
)

select
    order_sn,
    (item ->> 'item_id')::bigint as item_id,
    item ->> 'item_sku' as item_sku,
    item ->> 'item_name' as item_name,
    (item ->> 'model_id')::bigint as model_id,
    nullif(item ->> 'model_sku', '') as model_sku,
    nullif(item ->> 'model_name', '') as model_name,
    (item ->> 'model_quantity_purchased')::int as quantity_purchased,
    (item ->> 'model_original_price')::numeric as preco_tabela,
    (item ->> 'model_discounted_price')::numeric as discounted_price,
    extraction_date
from items_exploded