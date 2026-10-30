from __future__ import annotations

from dataclasses import dataclass

from backend.app.agent.models import AgentSchema, SQLProposal
from backend.app.errors import AppError
from backend.app.services.dataset_store import DEMO_ID


@dataclass(frozen=True)
class DemoExample:
    question: str
    sql: str
    explanation: str


DEMO_EXAMPLES = (
    DemoExample(
        "How many orders are there?",
        "SELECT COUNT(*) AS order_count FROM orders",
        "Counts all rows in the orders table.",
    ),
    DemoExample(
        "What is the total revenue?",
        "SELECT ROUND(SUM(quantity * unit_price), 2) AS total_revenue FROM orders",
        "Sums quantity multiplied by unit price across all orders.",
    ),
    DemoExample(
        "What are the top 5 products by revenue?",
        """SELECT p.product_name, ROUND(SUM(o.quantity * o.unit_price), 2) AS revenue
        FROM orders AS o JOIN products AS p ON p.product_id = o.product_id
        GROUP BY p.product_id, p.product_name ORDER BY revenue DESC LIMIT 5""",
        "Joins orders to products and ranks products by calculated revenue.",
    ),
    DemoExample(
        "What was the revenue in September 2026?",
        """SELECT ROUND(SUM(quantity * unit_price), 2) AS revenue
        FROM orders WHERE order_date >= '2026-09-01' AND order_date < '2026-10-01'""",
        "Calculates revenue for orders dated in September 2026.",
    ),
    DemoExample(
        "How does revenue compare by category?",
        """SELECT p.category, ROUND(SUM(o.quantity * o.unit_price), 2) AS revenue
        FROM orders AS o JOIN products AS p ON p.product_id = o.product_id
        GROUP BY p.category ORDER BY revenue DESC""",
        "Joins products to orders and groups calculated revenue by category.",
    ),
    DemoExample(
        "How many orders came from each customer segment?",
        """SELECT c.segment, COUNT(*) AS order_count
        FROM orders AS o JOIN customers AS c ON c.customer_id = o.customer_id
        GROUP BY c.segment ORDER BY order_count DESC, c.segment""",
        "Joins orders to customers and counts orders for each segment.",
    ),
    DemoExample(
        "What is the average quantity per order?",
        "SELECT ROUND(AVG(quantity), 2) AS average_quantity FROM orders",
        "Calculates the average item quantity recorded per order.",
    ),
    DemoExample(
        "Which cities generated the most revenue?",
        """SELECT c.city, ROUND(SUM(o.quantity * o.unit_price), 2) AS revenue
        FROM orders AS o JOIN customers AS c ON c.customer_id = o.customer_id
        JOIN products AS p ON p.product_id = o.product_id
        GROUP BY c.city ORDER BY revenue DESC""",
        "Uses the three demo tables and groups calculated revenue by customer city.",
    ),
)

_REGISTRY = {example.question.casefold(): example for example in DEMO_EXAMPLES}


class DemoSQLProvider:
    def generate(
        self,
        question: str,
        schema: AgentSchema,
        retry_feedback: str | None = None,
    ) -> SQLProposal:
        del retry_feedback
        if schema.dataset_id != DEMO_ID:
            raise AppError(
                "DEMO_DATASET_UNSUPPORTED",
                "Demo mode supports predefined questions only for the Retail Demo dataset.",
                400,
            )
        example = _REGISTRY.get(_normalize_question(question))
        if example is None:
            raise AppError(
                "DEMO_QUESTION_UNSUPPORTED",
                "Demo mode supports only the declared predefined questions.",
                400,
            )
        return SQLProposal(
            disposition="query",
            sql=example.sql,
            explanation=example.explanation,
        )


def _normalize_question(question: str) -> str:
    return " ".join(question.strip().split()).casefold()
