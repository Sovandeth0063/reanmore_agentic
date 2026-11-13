"""HTTPS session, speech-turn, and snapshot API for the snapshot tutor.

The app factory is lazy: importing this module never reads ``.env`` and never
constructs a provider client. Settings, the SQLite store, the fixed lesson, and
the default controller factory are resolved on the first request (or by an
explicit lifespan call). One HTTP client and one speech transcriber are shared
by every session for the life of the process and closed on shutdown. Tests pass
fakes so no provider, service, or credential is needed.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import sqlite3
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from server.contract import (
    MAX_AUDIO_BYTES,
    MAX_AUDIO_SECONDS,
    MAX_IMAGE_BYTES,
    SESSION_CREATE_PATH,
    SESSION_END_PATH,
    SESSION_SNAPSHOT_PATH,
    SESSION_TURN_PATH,
    ContractError,
    SessionResponse,
    ended_payload,
    error_payload,
    validate_purpose,
)

logger = logging.getLogger(__name__)

DEFAULT_LESSON_PATH = (
    Path(__file__).resolve().parents[1] / "agent" / "lessons" / "grade3_demo.yaml"
)


class SessionRegistry:
    """One lock and one controller per session, plus a serialized runner."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._controllers: dict[str, Any] = {}
        self._guard = threading.Lock()

    def lock_for(self, session_id: str) -> asyncio.Lock:
        with self._guard:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[session_id] = lock
            return lock

    def controller_for(
        self, session_id: str, factory: Callable[[str], Any]
    ) -> Any:
        with self._guard:
            controller = self._controllers.get(session_id)
            if controller is None:
                controller = factory(session_id)
                self._controllers[session_id] = controller
            return controller

    def discard(self, session_id: str) -> None:
        with self._guard:
            self._controllers.pop(session_id, None)
            self._locks.pop(session_id, None)

    async def run(
        self,
        session_id: str,
        operation: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Run one operation while holding that session's single lock.

        A sync operation runs in a worker thread so provider and model work
        never blocks the API event loop. The lock stays held for the whole
        call, so one session still sees its operations in order. Async
        operations are awaited on the loop as before.
        """
        async with self.lock_for(session_id):
            result = await asyncio.to_thread(operation, *args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            return result


class _Runtime:
    """Lazily resolved settings, store, lesson, shared providers, and factory.

    The runtime owns one ``httpx.Client`` and one ``Transcriber`` for the whole
    process. Controllers borrow both and never close them; :meth:`close` owns
    that lifecycle. An injected store or an injected controller factory's
    resources are never closed here.
    """

    def __init__(
        self,
        *,
        settings: Any = None,
        store: Any = None,
        lesson: Any = None,
        controller_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.lesson = lesson
        self.controller_factory = controller_factory
        self.http: Any = None
        self.transcriber: Any = None
        self.registry = SessionRegistry()
        self._lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._ready = False
        self._closed = False

    def ensure(self) -> "_Runtime":
        if self._ready:
            return self
        with self._lock:
            if self._ready:
                return self
            if self.settings is None and (
                self.store is None or self.controller_factory is None
            ):
                from agent.config import Settings

                self.settings = Settings.from_environment()
            if self.store is None:
                from agent.memory import SessionStore

                if self.settings is None:
                    raise RuntimeError(
                        "Settings are required to build the session store"
                    )
                self.store = SessionStore(self.settings.db_url)
            if self.lesson is None:
                from agent.lesson import load_lesson

                self.lesson = load_lesson(DEFAULT_LESSON_PATH)
            if self.controller_factory is None:
                self._build_shared_providers()
                self.controller_factory = self._default_controller_factory()
            try:
                self.store.prune()
            except (sqlite3.Error, OSError) as error:
                logger.warning("Session retention sweep failed: %s", error)
            self._ready = True
        return self

    def _build_shared_providers(self) -> None:
        """Build the process-wide HTTP client and speech model owner once."""
        if self.http is None:
            import httpx

            self.http = httpx.Client(timeout=10.0)
        if self.transcriber is None:
            from agent.stt import Transcriber

            if self.settings is None:
                raise RuntimeError(
                    "Settings are required to build the speech transcriber"
                )
            self.transcriber = Transcriber(
                self.settings.whisper_model,
                device=self.settings.whisper_device,
                compute_type=self.settings.whisper_compute_type,
            )

    def _default_controller_factory(self) -> Callable[[str], Any]:
        from agent.controller import TutorController

        settings = self.settings
        store = self.store
        lesson = self.lesson
        http = self.http
        transcriber = self.transcriber
        if settings is None or store is None or lesson is None:
            raise RuntimeError("Runtime is not ready for controllers")
        if http is None or transcriber is None:
            raise RuntimeError("Runtime is missing its shared providers")

        def factory(session_id: str) -> TutorController:
            from agent.llm import build_intent_client
            from agent.render import build_renderer
            from agent.vision import VisionClient

            # Every controller borrows the same client and transcriber. The
            # runtime owns their lifecycle, so no close hook is passed. The
            # intent client and renderer are selected per settings and carry
            # this session id so the hosted route gets a stable attribution
            # header. The renderer is per controller because it holds that
            # header; the template renderer is stateless either way.
            return TutorController(
                session_id,
                lesson=lesson,
                store=store,
                vision=VisionClient(
                    settings, http=http, session_id=session_id
                ),
                intent=build_intent_client(
                    settings, http=http, session_id=session_id
                ),
                transcriber=transcriber,
                renderer=build_renderer(
                    settings, http=http, session_id=session_id
                ),
                # The configured flow; choice stays the safe default so an
                # unset environment behaves exactly as before.
                flow_mode=settings.tutor_flow,
            )

        return factory

    def close(self) -> None:
        """Close the runtime-owned HTTP client once and drop the transcriber."""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            http = self.http
            self.http = None
            self.transcriber = None
        if http is not None:
            try:
                http.close()
            except Exception:  # noqa: BLE001 - shutdown must not raise
                logger.warning("The shared HTTP client could not be closed")


def create_app(
    *,
    settings: Any = None,
    store: Any = None,
    lesson: Any = None,
    controller_factory: Callable[[str], Any] | None = None,
) -> FastAPI:
    """Build one app; values are resolved lazily and never at import time."""
    runtime = _Runtime(
        settings=settings,
        store=store,
        lesson=lesson,
        controller_factory=controller_factory,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            runtime.close()

    app = FastAPI(
        title="AI Math Tutor snapshot API", lifespan=lifespan
    )
    app.state.runtime = runtime
    app.state.registry = runtime.registry

    @app.exception_handler(ContractError)
    async def _contract_error(
        request: Request, error: ContractError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code, content=error_payload(error)
        )

    @app.exception_handler(RequestValidationError)
    async def _request_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        contract_error = ContractError(
            "invalid_request",
            "The request is missing or has an invalid field",
            400,
        )
        return JSONResponse(
            status_code=contract_error.status_code,
            content=error_payload(contract_error),
        )

    @app.post(SESSION_CREATE_PATH)
    async def create_session() -> dict[str, Any]:
        runtime.ensure()
        session_id = _new_session_id(runtime)
        runtime.store.create(session_id)
        controller = runtime.registry.controller_for(
            session_id, runtime.controller_factory
        )
        return _payload(controller.create_response())

    @app.post(SESSION_TURN_PATH)
    async def submit_turn(
        session_id: str, audio: UploadFile = File(...)
    ) -> dict[str, Any]:
        runtime.ensure()
        _require_session(runtime, session_id)
        content_type = audio.content_type
        data = await _read_bounded(
            audio,
            MAX_AUDIO_BYTES,
            "audio_too_long",
            f"audio must be at most {MAX_AUDIO_SECONDS} seconds",
            413,
        )
        controller = runtime.registry.controller_for(
            session_id, runtime.controller_factory
        )
        result = await runtime.registry.run(
            session_id, controller.handle_audio, data, content_type
        )
        return _payload(result)

    @app.post(SESSION_SNAPSHOT_PATH)
    async def submit_snapshot(
        session_id: str,
        image: UploadFile = File(...),
        purpose: str = Form(...),
        exercise_id: str | None = Form(default=None),
    ) -> dict[str, Any]:
        runtime.ensure()
        _require_session(runtime, session_id)
        validate_purpose(purpose)
        content_type = image.content_type
        data = await _read_bounded(
            image,
            MAX_IMAGE_BYTES,
            "payload_too_large",
            f"image must be at most {MAX_IMAGE_BYTES} bytes",
            413,
        )
        controller = runtime.registry.controller_for(
            session_id, runtime.controller_factory
        )
        result = await runtime.registry.run(
            session_id,
            controller.handle_snapshot,
            data,
            content_type,
            purpose,
            exercise_id,
        )
        return _payload(result)

    @app.delete(SESSION_END_PATH)
    async def end_session(session_id: str) -> dict[str, Any]:
        runtime.ensure()
        _require_session(runtime, session_id)
        controller = runtime.registry.controller_for(
            session_id, runtime.controller_factory
        )
        try:
            await runtime.registry.run(session_id, controller.end)
        finally:
            runtime.store.delete(session_id)
            runtime.registry.discard(session_id)
        return ended_payload(session_id)

    return app


def _new_session_id(runtime: _Runtime) -> str:
    while True:
        session_id = uuid4().hex
        if runtime.store.get(session_id) is None:
            return session_id


def _require_session(runtime: _Runtime, session_id: str) -> None:
    if runtime.store.get(session_id) is None:
        raise ContractError("invalid_session", "Session not found", 404)


async def _read_bounded(
    file: UploadFile,
    limit: int,
    code: str,
    message: str,
    status_code: int,
) -> bytes:
    try:
        data = await file.read(limit + 1)
    finally:
        await file.close()
    if len(data) > limit:
        raise ContractError(code, message, status_code)
    return data


def _payload(result: Any) -> Any:
    if isinstance(result, SessionResponse):
        return result.to_payload()
    return result


app = create_app()
