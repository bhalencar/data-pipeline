-- Cria o schema (como uma "pasta" dentro do banco, separando por camada)
CREATE SCHEMA IF NOT EXISTS bronze;

-- Tabela de controle: lista enxuta de pedidos (order_sn + status)
CREATE TABLE bronze.get_order_list (
    id SERIAL PRIMARY KEY,
    order_sn TEXT NOT NULL,
    raw_data JSONB NOT NULL,
    extraction_date DATE NOT NULL,
    loaded_at TIMESTAMP NOT NULL DEFAULT now()
);

-- Tabela com o pedido completo (inclui item_list aninhado)
CREATE TABLE bronze.get_order_detail (
    id SERIAL PRIMARY KEY,
    order_sn TEXT NOT NULL,
    raw_data JSONB NOT NULL,
    extraction_date DATE NOT NULL,
    loaded_at TIMESTAMP NOT NULL DEFAULT now()
);