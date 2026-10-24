-- =====================================================================
-- sentinela-gold — scheduled query diária do BigQuery
-- grava em: sandbox.snapshot_estrutura_gold
-- =====================================================================
--
-- ONDE ISTO RODA: scheduled query no console do BigQuery, diária às
-- 09:30 UTC (06:30 BRT). Nome no console: `sentinela-gold`.
-- Este arquivo NÃO é executado pelo dbt nem pelo Cloud Run. Ele existe
-- para que o SQL da scheduled query sobreviva no Git.
--
-- ATENÇÃO — ESTE ARQUIVO JÁ DIVERGIU DA PRODUÇÃO UMA VEZ.
-- A versão commitada em 13/09/2026 tinha só o snapshot. Em algum momento
-- depois disso, o bloco de verificação (`begin ... raise`) foi acrescentado
-- direto no console e nunca voltou para o Git. Em 24/10/2026 eu li este
-- arquivo, assumi que ele era a produção, e quase entreguei um runbook
-- mandando colar por cima — o que teria apagado as três verificações em
-- silêncio. **Antes de editar: leia o SQL real em Consultas programadas →
-- sentinela-gold → Detalhes, e confira que bate com este arquivo.**
--
-- O QUE ELA FAZ, EM DUAS PARTES
-- ------------------------------
-- 1. Grava o snapshot do dia, SEMPRE.
-- 2. Confere quatro condições e, se alguma for verdadeira, derruba a
--    rodada com `raise` e uma mensagem que diz o que fazer.
--
-- O snapshot vem primeiro de propósito: mesmo numa rodada que vai falhar,
-- a linha do dia fica registrada. O histórico é o produto.
--
-- POR QUE VIVE FORA DA IMAGEM DO CLOUD RUN
-- -----------------------------------------
-- Verificação que vive dentro da imagem é cega para o caso de a imagem
-- estar velha, que foi exatamente o card #12.
--
-- AS QUATRO CONDIÇÕES
-- --------------------
--   REGRESSÃO DE SCHEMA — assinatura mudou E número de colunas caiu.
--       Job rodou, passou, e entregou estrutura errada. Suspeito nº 1:
--       imagem do Cloud Run desatualizada.
--
--   JOB PAROU — alguma tabela do gold não é reescrita há mais de 30h.
--       Como o dbt faz `CREATE OR REPLACE`, toda tabela é reescrita todo
--       dia; se parou de ser reescrita, o job parou. 30h cobre atraso de
--       rodada sem acusar dia pulado como se fosse semana parada.
--
--   TABELA VAZIA — alguma tabela do gold com zero linhas.
--       Recriada mas vazia passa por todas as outras verificações:
--       mesma assinatura, mesmo número de colunas, escrita de hoje.
--
--   CAMPO ÓRFÃO — coluna no gold sem linha no dicionário.
--
-- O QUE MUDOU EM 24/10/2026, E POR QUÊ
-- -------------------------------------
-- A condição de frescor usava `max(loaded_at)` do `bronze.get_order_detail`
-- com limite de 12h, apoiada nesta premissa, escrita no comentário antigo:
--
--     "So funciona porque a extracao rele 30 dias e escreve linha toda
--      rodada, inclusive em dia sem venda."
--
-- **A premissa é falsa.** O `get_orders.py` só grava `get_order_detail`
-- quando a janela de releitura traz algum pedido:
--
--     if order_list:
--         ... salvar("get_order_detail", ...)
--
-- Então ela sobrevive a um DIA sem venda, não a uma JANELA sem venda.
-- O último pedido da loja foi 12/09/2026. A rodada de 12/10 cobriu
-- [12/09, 11/10] — último dia com o pedido dentro dos 30 dias. De 13/10
-- em diante não havia o que gravar, e a sentinela passou a gritar
-- "BRONZE PARADO" todo dia, por 11 dias, enquanto o pipeline rodava
-- perfeitamente. Alarme falso diário é pior que sentinela nenhuma:
-- treina a equipe a ignorar o sinal.
--
-- A correção troca a pergunta. Antes: "entrou dado novo no bronze?" —
-- que depende do negócio ter acontecido. Agora: "o dbt reescreveu a
-- tabela?" — que depende só do job. São perguntas diferentes, e só a
-- segunda é falha de pipeline. Ver a seção 5.1 da skill do Pedro.
--
-- O que se PERDE com a troca: a sentinela deixa de acusar o caso "job
-- rodou mas a extração não trouxe nada". Esse caso agora é invisível
-- aqui — e continua invisível para os alertas do GCP, porque o job
-- termina com sucesso. É dívida conhecida, não esquecimento.
-- Fechá-la exige comparar o bronze com a janela de releitura, e isso
-- depende de saber a data do último pedido, que é dado de negócio.
--
-- POR QUE `__TABLES__` E NÃO `INFORMATION_SCHEMA.TABLE_STORAGE`
-- --------------------------------------------------------------
-- O TABLE_STORAGE tem os mesmos números e é a API moderna, mas popula
-- com atraso de até ~24h. Numa sentinela DIÁRIA de frescor, 24h é
-- exatamente a ordem de grandeza do sinal que se quer medir — seria
-- medir o relógio com o próprio relógio atrasado. O `__TABLES__` é
-- legado, mas reflete a escrita na hora.
--
-- NOTIFICAÇÃO — SEM ISSO, NADA DISTO SERVE
-- -----------------------------------------
-- Até 24/10/2026 a agenda estava com "Enviar notificações por e-mail"
-- DESMARCADO. A sentinela falhou 11 dias seguidos e ninguém soube: o
-- erro só aparecia em Consultas programadas → sentinela-gold →
-- Histórico de execuções, uma tela que ninguém abre por hábito.
-- Programação → Atualizar consulta programada → Opções de notificação →
-- marcar "Enviar notificações por e-mail".
--
-- COMO AGENDAR DE NOVO, se a agenda se perder
-- --------------------------------------------
-- Console → BigQuery → Consultas programadas → Criar
--   destino : NÃO marque "Definir uma tabela de destino". O insert está
--             dentro do SQL, porque a parte 2 é script e scheduled query
--             com destino configurado não aceita múltiplas instruções.
--   horário : diário. ATENÇÃO: o formulário salva em UTC. Para 06:30 BRT
--             escreva 09:30. Foi esse detalhe que criou alertas às
--             03:30 em agosto.
--   e-mail  : marque a notificação. Ver o bloco acima.
--
-- COLUNA NOVA no destino exige `alter table ... add column` ANTES de a
-- query nova entrar no ar. O insert nomeia as colunas explicitamente,
-- então a ordem do select não importa — mas a coluna precisa existir.
--
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Snapshot de hoje, sempre.
-- ---------------------------------------------------------------------
insert into `cp-pipeline-503623.sandbox.snapshot_estrutura_gold`
  (aferido_em, tabela, colunas, assinatura, linhas, ultima_escrita)
with estrutura as (
    select
        table_name as tabela,
        count(*)   as colunas,
        -- O `order by` dentro do string_agg não é cosmético: sem ele, o
        -- BigQuery pode devolver a mesma estrutura em ordens diferentes
        -- entre execuções, e cada dia pareceria uma mudança.
        string_agg(column_name, ',' order by column_name) as assinatura
    from `cp-pipeline-503623.gold.INFORMATION_SCHEMA.COLUMNS`
    group by table_name
),
volume as (
    select
        table_id                             as tabela,
        row_count                            as linhas,
        timestamp_millis(last_modified_time) as ultima_escrita
    from `cp-pipeline-503623.gold.__TABLES__`
)
-- LEFT JOIN de propósito: view criada no gold aparece no
-- INFORMATION_SCHEMA.COLUMNS e não tem row_count útil no __TABLES__.
-- Prefiro registrar a estrutura dela com volume nulo a deixá-la fora.
select
    current_timestamp(),
    e.tabela,
    e.colunas,
    e.assinatura,
    v.linhas,
    v.ultima_escrita
from estrutura e
left join volume v using (tabela);

-- ---------------------------------------------------------------------
-- 2. Confere, e falha com mensagem se algo estiver errado.
-- ---------------------------------------------------------------------
begin
  declare mensagem string;

  set mensagem = (
    with agora as (
      select
        table_name as tabela,
        count(*)   as colunas,
        string_agg(column_name, ',' order by column_name) as assinatura
      from `cp-pipeline-503623.gold.INFORMATION_SCHEMA.COLUMNS`
      group by table_name
    ),
    anterior as (
      -- o penúltimo snapshot: o de hoje acabou de ser gravado acima
      select tabela, colunas, assinatura
      from `cp-pipeline-503623.sandbox.snapshot_estrutura_gold`
      qualify row_number() over (partition by tabela order by aferido_em desc) = 2
    ),
    regressao as (
      select a.tabela, ant.colunas as antes, a.colunas as depois
      from agora a
      join anterior ant using (tabela)
      where a.assinatura <> ant.assinatura
        and a.colunas < ant.colunas
    ),
    escrita as (
      -- Mede se o dbt reescreveu a tabela, não se entrou dado novo.
      -- Funciona porque o gold é CREATE OR REPLACE: toda tabela é
      -- reescrita toda rodada, inclusive em dia sem venda.
      select
        table_id as tabela,
        timestamp_diff(current_timestamp(),
                       timestamp_millis(last_modified_time), hour) as horas,
        row_count as linhas
      from `cp-pipeline-503623.gold.__TABLES__`
    ),
    parado as (
      select tabela, horas from escrita where horas > 30
    ),
    vazia as (
      select tabela from escrita where linhas = 0
    ),
    orfao as (
      select count(*) as n
      from `cp-pipeline-503623.gold.INFORMATION_SCHEMA.COLUMNS` c
      left join `cp-pipeline-503623.silver.dicionario_campos` d
        on  d.tabela = c.table_name
        and d.campo  = c.column_name
      where d.campo is null
    )

    select case

      when (select count(*) from regressao) > 0 then concat(
        'REGRESSAO DE SCHEMA no gold: ',
        (select string_agg(concat(tabela,' ',cast(antes as string),'->',cast(depois as string)))
           from regressao),
        '. O job rodou e passou, mas entregou a estrutura errada. Suspeito ',
        'numero 1: imagem do Cloud Run desatualizada. Ver card #12.')

      when (select count(*) from parado) > 0 then concat(
        'JOB PAROU: ',
        (select string_agg(concat(tabela,' ha ',cast(horas as string),'h')) from parado),
        ' sem ser reescrita. O gold e CREATE OR REPLACE, entao tabela que nao ',
        'foi reescrita significa job que nao rodou ou que falhou no meio -- ',
        'confira o historico de execucoes do Cloud Run. NAO confunda com dado ',
        'velho: se a loja nao vende, o gold continua sendo recriado todo dia ',
        'sobre o mesmo dado, e isto aqui NAO dispara.')

      when (select count(*) from vazia) > 0 then concat(
        'TABELA VAZIA no gold: ',
        (select string_agg(tabela) from vazia),
        ' com zero linhas. Recriada, mas sem conteudo -- passa por todas as ',
        'outras verificacoes. Suspeito numero 1: modelo do dbt filtrando tudo, ',
        'ou fonte do silver vazia.')

      when (select n from orfao) > 0 then concat(
        'CAMPO ORFAO: ', cast((select n from orfao) as string),
        ' coluna(s) do gold sem linha no dicionario.')

      else null
    end
  );

  if mensagem is not null then
    raise using message = mensagem;
  end if;
end;

-- =====================================================================
-- Validado em 24/10/2026 contra a produção: 4 tabelas, com 6, 29, 13 e 33
-- colunas (idêntico à última linha gravada pela versão antiga), linhas
-- 33 / 5.696 / 5.265 / 104, e ultima_escrita 2026-10-23 06:01 nas quatro.
-- Nenhuma das quatro condições dispara com esse estado.
--
-- CONSULTA ÚTIL 1: o que mudou de estrutura, e quando
--
--   select tabela, date(aferido_em,'America/Sao_Paulo') as dia, colunas
--   from `cp-pipeline-503623.sandbox.snapshot_estrutura_gold`
--   qualify assinatura != lag(assinatura) over (
--       partition by tabela order by aferido_em)
--   order by aferido_em desc
--
-- CONSULTA ÚTIL 2: alguma tabela parou de ser recriada, ou esvaziou
--
--   select tabela,
--          date_diff(current_date('America/Sao_Paulo'),
--                    date(ultima_escrita,'America/Sao_Paulo'), day) as dias_sem_escrita,
--          linhas
--   from `cp-pipeline-503623.sandbox.snapshot_estrutura_gold`
--   qualify aferido_em = max(aferido_em) over (partition by tabela)
--   order by dias_sem_escrita desc
--
-- Esperado: dias_sem_escrita = 0 nas quatro, e linhas > 0 nas quatro.
-- =====================================================================
