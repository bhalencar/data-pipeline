-- Grao do master_orders: 1 linha por variacao (model_id) de cada item (item_id)
-- dentro de um pedido. Produtos com variacao repetem o item_id do pai no mesmo
-- pedido, entao model_id faz parte da chave.
select
    order_sn,
    item_id,
    model_id,
    count(*) as linhas
from {{ ref('master_orders') }}
group by 1, 2, 3
having count(*) > 1