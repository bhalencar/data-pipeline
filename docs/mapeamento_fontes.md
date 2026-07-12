# Mapeamento de Fontes — Shopee

Documento de referência para a camada de extração (bronze). Lista as bases e colunas
que serão extraídas via API, antes de qualquer definição de métrica (isso é definido
depois, na camada silver/gold e no dashboard).

## Bases a extrair

| Base (tabela bronze) | Endpoint da API | Principais colunas |
|---|---|---|
| Pedidos (lista) | `Order.get_order_list` | `order_sn`, `order_status`, `create_time`, `update_time` |
| Pedidos (detalhe) | `Order.get_order_detail` | `order_sn`, `total_amount`, `order_status`, `payment_method`, `create_time`, `pay_time`, `buyer_username`, `actual_shipping_fee`, `shipping_carrier` |
| Itens do pedido | `Order.get_order_detail` (lista aninhada `item_list`) | `order_sn`, `item_id`, `item_sku`, `item_name`, `model_sku`, `quantity_purchased`, `original_price`, `discounted_price` |
| Financeiro/Escrow | `Payment.get_escrow_detail` | `order_sn`, `escrow_amount`, `commission_fee`, `service_fee`, `buyer_payment_amount` |
| Catálogo de produtos | `Product.get_item_list` + `Product.get_item_base_info` | `item_id`, `item_sku`, `item_name`, `category_id`, `price`, `stock` |
| Campanhas de Ads | API de Ads (relatório de performance) | `campaign_id`, `item_id`, `date`, `impressions`, `clicks`, `expense`, `broad_gmv`, `direct_gmv`, `orders`, `roas` |

## Pontos em aberto / a validar

- **Fontes de tráfego** (Card do Produto, Pesquisar, Recomendação, Lives, etc.): não
  confirmado se existe endpoint público equivalente na Open API. Parece ser exclusivo
  do painel "Central de Dados" do Seller Center. Validar assim que tivermos acesso
  liberado à documentação completa no portal de desenvolvedor.
- **API de Ads**: provavelmente exige aprovação/permissão adicional separada da
  aprovação do app base (já solicitada em `[data de solicitação]`).

## Fonte de custo (planilha manual)

| Base | Origem | Principais colunas |
|---|---|---|
| Custo de produtos | `custo_produtos.xlsx` (upload manual) | `sku`, `nome_produto`, `custo_unitario`, `data_vigencia_inicio`, `observacao` |

> Chave de cruzamento entre Shopee e custo: `item_sku` (Shopee) ↔ `sku` (planilha de custo).

---
_Última atualização: 12/07/2026_