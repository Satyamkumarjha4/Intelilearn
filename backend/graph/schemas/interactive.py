"""Interactives: what each page gets (plan), the media agent's final answer, and generated widget code."""

import re
from typing import Literal

from pydantic import BaseModel, Field

InteractiveKind = Literal["interactive_graph", "simulation", "css_animation", "svg_diagram", "code_playground",
                          "image", "gif"]  # fmt: skip
MEDIA_KINDS = ("image", "gif")


class InteractiveSpec(BaseModel):
    id: str = Field(description='Unique id, letters/digits/underscores, e.g. "bs_stepper".')
    page: Literal["introduction", "core", "advanced"]
    anchor_section: str = Field(description="The id of the section it belongs to (from the page).")
    kind: InteractiveKind
    purpose: str = Field(description="The concept it teaches and why it teaches it better than text.")
    description: str = Field(description="What the learner sees and can do, concretely.")
    media_query: str = Field(default="", description="image/gif only: a short search query for the media library.")


class InteractivePlan(BaseModel):
    specs: list[InteractiveSpec]


class InteractiveComponent(BaseModel):
    spec_id: str
    component_name: str = Field(description="Exactly the name you were given.")
    tsx: str = Field(description="One self-contained function component, no imports or exports.")


def component_name(spec_id: str) -> str:
    return "Interactive_" + re.sub(r"\W", "_", spec_id)


class MediaCandidate(BaseModel):
    source: Literal["wikimedia", "openverse", "giphy"]
    file_url: str = Field(description="Direct URL of the image/GIF file, exactly as returned by a search tool.")
    page_url: str = Field(description="The file's page, exactly as returned by the search tool.")
    title: str
    license: str = Field(description="As returned by the search tool.")
    attribution: str = Field(description="Author/credit line, as returned by the search tool.")
    why: str = Field(description="Why this shows what the spec describes.")


class MediaSelection(BaseModel):
    """Arguments of the final submit_media tool call: the best candidates, best first."""

    candidates: list[MediaCandidate] = Field(description="1-3 candidates, best first. Empty if nothing fits.")


class MediaVerdict(BaseModel):
    approved: bool = Field(description="Does the image clearly show what the spec describes, and suit a lesson?")
    reason: str
    alt_text: str = Field(description="Concise alt text describing the image for a screen reader.")
    caption: str = Field(description="One-line caption for the lesson.")
