-- Unicidade do grao: uma linha por item, por palavra, por snapshot.
--
-- Duplicata aqui e mais insidiosa do que nas outras tabelas do gold: ela nao
-- infla dinheiro, infla a SERIE. Um snapshot duplicado faz o lag() comparar a
-- linha com ela mesma, e a variacao vira zero -- ou seja, "esse termo nao
-- mudou" quando na verdade ninguem sabe.
--
-- A causa mais provavel e a recoleta: se a coleta semanal for reexecutada no
-- mesmo dia depois de uma falha, o bronze ganha as duas versoes e o dedup do
-- silver precisa escolher uma. Este teste confirma que escolheu.

select
    item_id,
    palavra,
    data_snapshot,
    count(*) as n
from {{ ref('master_keywords') }}
group by item_id, palavra, data_snapshot
having count(*) > 1
