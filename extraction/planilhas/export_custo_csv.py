"""
DESATIVADO EM 14/11/2026. Este script destruiria dados se rodasse hoje.

O QUE ELE FAZIA. Lia `extraction/planilhas/custo_produtos.xlsx` e sobrescrevia
`dbt/seeds/custo_produtos.csv` inteiro -- `to_csv`, nao append.

POR QUE ISSO VIROU PERIGO. A xlsx local parou em 01/08/2026. De agosto para ca
os custos passaram a ser cadastrados direto no CSV, e depois na tabela. A
planilha nao tem nenhum produto de Natal, nenhum SKU de Comedouro, nao tem
MRG-01 nem BBKIT-01, e ainda carrega custo velho de 3MES e ESC4.

Rodar este script apagaria tudo o que entrou desde agosto, em silencio: sem
erro, sem aviso, sem diff na tela. O estrago so apareceria na manha seguinte,
como `cmv_unitario` nulo derrubando o build -- exatamente o incidente de
11 a 14/11/2026, que custou tres dias de pipeline parado.

QUAL E O CAMINHO AGORA. O custo mora em `cp-pipeline-503623.config.custo_produtos`,
lido em tempo de execucao pelo `master_orders`. Cadastrar e um insert, e vale na
rodada seguinte -- sem seed, sem commit, sem deploy:

    insert into `cp-pipeline-503623.config.custo_produtos`
      (sku, nome_produto, custo_unitario, data_vigencia_inicio,
       observacao, origem, alterado_em)
    values ('SKU-01', 'Nome do produto', 12.34, date '2026-11-01',
            'de onde veio o custo', 'manual', current_timestamp());

Custo que MUDOU nao vira update: entra como linha nova com
`data_vigencia_inicio` nova. O `master_orders` escolhe a vigencia mais recente
anterior a data do pedido, entao reescrever linha antiga reescreveria margem de
pedido ja fechado.

POR QUE O ARQUIVO CONTINUA AQUI, em vez de apagado. Quem lembra do fluxo antigo
vai procurar por ele; encontrar um aviso e melhor que encontrar nada e
reconstruir o script de memoria. Pode ser removido do repositorio quando o
fluxo novo estiver velho o suficiente para ninguem procurar.

A planilha de precificacao continua util: e de la que saem os custos novos. O
que morreu foi o caminho automatico planilha -> seed, nao a planilha.
"""

import sys

sys.exit(
    "export_custo_csv.py esta desativado desde 14/11/2026.\n"
    "A planilha local parou em 01/08 e sobrescrever o seed com ela apagaria\n"
    "todos os custos cadastrados desde agosto.\n\n"
    "O custo agora mora em cp-pipeline-503623.config.custo_produtos e se\n"
    "cadastra por insert, sem deploy. Veja o docstring deste arquivo."
)
