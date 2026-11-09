from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response

from console.serializers_credits import ErasureInputSerializer, ErasurePreviewSerializer, ErasureResultSerializer
from console.services.erasure import LearnerErasure
from credits.erasure import AccountErasure

from .base import CONSOLE_TAG, ConsoleView


class LearnerErasureView(ConsoleView):
    #: Builds the erasure for a request (a test swaps in one without a checkpoint store).
    erasure_factory = staticmethod(lambda trail: AccountErasure(trail=trail))

    @extend_schema(
        tags=CONSOLE_TAG,
        summary="What erasing a learner would do",
        description=(
            "What would be deleted (lessons, quizzes, sign-ins) and what would stay without identity (the ledger, "
            "purchases and orders), the credits that would be written off, and `blocked` when the account cannot be "
            "erased from here (`cannot_erase_self`, `staff_account`, `already_erased`). Writes nothing."
        ),
        responses={200: ErasurePreviewSerializer},
    )
    def get(self, request, learner_id):
        return Response(ErasurePreviewSerializer(self.service(request).preview(learner_id)).data)

    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Erase a learner",
        description=(
            "Deletes everything of the learner's that is theirs and cannot be undone: their lessons, quizzes and "
            "checkpoints, streak, sign-ins (refresh tokens and sessions), the admin's log rows about the account, and "
            "the free text in the change log about them. The account row is anonymised in place (email, name, "
            "password and profile emptied, inactive), the unspent credits are written off, and the money records "
            "(ledger, purchases, orders) stay with no name or email. **`confirm_email` must be the account's own "
            "email**, in any case. Writes one `learner.erase` entry (counts and the learner's id, never a name or "
            "email) in the same transaction. `409` with a code for your own account, a staff account or one already "
            "erased; `400` for a wrong email."
        ),
        request=ErasureInputSerializer,
        responses={
            200: ErasureResultSerializer,
            409: OpenApiResponse(description="`cannot_erase_self`, `staff_account` or `already_erased`."),
        },
    )
    def delete(self, request, learner_id):
        data = ErasureInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        result = self.service(request).erase(learner_id, data.validated_data["confirm_email"], request.user)
        return Response(ErasureResultSerializer(result).data)

    def service(self, request) -> LearnerErasure:
        return LearnerErasure(self.audit, self.erasure_factory)
