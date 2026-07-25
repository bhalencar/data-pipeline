import pandas as pd

# Lê só a aba de dados (ignora a aba "legenda")
df = pd.read_excel(
    "extraction/planilhas/custo_produtos.xlsx",
    sheet_name="custo_produtos",
    header=3,  # a linha 4 da planilha é o cabeçalho de verdade (linhas 1-2 são título/instrução)
)

# Remove linhas totalmente vazias (as linhas em branco reservadas pra digitação futura)
df = df.dropna(how="all")

df.to_csv("dbt/seeds/custo_produtos.csv", index=False)
print(f"{len(df)} linhas exportadas para dbt/seeds/custo_produtos.csv")