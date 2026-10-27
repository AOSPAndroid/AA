"""Axis in a terminal inside AA: a client of the running AA's Admin backend chat.

The browser panel and this window talk to one Axis. The local Admin backend runs the model
conversation, approvals, memory and tools, on Atlas's own operations. This window shows the
conversation as it streams and answers approval prompts. It changes nothing by itself.
"""
import argparse
import http.client
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

if __package__:
    from .launch_atlas import AtlasLaunchError, _active_port
    from .it_tools import windows_account
    from .terminal_ui import TerminalUI
else:
    from launch_atlas import AtlasLaunchError, _active_port
    from it_tools import windows_account
    from terminal_ui import TerminalUI

HERE = os.path.dirname(os.path.abspath(__file__))
AA_ROOT = os.path.dirname(HERE)
NOT_RUNNING = "AA is not running. Start it with Start AA.bat; this terminal then talks to the same Axis as the map."


class Unavailable(RuntimeError):
    pass


class AAChat:
    """One conversation with the Admin backend's Axis, shown in a TerminalUI."""

    def __init__(self, base, ui, opener=None):
        self.base = base.rstrip("/")
        self.ui = ui
        # The backend is local; never route it through a system proxy.
        self.http = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.session_id = None
        self._token = None
        self.think = True  # The terminal shows the model's reasoning by default; --no-think hides it.

    def request(self, method, path, body=None, timeout=30):
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
            headers["X-Atlas-Token"] = self.token()
        return self.http.open(urllib.request.Request(self.base + path, data=data, headers=headers, method=method),
                              timeout=timeout)

    def json(self, method, path, body=None):
        try:
            with self.request(method, path, body) as response:
                return json.loads(response.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as error:
            raise Unavailable(detail(error)) from None
        except (urllib.error.URLError, OSError) as error:
            raise Unavailable("Cannot reach AA at %s (%s). %s" % (self.base, error, NOT_RUNNING)) from None

    def token(self):
        if self._token is None:
            with self.http.open(urllib.request.Request(self.base + "/api/session"), timeout=10) as response:
                self._token = json.loads(response.read().decode("utf-8"))["token"]
        return self._token

    def status(self):
        return self.json("GET", "/api/axis/status")

    def resume(self):
        """Continue the latest chat, as the browser panel does when it opens."""
        data = self.json("POST", "/api/axis/resume", {})
        self.session_id = data.get("session_id")
        return data.get("transcript") or []

    def send(self, message):
        body = {"message": message, "client": "terminal", "think": self.think}
        if self.session_id:
            body["session_id"] = self.session_id
        try:
            response = self.request("POST", "/api/axis/chat", body, timeout=None)
        except urllib.error.HTTPError as error:
            if error.code == 404 and self.session_id:
                self.session_id = None  # The chat expired on the server; start a new one.
                self.ui.notice("That chat has expired; starting a new one.", "warning")
                return self.send(message)
            raise Unavailable(detail(error)) from None
        except (urllib.error.URLError, OSError) as error:
            raise Unavailable("Cannot reach AA at %s (%s). %s" % (self.base, error, NOT_RUNNING)) from None
        try:
            with response:
                for event in events(response):
                    if not self.show(event):
                        break
        except KeyboardInterrupt:
            self.cancel()
            self.ui.notice("Request cancelled. Accepted background jobs continue.", "warning")
        except (OSError, http.client.HTTPException) as error:
            raise Unavailable("The connection to AA ended during the answer (%s). Accepted jobs continue; "
                              "/jobs shows them." % error) from None
        finally:
            self.ui.end_thinking()
            self.ui.end_response()

    def cancel(self):
        if self.session_id:
            try:
                self.json("POST", "/api/axis/cancel", {"session_id": self.session_id})
            except Unavailable:
                pass

    def show(self, event):
        """Render one streamed event; False when the turn is over."""
        kind = event.get("type")
        ui = self.ui
        if kind == "session":
            self.session_id = event.get("session_id") or self.session_id
        elif kind == "thinking":
            ui.write_thinking(event.get("text", ""))
        elif kind == "answer":
            ui.write_response(event.get("text", ""))
        elif kind == "assistant":
            ui.assistant(event.get("text", ""))
        elif kind == "tool_start":
            ui.tool_start(event.get("name", ""), event.get("args"))
        elif kind == "tool_result":
            ui.tool_result(event.get("name", ""), event.get("result", ""), event.get("elapsed") or 0, event.get("output_id"))
        elif kind == "approval":
            approved = bool(ui.confirm(event.get("action", "")))
            try:
                self.json("POST", "/api/axis/approve", {"session_id": self.session_id, "approval_id": event.get("id"),
                                                        "approved": approved})
            except Unavailable as error:
                ui.error("The answer did not reach AA: %s" % error)
        elif kind == "notice":
            ui.notice(event.get("text", ""), event.get("tone") or "info")
        elif kind == "error":
            ui.error(event.get("text", ""))
        elif kind == "done":
            self.session_id = event.get("session_id") or self.session_id
            return False
        return True  # activity and unknown events change nothing on screen.

    def replay(self, transcript):
        """Show a resumed chat; saved approvals are history and cannot be answered again."""
        for event in transcript:
            kind = event.get("type")
            if kind == "user":
                self.ui.user(event.get("text", ""))
            elif kind == "approval":
                self.ui.notice("Approval (%s): %s" % (event.get("decision") or "not answered", event.get("action", "")), "dim")
            elif kind in ("thinking", "answer", "assistant", "tool_start", "tool_result", "notice", "error"):
                self.show(event)
        self.ui.end_thinking()
        self.ui.end_response()


def detail(error):
    try:
        message = json.loads(error.read().decode("utf-8")).get("detail")
    except (ValueError, AttributeError, OSError):
        message = None
    return "AA refused the request (%s): %s" % (error.code, message or error.reason)


def events(response):
    """Server-sent events from the chat stream: one JSON object per data line."""
    for raw in response:
        line = raw.decode("utf-8").rstrip("\r\n")
        if line.startswith("data: "):
            try:
                yield json.loads(line[6:])
            except ValueError:
                continue


def admin_base(root=AA_ROOT):
    """The running AA's local Admin address, after checking it is this folder's AA under this account."""
    try:
        port = _active_port(Path(root), windows_account())
    except AtlasLaunchError as error:
        raise Unavailable(str(error)) from None
    if port is None:
        raise Unavailable(NOT_RUNNING)
    return "http://127.0.0.1:%d" % port


def earlier_terminal_jobs(root=AA_ROOT):
    if __package__:
        from .agent import unresolved_jobs
    else:
        from agent import unresolved_jobs
    return unresolved_jobs(os.path.join(root, "axis", "state"))


def main(argv=None, ui=None, chat=None):
    p = argparse.ArgumentParser(description="Axis in a terminal, using the running AA.")
    p.add_argument("task", nargs="*", help="send one message and exit")
    p.add_argument("--resume", action="store_true", help="continue the latest chat (the one the map panel shows)")
    p.add_argument("--plain", action="store_true", help="plain output without colour or animation")
    p.add_argument("--compact", dest="verbose", action="store_false", default=True,
                   help="summarize tool results; thinking remains visible")
    p.add_argument("--no-think", dest="think", action="store_false", default=True,
                   help="hide the model's reasoning (faster, quieter)")
    a, ignored = p.parse_known_args(argv)
    ui = ui or TerminalUI(plain=a.plain, verbose=a.verbose)
    if ignored:
        ui.notice("Inside AA the model, database and package settings come from AA; ignored: %s" % " ".join(ignored), "dim")
    try:
        chat = chat or AAChat(admin_base(), ui)
        chat.think = a.think
        status = chat.status()
    except Unavailable as error:
        ui.error(str(error))
        return 1
    ui.notice("Axis in AA (%s) · model: %s. Changes need your approval; the map's chat panel shows the same Axis."
              % (chat.base, status.get("model") or "not ready"), "dim")
    legacy = earlier_terminal_jobs()
    if legacy:
        ui.notice("Earlier terminal jobs in axis\\state are unresolved: %s. Ask Axis about them with their job ID "
                  "before changing those PCs." % ", ".join(legacy), "warning")
    try:
        if a.resume:
            chat.replay(chat.resume())
        if a.task:
            chat.send(" ".join(a.task))
            return 0
        while True:
            try:
                message = ui.prompt().strip()
            except EOFError:
                return 0
            if not message:
                continue
            command = message.split()[0].lower()
            if command in ("/exit", "/quit"):
                return 0
            if command == "/clear":
                ui.clear()
                continue
            try:
                chat.send(message)
            except Unavailable as error:
                ui.error(str(error))  # One refused or interrupted message; the chat goes on.
    except Unavailable as error:
        ui.error(str(error))
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
