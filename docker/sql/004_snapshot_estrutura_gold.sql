-- =====================================================================
-- sandbox.snapshot_estrutura_gold — detector de mudança de estrutura
-- =====================================================================
--
-- ONDE ISTO RODA: scheduled query no console do BigQuery, diária.
-- Este arquivo NÃO é executado pelo dbt nem pelo Cloud Run. Ele existe
-- para que o SQL da scheduled query sobreviva no Git.
--
-- POR QUE VERSIONAR ALGO QUE RODA NO CONSOLE
-- -------------------------------------------
-- A tabela foi criada direto no console e ficou fora do controle de versão
-- até 13/09/2026. Se alguém apagasse a agenda, ninguém perceberia, e as 27
-- aferições acumuladas sumiriam junto. Query que vive só no console é
-- conhecimento que depende de uma pessoa lembrar que ela existe.
--
-- O QUE ELA FAZ, E POR QUE ISSO NÃO É REDUNDANTE
-- -----------------------------------------------
-- Grava, todo dia, a assinatura de colunas de cada tabela do gold.
-- Comparando dias, dá para ver que a estrutura mudou — e quando.
--
-- Parece sobrepor o teste `assert_dicionario_sem_campo_orfao`, mas são
-- coisas diferentes:
--
--   - o teste dbt responde "existe campo sem documentação AGORA?" e
--     falha ou passa. Não guarda série.
--   - esta tabela responde "o que mudou, e em que dia?", com histórico.
--
-- Provou seu valor em 10/09/2026: master_orders passou de 32 para 33
-- colunas, um dia depois do deploy do `loaded_at`. Ela registrou a
-- mudança sozinha, sem ninguém pedir.
--
-- POR QUE NÃO VIROU TESTE dbt
-- ----------------------------
-- Teste dbt passa ou falha; não guarda o histórico. Aqui o histórico É o
-- produto — sem ele não dá para dizer "mudou no dia tal". A alternativa
-- seria um snapshot dbt, que resolveria, mas exigiria rodar dentro do
-- pipeline e amarrar a checagem de estrutura ao sucesso da extração.
-- Mantive separado de propósito: se a extração falhar, ainda quero saber
-- se alguém mexeu no schema.
--
-- COMO AGENDAR DE NOVO, se a agenda se perder
-- --------------------------------------------
-- Console → BigQuery → Consultas programadas → Criar
--   destino : cp-pipeline-503623.sandbox.snapshot_estrutura_gold
--   escrita : Anexar à tabela (append) -- NUNCA sobrescrever, o
--             histórico é o produto
--   horário : diário. ATENÇÃO: o formulário salva em UTC. Para 06:30 BRT
--             escreva 09:30. Foi esse detalhe que criou alertas às
--             03:30 em agosto.
--
-- =====================================================================

select
    current_timestamp() as aferido_em,
    table_name          as tabela,
    count(*)            as colunas,

    -- A assinatura é a lista ordenada de colunas. O `order by` dentro do
    -- string_agg não é cosmético: sem ele, o BigQuery pode devolver a
    -- mesma estrutura em ordens diferentes entre execuções, e cada dia
    -- pareceria uma mudança. Falso positivo diário treina a equipe a
    -- ignorar o sinal.
    string_agg(column_name, ',' order by column_name) as assinatura

from `cp-pipeline-503623.gold.INFORMATION_SCHEMA.COLUMNS`
group by table_name

-- Validado em 13/09/2026: reproduz exatamente a última linha gravada pela
-- scheduled query nas 4 tabelas do gold — 6, 29, 13 e 33 colunas, com
-- assinatura idêntica.
--
-- CONSULTA ÚTIL: o que mudou e quando
--
--   select tabela, date(aferido_em,'America/Sao_Paulo') as dia, colunas
--   from `cp-pipeline-503623.sandbox.snapshot_estrutura_gold`
--   qualify assinatura != lag(assinatura) over (
--       partition by tabela order by aferido_em)
--   order by aferido_em desc
--
-- Ela devolve só os dias em que a estrutura mudou de verdade.
