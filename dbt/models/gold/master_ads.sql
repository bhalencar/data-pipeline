{{ config(materialized='table') }}

-- master_ads — desempenho de midia paga, grao CAMPANHA x DIA.
--
-- Card #1 do Roadmap de Dados. Fonte: Shopee Ads API, modulo 105.
--
-- ================================================================= GRAO
-- Uma linha por campanha por dia. `canal` existe desde ja, constante 'shopee',
-- pelo mesmo motivo da despesa_operacional: o dia em que entrar Mercado Livre,
-- o DRE por canal nasce funcionando dos dois lados.
--
-- POR QUE NAO GRAO POR SKU. Seria o mais util para a Clara, e nao da para
-- fazer com honestidade: uma campanha pode anunciar varios itens e a Shopee
-- nao reparte o gasto entre eles. Ratear daria um numero com aparencia de
-- exato e sem lastro. Hoje a questao e teorica -- nas 24 campanhas medidas em
-- 02/09/2026 nenhuma tinha mais de um item -- e por isso `item_id` esta aqui
-- como coluna. O teste assert_ads_campanha_um_item avisa quando deixar de ser.
--
-- ============================================== O TOTAL DO DRE NAO SAI DAQUI
-- Some `gasto` desta tabela e voce chega perto do gasto real, nao nele.
-- O numero do DRE e o do nivel loja, em `silver.stg_ads_shop_daily`.
--
-- Medido em julho/2026: loja 839.17, soma das campanhas 839.20. Tres centavos
-- sobre 744 linhas -- arredondamento por linha, nao dado faltando. A diferenca
-- e pequena e mesmo assim a regra vale, porque campanha apagada some da
-- listagem e o gasto dela sai junto: o total por campanha pode encolher no
-- futuro sem nada ter mudado no passado.
--
-- ================================================================ CUIDADOS
-- `gmv_amplo` e `pedidos_amplos` NAO SE SOMAM entre campanhas. A atribuicao
-- ampla credita a mesma venda a mais de uma campanha, do mesmo jeito que o
-- `escrow_amount` repete o valor do pedido em cada item. Somar infla.
--
-- A atribuicao usa janela de 7 dias creditada ao DIA DO CLIQUE. O GMV daqui
-- nunca vai bater com o `master_orders` do mesmo dia, e isso nao e defeito:
-- sao perguntas diferentes. "Quanto o anuncio de terca gerou" e "quanto
-- vendemos na terca" sao coisas distintas.
--
-- `roi_direto`, `ctr`, `cir` e `custo_por_clique` sao RAZOES ja calculadas
-- pela Shopee: media de razao nao e razao da media. Para o periodo, recalcule
-- -- sum(gmv) / sum(gasto) -- em vez de tirar media da coluna.

with performance as (
    select * from {{ ref('stg_ads_campaign_daily') }}
),

configuracao as (
    select * from {{ ref('stg_ads_campaign_setting') }}
)

select
    -- canal: constante enquanto a Shopee for o unico marketplace. Ver o
    -- comentario equivalente em despesa_operacional e master_orders.
    'shopee' as canal,

    p.campaign_id,
    p.data,

    -- Nome e tipo vem da performance, nao da configuracao: a performance
    -- carrega o nome vigente no periodo consultado, enquanto a configuracao e
    -- sempre o estado de agora.
    p.nome_anuncio,
    p.tipo_anuncio,
    p.posicionamento,

    -- Ligacao com o produto. Nulo quando a campanha nao aparece mais na
    -- listagem -- campanha encerrada some, e o gasto historico dela continua
    -- aqui sem item associado. Left join de proposito: perder a linha de gasto
    -- seria pior do que ficar sem o SKU dela.
    c.item_id,
    c.qtd_itens,
    c.status        as status_campanha,
    c.orcamento     as orcamento_campanha,
    c.meta_roas,

    -- Volume
    p.impressoes,
    p.cliques,
    p.ctr,

    -- Dinheiro. `gasto` e o unico campo somavel sem ressalva.
    p.gasto,
    p.custo_por_clique,
    p.custo_por_conversao_direta,

    -- Retorno direto: so a venda do proprio item anunciado, clique -> compra.
    -- E o numero conservador, e o que se usa quando ha duvida.
    p.pedidos_diretos,
    p.gmv_direto,
    p.roi_direto,
    p.cir_direto,

    -- Retorno amplo: inclui venda de outros itens da loja depois do clique.
    -- NAO SOMAR ENTRE CAMPANHAS.
    p.pedidos_amplos,
    p.gmv_amplo,
    p.roi_amplo,
    p.cir_amplo,

    p.valor_pedidos_diretos,
    p.valor_pedidos_amplos,
    p.taxa_conversao,

    p.loaded_at

from performance p
left join configuracao c
    on c.campaign_id = p.campaign_id
