-- Palavras-chave da Shopee com volume de busca, por item e por snapshot.
--
-- GRAO: item_id x keyword x data_snapshot.
--
-- O dedup usa as TRES COLUNAS, nao a chave_natural do bronze. A keyword e
-- texto livre, com espaco e acento, e chave concatenada com delimitador fica
-- fragil quando o proprio texto pode conter o delimitador. As colunas
-- extraidas nao tem esse problema.
--
-- A releitura acontece quando a coleta semanal e reexecutada no mesmo dia --
-- por exemplo depois de uma falha de rate limit. Nesse caso vale a leitura
-- mais recente, igual ao resto do projeto.

with source as (
    select
        raw_data,
        extraction_date,
        loaded_at
    from {{ source('bronze', 'get_keywords') }}
),

tipado as (

{% if target.type == 'bigquery' %}

    select
        cast(json_value(raw_data, '$.item_id') as int64)        as item_id,
        json_value(raw_data, '$.keyword')                       as palavra,
        date(json_value(raw_data, '$.data_snapshot'))           as data_snapshot,
        cast(json_value(raw_data, '$.search_volume')  as int64) as volume_busca,
        cast(json_value(raw_data, '$.quality_score')  as int64) as qualidade,
        cast(json_value(raw_data, '$.suggested_bid')  as numeric) as lance_sugerido,
        cast(json_value(raw_data, '$.no_catalogo')    as bool)  as no_catalogo,
        extraction_date,
        loaded_at
    from source

{% else %}

    select
        (raw_data ->> 'item_id')::bigint        as item_id,
        raw_data ->> 'keyword'                  as palavra,
        (raw_data ->> 'data_snapshot')::date    as data_snapshot,
        (raw_data ->> 'search_volume')::bigint  as volume_busca,
        (raw_data ->> 'quality_score')::bigint  as qualidade,
        (raw_data ->> 'suggested_bid')::numeric as lance_sugerido,
        (raw_data ->> 'no_catalogo')::boolean   as no_catalogo,
        extraction_date,
        loaded_at
    from source

{% endif %}

)

{% if target.type == 'bigquery' %}

select * from tipado
qualify row_number() over (
    partition by item_id, palavra, data_snapshot
    order by loaded_at desc
) = 1

{% else %}

select distinct on (item_id, palavra, data_snapshot) *
from tipado
order by item_id, palavra, data_snapshot, loaded_at desc

{% endif %}
