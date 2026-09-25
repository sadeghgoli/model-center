import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from mc_api.routes.admin import router as admin_router
from mc_api.routes.v1 import router as v1_router
from mc_shared.db import init_db
from mc_shared.errors import PlatformError, openai_error
from mc_shared.settings import get_settings

init_db()
settings = get_settings()
app = FastAPI(title="Model Center", version="0.1.0")
app.include_router(admin_router)
app.include_router(v1_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


@app.middleware("http")
async def context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    body = await request.body()
    if len(body) > get_settings().max_body_bytes:
        return JSONResponse(status_code=413, content=openai_error(PlatformError("invalid_request", "Request is too large.", 413)))
    request.state.request_id = str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.exception_handler(PlatformError)
async def platform_error(request: Request, exc: PlatformError) -> JSONResponse:
    if request.url.path.startswith("/v1/"):
        return JSONResponse(status_code=exc.status_code, content=openai_error(exc))
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {"code": exc.code, "message": exc.message},
            "request_id": getattr(request.state, "request_id", None),
        },
    )


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"success": True, "data": {"status": "ok"}, "request_id": getattr(request.state, "request_id", None)})
