-- =============================================================================
-- DDL do dataset `sandbox` no BigQuery
-- =============================================================================
--
-- ATENCAO AO DIALETO: os arquivos 001 e 002 desta pasta sao PostgreSQL, da fase
-- antiga do projeto, e estao congelados. Este e GoogleSQL, e descreve
-- infraestrutura viva.
--
-- Por que existe: a `sandbox` e a `log_execucao_agentes` foram criadas pelo
-- console em agosto/2026 e nao existiam em lugar nenhum do repositorio. Se o
-- projeto precisasse ser recriado, o log de execucao dos agentes -- que e a
-- unica prova de que um agente rodou -- sumiria sem deixar rastro de como
-- reconstrui-lo.
--
-- Este arquivo NAO roda no pipeline. E DDL de referencia, para recriar a
-- estrutura a mao quando necessario. Todos os comandos sao idempotentes.
--
-- Uso:
--   bq query --use_legacy_sql=false --location=southamerica-east1 < 003_create_sandbox_bigquery.sql
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. O dataset
-- -----------------------------------------------------------------------------
-- `sandbox` e bancada de trabalho, nao deposito: e o unico dataset em que os
-- agentes podem escrever. Prototipo criado aqui deve ser removido ao fim da
-- analise que o motivou.
create schema if not exists `cp-pipeline-503623.sandbox`
options (
    location    = 'southamerica-east1',
    description = 'Bancada de trabalho dos agentes. Unico dataset com escrita permitida. Prototipo e removido apos uso; o que persiste aqui e so o log de execucao.'
);


-- -----------------------------------------------------------------------------
-- 2. Log de execucao dos agentes
-- -----------------------------------------------------------------------------
-- Toda rodada de agente grava uma linha, com achado ou sem. A assimetria e o
-- ponto: card ausente com linha de log presente significa "esta tudo bem";
-- linha de log ausente significa "o agente parou de rodar".
--
-- `veredito = 'achado'` com `cards_criados = 0` e resultado legitimo -- e o que
-- acontece quando o agente viu algo mas o achado nao justificou abrir card. A
-- `observacao` e onde esse achado fica guardado, e e o que o agente le na
-- rodada seguinte, porque ele nao tem memoria entre execucoes.
create table if not exists `cp-pipeline-503623.sandbox.log_execucao_agentes`
(
    agente        string    not null options (description = 'Nome do agente: Heitor, Pedro, Clara, Miranda, Inacio, Aurea, Iris, Ana ou Rubem.'),
    executado_em  timestamp not null options (description = 'Quando a rodada terminou, em UTC.'),
    tipo          string             options (description = 'agendada, sob_demanda ou sincrona.'),
    escopo        string             options (description = 'O que a rodada olhou, incluindo o recorte de periodo.'),
    veredito      string             options (description = 'sem_achado, achado ou erro. achado com cards_criados = 0 e legitimo: o agente viu algo que nao justificou card.'),
    cards_criados int64              options (description = 'Quantos cards do Trello a rodada abriu.'),
    observacao    string             options (description = 'O achado em texto. E aqui que fica o que nao virou card, e e isto que o agente le na rodada seguinte.'),
    duracao_seg   int64              options (description = 'Tempo ativo da rodada em segundos. Permite medir custo por agente em vez de estimar.')
)
options (
    description = 'Uma linha por rodada de agente. Ausencia de linha significa que o agente parou de rodar.'
);


-- -----------------------------------------------------------------------------
-- Conferencia
-- -----------------------------------------------------------------------------
-- select table_name from `cp-pipeline-503623.sandbox.INFORMATION_SCHEMA.TABLES`;
--
-- Rodadas por agente nos ultimos 30 dias:
-- select agente,
--        count(*)                                        as rodadas,
--        countif(veredito = 'achado')                    as com_achado,
--        sum(cards_criados)                              as cards,
--        round(sum(duracao_seg) / 60, 1)                 as minutos
-- from `cp-pipeline-503623.sandbox.log_execucao_agentes`
-- where executado_em >= timestamp_sub(current_timestamp(), interval 30 day)
-- group by agente
-- order by minutos desc;
