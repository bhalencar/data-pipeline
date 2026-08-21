-- Grao da despesa_operacional: 1 linha por descricao, dentro de uma categoria,
-- de um canal, dentro de um mes de competencia. Duas linhas iguais quase sempre
-- significam lancamento duplicado na planilha -- e dinheiro contado duas vezes
-- no DRE.
select
    competencia,
    canal,
    categoria,
    descricao,
    count(*) as linhas
from {{ ref('despesa_operacional') }}
group by 1, 2, 3, 4
having count(*) > 1
