select
count(distinct order_sn) as pedidos,
sum(gmv_item) as gmv
--sum(valor_pago_produto) as receita_produto,
--sum(escrow_amount) as escrow_amount
from data_pipeline.gold.master_orders
where --order_status = 'COMPLETED'
pay_time <= '2026-07-01'

