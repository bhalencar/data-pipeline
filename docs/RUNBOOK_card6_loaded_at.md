# Runbook — `loaded_at` no `master_orders` (card #6)

Medido e escrito em 09/09/2026.

---

## 1. O que muda e por quê

O `master_orders` passa a ter **coluna de carga**: dá para saber há quanto tempo
a Shopee não manda notícia de cada pedido. Hoje isso só existe no bronze, e o
`master_ads` e o `master_keywords` já têm — o `master_orders` era a exceção.

É a única das três lacunas do card #6 que se confirmou real.

---

## 2. Arquivos tocados

| Arquivo | O que mudou |
|---|---|
| `dbt/models/silver/stg_order_items.sql` | **a correção de verdade** — propaga `loaded_at` pelo explode de `item_list` |
| `dbt/models/gold/master_orders.sql` | traz `loaded_at` para `items_orders` e expõe no select final |
| `dbt/models/silver/schema.yml` | declara `stg_order_items.loaded_at` + `not_null` |
| `dbt/models/gold/schema.yml` | declara `master_orders.loaded_at` + `not_null` |
| `dbt/seeds/dicionario_campos.csv` | 80 → 81 linhas; reforça o cuidado de `discounted_price` |
| `docs/dicionario_master_orders.md` | seções 6 e 7 |

### O erro que eu cometi e corrigi no meio do caminho

Minha primeira edição mexeu **só** no `master_orders.sql`, assumindo que
`stg_order_items` expunha `loaded_at` — o arquivo seleciona o campo no CTE
`source` e no `deduped`, então parecia óbvio.

O sandbox provou que não: `Name loaded_at not found inside soi`.

A causa é o CTE `items_exploded`, que faz o `unnest` de `item_list` carregando
apenas `order_sn`, `item` e `extraction_date`. **O `loaded_at` morria ali.**
Consertar só no gold não funcionaria — e eu teria descoberto isso no seu terminal,
não no meu.

Registro porque é o tipo de coisa que se repete: num modelo com explode, coluna
que não é carregada explicitamente pelo `unnest` desaparece silenciosamente.

---

## 3. Como validei

Reproduzi a lógica nova em `sandbox` contra o bronze real:

```sql
-- contagem e integridade
select
  (select count(*) from `cp-pipeline-503623.silver.stg_order_items`) as view_atual,
  (select count(*) from sandbox.proto_soi_loaded_at)                 as proto,
  (select countif(loaded_at is null) from sandbox.proto_soi_loaded_at) as nulos
```

| medida | resultado |
|---|---|
| linhas na view atual | 101 |
| linhas no protótipo | **101** — o explode não duplicou nem perdeu |
| `loaded_at` nulo | **0** |
| valores distintos | 18 |
| linhas do gold sem match na junção | **0** |

Faixa de carga: 30/07/2026 a 09/09/2026. Plausível — o `get_orders` relê 30 dias,
então pedido antigo mantém carga antiga, e é exatamente isso que a coluna deve
mostrar.

Protótipo removido do `sandbox` depois da validação.

---

## 4. Comandos, na ordem

```bash
source ~/.venvs/cp-bigquery/bin/activate
cd ~/Documents/"Casa e Patas"/data-pipeline/dbt

# 1. o seed primeiro -- o dicionario ganhou linha
dbt seed --target bigquery

# 2. build completo, SEM --select
dbt build --target bigquery
```

**Por que sem `--select`:** em 02/09 eu usei `--select` e deixei 29 colunas órfãs
no dicionário, o que teria quebrado a rodada das 06:00. A cadeia aqui é
`stg_order_items` → `master_orders` → testes → seed do dicionário. `--select`
pega um pedaço e o teste de campo órfão falha no dia seguinte.

---

## 5. O que esperar na saída

- `dbt seed`: 3 seeds, `dicionario_campos` com **81 linhas** (era 80)
- `dbt build`: **PASS** em tudo, nenhum ERROR
- dois testes `not_null` novos (um no silver, um no gold), ambos passando
- `assert_dicionario_sem_campo_orfao` **precisa passar** — é ele que prova que a
  coluna nova foi documentada

---

## 6. Como verificar que deu certo

```sql
select
  count(*)                        as linhas,
  countif(loaded_at is null)      as sem_carga,
  count(distinct loaded_at)       as cargas_distintas,
  min(loaded_at)                  as mais_antiga,
  max(loaded_at)                  as mais_recente
from `cp-pipeline-503623.gold.master_orders`
```

**Números esperados:** `linhas` = 101, `sem_carga` = **0**,
`cargas_distintas` = 18, `mais_recente` dentro das últimas 24h.

Se `sem_carga` > 0, o `not_null` já teria falhado no build — mas confira mesmo
assim, porque é o número que prova que a coluna serve para alguma coisa.

E a pergunta que a coluna passa a responder:

```sql
select order_sn, order_status,
       timestamp_diff(current_timestamp(), loaded_at, hour) as horas_sem_noticia
from `cp-pipeline-503623.gold.master_orders`
where order_status not in ('COMPLETED','CANCELLED')
order by horas_sem_noticia desc
```

Pedido em trânsito parado há muito tempo é candidato a travamento.

---

## 7. Como reverter

```bash
cd ~/Documents/"Casa e Patas"/data-pipeline
git checkout dbt/models/silver/stg_order_items.sql \
             dbt/models/gold/master_orders.sql \
             dbt/models/silver/schema.yml \
             dbt/models/gold/schema.yml \
             dbt/seeds/dicionario_campos.csv \
             docs/dicionario_master_orders.md
dbt seed --target bigquery && dbt build --target bigquery
```

A coluna some e nada mais muda — nenhum modelo depende dela, e nenhum número
financeiro foi tocado. É uma adição pura.

---

## 8. O que pode dar errado

**`stg_order_items` é view.** O `dbt build` recria; se você rodar só o
`master_orders`, ele lê a view velha e falha com `Name loaded_at not found`.
Foi exatamente o erro que eu cometi no sandbox. Rode o build inteiro.

**Ordem seed → build.** Se inverter, o teste de campo órfão falha: a coluna
existe no gold e a linha ainda não existe no dicionário.

**O `not_null` do gold é agressivo de propósito.** Se a Shopee mandar um pedido
sem `loaded_at` no bronze, o build para. É o comportamento certo: coluna de carga
que aceita nulo não serve para monitorar frescor.

---

## 9. O que NÃO fiz, e por quê

O card #6 pede teste para `gmv_item` nulo e para `discounted_price` zerado.
**Não escrevi nenhum dos dois**, e a razão é a mesma nos dois casos.

**`gmv_item` nulo:** zero ocorrências em 101 linhas. A regra da minha skill é
provar que a invariante é invariante antes de adotá-la — eu não tenho um único
caso observado.

**`discounted_price` zerado:** existe 1 caso (`2607219SB9DK7B`, 21/07) e **não é
defeito**. `preco_desconto_linha` R$ 56,16, `valor_pago_produto` R$ 56,16 e
`gmv_item` R$ 55,03 estão corretos. Um teste de não-zero falharia numa venda
saudável — o mesmo erro do `receita_liquida` em 21/08, com outra roupa.

Em vez de testes, registrei os dois fatos no dicionário: é o que impede alguém de
criar esses testes daqui a seis meses achando que encontrou um bug.
