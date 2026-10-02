"""Import support tables so they share one metadata registry."""


def load_models() -> None:
    """Import every support model module. Import order is not significant."""
    import assistflow_conversations.models
    import assistflow_customers.models
    import assistflow_knowledge.models
    import assistflow_memory.models
    import assistflow_orders.models
    import assistflow_refunds.models
    import assistflow_returns.models
    import assistflow_shipping.models
    import assistflow_tickets.models

    _ = (
        assistflow_conversations.models,
        assistflow_customers.models,
        assistflow_knowledge.models,
        assistflow_memory.models,
        assistflow_orders.models,
        assistflow_refunds.models,
        assistflow_returns.models,
        assistflow_shipping.models,
        assistflow_tickets.models,
    )
