CREATE TABLE bronze.get_escrow_detail (
    id SERIAL PRIMARY KEY,
    order_sn TEXT NOT NULL,
    raw_data JSONB NOT NULL,
    extraction_date DATE NOT NULL,
    loaded_at TIMESTAMP NOT NULL DEFAULT now()
);