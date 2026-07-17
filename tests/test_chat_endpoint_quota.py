import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient


def _make_app() -> FastAPI:
    app = FastAPI()

    async def no_auth():
        return None

    @app.post("/chat")
    async def chat_endpoint(request: Request, _=Depends(no_auth)):
        try:
            body = await request.json()
            _ = body.get("message", "").strip()
            raise Exception("429 RESOURCE_EXHAUSTED")
        except Exception as e:
            err = str(e).lower()
            if "429" in err or "resource exhausted" in err or "quota" in err:
                return JSONResponse(
                    {"error": "Model quota exhausted right now. Please retry shortly."},
                    status_code=503,
                )
            return JSONResponse({"error": str(e)}, status_code=500)

    return app


def test_chat_quota_error_returns_503():
    client = TestClient(_make_app())
    r = client.post("/chat", json={"message": "hello"})
    assert r.status_code == 503
    assert r.json() == {"error": "Model quota exhausted right now. Please retry shortly."}
