-- As duas fontes de gasto com midia tem que fechar no dia.
--
-- POR QUE ESTE TESTE EXISTE
-- --------------------------
-- O projeto sempre tratou a igualdade entre o nivel loja e a soma das
-- campanhas como fato estavel. O cabecalho do `master_ads` e o
-- `docs/dicionario_master_ads.md` dizem a mesma coisa, com o mesmo numero:
-- julho/2026, loja 839.17 contra campanhas 839.20, tres centavos em 744
-- linhas. A conclusao tirada dali foi que a separacao entre as duas fontes
-- era disciplina contra dupla contagem, "nao reconciliacao".
--
-- Em 30/10/2026 isso deixou de ser verdade, e ninguem viu. A loja passou a
-- marcar mais que a soma das campanhas, todo dia, porque uma campanha
-- comecou a gastar FORA da lista que a extracao enxerga. Cinco dias em
-- silencio, descoberto so porque o Bruno conferiu a mao contra a plataforma.
--
-- A causa e outro card. Este arquivo existe para a proxima vez: nenhum teste
-- do projeto guardava essa igualdade, entao o unico detector era alguem
-- reparar. Agora o detector e automatico.
--
-- POR QUE O assert_ads_campanha_um_item NAO PEGARIA ISSO
-- ------------------------------------------------------
-- Ele le do `stg_ads_campaign_setting`, que so contem as campanhas que a
-- extracao JA busca. Por construcao, ele nunca enxerga campanha ausente.
-- Teste que le so o que foi coletado nao detecta falha de coleta. Este le o
-- nivel loja, que e independente da listagem de campanhas -- e e isso que o
-- torna capaz de ver o buraco.
--
-- A TOLERANCIA, E POR QUE R$ 1,00
-- --------------------------------
-- A diferenca legitima e arredondamento por linha: tres centavos em 744
-- linhas no pior mes medido. Um real e duas ordens de grandeza acima disso e
-- uma ordem abaixo do menor dia de divergencia real (R$ 3,08 em 30/10).
-- Conferido contra o historico inteiro em 03/11/2026: de 01/03 a 29/10 o
-- teste devolve ZERO linhas, e de 30/10 em diante devolve exatamente os
-- quatro dias do defeito conhecido. Nenhum falso positivo em oito meses.
--
-- SEVERIDADE: error, desde 05/11/2026
-- ------------------------------------
-- Nasceu como `warn` em 03/11, porque na epoca ele acusava um defeito real e
-- ja conhecido -- cinco campanhas em grupo fora da extracao -- e derrubar o
-- gold inteiro para avisar de algo que ja estava no board nao protegeria
-- ninguem.
--
-- O conserto subiu em 04/11 e a rodada da nuvem de 05/11 confirmou:
-- 249 dias avaliados, ZERO acima da tolerancia, maior diferenca diaria de
-- R$ 0,02 e R$ 0,40 de diferenca absoluta somada em todo o historico.
--
-- Com a casa limpa, `error` e o unico valor honesto. Em `warn` ele viraria
-- ruido que todo mundo aprende a pular, e a proxima campanha ausente passaria
-- exatamente como esta passou: cinco dias em silencio.
--
-- SE ESTE TESTE DERRUBAR A RODADA, o mais provavel NAO e defeito de codigo: e
-- campanha nova em grupo que a listagem da Shopee nao enumera. Pegue o id na
-- URL do Seller Centre (.../pas/product/manual-mpd/<id>) e acrescente uma
-- linha em `extraction/shopee/campanhas_extras.csv`. Ver o cabecalho do
-- `carregar_campanhas_extras()` em get_ads.py.

{{ config(severity='error') }}

{% if target.type == 'bigquery' %}

with loja as (

    select data, gasto
    from {{ ref('stg_ads_shop_daily') }}

),

campanhas as (

    select data, sum(gasto) as gasto
    from {{ ref('master_ads') }}
    group by data

)

-- Left join a partir da loja, nao inner: dia que existe no nivel loja e nao
-- existe em campanha nenhuma e justamente o caso que queremos pegar. Inner
-- join esconderia o pior cenario -- a campanha sumir por inteiro.
select
    l.data,
    l.gasto                      as gasto_loja,
    coalesce(c.gasto, 0)         as gasto_campanhas,
    round(l.gasto - coalesce(c.gasto, 0), 2) as diferenca
from loja l
left join campanhas c
    on c.data = l.data
where abs(l.gasto - coalesce(c.gasto, 0)) > 1.00
order by l.data

{% else %}

-- Alvo Postgres congelado desde a migracao para o BigQuery, igual ao
-- assert_ads_campanha_um_item.
select
    null::date    as data,
    null::numeric as gasto_loja,
    null::numeric as gasto_campanhas,
    null::numeric as diferenca
where false

{% endif %}
