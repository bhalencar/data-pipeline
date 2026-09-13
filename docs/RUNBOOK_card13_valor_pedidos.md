# Runbook — card #13: `gmv_amplo` = `gmv_direto`, e o campo que parece dinheiro

Investigado em 13/09/2026.

---

## 1. O que muda e por quê

Duas conclusões, uma tranquilizadora e outra não:

1. **`gmv_amplo` idêntico a `gmv_direto` não é defeito nosso.** A Shopee
   entrega os dois campos iguais já no bronze.
2. **`valor_pedidos_diretos` e `valor_pedidos_amplos` não são valores em
   reais — são contagem de itens.** O dicionário dizia "Valor dos pedidos
   diretos", e isso está errado.

Só a documentação muda. Nenhum modelo, nenhum número, nenhum deploy.

---

## 2. O card #13 partia de uma estatística inflada

O card dizia "4.608 de 4.608 linhas iguais". O número está certo, mas
**4.641 das 4.704 linhas atuais são zero nos dois campos** — dias sem venda.
Zero igual a zero não informa nada.

O teste real é **63 de 63 linhas com GMV positivo**, entre 23/03 e 04/08,
somando R$ 3.604,08 e 86 pedidos.

Continua sendo uniformidade perfeita. Mas com N=63, não N=4.704 — e essa
diferença muda o peso da conclusão.

---

## 3. Achado 1: a igualdade vem da Shopee — 🟢 alta

Consultei o bronze, antes de qualquer transformação:

```sql
select json_value(raw_data,'$.date_iso')                    as dia,
       cast(json_value(raw_data,'$.direct_gmv') as numeric) as direct_gmv,
       cast(json_value(raw_data,'$.broad_gmv')  as numeric) as broad_gmv
from `cp-pipeline-503623.bronze.get_ads_campaign_daily`
where cast(json_value(raw_data,'$.direct_gmv') as numeric) > 0
```

O JSON tem os dois campos **separados**, com valores **idênticos**:

```json
"direct_gmv": 175.83, "broad_gmv": 175.83,
"direct_order": 3,    "broad_order": 3
```

O silver e o gold apenas copiam. **Não há o que consertar no código.**

### Por que isso é esperado — 🟡 média

*Broad* atribui venda de **outros** itens da loja após o clique. Para
divergir, alguém precisa clicar num anúncio e comprar **produto diferente**
na janela de atribuição.

Cada campanha da Casa e Patas anuncia **um item só**, e a loja faz ~10
pedidos por semana. A coincidência é raríssima nesta escala.

**O que falsifica:** um mês de volume maior em que os campos divirjam. Isso
confirmaria que a distinção existe e apenas não se manifesta hoje.

**O cuidado de "não somar entre campanhas" continua no dicionário** — ele
protege contra um problema adormecido, não resolvido.

---

## 4. Achado 2: `valor_pedidos_*` é quantidade — 🟢 alta

Este é o que tem risco de dinheiro.

O dicionário dizia: *"Valor dos pedidos diretos. Distinto do gmv_direto pela
forma como a Shopee contabiliza."* Isso sugere diferença de **método**.
A diferença é de **unidade**.

### As três provas

**Ordem de grandeza.** Nas 63 linhas com venda, o campo varia de **1 a 4**,
média 1,56 — contra GMV médio de **R$ 57,21**. Nenhum faturamento diário de
campanha é R$ 2.

**Relação com `pedidos_diretos`.** Em **63 de 63 linhas** é maior ou igual,
nunca menor. É exatamente a relação entre itens e pedidos.

**A divisão — prova definitiva.** `gmv_direto ÷ valor_pedidos_diretos`:

| campanha | resultado | preço no `master_orders` |
|---|---|---|
| 108961687 (Esteira Porta Copos), 17 dias | **25,86** | R$ 25,49 a 26,41 |
| 108573621 (Trio de Mesas), 9 dias | **57,10** | R$ 58,19 |

A divisão devolve o **preço unitário do produto**. Isso só é possível se o
denominador for quantidade.

Confirma também o `unidades_por_pedido` de 1,25 a 1,33 medido no
`master_orders` para esses mesmos itens.

### O erro que isso causaria

Somar `valor_pedidos_diretos` como receita devolve **R$ 98** no período,
onde o GMV real foi **R$ 3.604,08**. Erro de **37 vezes para baixo** — e o
número parece plausível à primeira vista, que é o que torna isso perigoso.

---

## 5. Arquivos tocados

| Arquivo | O que mudou |
|---|---|
| `dbt/seeds/dicionario_campos.csv` | 3 linhas corrigidas: `valor_pedidos_diretos`, `valor_pedidos_amplos`, `gmv_amplo` |
| `dbt/models/gold/schema.yml` | as mesmas 3 descrições |
| `docs/dicionario_master_ads.md` | 2 seções novas |

Contagem de linhas do seed **não muda**: 81 antes, 81 depois.

---

## 6. Por que NÃO renomeei a coluna

`valor_pedidos_diretos` deveria se chamar `itens_diretos`. Não renomeei, e a
razão é ponderada:

- renomear quebra qualquer consulta existente que use o nome antigo
- exige deploy e rodada da nuvem para valer em produção
- o campo **não está errado** — o nome e a descrição é que estavam

A correção de documentação resolve o risco real (alguém somar como receita)
sem custo de migração. **Se for renomear um dia**, faça junto com uma
varredura de quem consome a coluna — e não numa sexta-feira.

---

## 7. Comandos

```bash
source ~/.venvs/cp-bigquery/bin/activate
cd ~/Documents/"Casa e Patas"/data-pipeline/dbt

dbt seed --target bigquery
dbt build --target bigquery
```

**Esperado:** `dicionario_campos` com **81 linhas** (mesmo número de antes —
foram edições, não inserções). `dbt build` com **PASS=70**, zero ERROR.

---

## 8. Como verificar que deu certo

```sql
select campo, substr(descricao, 1, 60) as inicio_descricao
from `cp-pipeline-503623.silver.dicionario_campos`
where tabela = 'master_ads'
  and campo in ('valor_pedidos_diretos','valor_pedidos_amplos')
order by campo
```

**Esperado:** as duas descrições começando com **"CONTAGEM DE ITENS"**. Se
ainda disserem "Valor dos pedidos", o `dbt seed` não rodou.

---

## 9. Como reverter

```bash
cd ~/Documents/"Casa e Patas"/data-pipeline
git checkout dbt/seeds/dicionario_campos.csv \
             dbt/models/gold/schema.yml \
             docs/dicionario_master_ads.md
dbt seed --target bigquery
```

Reverter devolve a descrição errada. Só faz sentido se alguma prova aqui for
contestada.

---

## 10. O que pode dar errado

**Alguém já somou esse campo como receita.** Não sei se aconteceu. Se algum
relatório de mídia parece baixo demais para o período mar–ago, vale conferir
qual coluna foi usada — é o Inácio quem consome `master_ads`.

**Confundir os dois achados.** Eles são independentes: a igualdade entre
amplo e direto é comportamento normal da Shopee; o nome errado do
`valor_pedidos_*` é defeito de documentação nosso. Um não explica o outro.
