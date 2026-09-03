-- A premissa que sustenta o grao do master_ads.
--
-- O modelo guarda `item_id` como COLUNA, e isso so e honesto enquanto cada
-- campanha anunciar um item so. Em 02/09/2026, nas 24 campanhas da loja,
-- nenhuma tinha mais de um -- por isso a coluna. Se isso mudar, o gasto deixa
-- de ser atribuivel a um SKU sem rateio arbitrario, e o modelo precisa virar
-- tabela ponte campanha x item.
--
-- Este teste e o aviso. Sem ele, a mudanca entraria calada: o master_ads
-- continuaria mostrando UM item_id por campanha -- o primeiro do array -- e
-- toda analise por SKU passaria a atribuir a um produto gasto que foi de
-- varios. Numero errado com aparencia normal, que e o pior tipo.
--
-- Quando este teste falhar, NAO aumente o limite. Leia a nota de grao no
-- master_ads.sql e converta para tabela ponte.

{% if target.type == 'bigquery' %}

select
    campaign_id,
    nome_anuncio,
    qtd_itens
from {{ ref('stg_ads_campaign_setting') }}
where qtd_itens > 1
order by qtd_itens desc

{% else %}

-- Alvo Postgres congelado desde a migracao para o BigQuery.
select null as campaign_id, null as nome_anuncio, null as qtd_itens
where false

{% endif %}
