{{ config(materialized='table') }}

-- master_keywords — volume de busca da Shopee, com serie temporal.
--
-- Card #2 do Roadmap de Dados. Fonte: Shopee Ads API, modulo 105.
--
-- ================================================================= GRAO
-- Uma linha por palavra, por item, por snapshot semanal.
-- `canal` existe desde ja, constante 'shopee', pelo mesmo motivo das outras
-- tabelas do gold: o DRE e as analises por canal nascem funcionando dos dois
-- lados quando o Mercado Livre entrar.
--
-- ================================================== POR QUE O SNAPSHOT EXISTE
-- O `volume_busca` da Shopee e uma janela MOVEL de 30 dias, e a plataforma nao
-- guarda historico. Sem snapshot, "esse termo cresceu" e uma frase impossivel
-- de dizer. Esta tabela existe para tornar essa frase possivel.
--
-- Consequencia direta: snapshot nao coletado esta PERDIDO. Nao ha backfill.
-- Diferente do master_orders e do master_ads, que releem 30 dias e se
-- autocorrigem, aqui uma semana sem coleta e um buraco permanente na serie --
-- e a tabela continua tendo linhas, entao a falha e silenciosa. O teste
-- assert_keywords_frescor existe por causa disso.
--
-- ============================================================== CUIDADOS
-- `volume_busca` e da LOJA INTEIRA na Shopee, nao do nosso item. E quanta
-- gente buscou o termo, nao quanto vendemos com ele. Nao existe relacao
-- direta com o master_orders, e cruzar os dois exige cuidado.
--
-- A MESMA palavra aparece para itens diferentes, com o MESMO volume -- porque
-- o volume e do termo, nao do par termo-item. Somar volume entre itens conta
-- a mesma busca varias vezes. Para volume de um termo, filtre um item ou use
-- max/any_value, nunca sum.
--
-- `no_catalogo` diz se o item estava ativo NAQUELE snapshot. Produto pausado
-- continua sendo coletado de proposito: a "Caminha Pet MDF Tipo Berco" saiu do
-- ar em agosto por falta de estoque no fornecedor e vai voltar -- quando
-- voltar, a serie dela nao tera buraco.

with atual as (
    select * from {{ ref('stg_keywords') }}
)

select
    -- canal: constante enquanto a Shopee for o unico marketplace.
    'shopee' as canal,

    a.item_id,
    a.palavra,
    a.data_snapshot,

    a.volume_busca,
    a.qualidade,
    a.lance_sugerido,
    a.no_catalogo,

    -- A serie. E isto que o card #2 existe para entregar: sem estas colunas a
    -- tabela seria so uma consulta pontual repetida, e o Rubem continuaria
    -- cego para movimento.
    --
    -- lag() sobre item + palavra, ordenado por data: compara o snapshot com o
    -- anterior DA MESMA palavra no MESMO item. Nulo no primeiro snapshot de
    -- cada palavra, o que e esperado e nao e defeito.
    lag(a.volume_busca) over (
        partition by a.item_id, a.palavra order by a.data_snapshot
    ) as volume_anterior,

    a.volume_busca - lag(a.volume_busca) over (
        partition by a.item_id, a.palavra order by a.data_snapshot
    ) as variacao_absoluta,

    -- nullif protege contra divisao por zero quando o volume anterior era 0.
    round(
        safe_divide(
            a.volume_busca - lag(a.volume_busca) over (
                partition by a.item_id, a.palavra order by a.data_snapshot
            ),
            nullif(lag(a.volume_busca) over (
                partition by a.item_id, a.palavra order by a.data_snapshot
            ), 0)
        ) * 100
    , 1) as variacao_pct,

    -- Posicao da palavra dentro do item naquele snapshot. Serve para o Rubem
    -- olhar "as 5 mais buscadas deste produto" sem recalcular toda vez.
    row_number() over (
        partition by a.item_id, a.data_snapshot order by a.volume_busca desc
    ) as posicao_no_item,

    a.loaded_at

from atual a
