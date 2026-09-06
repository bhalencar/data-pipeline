-- Snapshot semanal que nao aconteceu.
--
-- ESTE E O TESTE MAIS IMPORTANTE DESTA TABELA, e a razao e o que ela tem de
-- diferente de todas as outras do gold:
--
--   master_orders e master_ads releem 30 dias e se AUTOCORRIGEM. Se uma
--   rodada falhar, a seguinte conserta.
--
--   Aqui nao. O volume de busca da Shopee e uma janela movel de 30 dias, sem
--   historico. Snapshot que nao foi coletado esta PERDIDO -- nao existe
--   backfill, nem hoje nem nunca.
--
-- E a falha e silenciosa: a tabela continua tendo milhares de linhas, as
-- consultas continuam respondendo, e ninguem percebe que faltou uma semana.
-- Meses depois alguem olha a serie e ve um buraco que nao da mais para
-- explicar nem preencher.
--
-- 10 dias de tolerancia, e nao 7: a coleta e semanal, entao 8 ou 9 dias de
-- intervalo e variacao normal (feriado, rodada que atrasou, reexecucao no dia
-- seguinte). Acima de 10 houve semana pulada de verdade.
--
-- Se este teste falhar, NAO aumente a tolerancia. O dado daquela semana ja
-- se perdeu -- o que resta e garantir que a proxima aconteca.

{% if target.type == 'bigquery' %}

select
    max(data_snapshot) as ultimo_snapshot,
    date_diff(current_date('America/Sao_Paulo'), max(data_snapshot), day) as dias_sem_coleta
from {{ ref('master_keywords') }}
having date_diff(current_date('America/Sao_Paulo'), max(data_snapshot), day) > 10

{% else %}

-- Alvo Postgres congelado desde a migracao para o BigQuery.
select null as ultimo_snapshot, null as dias_sem_coleta
where false

{% endif %}
