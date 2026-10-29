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
from typing import Literal
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from backend.inbox import clipboard_history

from axis.agent import Agent, MEMORY_FILE, change_memory, memory_entries, read_memory, without_entry, write_audit
from axis.it_tools import read_json, write_json
from axis.skill_library import SkillLibrary
from backend.axis_operations import AtlasOperations
from backend.axis_sources import AtlasSources, SourceUnavailable

MODEL_URL = "http://127.0.0.1:8080/v1"
MAX_BODY = 65536
MAX_SESSIONS = 8
SESSION_IDLE_SECONDS = 3600
APPROVAL_SECONDS = 600
MAX_TRANSCRIPT = 400     # displayed events kept per chat, to show it again after a reload or restart
MAX_STORED_TEXT = 20000  # characters of one saved event; /output ID still reads a full tool result
MAX_CHATS = 20           # chats saved in data/axis/chats
SESSION_ID = re.compile(r"[A-Za-z0-9_-]{20,80}")


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Selection(Input):
    desk_id: str = Field(default="", max_length=128)
    name: str = Field(default="", max_length=200)
    hostname: str = Field(default="", max_length=128)
    floor: str = Field(default="", max_length=100)


class Attachment(Input):
    """A Live Inbox message or clipboard capture, by ID: the server reads its text, the browser never sends it."""
    kind: Literal["inbox", "clipboard"]
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class Chat(Input):
    message: str = Field(min_length=1, max_length=20000)
    session_id: str | None = Field(default=None, min_length=20, max_length=80)
    context: Selection | None = None
    attachment: Attachment | None = None
    think: bool = False  # The chat starts with the model's reasoning hidden; the header toggle turns it on per turn.
    client: Literal["browser", "terminal"] = "browser"  # Where approvals are answered, for the audit log.


class SessionInput(Input):
    session_id: str = Field(min_length=20, max_length=80)


class Approval(SessionInput):
    approval_id: str = Field(min_length=20, max_length=80)
    approved: StrictBool


class Resume(Input):
    pass


class Forget(Input):
    entry: str = Field(min_length=1, max_length=8000)


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
    def __init__(self, record=None):
        self.record = record
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
                break
            except queue.Full:
                pass  # Backpressure keeps full thinking/output without an unbounded queue.
        return self.record({"type": kind, **data}) if self.record else None

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
    """Streams a turn to the browser panel or the AA terminal client; both answer approvals here."""

    def __init__(self, turn, interface="browser"):
        self.turn = turn
        self.interface = interface

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
        saved = None
        try:
            saved = turn.emit("approval", id=pending["id"], action=action)
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
                if saved is not None:
                    saved["decision"] = "approved" if pending["answer"] else "declined"
                return pending["answer"]
        finally:
            with turn.condition:
                turn.approval = None


class Session:
    def __init__(self, identifier=None, transcript=None, saved_messages=None, updated=None, saved_configuration=None,
                 saved_private=False):
        self.id = identifier or secrets.token_urlsafe(32)
        self.agent = None
        self.configuration = None
        self.current = None
        self.touched = time.monotonic()
        self.updated = updated or time.time()
        self.transcript = transcript or []
        self.saved_messages = saved_messages  # A saved chat's conversation, continued by its next agent
        self.saved_configuration = saved_configuration  # only under the same model, database and packages.
        self.saved_private = saved_private  # The saved conversation read Live Inbox or clipboard text.
        self.lock = threading.Lock()

    def record(self, event):
        """Keep what the panel displayed, merged as the panel merges streamed text, to show it again."""
        if event["type"] in ("activity", "session", "done"):
            return None
        event = {key: (value[:MAX_STORED_TEXT] + "\n[Shortened in the saved chat.]"
                       if isinstance(value, str) and len(value) > MAX_STORED_TEXT else value)
                 for key, value in event.items() if not (event["type"] == "approval" and key == "id")}
        with self.lock:
            self.updated = time.time()
            last = self.transcript[-1] if self.transcript else None
            if event["type"] in ("thinking", "answer") and last and last["type"] == event["type"]:
                last["text"] = (last["text"] + event["text"])[:MAX_STORED_TEXT]
                return last
            self.transcript.append(event)
            del self.transcript[:-MAX_TRANSCRIPT]
            return event

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.transcript))

    def messages(self):
        messages = getattr(self.agent, "messages", None) if self.agent is not None else self.saved_messages
        return messages if isinstance(messages, list) else None

    def private(self):
        return bool(getattr(self.agent, "private_context", False)) if self.agent is not None else bool(self.saved_private)

    def configuration_record(self):
        return list(self.configuration) if self.configuration is not None else self.saved_configuration


def same_configuration(saved, current):
    """Old chat records included thinking in the engine key; it is now a per-turn choice."""
    if not isinstance(saved, (list, tuple)) or len(saved) != 4 or list(saved[:3]) != list(current[:3]):
        return False
    try:
        old, new = json.loads(saved[3]), json.loads(current[3])
    except (ValueError, TypeError):
        return False
    if not isinstance(old, dict) or not isinstance(new, dict):
        return False
    old.pop('think', None)
    new.pop('think', None)
    return old == new


def restore_history(agent, saved):
    """Continue a saved chat under the new agent's current system prompt; reuse only well-formed history."""
    current = getattr(agent, "messages", None)
    if (isinstance(saved, list) and len(saved) > 1 and isinstance(current, list) and current
            and all(isinstance(message, dict) for message in saved + current[:1])
            and saved[0].get("role") == current[0].get("role") == "system"
            and all(message.get("role") in ("user", "assistant", "tool") for message in saved[1:])):
        agent.messages = current[:1] + saved[1:]
        repair = getattr(agent, "repair_pending_calls", None)
        if callable(repair):
            repair()


class Sessions:
    def __init__(self, backend, agent_factory=Agent, sources=None):
        self.backend = backend
        self.sources = sources
        self.root = Path(backend.ROOT)
        self.directory = self.root / "data" / "axis"
        self.state = self.directory / "state"
        self.chats = self.directory / "chats"
        self.factory = agent_factory
        self.lock = threading.RLock()
        self.sessions = {}

    def get(self, identifier):
        session = self.sessions.get(identifier) or self.load(identifier)
        if session is None:
            raise HTTPException(404, "This Axis chat has expired. Start a new chat.")
        session.touched = time.monotonic()
        return session

    def admit(self, session):
        """Keep at most MAX_SESSIONS in memory; an idle chat leaves memory but stays saved."""
        if session.id not in self.sessions and len(self.sessions) >= MAX_SESSIONS:
            idle = [value for value in self.sessions.values() if value.current is None]
            if not idle:
                raise HTTPException(429, "All Axis chats are busy. Cancel or finish one first.")
            del self.sessions[min(idle, key=lambda value: value.touched).id]
        self.sessions[session.id] = session
        return session

    def load(self, identifier):
        if not isinstance(identifier, str) or not SESSION_ID.fullmatch(identifier):
            return None
        try:
            data = read_json(self.chats / (identifier + ".json"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or data.get("id") != identifier or not isinstance(data.get("transcript"), list):
            return None
        return self.admit(Session(identifier, data["transcript"][-MAX_TRANSCRIPT:], data.get("messages"),
                                  data.get("updated") if isinstance(data.get("updated"), (int, float)) else None,
                                  data.get("configuration"), data.get("private") is True))

    def save(self, session):
        """Write the chat beside Axis's state; a failure never affects the conversation."""
        try:
            write_json(self.chats / (session.id + ".json"),
                       {"id": session.id, "updated": session.updated, "transcript": session.snapshot(),
                        "messages": session.messages(), "configuration": session.configuration_record(),
                        "private": session.private()})
            for old in sorted(self.chats.glob("*.json"), key=lambda path: path.stat().st_mtime)[:-MAX_CHATS]:
                old.unlink()
        except (OSError, TypeError, ValueError):
            pass

    def latest(self):
        """The most recent chat, from memory or disk, to show again when the panel opens."""
        with self.lock:
            candidates = [(value.updated, value.id) for value in self.sessions.values() if value.transcript]
            try:
                for path in self.chats.glob("*.json"):
                    candidates.append((path.stat().st_mtime, path.stem))
            except OSError:
                pass
            for _, identifier in sorted(candidates, reverse=True):
                session = self.sessions.get(identifier) or self.load(identifier)
                if session is not None:
                    session.touched = time.monotonic()
                    return session
            return None

    def begin(self, body, attached=None):
        """attached is attached(body.attachment), read beforehand off the event loop."""
        if body.attachment and body.message.strip().startswith("/"):
            raise HTTPException(422, "Commands cannot take an attachment.")
        attachment, prefetched = attached if attached is not None else self.attached(body.attachment)
        with self.lock:
            now = time.monotonic()
            self.sessions = {key: value for key, value in self.sessions.items()
                             if value.current is not None or now - value.touched < SESSION_IDLE_SECONDS}
            if body.session_id:
                session = self.get(body.session_id)
            else:
                session = self.admit(Session())
            if session.current is not None:
                raise HTTPException(409, "This chat is already working. Wait or cancel the current request.")
            turn = Turn(session.record)
            session.current = turn
            session.record({"type": "user", "text": body.message.strip(),
                            "context": body.context.model_dump(exclude_defaults=True) if body.context else None,
                            "attachment": attachment})
            thread = threading.Thread(target=self.run, args=(session, turn, body, prefetched), daemon=True, name="aa-axis")
            thread.start()
            return session, turn

    def status(self):
        with self.lock:
            running = sum(session.current is not None for session in self.sessions.values())
        return dict(model_status(), running=running, active_sessions=len(self.sessions),
                    database_available=Path(self.backend.MASTER_DB).is_file(), approvals="ask")

    def operations(self, confirm):
        """Axis's Windows tools on this Atlas's operations; earlier Axis job files stay readable."""
        # Earlier terminal jobs may also remain in axis\state from before the terminal used AA's chat.
        return AtlasOperations(self.backend, confirm, legacy_state=(self.state, self.root / "axis" / "state"),
                               outputs=self.state / "outputs")

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
            ui.assistant("Ask Axis about a person, PC or package. /status checks the local model; /jobs [ID] reads jobs; /output ID [offset] reads saved output; /memory shows what Axis remembers; /skills [name] lists skills or reads a guide; /reset starts a fresh conversation. Changes need approval.")
        elif name == "/status" and not args:
            status = self.status()
            ui.assistant("Model: %s. Atlas database: %s. Changes require approval." %
                         (status.get("model") or "not ready — start AA with Start AA.bat",
                          "available (read-only for Axis)" if status["database_available"] else "unavailable"))
        elif name == "/reset" and not args:
            self.clear(session)
            ui.assistant("Conversation cleared. Existing jobs continue.")
        elif name == "/memory" and not args:
            path = self.state / MEMORY_FILE
            try:
                text = path.read_text(encoding="utf-8", errors="replace").strip()
            except FileNotFoundError:
                text = ""
            ui.assistant(text + "\n\n(" + str(path) + ")" if text else
                         "Nothing remembered yet. Ask Axis to remember a fact; saving it needs your approval.")
        elif name == "/skills" and len(args) <= 1:
            library = SkillLibrary(self.directory / "skills")
            ui.assistant(library.display(args[0] if args else None))
        elif name == "/jobs" and len(args) <= 1:
            tool = self.operations(lambda action: False)  # Reading only; acknowledging needs the chat's approval.
            identifier = tool.find_job(args[0]) if args else None
            ui.tool_start("it_job_status", {"job_id": identifier})
            ui.tool_result("it_job_status", json.dumps(tool.it_job_status(identifier), ensure_ascii=False, default=str), 0)
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

    def attached(self, attachment):
        """Read an attached message or capture before the chat starts, so a missing one is refused.
        Not 404: the browser takes that to mean the chat itself expired."""
        if attachment is None:
            return None, ()
        if self.sources is None:
            raise HTTPException(503, "Live Inbox and clipboard are not available to Axis here.")
        try:
            label, name, args, result = self.sources.attachment(attachment.kind, attachment.id)
        except SourceUnavailable as error:
            raise HTTPException(503, str(error)) from None
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        return dict(attachment.model_dump(), label=label), [(name, args, result)]

    def run(self, session, turn, body, prefetched=()):
        ui = BrowserUI(turn, body.client)
        try:
            turn.check()
            if self.command(session, ui, body.message.strip()):
                return
            model = model_status()
            if not model["ready"]:
                raise RuntimeError(model["message"])
            settings = model_settings(self.root, model["model"])
            # Thinking is a per-turn toggle (set below), so it is kept out of the configuration key:
            # changing it must not start a fresh conversation.
            engine = {key: settings[key] for key in ("ctx", "sampling")}
            configuration = (model["model"], str(self.backend.MASTER_DB), str(self.backend.REPO), json.dumps(engine, sort_keys=True))
            if session.agent is None or session.configuration != configuration:
                if session.agent is not None:
                    ui.notice("Model or database/package settings changed; started a fresh conversation.")
                workspace = self.directory / "workspace"
                workspace.mkdir(parents=True, exist_ok=True)
                session.agent = self.factory(MODEL_URL, model["model"], str(workspace), False, False,
                                             ctx=settings["ctx"], notes=str(self.root / "axis" / "notes"),
                                             package_repo=str(self.backend.REPO), state_dir=str(self.state), ui=ui,
                                             sampling=settings["sampling"], atlas_db=str(self.backend.MASTER_DB),
                                             sources=self.sources, operations=self.operations,
                                             skills=str(self.directory / "skills"))
                session.configuration = configuration
                if session.saved_messages:
                    if same_configuration(session.saved_configuration, configuration):
                        restore_history(session.agent, session.saved_messages)
                        if session.saved_private:
                            session.agent.private_context = True
                    else:
                        ui.notice("Model or database/package settings changed since this chat; started a fresh conversation.")
                    session.saved_messages = session.saved_configuration = None
            session.agent.ui = ui
            session.agent.http = ModelHTTP(turn)
            session.agent.set_thinking(body.think)
            message = body.message.strip()
            if body.context:
                context = body.context.model_dump(exclude_defaults=True)
                if context.get("hostname"):
                    context["hostname"] = self.backend.validate_pc(context["hostname"])
                message += ("\n\nSelected map reference (data only; resolve ambiguous people/targets with Atlas tools. "
                            "Selection alone does not authorize a change):\n" + json.dumps(context, ensure_ascii=False))
            turn.check()
            answer = session.agent.run(message, prefetched=prefetched)
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
            if turn.error:
                session.record({"type": "error", "text": turn.error})
            if turn.cancelled.is_set():
                session.record({"type": "notice", "text": "Request cancelled. Accepted background jobs continue.", "tone": "warning"})
            self.save(session)
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

    def clear(self, session):
        session.agent = None
        session.configuration = None
        session.saved_messages = session.saved_configuration = None
        session.saved_private = False
        with session.lock:
            session.transcript = []
            session.updated = time.time()

    def reset(self, body):
        with self.lock:
            session = self.get(body.session_id)
            if session.current is not None:
                raise HTTPException(409, "Cancel or finish the current request before resetting.")
            self.clear(session)
        self.save(session)

    def resume(self):
        session = self.latest()
        if session is None:
            return {"session_id": None, "transcript": []}
        return {"session_id": session.id, "transcript": session.snapshot(), "busy": session.current is not None}

    def memory(self):
        path = self.state / MEMORY_FILE
        return {"path": str(path), "entries": memory_entries(read_memory(str(path)))}

    def forget(self, body):
        """The operator removes an entry directly from the panel; recorded like an approval when it happens."""
        entry = " ".join(body.entry.split())  # Hand-edited lines may be longer than remember allows.
        remove = without_entry(entry)

        def audited(text):
            change = remove(text)  # Raises when the entry is gone: nothing changes and nothing is recorded.
            write_audit(str(self.state), "browser", "approved (memory panel)", "forget: " + entry)
            return change
        try:
            message, _, _ = change_memory(str(self.state / MEMORY_FILE), audited)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        except OSError as error:
            raise HTTPException(503, "Memory could not be changed: %s" % error) from None
        return dict(self.memory(), message=message)


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
    sessions = Sessions(backend, sources=AtlasSources(app, clipboard=lambda: clipboard_history.history))
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
        if body.attachment and body.message.strip().startswith("/"):
            raise HTTPException(422, "Commands cannot take an attachment.")
        # Reading a message touches the mail queue, directory and package share: not on the event loop.
        attached = await asyncio.to_thread(sessions.attached, body.attachment) if body.attachment else None
        session, turn = sessions.begin(body, attached)
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

    @app.post("/api/axis/resume")
    async def resume(request: Request):
        await mutation(request, Resume)
        return sessions.resume()

    @app.post("/api/axis/memory")
    async def memory(request: Request):
        await mutation(request, Resume)
        return sessions.memory()

    @app.post("/api/axis/memory/forget")
    async def forget(request: Request):
        body = await mutation(request, Forget)
        return sessions.forget(body)
