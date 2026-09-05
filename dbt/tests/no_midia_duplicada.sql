-- Testa se há duplicação de gasto com mídia entre as duas fontes
-- Se esta query retornar 1 linha, significa que há midia_manual com valor > 0
-- enquanto stg_ads também existe, o que configuraria duplicação.

select 1
from (
  select
    'midia_manual' as source,
    round(sum(valor), 2) as total
  from {{ ref('despesa_operacional_manual') }}
  where categoria = 'midia_manual' and canal = 'shopee'

  union all

  select
    'stg_ads' as source,
    round(sum(gasto), 2) as total
  from {{ ref('stg_ads_shop_daily') }}
  where data between '2026-03-01' and '2026-08-31'
)
where source = 'midia_manual' and total > 0
-- Se houver linha aqui, há duplicação: midia_manual não deveria ter valores quando stg_ads existe
