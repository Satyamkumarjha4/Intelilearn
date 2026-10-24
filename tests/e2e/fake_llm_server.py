"""A fake OpenAI-compatible chat server for exercising the real stack without API keys or cost.

It answers `POST /v1/chat/completions` with canned, schema-valid output chosen by the name of the structured-output
schema in the request (a `response_format` json_schema, or the function of a forced tool call), so the real gateway,
the real LangChain client and the real graph run end to end. It also records nothing and never calls out.

    PYTHONPATH=/app:/tests python /tests/e2e/fake_llm_server.py      (port from FAKE_LLM_PORT, default 9000)

Used by `tests/e2e/test_fake_llm_gateway.py` and by the `fake-llm` compose service (`make fake-llm`) for walking the app
in a browser. Add a builder here whenever a phase adds an LLM output schema.
"""

import json
import os
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from support.quiz_data import make_prerequisites, make_questions

from graph.schemas.diagnostic import BANDS


class Canned:
    """Builds the payload for each schema the fake knows."""

    def __init__(self, request: dict):
        self.messages = request.get("messages", [])
        self.text = "\n".join(self._text(m) for m in self.messages)
        match = re.search(r'Topic: "([^"]+)"', self.text)
        self.topic = match.group(1) if match else "the topic"

    @staticmethod
    def _text(message: dict) -> str:
        content = message.get("content")
        if isinstance(content, list):
            return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
        return content or ""

    def for_schema(self, name: str) -> dict:
        try:
            return getattr(self, f"build_{name}")()
        except AttributeError:
            raise KeyError(name) from None

    # --- Stage A ---

    def build_DiagnosticBundle(self) -> dict:
        questions = make_questions()
        for number, q in enumerate(questions):
            q["concept"] = f"{self.topic}: idea {number + 1}"
            q["question"] = f"({BANDS[number // 2]}) Which statement about idea {number + 1} of {self.topic} is true?"
            right = number % 4
            wrong = [f"A false claim {c} about idea {number + 1}" for c in "XYZ"]
            q["options"] = wrong[:right] + [f"The true statement about idea {number + 1}"] + wrong[right:]
            q["correct_index"] = right
            q["explanation"] = f"Idea {number + 1} of {self.topic} works that way."
        prerequisites, prerequisite_questions = make_prerequisites()
        for number, (p, q) in enumerate(zip(prerequisites, prerequisite_questions, strict=True), start=1):
            p["name"] = q["prerequisite"] = f"Foundation {number} for {self.topic}"
            q["question"] = f"What is the key point of foundation {number}?"
            q["options"] = [f"Wrong {c} {number}" for c in "AB"] + [f"Right answer {number}", f"Wrong C {number}"]
            q["correct_index"] = 2
        return {
            "diagnostic": questions,
            "prerequisites": prerequisites,
            "prerequisite_questions": prerequisite_questions,
        }

    def build_QuizReview(self) -> dict:
        return {"issues": []}

    def build_LearnerAssessment(self) -> dict:
        return {
            "level": "intermediate",
            "known_concepts": [f"{self.topic}: idea 1"],
            "gaps": [f"{self.topic}: idea 9"],
            "prerequisites_to_cover": [],
            "start_point": f"The core mechanism of {self.topic}",
            "author_notes": "Short sentences and one worked example per idea.",
            "confidence": "medium",
        }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # quiet
        pass

    def do_GET(self):
        self._send(200, {"status": "ok"} if self.path == "/health" else {"data": []})

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if not self.path.endswith("/chat/completions"):
            return self._send(404, {"error": {"message": f"unknown path {self.path}"}})
        schema = self._schema_name(request)
        try:
            payload = Canned(request).for_schema(schema) if schema else None
        except KeyError:
            return self._send(400, {"error": {"message": f"The fake LLM has no canned output for {schema!r}."}})
        if payload is None:
            return self._send(400, {"error": {"message": "The fake LLM only serves structured output so far."}})
        text = json.dumps(payload)
        message = {"role": "assistant", "content": text}
        if request.get("tools"):
            call = {
                "id": f"call_{uuid.uuid4().hex[:8]}",
                "type": "function",
                "function": {"name": schema, "arguments": text},
            }
            message = {"role": "assistant", "content": None, "tool_calls": [call]}
        self._send(200, {
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}", "object": "chat.completion", "created": 0,
            "model": request.get("model", "fake-model"),
            "choices": [{"index": 0, "message": message,
                         "finish_reason": "tool_calls" if request.get("tools") else "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": len(text) // 4, "total_tokens": 100 + len(text) // 4},
        })  # fmt: skip

    @staticmethod
    def _schema_name(request: dict) -> str | None:
        schema = (request.get("response_format") or {}).get("json_schema", {}).get("name")
        if schema:
            return schema
        tools = request.get("tools") or []
        return tools[0]["function"]["name"] if tools else None

    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class FakeLLMServer:
    """The server in a background thread, for tests (port 0 picks a free one)."""

    def __init__(self, port: int = 0):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


if __name__ == "__main__":
    port = int(os.environ.get("FAKE_LLM_PORT", "9000"))
    print(f"fake LLM listening on :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()  # noqa: S104 (a dev-only container)
