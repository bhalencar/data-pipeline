-- Performance diaria de anuncios, nivel loja.
--
-- E a FONTE DE VERDADE do gasto com midia: uma linha por dia, sem risco de
-- dupla contagem. Medido em 02/09/2026 contra o nivel campanha em julho
-- inteiro: 839.17 aqui, 839.20 la. Tres centavos sobre 744 linhas.
--
-- Todo numero e cast explicito de texto. O bronze guarda raw_data como STRING
-- de proposito: quando a Shopee devolve um dia zerado, o JSON traz `0` (int)
-- onde normalmente vem `13.66` (float). Schema inferido de uma amostra assim
-- faria `expense` virar INTEGER e truncar centavo.

with source as (
    select
        chave_natural,
        raw_data,
        extraction_date,
        loaded_at
    from {{ source('bronze', 'get_ads_shop_daily') }}
),

-- Uma linha por dia. A releitura de 30 dias recarrega o mesmo dia varias
-- vezes de proposito, porque a Shopee ajusta metrica de atribuicao depois do
-- fato: `broad_*` credita conversao numa janela de 7 dias a partir do clique.
deduped as (

{% if target.type == 'bigquery' %}

    select chave_natural, raw_data, extraction_date, loaded_at
    from source
    qualify row_number() over (
        partition by chave_natural order by loaded_at desc
    ) = 1

{% else %}

    select distinct on (chave_natural)
        chave_natural, raw_data, extraction_date, loaded_at
    from source
    order by chave_natural, loaded_at desc

{% endif %}

)

select

{% if target.type == 'bigquery' %}

    date(json_value(raw_data, '$.date_iso'))                        as data,
    cast(json_value(raw_data, '$.impression')          as int64)    as impressoes,
    cast(json_value(raw_data, '$.clicks')              as int64)    as cliques,
    cast(json_value(raw_data, '$.ctr')                 as numeric)  as ctr,
    cast(json_value(raw_data, '$.expense')             as numeric)  as gasto,
    cast(json_value(raw_data, '$.direct_order')        as int64)    as pedidos_diretos,
    cast(json_value(raw_data, '$.broad_order')         as int64)    as pedidos_amplos,
    cast(json_value(raw_data, '$.direct_item_sold')    as int64)    as itens_diretos,
    cast(json_value(raw_data, '$.broad_item_sold')     as int64)    as itens_amplos,
    cast(json_value(raw_data, '$.direct_gmv')          as numeric)  as gmv_direto,
    cast(json_value(raw_data, '$.broad_gmv')           as numeric)  as gmv_amplo,
    cast(json_value(raw_data, '$.direct_roas')         as numeric)  as roas_direto,
    cast(json_value(raw_data, '$.broad_roas')          as numeric)  as roas_amplo,
    cast(json_value(raw_data, '$.direct_conversions')  as numeric)  as conversao_direta,
    cast(json_value(raw_data, '$.broad_conversions')   as numeric)  as conversao_ampla,
    cast(json_value(raw_data, '$.cost_per_conversion') as numeric)  as custo_por_conversao,

{% else %}

    (raw_data ->> 'date_iso')::date              as data,
    (raw_data ->> 'impression')::bigint          as impressoes,
    (raw_data ->> 'clicks')::bigint              as cliques,
    (raw_data ->> 'ctr')::numeric                as ctr,
    (raw_data ->> 'expense')::numeric            as gasto,
    (raw_data ->> 'direct_order')::bigint        as pedidos_diretos,
    (raw_data ->> 'broad_order')::bigint         as pedidos_amplos,
    (raw_data ->> 'direct_item_sold')::bigint    as itens_diretos,
    (raw_data ->> 'broad_item_sold')::bigint     as itens_amplos,
    (raw_data ->> 'direct_gmv')::numeric         as gmv_direto,
    (raw_data ->> 'broad_gmv')::numeric          as gmv_amplo,
    (raw_data ->> 'direct_roas')::numeric        as roas_direto,
    (raw_data ->> 'broad_roas')::numeric         as roas_amplo,
    (raw_data ->> 'direct_conversions')::numeric as conversao_direta,
    (raw_data ->> 'broad_conversions')::numeric  as conversao_ampla,
    (raw_data ->> 'cost_per_conversion')::numeric as custo_por_conversao,

{% endif %}

    extraction_date,
    loaded_at
from deduped
