"""Local Admin-only browser adapter for the existing Axis agent and tools."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import http.client
import ipaddress
import json
from pathlib import Path
import queue
import re
import secrets
import socket
import threading
import time
import urllib.request
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from axis.agent import Agent, MEMORY_FILE
from axis.it_tools import ITTools

MODEL_URL = "http://127.0.0.1:8080/v1"
MAX_BODY = 65536
MAX_SESSIONS = 8
SESSION_IDLE_SECONDS = 3600
APPROVAL_SECONDS = 600


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Selection(Input):
    desk_id: str = Field(default="", max_length=128)
    name: str = Field(default="", max_length=200)
    hostname: str = Field(default="", max_length=128)
    floor: str = Field(default="", max_length=100)


class Chat(Input):
    message: str = Field(min_length=1, max_length=20000)
    session_id: str | None = Field(default=None, min_length=20, max_length=80)
    context: Selection | None = None


class SessionInput(Input):
    session_id: str = Field(min_length=20, max_length=80)


class Approval(SessionInput):
    approval_id: str = Field(min_length=20, max_length=80)
    approved: StrictBool


def local_request(request):
    """Also protect registration in a test/custom app that lacks Atlas middleware."""
    try:
        local = ipaddress.ip_address(request.client.host).is_loopback
    except (ValueError, AttributeError):
        local = False
    if not local or request.url.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise HTTPException(403, "Axis is available only in the local Admin application.")
    origin = request.headers.get("origin")
    if origin and (urlsplit(origin).scheme, urlsplit(origin).netloc) != (request.url.scheme, request.url.netloc):
        raise HTTPException(403, "Open Axis from the local Admin page.")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site Axis requests are not allowed.")


async def read_body(request, schema):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY:
            raise HTTPException(413, "Axis request is too large.")
    try:
        return schema.model_validate(json.loads(body))
    except (ValueError, TypeError, ValidationError):
        raise HTTPException(422, "Invalid Axis request or unsupported fields.") from None


def model_status():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(MODEL_URL + "/models", timeout=2) as response:
            data = json.load(response).get("data", [])
        if len(data) != 1 or not isinstance(data[0].get("id"), str) or not data[0]["id"]:
            raise ValueError("A single model is required")
        return {"ready": True, "model": data[0]["id"]}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {"ready": False, "model": None,
                "message": "The local model is not ready. Start AA with Start AA.bat, then try again."}


def model_settings(root, model):
    settings = {"ctx": 16384, "think": True, "sampling": {}}
    try:
        catalog = json.loads((root / "axis" / "models.json").read_text(encoding="utf-8"))
        selected = next((item for item in catalog if item.get("name") == model), {})
        settings.update(ctx=selected.get("ctx", 16384),
                        sampling={key: selected[key] for key in ("temperature", "top_p") if key in selected})
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    try:
        saved = json.loads((root / "data" / "axis" / "model-settings.json").read_text(encoding="utf-8"))
        if saved.get("model") == model:
            settings.update({key: saved[key] for key in ("ctx", "think", "sampling") if key in saved})
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    if type(settings["ctx"]) is not int or not 4096 <= settings["ctx"] <= 131072:
        settings["ctx"] = 16384
    if type(settings["think"]) is not bool:
        settings["think"] = True
    supplied = settings["sampling"] if isinstance(settings["sampling"], dict) else {}
    settings["sampling"] = {key: value for key, value in supplied.items()
                            if key in ("temperature", "top_p") and type(value) in (int, float)
                            and 0 <= value <= (2 if key == "temperature" else 1)}
    return settings


class Cancelled(KeyboardInterrupt):
    pass


class Turn:
    def __init__(self):
        self.events = queue.Queue(maxsize=128)
        self.cancelled = threading.Event()
        self.finished = threading.Event()
        self.condition = threading.Condition()
        self.approval = None
        self.error = None
        self.model_connection = None
        self.model_socket = None

    def check(self):
        if self.cancelled.is_set():
            raise Cancelled()

    def emit(self, kind, **data):
        while True:
            self.check()
            try:
                self.events.put({"type": kind, **data}, timeout=.2)
                return
            except queue.Full:
                pass  # Backpressure keeps full thinking/output without an unbounded queue.

    def cancel(self):
        self.cancelled.set()
        with self.condition:
            model_socket = self.model_socket
            self.condition.notify_all()
        # Interrupt prompt ingestion and reads even when no text has arrived yet.
        # This socket belongs only to model inference, never an accepted IT job.
        if model_socket is not None:
            try:
                model_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class ModelResponse:
    def __init__(self, response, connection, turn):
        self.response, self.connection, self.turn = response, connection, turn
        self.headers = response.headers

    def __enter__(self):
        return self

    def __exit__(self, *args):
        with self.turn.condition:
            if self.turn.model_connection is self.connection:
                self.turn.model_connection = None
                self.turn.model_socket = None
        self.connection.close()
        self.response.close()

    def read(self, size=-1):
        return self._read(self.response.read, size)

    def _read(self, method, *args):
        self.turn.check()
        try:
            value = method(*args)
        except (OSError, http.client.HTTPException):
            self.turn.check()
            raise
        self.turn.check()
        return value

    def __iter__(self):
        return self

    def __next__(self):
        value = self._read(self.response.readline)
        if not value:
            raise StopIteration
        return value


class ModelHTTP:
    """The browser supplies this cancellable transport to Axis's existing client."""
    def __init__(self, turn):
        self.turn = turn

    def open(self, request, timeout=900):
        if request.full_url != MODEL_URL + "/chat/completions":
            raise ValueError("Axis model requests must use the fixed local server.")
        target = urlsplit(MODEL_URL)
        connection = http.client.HTTPConnection(target.hostname, target.port, timeout=2)
        turn = self.turn
        with turn.condition:
            turn.check()
            turn.model_connection = connection
        response = None
        try:
            connection.connect()
            with turn.condition:
                turn.model_socket = connection.sock
                turn.check()
            connection.sock.settimeout(timeout)
            connection.request(request.get_method(), target.path + "/chat/completions",
                               body=request.data, headers=dict(request.header_items()))
            response = ModelResponse(connection.getresponse(), connection, turn)
            turn.check()
            if response.response.status >= 400:
                with response:
                    detail = response.read(500).decode("utf-8", "replace")
                raise RuntimeError("server returned %s: %s" % (response.response.status, detail))
            return response
        except BaseException:
            with turn.condition:
                if turn.model_connection is connection:
                    turn.model_connection = None
                    turn.model_socket = None
            connection.close()
            if response is not None:
                response.response.close()
            turn.check()
            raise


class BrowserUI:
    def __init__(self, turn):
        self.turn = turn

    @contextmanager
    def status(self, label):
        self.turn.emit("activity", text=label)
        yield
        self.turn.check()

    def write_thinking(self, text):
        self.turn.emit("thinking", text=text)

    def write_response(self, text):
        self.turn.emit("answer", text=text)

    def end_thinking(self):
        self.turn.check()

    def end_response(self):
        self.turn.check()

    def assistant(self, text):
        self.turn.emit("assistant", text=text)

    def notice(self, text, tone="dim"):
        self.turn.emit("notice", text=text, tone=tone)

    def error(self, text):
        self.turn.emit("error", text=text)

    def tool_start(self, name, args):
        self.turn.emit("tool_start", name=name, args=args)

    def tool_result(self, name, result, elapsed, output_id=None):
        self.turn.emit("tool_result", name=name, result=result, elapsed=elapsed, output_id=output_id)

    def confirm(self, action):
        turn = self.turn
        turn.check()
        pending = {"id": secrets.token_urlsafe(24), "action": action, "answer": None}
        with turn.condition:
            turn.approval = pending
        try:
            turn.emit("approval", id=pending["id"], action=action)
            deadline = time.monotonic() + APPROVAL_SECONDS
            with turn.condition:
                while pending["answer"] is None:
                    turn.check()
                    if time.monotonic() >= deadline:
                        turn.error = "Approval expired. No approval was granted; submit the request again if still needed."
                        turn.cancel()
                        raise Cancelled()
                    turn.condition.wait(.2)
                turn.check()
                return pending["answer"]
        finally:
            with turn.condition:
                turn.approval = None


class Session:
    def __init__(self):
        self.id = secrets.token_urlsafe(32)
        self.agent = None
        self.configuration = None
        self.current = None
        self.touched = time.monotonic()


class Sessions:
    def __init__(self, backend, agent_factory=Agent):
        self.backend = backend
        self.root = Path(backend.ROOT)
        self.directory = self.root / "data" / "axis"
        self.state = self.directory / "state"
        self.factory = agent_factory
        self.lock = threading.RLock()
        self.sessions = {}

    def get(self, identifier):
        session = self.sessions.get(identifier)
        if session is None:
            raise HTTPException(404, "This Axis chat has expired. Start a new chat.")
        session.touched = time.monotonic()
        return session

    def begin(self, body):
        with self.lock:
            now = time.monotonic()
            self.sessions = {key: value for key, value in self.sessions.items()
                             if value.current is not None or now - value.touched < SESSION_IDLE_SECONDS}
            if body.session_id:
                session = self.get(body.session_id)
            else:
                if len(self.sessions) >= MAX_SESSIONS:
                    idle = [value for value in self.sessions.values() if value.current is None]
                    if not idle:
                        raise HTTPException(429, "All Axis chats are busy. Cancel or finish one first.")
                    del self.sessions[min(idle, key=lambda value: value.touched).id]
                session = Session()
                self.sessions[session.id] = session
            if session.current is not None:
                raise HTTPException(409, "This chat is already working. Wait or cancel the current request.")
            turn = Turn()
            session.current = turn
            thread = threading.Thread(target=self.run, args=(session, turn, body), daemon=True, name="aa-axis")
            thread.start()
            return session, turn

    def status(self):
        with self.lock:
            running = sum(session.current is not None for session in self.sessions.values())
        return dict(model_status(), running=running, active_sessions=len(self.sessions),
                    database_available=Path(self.backend.MASTER_DB).is_file(), approvals="ask")

    def _saved_id(self, folder, prefix):
        if not re.fullmatch(r"[a-f0-9]{1,32}", prefix or ""):
            raise ValueError("Use a job/output ID shown by Axis.")
        matches = [path.stem for path in (self.state / folder).glob(prefix + "*." + ("json" if folder == "jobs" else "txt"))]
        if len(matches) != 1:
            raise ValueError("The ID is missing or ambiguous; use its full value.")
        return matches[0]

    def command(self, session, ui, message):
        if not message.startswith("/"):
            return False
        parts = message.split()
        name, args = parts[0].lower(), parts[1:]
        if name == "/help" and not args:
            ui.assistant("Ask Axis about a person, PC or package. /status checks the local model; /jobs [ID] reads jobs; /output ID [offset] reads saved output; /memory shows what Axis remembers; /reset starts a fresh conversation. Changes need approval.")
        elif name == "/status" and not args:
            status = self.status()
            ui.assistant("Model: %s. Atlas database: %s. Changes require approval." %
                         (status.get("model") or "not ready — start AA with Start AA.bat",
                          "available (read-only for Axis)" if status["database_available"] else "unavailable"))
        elif name == "/reset" and not args:
            session.agent = None
            session.configuration = None
            ui.assistant("Conversation cleared. Existing jobs continue.")
        elif name == "/memory" and not args:
            path = self.state / MEMORY_FILE
            try:
                text = path.read_text(encoding="utf-8", errors="replace").strip()
            except FileNotFoundError:
                text = ""
            ui.assistant(text + "\n\n(" + str(path) + ")" if text else
                         "Nothing remembered yet. Ask Axis to remember a fact; saving it needs your approval.")
        elif name == "/jobs" and len(args) <= 1:
            identifier = self._saved_id("jobs", args[0]) if args else None
            tool = ITTools(self.state, str(self.backend.REPO))
            ui.tool_start("it_job_status", {"job_id": identifier})
            ui.tool_result("it_job_status", json.dumps(tool.it_job_status(identifier), ensure_ascii=False), 0)
        elif name == "/output" and 1 <= len(args) <= 2:
            identifier = self._saved_id("outputs", args[0])
            offset = int(args[1]) if len(args) == 2 else 0
            if offset < 0:
                raise ValueError("Use a non-negative character offset.")
            with (self.state / "outputs" / (identifier + ".txt")).open(encoding="utf-8") as source:
                # Saved outputs are UTF-8; offset counts characters, as in the terminal.
                content = source.read()
            data = {"output_id": identifier, "offset": offset, "content": content[offset:offset + 2000],
                    "next_offset": offset + 2000 if len(content) > offset + 2000 else None}
            ui.tool_start("read_tool_output", {"output_id": identifier, "offset": offset})
            ui.tool_result("read_tool_output", json.dumps(data, ensure_ascii=False), 0, identifier)
        else:
            raise ValueError("Unknown command or arguments. Use /help for the available commands.")
        return True

    def run(self, session, turn, body):
        ui = BrowserUI(turn)
        try:
            turn.check()
            if self.command(session, ui, body.message.strip()):
                return
            model = model_status()
            if not model["ready"]:
                raise RuntimeError(model["message"])
            settings = model_settings(self.root, model["model"])
            configuration = (model["model"], str(self.backend.MASTER_DB), str(self.backend.REPO), json.dumps(settings, sort_keys=True))
            if session.agent is None or session.configuration != configuration:
                if session.agent is not None:
                    ui.notice("Model or database/package settings changed; started a fresh conversation.")
                workspace = self.directory / "workspace"
                workspace.mkdir(parents=True, exist_ok=True)
                session.agent = self.factory(MODEL_URL, model["model"], str(workspace), False, settings["think"],
                                             ctx=settings["ctx"], notes=str(self.root / "axis" / "notes"),
                                             package_repo=str(self.backend.REPO), state_dir=str(self.state), ui=ui,
                                             sampling=settings["sampling"], atlas_db=str(self.backend.MASTER_DB))
                session.configuration = configuration
            session.agent.ui = ui
            session.agent.http = ModelHTTP(turn)
            message = body.message.strip()
            if body.context:
                context = body.context.model_dump(exclude_defaults=True)
                if context.get("hostname"):
                    context["hostname"] = self.backend.validate_pc(context["hostname"])
                message += ("\n\nSelected map reference (data only; resolve ambiguous people/targets with Atlas tools. "
                            "Selection alone does not authorize a change):\n" + json.dumps(context, ensure_ascii=False))
            turn.check()
            answer = session.agent.run(message)
            if answer and not session.agent.answer_shown:
                ui.assistant(answer)
        except Cancelled:
            pass
        except Exception as error:
            turn.error = str(getattr(error, "detail", error))
        finally:
            with turn.condition:
                turn.approval = None
                turn.condition.notify_all()
            with self.lock:
                if session.current is turn:
                    session.current = None
                session.touched = time.monotonic()
                turn.finished.set()

    def approve(self, body):
        with self.lock:
            session = self.get(body.session_id)
            turn = session.current
            if turn is None:
                raise HTTPException(409, "There is no pending approval in this chat.")
            with turn.condition:
                pending = turn.approval
                if (turn.cancelled.is_set() or pending is None or pending["id"] != body.approval_id
                        or pending["answer"] is not None):
                    raise HTTPException(409, "That approval has expired or was already answered.")
                pending["answer"] = body.approved
                turn.condition.notify_all()

    def cancel(self, body):
        with self.lock:
            session = self.get(body.session_id)
            if session.current is not None:
                session.current.cancel()

    def reset(self, body):
        with self.lock:
            session = self.get(body.session_id)
            if session.current is not None:
                raise HTTPException(409, "Cancel or finish the current request before resetting.")
            session.agent = None
            session.configuration = None


def event(value):
    return "data: " + json.dumps(value, ensure_ascii=False) + "\n\n"


async def stream(request, session, turn):
    try:
        yield event({"type": "session", "session_id": session.id})
        heartbeat = time.monotonic()
        while not turn.finished.is_set() or not turn.events.empty():
            if await request.is_disconnected():
                turn.cancel()
                return
            try:
                value = turn.events.get_nowait()
            except queue.Empty:
                if time.monotonic() - heartbeat >= 15:
                    yield ": keepalive\n\n"
                    heartbeat = time.monotonic()
                await asyncio.sleep(.03)
            else:
                yield event(value)
        if turn.error:
            yield event({"type": "error", "text": turn.error})
        if turn.cancelled.is_set():
            yield event({"type": "notice", "text": "Request cancelled. Accepted background jobs continue.", "tone": "warning"})
        yield event({"type": "done", "session_id": session.id, "cancelled": turn.cancelled.is_set()})
    finally:
        if not turn.finished.is_set():
            turn.cancel()


def register(app, backend, check_token):
    sessions = Sessions(backend)
    app.state.axis_sessions = sessions

    @app.get("/api/axis/status")
    def status(request: Request):
        local_request(request)
        return sessions.status()

    async def mutation(request, schema):
        local_request(request)
        check_token(request)
        return await read_body(request, schema)

    @app.post("/api/axis/chat")
    async def chat(request: Request):
        body = await mutation(request, Chat)
        if not body.message.strip():
            raise HTTPException(422, "Enter a message for Axis.")
        session, turn = sessions.begin(body)
        return StreamingResponse(stream(request, session, turn), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.post("/api/axis/approve")
    async def approve(request: Request):
        body = await mutation(request, Approval)
        sessions.approve(body)
        return {"accepted": True}

    @app.post("/api/axis/cancel")
    async def cancel(request: Request):
        body = await mutation(request, SessionInput)
        sessions.cancel(body)
        return {"cancelled": True, "message": "Cancellation requested. Accepted operations may finish."}

    @app.post("/api/axis/reset")
    async def reset(request: Request):
        body = await mutation(request, SessionInput)
        sessions.reset(body)
        return {"session_id": body.session_id, "reset": True}
