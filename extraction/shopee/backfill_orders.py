"""
Reextração pontual de um intervalo de datas, fora da rodada diária.

Uso:
    python extraction/shopee/backfill_orders.py                          # 01/01/2026 até ontem
    python extraction/shopee/backfill_orders.py 2026-07-15 2026-07-22    # só esse intervalo

As datas são de CRIAÇÃO do pedido, no fuso de Brasília, e o intervalo é inclusivo
nas duas pontas.
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta, timezone
from get_orders import (
    get_order_list,
    get_order_detail,
    get_escrow_detail,
    fatiar_janela,
    MAX_WINDOW_DAYS as WINDOW_DAYS,
)

TZ = timezone(timedelta(hours=-3))  # Brasília


def run_backfill(start_date, end_date):
    # fatiar_janela vem do get_orders: uma implementação só do fatiamento, para
    # o backfill e a rodada diária não divergirem no limite da API.
    windows = fatiar_janela(start_date, end_date)
    print(f"Backfill de {start_date} a {end_date}, em {len(windows)} janela(s) de até {WINDOW_DAYS} dias.")

    for window_start, window_end in windows:
        label = window_start.isoformat()  # nome do arquivo = data de início da janela
        print(f"\n--- Janela: {window_start} a {window_end} ---")

        time_from = int(datetime.combine(window_start, datetime.min.time(), tzinfo=TZ).timestamp())
        time_to = int(datetime.combine(window_end, datetime.max.time(), tzinfo=TZ).timestamp())

        order_list = get_order_list(time_from, time_to)
        print(f"{len(order_list)} pedidos encontrados nessa janela.")

        os.makedirs("data/bronze/get_order_list", exist_ok=True)
        with open(f"data/bronze/get_order_list/{label}.json", "w") as f:
            json.dump(order_list, f, indent=2)

        if not order_list:
            continue

        order_sns = [o["order_sn"] for o in order_list]

        order_details = get_order_detail(order_sns)
        os.makedirs("data/bronze/get_order_detail", exist_ok=True)
        with open(f"data/bronze/get_order_detail/{label}.json", "w") as f:
            json.dump(order_details, f, indent=2)
        print(f"Detalhes salvos para {len(order_details)} pedidos.")

        escrow_details = get_escrow_detail(order_sns)
        os.makedirs("data/bronze/get_escrow_detail", exist_ok=True)
        with open(f"data/bronze/get_escrow_detail/{label}.json", "w") as f:
            json.dump(escrow_details, f, indent=2)
        print(f"Dados financeiros salvos para {len(escrow_details)} pedidos.")

        time.sleep(1)  # pequena pausa entre janelas, por precaução

    print("\nBackfill concluído.")


if __name__ == "__main__":
    ontem = datetime.now(TZ).date() - timedelta(days=1)

    if len(sys.argv) == 3:
        START_DATE = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
        END_DATE = datetime.strptime(sys.argv[2], "%Y-%m-%d").date()
    elif len(sys.argv) == 1:
        START_DATE = datetime(2026, 1, 1).date()
        END_DATE = ontem
    else:
        print("Uso: backfill_orders.py [AAAA-MM-DD AAAA-MM-DD]")
        sys.exit(2)

    if START_DATE > END_DATE:
        print(f"Erro: data inicial ({START_DATE}) é depois da final ({END_DATE}).")
        sys.exit(2)
    if END_DATE > ontem:
        print(f"Erro: data final ({END_DATE}) é depois de ontem ({ontem}). "
              "O dia corrente ainda está aberto e não deve ser extraído.")
        sys.exit(2)

    run_backfill(START_DATE, END_DATE)