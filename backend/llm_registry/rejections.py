"""Keep what a model wrote when a validator refused it, on the `ModelCall` of the attempt that wrote it.

A refusal such as "options must all be different" says a quiz was refused, not what the model had written, so nobody
could tell a model's mistake from a rule that was too strict. The refused output answers that. It can hold what a
lesson was about, so it is for staff only (the console's run detail), is emptied after
`REJECTED_OUTPUT_RETENTION_DAYS` by the daily purge, and is deleted with the lesson or quiz when an account is erased
(the `ModelCall` rows go by lesson and quiz id). Writing it must never fail a lesson.
"""

import json
import logging
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from .models import ModelCall
from .redaction import REDACTOR, Redactor

logger = logging.getLogger(__name__)


class RejectedOutputs:
    MAX_CHARS = 20_000
    CUT = "… (cut)"

    def __init__(self, redactor: Redactor = REDACTOR):
        self._redactor = redactor

    def record(self, call_id: int | None, output: Any, problems: Iterable[str]) -> bool:
        """Store `output` and the validator's `problems` on call `call_id`. False when nothing was stored."""
        if call_id is None:
            return False
        try:
            stored = ModelCall.objects.filter(pk=call_id).update(
                rejected_output=self._text(output), rejection=self._redactor.redact("\n".join(problems))
            )
        except Exception:  # keeping the evidence must never break a generation run
            logger.exception("llm_registry: could not keep a refused output")
            return False
        return stored > 0

    def forget_before(self, cutoff: datetime) -> int:
        """Empty the refused output of the calls older than `cutoff` (the call rows stay: they are the usage log)."""
        return (
            ModelCall.objects.filter(created_at__lt=cutoff)
            .exclude(rejected_output="", rejection="")
            .update(rejected_output="", rejection="")
        )

    def _text(self, output: Any) -> str:
        text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, default=str, indent=1)
        text = self._redactor.redact(text)
        return text if len(text) <= self.MAX_CHARS else text[: self.MAX_CHARS] + self.CUT
