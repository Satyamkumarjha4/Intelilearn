"""A fake OpenAI-compatible chat server for exercising the real stack without API keys or cost.

It answers `POST /v1/chat/completions` with canned, schema-valid output chosen by the name of the structured-output
schema in the request (a `response_format` json_schema, or the function of a forced tool call), so the real gateway,
the real LangChain client and the real graph run end to end. It also records nothing and never calls out.

    PYTHONPATH=/app:/tests python /tests/e2e/fake_llm_server.py      (port from FAKE_LLM_PORT, default 9000)

It can also be told to fail (`/_control/...`, tests/e2e/fake_failures.py): a reply that is not JSON, one the validators
refuse, a timeout, a 429, a 401. That is how the audit exercises the fallback and refund paths.

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

try:
    from .canned_lesson import LessonCanned, canned_question
    from .fake_failures import FAILURES, FailureContext, FailurePlan, UnknownFailure
except ImportError:  # run as a script (python /tests/e2e/fake_llm_server.py)
    from canned_lesson import LessonCanned, canned_question
    from fake_failures import FAILURES, FailureContext, FailurePlan, UnknownFailure
from graph.schemas.diagnostic import BANDS


class Canned(LessonCanned):
    """Builds the payload for each schema the fake knows."""

    def __init__(self, request: dict):
        self.messages = request.get("messages", [])
        self.text = "\n".join(self._text(m) for m in self.messages)
        match = re.search(r'Topic: "([^"]+)"', self.text)
        self.topic = match.group(1) if match else "the topic"
        listed = re.search(r"must be covered: (\[.*?\])", self.text, re.S)
        self.concepts = json.loads(listed.group(1)) if listed else [self.topic]

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
            "level": "proficient",
            "known_concepts": [f"{self.topic}: idea 1"],
            "gaps": [f"{self.topic}: idea 9"],
            "prerequisites_to_cover": [],
            "start_point": f"The core mechanism of {self.topic}",
            "author_notes": "Short sentences and one worked example per idea.",
            "confidence": "medium",
        }

    def build_PrerequisiteList(self) -> dict:
        names = ["Counting and ordering", "Reading a simple list", "Comparing two values"]
        return {
            "prerequisites": [
                {"name": f"{name} for {self.topic}", "why_needed": f"{self.topic} relies on {name.lower()}."}
                for name in names
            ]
        }

    def build_TopicTraitsJudgement(self) -> dict:
        """A topic is calculation when it says so, and programming when it names code: enough for the wizard's rules."""
        topic = self.topic.lower()
        return {
            "quantitative": any(word in topic for word in ("math", "equation", "calcul", "physics", "arithmetic")),
            "programming": any(word in topic for word in ("python", "code", "program", "javascript")),
        }

    def build_MediaVerdict(self) -> dict:
        return {
            "approved": True,
            "reason": "The picture shows the process the spec asks for, clearly.",
            "alt_text": f"A labelled diagram that helps explain {self.topic}.",
            "caption": f"An illustration for {self.topic}.",
        }

    def build_TopicSuggestions(self) -> dict:
        """A translation request lists the topics to translate (JSON data): the same ones come back in the same order.
        A suggestion request describes the learner: six topics, named for the field of study when there is one."""
        listed = re.search(r"Topics to translate \(JSON data\):\n(\[.*\])", self.text, re.S)
        if listed:
            return {
                "topics": [
                    {
                        "title": t["title"],
                        "title_en": t["title_en"],
                        "subject": t["subject"],
                        "reason": t["reason"],
                    }
                    for t in json.loads(listed.group(1))
                ]
            }
        field = re.search(r'"field_of_study": "([^"]+)"', self.text)
        area = field.group(1) if field else "Science"
        return {
            "topics": [
                {
                    "title": f"{area}: first idea {number}",
                    "title_en": f"{area}: first idea {number}",
                    "subject": area,
                    "reason": "A good place to start.",
                }
                for number in range(1, 7)
            ]
        }

    # --- Mastery path ---

    def _concept_text(self, number: int) -> str:
        return self.concepts[number % len(self.concepts)]

    def build_CheatSheet(self) -> dict:
        def item(number: int, kind: str = "rule") -> dict:
            return {
                "label": f"{self._concept_text(number)} ({number})",
                "kind": kind,
                "content": f"Remember: {self._concept_text(number)} works like this in {self.topic}.",
                "formula": "T(n) = O(\\log n)" if kind == "formula" else "",
                "variables": [{"symbol": "n", "meaning": "size of the input"}] if kind == "formula" else [],
                "when_to_use": "Whenever the input is ordered.",
            }

        sections = [
            {"heading": "Key ideas", "items": [item(0, "formula"), item(1), item(2), item(3)]},
            {"heading": "Watch out for", "items": [item(4), item(5), item(6)]},
        ]
        return {
            "title": f"{self.topic}: cheat sheet",
            "summary": f"The essentials of {self.topic}.",
            "sections": sections,
        }

    def build_RevisionSheet(self) -> dict:
        subtopics = [
            {
                "title": self._concept_text(n),
                "summary": f"{self._concept_text(n)} is a central part of {self.topic}. " * 4
                + "Work through a small example before moving on, then explain it back in your own words.",
                "key_points": ["Know the definition.", "Know when it applies.", "Know the usual pitfall."],
                "worked_examples": [
                    {"problem": f"Apply {self._concept_text(n)} once.", "solution": "Step 1, then step 2."}
                ],
                "common_mistakes": ["Skipping the boundary case."],
            }
            for n in range(5)
        ]
        return {"title": f"{self.topic}: revision", "overview": f"Every part of {self.topic}.", "subtopics": subtopics,
                "final_tips": ["Explain each idea aloud.", "Redo the mistakes."]}  # fmt: skip

    def build_PracticeSheet(self) -> dict:
        kinds = ["mcq", "msq", "numerical", "short_answer"]
        levels = ["easy"] * 3 + ["basic"] * 3 + ["standard"] * 3 + ["difficult"] * 3 + ["expert"] * 3
        questions = [
            canned_question(
                kinds[(n - 1) % 4],
                n,
                levels[n - 1],
                self._concept_text(n),
                f"Practice {n}: {self._concept_text(n)} in {self.topic}?",
            )
            for n in range(1, 16)
        ]
        return {"title": f"{self.topic}: practice", "instructions": "Answer, then check.", "questions": questions}

    # --- Replies that fit the schema and that the real validators refuse (the `rejected` failure mode) ---

    def rejected(self, schema: str) -> dict:
        try:
            return getattr(self, f"rejected_{schema}")()
        except AttributeError:
            raise KeyError(schema) from None

    def rejected_DiagnosticBundle(self) -> dict:
        """The first question offers the same option twice: valid JSON, refused by `TextRules.option_problems`."""
        bundle = self.build_DiagnosticBundle()
        first = bundle["diagnostic"][0]
        right = first["correct_index"]
        first["options"][(right + 1) % len(first["options"])] = first["options"][right]
        return bundle


class FakeHTTPServer(ThreadingHTTPServer):
    """The HTTP server, carrying the failure plan its handlers consult."""

    def __init__(self, address, handler, failures: FailurePlan):
        super().__init__(address, handler)
        self.failures = failures


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # quiet
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            return self._send(200, {"status": "ok"})
        if path == "/_control/plan":
            return self._send(200, self.server.failures.snapshot())
        if path.endswith("api.php"):
            return self._send(200, self._wikimedia())
        if path.startswith("/media/"):
            return self._image(path.removeprefix("/media/"))
        self._send(200, {"data": []})

    def _wikimedia(self) -> dict:
        """What Wikimedia Commons' search API returns, with two openly licensed 'files' served by this server."""
        host = self.headers.get("Host", "fake-llm.lan:9000")
        pages = {
            str(n): {
                "title": f"File:Amoeba {n}.png",
                "imageinfo": [{
                    "url": f"http://{host}/media/amoeba{n}.png", "thumburl": f"http://{host}/media/amoeba{n}.png",
                    "descriptionurl": f"https://commons.example.org/wiki/File:Amoeba_{n}.png",
                    "thumbwidth": 400, "thumbheight": 300,
                    "extmetadata": {
                        "LicenseShortName": {"value": "CC BY-SA 4.0"},
                        "Artist": {"value": "Fake Photographer"},
                        "ImageDescription": {"value": "An amoeba dividing (generated test image)"},
                    },
                }],
            }
            for n in (1, 2)
        }  # fmt: skip
        return {"query": {"pages": pages}}

    def _image(self, name: str) -> None:
        from io import BytesIO

        from PIL import Image, ImageDraw

        image = Image.new("RGB", (400, 300), (200, 230, 210))
        draw = ImageDraw.Draw(image)
        draw.ellipse((100, 70, 300, 230), fill=(120, 180, 140), outline=(40, 90, 60), width=4)
        draw.ellipse((170, 120, 230, 180), fill=(60, 110, 80))
        buffer = BytesIO()
        image.save(buffer, "PNG")
        data = buffer.getvalue()
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}"
        if self.path.startswith("/_control/"):
            return self._control(raw)
        request = json.loads(raw)
        if not self.path.endswith("/chat/completions"):
            return self._send(404, {"error": {"message": f"unknown path {self.path}"}})
        schema = self._schema_name(request)
        if self._fails(request, schema or ("agent" if self._is_agent_request(request) else "text")):
            return
        if self._is_agent_request(request):
            return self._complete(request, self._agent_reply(request))
        if schema is None and not request.get("tools"):
            return self._complete_text(request)
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

    def _control(self, raw: bytes) -> None:
        """Rules for failing on cue (tests/e2e/fake_failures.py): add one, read the plan, forget them all."""
        plan: FailurePlan = self.server.failures
        action = self.path.removeprefix("/_control/")
        try:
            body = json.loads(raw)
            if action == "fail":
                plan.add(
                    body.get("mode", ""),
                    schema=body.get("schema", "*"),
                    times=body.get("times", 1),
                    delay_s=body.get("delay_s", 0),
                )
            elif action == "reset":
                plan.reset()
            else:
                return self._send(404, {"error": {"message": f"unknown control path {self.path}"}})
        except (UnknownFailure, json.JSONDecodeError, AttributeError) as problem:
            # a rule refused, bad JSON, or a body that is not an object (`.get` on a list)
            return self._send(400, {"error": {"message": str(problem)}})
        self._send(200, plan.snapshot())

    def _fails(self, request: dict, schema: str) -> bool:
        """Answer with the failure the plan holds for this call, if any. True when the call is over."""
        rule = self.server.failures.take(schema)
        if rule is None:
            return False
        context = FailureContext(request, schema, Canned(request), rule)
        reply = FAILURES[rule.mode].respond(context)
        if reply is None:  # the caller was left waiting; it has gone by now
            self.close_connection = True
        else:
            self._send(reply.status, reply.body, reply.headers)
        return True

    @staticmethod
    def _schema_name(request: dict) -> str | None:
        schema = (request.get("response_format") or {}).get("json_schema", {}).get("name")
        if schema:
            return schema
        choice = request.get("tool_choice")
        if isinstance(choice, dict):
            return choice["function"]["name"]
        tools = request.get("tools") or []
        return tools[0]["function"]["name"] if len(tools) == 1 else None

    @staticmethod
    def _is_agent_request(request: dict) -> bool:
        """The media agent: tools offered with no forced choice (a structured call forces one function)."""
        return bool(request.get("tools")) and not isinstance(request.get("tool_choice"), dict)

    @staticmethod
    def _agent_reply(request: dict) -> dict:
        """Search once, then submit the first result the search returned (or nothing if it found nothing)."""
        names = [t["function"]["name"] for t in request["tools"]]
        messages = request["messages"]
        last = messages[-1]
        if last.get("role") != "tool":
            search = next(n for n in names if n.startswith("search_"))
            return {"name": search, "args": {"query": "amoeba binary fission"}}
        try:
            found = json.loads(last["content"])
        except ValueError:
            found = []
        keep = [
            {"source": r["source"], "file_url": r["file_url"], "page_url": r["page_url"], "title": r["title"],
             "license": r["license"], "attribution": r["attribution"], "why": "It shows the process clearly."}
            for r in found[:1]
        ]  # fmt: skip
        return {"name": "submit_media", "args": {"candidates": keep}}

    def _complete_text(self, request: dict) -> None:
        try:
            text = Canned(request).for_text()
        except KeyError:
            return self._send(400, {"error": {"message": "The fake LLM has no canned text output for this prompt."}})
        self._send(200, {
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}", "object": "chat.completion", "created": 0,
            "model": request.get("model", "fake-model"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": len(text) // 4, "total_tokens": 100 + len(text) // 4},
        })  # fmt: skip

    def _complete(self, request: dict, call: dict) -> None:
        tool_call = {"id": f"call_{uuid.uuid4().hex[:8]}", "type": "function",
                     "function": {"name": call["name"], "arguments": json.dumps(call["args"])}}  # fmt: skip
        self._send(200, {
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}", "object": "chat.completion", "created": 0,
            "model": request.get("model", "fake-model"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": None, "tool_calls": [tool_call]},
                         "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        })  # fmt: skip

    def _send(self, status: int, body: dict, headers: dict[str, str] | None = None) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)


class FakeLLMServer:
    """The server in a background thread, for tests (port 0 picks a free one)."""

    def __init__(self, port: int = 0):
        self.failures = FailurePlan()
        self.httpd = FakeHTTPServer(("127.0.0.1", port), Handler, self.failures)
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
    FakeHTTPServer(("0.0.0.0", port), Handler, FailurePlan()).serve_forever()  # noqa: S104 (a dev-only container)
