"""Media subgraph prompts: finding a real image or GIF, and checking it with a vision model."""

from langchain_core.messages import BaseMessage, HumanMessage

from .base import Prompt


class MediaAgentPrompt(Prompt):
    """Subject also carries `spec` and `tools_available` (the tool names the agent may call)."""

    def system(self, subject: dict) -> str:
        spec = subject["spec"]
        return f"""You find ONE real, openly licensed {spec["kind"]} for a lesson.

Search with the tools ({", ".join(subject["tools_available"])}), try different queries if the first results are poor, \
then call submit_media with 1-3 candidates, best first. Copy file_url, page_url, license and attribution EXACTLY \
as the search tool returned them. Only choose results that clearly show what the lesson needs, suit teaching, \
and are not diagrams full of tiny text. If nothing fits after a few searches, call submit_media with an empty \
list."""

    def user(self, subject: dict) -> str:
        spec = subject["spec"]
        return f"""Topic: "{subject["topic"]}"
What the lesson needs: {spec["description"]}
Purpose: {spec["purpose"]}
Suggested query: {spec.get("media_query") or spec["description"]}"""


class VerifyMediaPrompt(Prompt):
    """A single multimodal message. Subject also carries `spec`, `candidate`, `image_b64` and `mime`."""

    def messages(self, subject: dict, feedback: list[str] | None = None) -> list[BaseMessage]:
        image = {"type": "image", "base64": subject["image_b64"], "mime_type": subject["mime"]}
        return [HumanMessage(content=[{"type": "text", "text": self.user(subject)}, image])]

    def system(self, subject: dict) -> str:
        return ""

    def user(self, subject: dict) -> str:
        spec, candidate = subject["spec"], subject["candidate"]
        return f"""A lesson on "{subject["topic"]}" needs: {spec["description"]} (purpose: {spec["purpose"]}).
Candidate: "{candidate["title"]}" from {candidate["source"]}.
Does this image clearly show what is needed, and is it appropriate for teaching? Write alt text and a caption."""
