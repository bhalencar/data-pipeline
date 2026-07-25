-- Esse teste PASSA se a query não retornar nenhuma linha.
-- Se retornar linhas, significa que existe order_sn + item_id duplicado.
select
    order_sn,
    item_id,
    count(*) as qtd
from {{ ref('master_orders') }}
group by order_sn, item_id
having count(*) > 1