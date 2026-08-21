import pandas as pd

CANAIS = {"shopee", "mercado_livre", "comum"}

# Lê só a aba de dados (ignora a aba "legenda")
df = pd.read_excel(
    "extraction/planilhas/despesa_operacional.xlsx",
    sheet_name="despesa_operacional",
    header=3,  # a linha 4 da planilha é o cabeçalho de verdade (linhas 1-2 são título/instrução)
)

# Remove linhas totalmente vazias (as linhas em branco reservadas pra digitação futura)
df = df.dropna(how="all")

# competencia vem do Excel como datetime; o seed precisa de AAAA-MM-DD.
# Sem isso o dbt recebe "2026-08-01 00:00:00" e o cast para DATE falha.
df["competencia"] = pd.to_datetime(df["competencia"]).dt.strftime("%Y-%m-%d")

# Guarda-corpo 1: competência sempre no dia 1º. Despesa é mensal, e data no meio
# do mês significa que alguém entendeu a planilha como regime de caixa.
fora_do_dia_1 = df.loc[~df["competencia"].str.endswith("-01"), "competencia"]
if len(fora_do_dia_1):
    raise SystemExit(
        f"Erro: {len(fora_do_dia_1)} linha(s) com competencia fora do dia 1o: "
        f"{sorted(set(fora_do_dia_1))}. Corrija na planilha antes de exportar."
    )

# Guarda-corpo 2: canal precisa ser um dos três. Canal escrito errado não quebra
# o dbt -- ele vira uma categoria fantasma que some do DRE sem ninguém notar.
canal_invalido = set(df["canal"].dropna().unique()) - CANAIS
if canal_invalido:
    raise SystemExit(
        f"Erro: canal(is) fora da lista {sorted(CANAIS)}: {sorted(canal_invalido)}. "
        "Corrija na planilha antes de exportar."
    )

df.to_csv("dbt/seeds/despesa_operacional_manual.csv", index=False)
print(f"{len(df)} linhas exportadas para dbt/seeds/despesa_operacional_manual.csv")
