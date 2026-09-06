import logging
import time
import uuid

from fastapi import FastAPI
from pydantic import BaseModel

from src.order_support_agent.graph import run_graph

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("agent.api")

app = FastAPI(title="Order Support Agent")

# ponytail: in-memory only, lost on restart, no eviction — swap for a real store (redis/db) if sessions need to survive restarts or scale past one process.
SESSIONS: dict[str, list[dict]] = {}


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
def chat(req: ChatRequest):
    session_id = req.session_id or uuid.uuid4().hex
    history = SESSIONS.get(session_id)
    logger.info("request session_id=%s new_session=%s history_len=%d message=%r",
                session_id, history is None, len(history or []), req.message)
    started = time.monotonic()

    try:
        result = run_graph(req.message, history=history)
    except Exception as e:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        logger.exception("unhandled error session_id=%s elapsed_ms=%d", session_id, elapsed_ms)
        return {"response": None, "error": f"{type(e).__name__}: {e}", "tool_calls": [],
                "elapsed_ms": elapsed_ms, "session_id": session_id}

    SESSIONS[session_id] = result["messages"]
    elapsed_ms = round((time.monotonic() - started) * 1000)
    tool_calls = [m for m in result["messages"] if m["role"] == "tool"]
    logger.info("response session_id=%s elapsed_ms=%d tool_calls=%d history_len=%d error=%s",
                session_id, elapsed_ms, len(tool_calls), len(result["messages"]), result.get("error"))

    return {
        "response": result.get("response"),
        "error": result.get("error"),
        "tool_calls": tool_calls,
        "elapsed_ms": elapsed_ms,
        "session_id": session_id,
    }
