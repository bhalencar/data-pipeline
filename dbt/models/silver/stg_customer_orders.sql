with orders as (
    select
        order_sn,
        buyer_username,
        create_time
    from {{ ref('stg_orders') }}
    where buyer_username is not null
),

ranked as (
    select
        order_sn,
        buyer_username,
        create_time,
        row_number() over (
            partition by buyer_username
            order by create_time asc
        ) as order_sequence_number
    from orders
)

select
    order_sn,
    buyer_username,
    order_sequence_number,
    case
        when order_sequence_number = 1 then 'Novo'
        else 'Recorrente'
    end as customer_type
from ranked