-- Campo no gold sem linha no dicionario e falha, nao licenca para adivinhar.
--
-- Ate 21/08/2026 isso so era detectado se alguem rodasse a consulta na mao.
-- Agora roda todo dia, de graca, junto do dbt build.
--
-- A juncao usa DUAS chaves, tabela e campo. O dicionario ganhou a coluna
-- `tabela` quando o gold ganhou a segunda tabela: `descricao` existe nas duas e
-- significa coisas diferentes. Juntar so por `campo` faria campo homonimo de
-- tabelas diferentes se cobrir mutuamente, e o teste passaria sem testar nada.
--
-- Nao ha filtro de table_name: a consulta varre o dataset gold inteiro, entao
-- tabela nova entra na checagem sozinha. Os depends_on abaixo existem so para
-- garantir que o teste rode DEPOIS dos modelos; ao criar tabela nova no gold,
-- acrescente a linha dela. Se esquecer, o teste ainda pega a tabela -- na rodada
-- seguinte, e nao nesta.
--
-- depends_on: {{ ref('master_orders') }}
-- depends_on: {{ ref('despesa_operacional') }}

{% if target.type == 'bigquery' %}

select
    c.table_name,
    c.column_name
from `{{ target.project }}.gold.INFORMATION_SCHEMA.COLUMNS` c
left join {{ ref('dicionario_campos') }} d
    on  d.tabela = c.table_name
    and d.campo  = c.column_name
where d.campo is null
order by c.table_name, c.column_name

{% else %}

-- O alvo Postgres esta congelado desde a migracao para o BigQuery e nao tem
-- dataset gold. Devolver vazio faz o teste passar trivialmente la, em vez de
-- quebrar o parse com uma referencia que nao existe.
select
    null as table_name,
    null as column_name
where false

{% endif %}
