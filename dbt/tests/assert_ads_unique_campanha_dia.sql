-- Unicidade do grao do master_ads: uma linha por campanha por dia.
--
-- Duplicata aqui dobra o gasto de midia no DRE em silencio. As duas formas de
-- isso acontecer:
--
--   1. O dedup por loaded_at no silver falhar -- a releitura de 30 dias
--      recarrega o mesmo dia varias vezes de proposito.
--   2. O left join com stg_ads_campaign_setting multiplicar linha, se algum
--      dia aquele modelo passar a ter mais de uma linha por campaign_id.
--
-- O caso 2 e o que me preocupa: o setting nao tem data hoje, mas se a Shopee
-- passar a versionar configuracao, o join vira um-para-muitos e cada dia de
-- gasto se multiplica pelo numero de versoes. Silencioso e caro.

select
    campaign_id,
    data,
    count(*) as n
from {{ ref('master_ads') }}
group by campaign_id, data
having count(*) > 1
