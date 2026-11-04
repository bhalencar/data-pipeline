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
-- SEVERIDADE: warn, E ISSO E TEMPORARIO
-- --------------------------------------
-- Como `error`, este teste derrubaria a rodada das 06:00 HOJE, por um defeito
-- que ja conhecemos e que esta sendo consertado em outro card. Derrubar o
-- pipeline para avisar de algo que ja esta no board nao protege ninguem --
-- so impede o resto do gold de atualizar.
--
-- Como `warn`, a divergencia aparece na saida de toda rodada sem matar o
-- build.
--
-- TROQUE PARA `error` NO MESMO COMMIT QUE CONSERTAR A EXTRACAO. Se o teste
-- ficar em warn depois disso, ele vira ruido que todo mundo aprende a pular,
-- e a proxima campanha ausente passa igual a esta.

{{ config(severity='warn') }}

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
