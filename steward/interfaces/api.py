"""
API Server — HTTP interface for federation access to Steward.

Enables agent-city, agent-internet, and external services to call
steward over HTTP. Same StewardAgent, different I/O channel.

Endpoints:
    POST /task          — execute a task, return result
    POST /task/stream   — execute a task, stream events via SSE
    GET  /health        — health check + provider status
    GET  /stats         — session ledger stats + provider stats

Authentication:
    Bearer token via STEWARD_API_TOKEN environment variable.
    If not set, runs without auth (local dev only).

Usage:
    pip install steward-agent[api]
    STEWARD_API_TOKEN=secret steward-api
    # Or: python -m steward --api

Environment:
    STEWARD_API_TOKEN   — Bearer token for auth (optional)
    STEWARD_API_HOST    — Bind host (default: 0.0.0.0)
    STEWARD_API_PORT    — Bind port (default: 8420)
    STEWARD_CWD         — Working directory for the agent
    GOOGLE_API_KEY      — (provider keys as usual)
"""

import asyncio
import json
import logging
import os
import sys
import time

logger = logging.getLogger("STEWARD.API")


def _check_deps() -> None:
    """Check that API dependencies are installed."""
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        print("API dependencies not installed. Run: pip install steward-agent[api]", file=sys.stderr)
        sys.exit(1)


def create_app():
    """Create the FastAPI application.

    Lazy import to avoid requiring fastapi/uvicorn at steward import time.
    """
    _check_deps()

    from fastapi import Depends, FastAPI, HTTPException, Request
    from fastapi.responses import StreamingResponse
    from pydantic import BaseModel

    # ── App Setup ────────────────────────────────────────────────────
    from steward import __version__
    from steward.agent import StewardAgent
    from steward.interfaces import agent_internet as agent_internet_proxy
    from steward.provider import build_chamber
    from steward.session_ledger import SessionLedger
    from steward.types import EventType

    app = FastAPI(
        title="Steward API",
        description="Autonomous Superagent Engine — HTTP interface",
        version=__version__,
    )

    _API_TOKEN = os.environ.get("STEWARD_API_TOKEN")
    _CWD = os.environ.get("STEWARD_CWD")

    # Shared agent instance (created on first request)
    _state: dict = {"agent": None, "chamber": None}
    _agent_lock = asyncio.Lock()

    async def _get_agent() -> StewardAgent:
        if _state["agent"] is not None:
            return _state["agent"]
        async with _agent_lock:
            # Double-check after acquiring lock
            if _state["agent"] is not None:
                return _state["agent"]
            chamber = build_chamber()
            if len(chamber) == 0:
                raise HTTPException(
                    status_code=503,
                    detail="No LLM providers configured. Set GOOGLE_API_KEY, MISTRAL_API_KEY, etc.",
                )
            _state["chamber"] = chamber
            _state["agent"] = StewardAgent(provider=chamber, cwd=_CWD)
            return _state["agent"]

    # ── Auth ─────────────────────────────────────────────────────────

    async def _verify_token(request: Request) -> None:
        if not _API_TOKEN:
            return  # No auth configured (local dev)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != _API_TOKEN:
            raise HTTPException(status_code=401, detail="Invalid or missing API token")

    # ── Models ───────────────────────────────────────────────────────

    class TaskRequest(BaseModel):
        task: str
        max_tokens: int | None = None

    class TaskResponse(BaseModel):
        result: str
        tokens: int = 0
        tool_calls: int = 0
        rounds: int = 0
        buddhi_action: str = ""
        buddhi_phase: str = ""
        duration_ms: int = 0

    class HealthResponse(BaseModel):
        status: str
        version: str
        providers: int
        tools: list[str]

    class AgentInternetSemanticCallRequest(BaseModel):
        capability_id: str | None = None
        contract_id: str | None = None
        version: int | None = None
        input_payload: dict = {}

    # ── Endpoints ────────────────────────────────────────────────────

    @app.post("/task", response_model=TaskResponse, dependencies=[Depends(_verify_token)])
    async def execute_task(req: TaskRequest):
        """Execute a task and return the result."""
        agent = await _get_agent()
        t0 = time.monotonic()

        result_text = ""
        usage = None

        async for event in agent.run_stream(req.task):
            if event.type == EventType.TEXT:
                result_text = str(event.content) if event.content else ""
            elif event.type == EventType.TEXT_DELTA:
                result_text += str(event.content) if event.content else ""
            elif event.type == EventType.DONE:
                usage = event.usage
            elif event.type == EventType.ERROR:
                raise HTTPException(status_code=500, detail=str(event.content))

        duration_ms = int((time.monotonic() - t0) * 1000)

        return TaskResponse(
            result=result_text,
            tokens=(usage.input_tokens + usage.output_tokens) if usage else 0,
            tool_calls=usage.tool_calls if usage else 0,
            rounds=usage.rounds if usage else 0,
            buddhi_action=usage.buddhi_action or "" if usage else "",
            buddhi_phase=str(usage.buddhi_phase) if usage and usage.buddhi_phase else "",
            duration_ms=duration_ms,
        )

    @app.post("/task/stream", dependencies=[Depends(_verify_token)])
    async def execute_task_stream(req: TaskRequest):
        """Execute a task and stream events via Server-Sent Events (SSE)."""
        agent = await _get_agent()

        async def _event_stream():
            async for event in agent.run_stream(req.task):
                data: dict = {"type": event.type.value}

                if event.type in (EventType.TEXT, EventType.TEXT_DELTA, EventType.ERROR):
                    data["content"] = str(event.content) if event.content else ""
                elif event.type == EventType.TOOL_CALL and event.tool_use:
                    data["tool"] = event.tool_use.name
                    data["parameters"] = event.tool_use.parameters
                elif event.type == EventType.TOOL_RESULT and event.content:
                    data["success"] = getattr(event.content, "success", None)
                    data["output"] = str(getattr(event.content, "output", ""))[:2000]
                elif event.type == EventType.DONE and event.usage:
                    u = event.usage
                    data["usage"] = {
                        "tokens": u.input_tokens + u.output_tokens,
                        "tool_calls": u.tool_calls,
                        "rounds": u.rounds,
                        "buddhi_action": u.buddhi_action or "",
                    }

                yield f"data: {json.dumps(data)}\n\n"

        return StreamingResponse(
            _event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/health", response_model=HealthResponse)
    async def health():
        """Health check — shows provider count and available tools."""
        try:
            agent = await _get_agent()
            return HealthResponse(
                status="ok",
                version=__version__,
                providers=len(_state["chamber"]) if _state["chamber"] else 0,
                tools=agent.registry.list_tools(),
            )
        except HTTPException:
            return HealthResponse(status="no_providers", version=__version__, providers=0, tools=[])

    @app.get("/stats", dependencies=[Depends(_verify_token)])
    async def stats():
        """Session ledger stats + provider stats."""
        ledger = SessionLedger(cwd=_CWD)
        result: dict = {"ledger": ledger.stats}

        if _state["chamber"] is not None:
            result["providers"] = _state["chamber"].stats()

        return result

    # ── Agent Internet ────────────────────────────────────────────

    @app.get("/agent-internet/semantic/capabilities", dependencies=[Depends(_verify_token)])
    async def agent_internet_semantic_capabilities():
        """Proxy the published agent-internet semantic capability manifest."""
        try:
            agent_internet_proxy.load_agent_internet_proxy_config()
            return agent_internet_proxy.fetch_semantic_capabilities()
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/agent-internet/semantic/contracts", dependencies=[Depends(_verify_token)])
    async def agent_internet_semantic_contracts(
        capability_id: str | None = None,
        contract_id: str | None = None,
        version: int | None = None,
    ):
        """Proxy published agent-internet semantic contract descriptors."""
        try:
            agent_internet_proxy.load_agent_internet_proxy_config()
            return agent_internet_proxy.fetch_semantic_contracts(
                capability_id=capability_id, contract_id=contract_id, version=version
            )
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/agent-internet/semantic/call", dependencies=[Depends(_verify_token)])
    async def agent_internet_semantic_call(req: AgentInternetSemanticCallRequest):
        """Proxy published agent-internet semantic invocation through steward."""
        try:
            agent_internet_proxy.load_agent_internet_proxy_config()
            return agent_internet_proxy.invoke_semantic_http(
                capability_id=req.capability_id,
                contract_id=req.contract_id,
                version=req.version,
                input_payload=dict(req.input_payload or {}),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/agent-internet/repo-graph/capabilities", dependencies=[Depends(_verify_token)])
    async def agent_internet_repo_graph_capabilities():
        try:
            agent_internet_proxy.load_agent_internet_proxy_config()
            return agent_internet_proxy.fetch_repo_graph_capabilities()
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/agent-internet/repo-graph/contracts", dependencies=[Depends(_verify_token)])
    async def agent_internet_repo_graph_contracts(
        capability_id: str | None = None,
        contract_id: str | None = None,
        version: int | None = None,
    ):
        try:
            agent_internet_proxy.load_agent_internet_proxy_config()
            return agent_internet_proxy.fetch_repo_graph_contracts(
                capability_id=capability_id,
                contract_id=contract_id,
                version=version,
            )
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/agent-internet/repo-graph", dependencies=[Depends(_verify_token)])
    async def agent_internet_repo_graph(
        root: str,
        node_type: str | None = None,
        domain: str | None = None,
        query: str | None = None,
        limit: int | None = None,
    ):
        try:
            agent_internet_proxy.load_agent_internet_proxy_config()
            return agent_internet_proxy.fetch_repo_graph_snapshot(
                root=root,
                node_type=node_type,
                domain=domain,
                query=query,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/agent-internet/repo-graph/neighbors", dependencies=[Depends(_verify_token)])
    async def agent_internet_repo_graph_neighbors(
        root: str,
        node_id: str,
        relation: str | None = None,
        depth: int | None = None,
        limit: int | None = None,
    ):
        try:
            agent_internet_proxy.load_agent_internet_proxy_config()
            return agent_internet_proxy.fetch_repo_graph_neighbors(
                root=root,
                node_id=node_id,
                relation=relation,
                depth=depth,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/agent-internet/repo-graph/context", dependencies=[Depends(_verify_token)])
    async def agent_internet_repo_graph_context(root: str, concept: str):
        try:
            agent_internet_proxy.load_agent_internet_proxy_config()
            return agent_internet_proxy.fetch_repo_graph_context(root=root, concept=concept)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/agent-internet/public-graph", dependencies=[Depends(_verify_token)])
    async def agent_internet_public_graph(
        root: str,
        city_id: str | None = None,
        assistant_id: str | None = None,
        heartbeat_source: str | None = None,
    ):
        try:
            agent_internet_proxy.load_agent_internet_proxy_config()
            return agent_internet_proxy.fetch_public_graph(
                root=root,
                city_id=city_id,
                assistant_id=assistant_id,
                heartbeat_source=heartbeat_source,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/agent-internet/search-index", dependencies=[Depends(_verify_token)])
    async def agent_internet_search_index(
        root: str,
        city_id: str | None = None,
        assistant_id: str | None = None,
        heartbeat_source: str | None = None,
    ):
        try:
            agent_internet_proxy.load_agent_internet_proxy_config()
            return agent_internet_proxy.fetch_search_index(
                root=root,
                city_id=city_id,
                assistant_id=assistant_id,
                heartbeat_source=heartbeat_source,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/agent-internet/search", dependencies=[Depends(_verify_token)])
    async def agent_internet_search(
        root: str,
        q: str,
        limit: int | None = None,
        city_id: str | None = None,
        assistant_id: str | None = None,
        heartbeat_source: str | None = None,
    ):
        try:
            agent_internet_proxy.load_agent_internet_proxy_config()
            return agent_internet_proxy.search_index(
                root=root,
                query=q,
                limit=limit,
                city_id=city_id,
                assistant_id=assistant_id,
                heartbeat_source=heartbeat_source,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/agent-internet/federated-index", dependencies=[Depends(_verify_token)])
    async def agent_internet_federated_index(index_path: str | None = None):
        try:
            agent_internet_proxy.load_agent_internet_proxy_config()
            return agent_internet_proxy.fetch_federated_index(index_path=index_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/agent-internet/federated-search", dependencies=[Depends(_verify_token)])
    async def agent_internet_federated_search(
        q: str,
        limit: int | None = None,
        index_path: str | None = None,
        overlay_path: str | None = None,
        wordnet_path: str | None = None,
    ):
        try:
            agent_internet_proxy.load_agent_internet_proxy_config()
            return agent_internet_proxy.search_federated_index(
                query=q,
                limit=limit,
                index_path=index_path,
                overlay_path=overlay_path,
                wordnet_path=wordnet_path,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return app


def main() -> None:
    """Entry point for steward-api command."""
    _check_deps()

    import uvicorn

    host = os.environ.get("STEWARD_API_HOST", "0.0.0.0")
    port = int(os.environ.get("STEWARD_API_PORT", "8420"))

    logger.info("Starting Steward API on %s:%d", host, port)
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
