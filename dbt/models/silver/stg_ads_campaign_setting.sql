-- Configuracao das campanhas: orcamento, status, meta de ROAS e a ligacao com
-- o produto anunciado.
--
-- E aqui que mora `item_id_list`, o unico caminho entre gasto de midia e SKU.
-- Ele vem DENTRO de `common_info`, nao na raiz -- ler na raiz devolve lista
-- vazia sem erro nenhum, e foi o que aconteceu na exploracao de 02/09.
--
-- ATENCAO AO GRAO: uma linha por campanha, sem data. E um retrato do estado
-- ATUAL, e a Shopee nao expoe historico de configuracao. Se o orcamento mudou
-- em julho, isso nao esta aqui e nao ha como recuperar. Junte com
-- stg_ads_campaign_daily por campaign_id apenas -- nunca por data.

with source as (
    select
        chave_natural,
        raw_data,
        extraction_date,
        loaded_at
    from {{ source('bronze', 'get_ads_campaign_setting') }}
),

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

    cast(json_value(raw_data, '$.campaign_id') as int64)                    as campaign_id,
    json_value(raw_data, '$.common_info.ad_name')                           as nome_anuncio,
    json_value(raw_data, '$.common_info.ad_type')                           as tipo_anuncio,
    json_value(raw_data, '$.common_info.campaign_status')                   as status,
    json_value(raw_data, '$.common_info.bidding_method')                    as metodo_lance,
    json_value(raw_data, '$.common_info.campaign_placement')                as posicionamento,
    cast(json_value(raw_data, '$.common_info.campaign_budget') as numeric)  as orcamento,
    cast(json_value(raw_data, '$.auto_bidding_info.roas_target') as numeric) as meta_roas,

    -- item_id_list e um array. Guardamos o primeiro item e a contagem: nas 24
    -- campanhas medidas em 02/09 nenhuma tinha mais de um item, entao a coluna
    -- resolve. `qtd_itens` existe para o dia em que isso deixar de valer --
    -- quando ela passar de 1, este modelo precisa virar tabela ponte, e o teste
    -- em schema.yml avisa.
    cast(json_value(raw_data, '$.common_info.item_id_list[0]') as int64)     as item_id,
    array_length(json_query_array(raw_data, '$.common_info.item_id_list'))   as qtd_itens,

    timestamp_seconds(cast(
        json_value(raw_data, '$.common_info.campaign_duration.start_time') as int64
    ))                                                                       as inicio,

{% else %}

    (raw_data ->> 'campaign_id')::bigint                                    as campaign_id,
    raw_data -> 'common_info' ->> 'ad_name'                                 as nome_anuncio,
    raw_data -> 'common_info' ->> 'ad_type'                                 as tipo_anuncio,
    raw_data -> 'common_info' ->> 'campaign_status'                         as status,
    raw_data -> 'common_info' ->> 'bidding_method'                          as metodo_lance,
    raw_data -> 'common_info' ->> 'campaign_placement'                      as posicionamento,
    (raw_data -> 'common_info' ->> 'campaign_budget')::numeric              as orcamento,
    (raw_data -> 'auto_bidding_info' ->> 'roas_target')::numeric            as meta_roas,
    (raw_data -> 'common_info' -> 'item_id_list' ->> 0)::bigint             as item_id,
    jsonb_array_length(coalesce(raw_data -> 'common_info' -> 'item_id_list', '[]'::jsonb)) as qtd_itens,
    to_timestamp((raw_data -> 'common_info' -> 'campaign_duration' ->> 'start_time')::bigint) as inicio,

{% endif %}

    extraction_date,
    loaded_at
from deduped
