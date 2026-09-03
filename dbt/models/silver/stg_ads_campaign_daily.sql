-- Performance de anuncios por campanha x dia.
--
-- Serve para ATRIBUIR gasto -- por campanha e, via setting, por produto. O
-- total do DRE sai do stg_ads_shop_daily, nao daqui. Os dois batem (839.17 x
-- 839.20 em julho/2026), entao a separacao e disciplina contra dupla contagem,
-- nao correcao de divergencia.
--
-- ESTE ENDPOINT NAO TEM O MESMO SCHEMA DO NIVEL LOJA. Sao 19 campos contra 16,
-- e so 9 coincidem. Aqui existem cpc, cpdc, cr e cir, que la nao existem; la
-- existem item_sold e conversions, que aqui nao existem. E o que la se chama
-- `direct_roas` aqui se chama `direct_roi` -- provavelmente a mesma metrica com
-- nome diferente, mas isso e SUSPEITA e nao fato verificado. Por isso os nomes
-- em portugues nao foram unificados entre os dois modelos: unificar nome
-- afirmaria uma equivalencia que ninguem conferiu.

with source as (
    select
        chave_natural,
        raw_data,
        extraction_date,
        loaded_at
    from {{ source('bronze', 'get_ads_campaign_daily') }}
),

-- chave_natural aqui e "campaign_id|data" -- o grao real da tabela.
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

    cast(json_value(raw_data, '$.campaign_id') as int64)              as campaign_id,
    date(json_value(raw_data, '$.date_iso'))                          as data,
    json_value(raw_data, '$.ad_name')                                 as nome_anuncio,
    json_value(raw_data, '$.ad_type')                                 as tipo_anuncio,
    json_value(raw_data, '$.campaign_placement')                      as posicionamento,
    cast(json_value(raw_data, '$.impression')  as int64)              as impressoes,
    cast(json_value(raw_data, '$.clicks')      as int64)              as cliques,
    cast(json_value(raw_data, '$.ctr')         as numeric)            as ctr,
    cast(json_value(raw_data, '$.expense')     as numeric)            as gasto,
    cast(json_value(raw_data, '$.cpc')         as numeric)            as custo_por_clique,
    cast(json_value(raw_data, '$.cr')          as numeric)            as taxa_conversao,
    cast(json_value(raw_data, '$.cpdc')        as numeric)            as custo_por_conversao_direta,
    cast(json_value(raw_data, '$.direct_order')        as int64)      as pedidos_diretos,
    cast(json_value(raw_data, '$.broad_order')         as int64)      as pedidos_amplos,
    cast(json_value(raw_data, '$.direct_order_amount') as numeric)    as valor_pedidos_diretos,
    cast(json_value(raw_data, '$.broad_order_amount')  as numeric)    as valor_pedidos_amplos,
    cast(json_value(raw_data, '$.direct_gmv')  as numeric)            as gmv_direto,
    cast(json_value(raw_data, '$.broad_gmv')   as numeric)            as gmv_amplo,
    cast(json_value(raw_data, '$.direct_roi')  as numeric)            as roi_direto,
    cast(json_value(raw_data, '$.broad_roi')   as numeric)            as roi_amplo,
    cast(json_value(raw_data, '$.direct_cir')  as numeric)            as cir_direto,
    cast(json_value(raw_data, '$.broad_cir')   as numeric)            as cir_amplo,

{% else %}

    (raw_data ->> 'campaign_id')::bigint          as campaign_id,
    (raw_data ->> 'date_iso')::date               as data,
    raw_data ->> 'ad_name'                        as nome_anuncio,
    raw_data ->> 'ad_type'                        as tipo_anuncio,
    raw_data ->> 'campaign_placement'             as posicionamento,
    (raw_data ->> 'impression')::bigint           as impressoes,
    (raw_data ->> 'clicks')::bigint               as cliques,
    (raw_data ->> 'ctr')::numeric                 as ctr,
    (raw_data ->> 'expense')::numeric             as gasto,
    (raw_data ->> 'cpc')::numeric                 as custo_por_clique,
    (raw_data ->> 'cr')::numeric                  as taxa_conversao,
    (raw_data ->> 'cpdc')::numeric                as custo_por_conversao_direta,
    (raw_data ->> 'direct_order')::bigint         as pedidos_diretos,
    (raw_data ->> 'broad_order')::bigint          as pedidos_amplos,
    (raw_data ->> 'direct_order_amount')::numeric as valor_pedidos_diretos,
    (raw_data ->> 'broad_order_amount')::numeric  as valor_pedidos_amplos,
    (raw_data ->> 'direct_gmv')::numeric          as gmv_direto,
    (raw_data ->> 'broad_gmv')::numeric           as gmv_amplo,
    (raw_data ->> 'direct_roi')::numeric          as roi_direto,
    (raw_data ->> 'broad_roi')::numeric           as roi_amplo,
    (raw_data ->> 'direct_cir')::numeric          as cir_direto,
    (raw_data ->> 'broad_cir')::numeric           as cir_amplo,

{% endif %}

    extraction_date,
    loaded_at
from deduped
