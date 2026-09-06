.PHONY: seed test backend frontend

seed:
	uv run python src/db/seed_db.py

test:
	uv run python -m src.tools.tools
	uv run python -m src.order_support_agent.agent
	uv run python -m src.order_support_agent.graph

backend:
	set -a && . .env && set +a && uv run uvicorn src.order_support_agent.server:app --reload --port 8000

frontend:
	set -a && . .env && set +a && uv run streamlit run src/order_support_agent/app.py
