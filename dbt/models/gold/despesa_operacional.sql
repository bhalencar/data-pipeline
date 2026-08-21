-- Despesa operacional da loja, lancada a mao pelo Bruno.
--
-- Grao: competencia x canal x categoria x descricao. Uma linha por mes de
-- competencia, por proposito: despesa recorrente NAO se propaga sozinha. Se
-- ninguem lancou o mes, o mes nao tem despesa registrada -- e o DRE precisa dizer
-- que parou ali, em vez de assumir que o valor do mes passado continua valendo.
--
-- Regime de competencia: contrato anual pago de uma vez entra rateado, um doze
-- avos por mes. O desembolso nao esta no warehouse, e nao deve ser inferido daqui.
--
-- canal = 'comum' e despesa do NEGOCIO, nao de um canal. Ela nao vem rateada de
-- proposito: quem monta o DRE escolhe o criterio de rateio, e assim esse criterio
-- fica visivel e auditavel em vez de escondido na digitacao da planilha.
--
-- NAO cobre: imposto (ja esta em receita_liquida), CMV, embalagem e mao de obra
-- (ja estao no custo do produto, a loja opera sem estoque proprio).

-- O seed se chama despesa_operacional_manual, e nao despesa_operacional, de
-- proposito: seed e modelo com o mesmo nome colidem no grafo do dbt. Quando
-- colidiam, os testes declarados para o modelo rodavam contra o seed -- e
-- rodavam antes do modelo existir, entao nunca testaram o que diziam testar.
with fonte as (
    select * from {{ ref('despesa_operacional_manual') }}
)

select

{% if target.type == 'bigquery' %}

    -- cast do valor para numeric: o seed chega como FLOAT64, e soma de dinheiro
    -- em ponto flutuante acumula centavo de erro ao longo dos meses.
    cast(competencia as date)      as competencia,
    cast(valor as numeric)         as valor,

{% else %}

    competencia::date              as competencia,
    valor::numeric                 as valor,

{% endif %}

    canal,
    categoria,
    descricao,
    nullif(trim(coalesce(observacao, '')), '') as observacao

from fonte
where competencia is not null
  and valor is not null
