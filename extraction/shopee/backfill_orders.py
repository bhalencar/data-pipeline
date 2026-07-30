import os
import json
import time
from datetime import datetime, timedelta, timezone
from get_orders import get_order_list, get_order_detail, get_escrow_detail

WINDOW_DAYS = 15  # limite máximo da API por chamada
TZ = timezone(timedelta(hours=-3))  # Brasília


def daterange_windows(start_date, end_date, window_days=WINDOW_DAYS):
    """Gera janelas de até `window_days` dias, cobrindo start_date até end_date."""
    windows = []
    current = start_date
    while current <= end_date:
        window_end = min(current + timedelta(days=window_days - 1), end_date)
        windows.append((current, window_end))
        current = window_end + timedelta(days=1)
    return windows


def run_backfill(start_date, end_date):
    windows = daterange_windows(start_date, end_date)
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
    START_DATE = datetime(2026, 1, 1).date()
    END_DATE = datetime.now(TZ).date() - timedelta(days=1)  # até ontem

    run_backfill(START_DATE, END_DATE)