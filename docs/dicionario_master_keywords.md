# master_keywords — volume de busca

**Para quem lê número, não código.** A versão técnica está em `silver.dicionario_campos` e em `dbt/models/gold/schema.yml`.

Fonte: Shopee Ads API. Uma linha por **palavra, por produto, por semana**.

---

## Por que esta tabela existe

A Shopee mostra quantas pessoas buscaram cada termo nos últimos 30 dias. Mas é uma **janela móvel**: ela mostra o número de hoje, e o de semana passada some.

Sem guardar, *"esse termo cresceu"* é uma frase impossível de dizer.

Esta tabela guarda. É a única razão de ela existir.

---

## A regra que mais engana

> **Não some `volume_busca` entre produtos.**

A mesma palavra aparece para vários produtos, sempre **com o mesmo número** — porque o volume é do termo na Shopee inteira, não do seu produto.

Exemplo real: "escada pet" tem 34.274 buscas. Ela aparece na Escada Pet **e** em outro item do catálogo. Somando, daria 68.548 — o dobro de buscas que existem.

**Para saber o volume de um termo, olhe um produto só.** É a mesma armadilha do `broad_gmv` no `master_ads` e do `escrow_amount` no `master_orders`.

---

## O que o número quer dizer — e o que não quer

`volume_busca` é **quanta gente buscou o termo na Shopee**. Não é:

- quantas pessoas viram o seu produto
- quantas compraram
- quanto você vendeu com aquele termo

É demanda de mercado, não desempenho seu. Um termo com 122 mil buscas e nenhuma venda sua significa que há gente procurando e você não está aparecendo — o que é uma informação útil, mas diferente de "esse termo vende".

---

## Como ler a variação

Cada linha traz `variacao_absoluta` e `variacao_pct` contra a semana anterior.

**Leia as duas juntas.** Um crescimento de 100% pode ser 50 buscas virando 100 — ruído. Um crescimento de 5% pode ser 120.000 virando 126.000 — seis mil pessoas a mais procurando.

No primeiro snapshot de cada palavra as duas ficam **vazias**, porque não há com o que comparar. É esperado.

---

## O limite de 50 palavras por produto

A Shopee devolve no máximo **50 sugestões por produto**. Medido em 06/09/2026: dos 25 produtos, 6 pararam cravados em 50 e nenhum passou disso.

Para esses produtos, você está vendo **as 50 mais relevantes, não todas**.

Isso cria uma leitura falsa na série: se uma palavra sair do top 50 numa semana, ela **some da tabela** — e parece que a busca por ela desapareceu, quando na verdade só caiu de posição.

**Regra prática:** num produto com 50 linhas na semana, palavra que sumiu não é sinal de queda de busca. Num produto com menos de 50, o sumiço é real.

---

## Uma coisa que não dá para recuperar

O `master_orders` relê os últimos 30 dias todo dia: se uma rodada falhar, a seguinte conserta.

**Aqui não.** A Shopee não guarda histórico de volume. Se a coleta de uma segunda-feira falhar, aquela semana **não existe** e nunca mais vai existir.

E a falha é silenciosa: a tabela continua cheia, as consultas continuam respondendo, e o buraco só aparece meses depois quando alguém olha a série.

Por isso existe um teste que reclama se passaram mais de 10 dias sem coleta. Se ele disparar, o dado daquela semana já se perdeu — o que resta é garantir que a próxima aconteça.

---

## Quais produtos entram

Todos os do catálogo ativo, **mais** todos que já venderam ou foram anunciados algum dia. Hoje são 25.

Produto novo entra sozinho na coleta seguinte, assim que é cadastrado na loja — não precisa avisar ninguém.

**Produto pausado continua sendo consultado**, de propósito. A Caminha Pet MDF saiu do ar em agosto porque o fornecedor ficou sem estoque, não porque o produto acabou. Quando voltar, a série dela não terá buraco.

A coluna `no_catalogo` diz se o produto estava ativo naquela semana.

---

## O que esta tabela não responde

**Volume de termo fora do catálogo.** Testado em 06/09/2026: pedir "ração para gato" devolve palavras do próprio produto consultado, nunca do termo pedido. A Shopee só sugere a partir de um item seu.

Isso é **teto da plataforma**, não lacuna — nenhuma integração futura resolve. Para pesquisar um mercado onde a loja ainda não vende, é preciso outra fonte.

**Posição do seu anúncio na busca.** A tabela diz quanta gente procura, não em que lugar você aparece.
