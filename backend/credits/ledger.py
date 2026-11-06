"""The ledger: the one place credits move (docs/to_be_developed/credits-implementation-plan.md §6.1, T2 to T9).

Every movement runs in one transaction that first locks the learner's `Wallet` row, so a learner's movements never
interleave (lock order: the caller's lesson, if it holds one, then the wallet, then the buckets, in id order). Under the
lock it checks the idempotency key (a repeat returns the first result and changes nothing), writes off any bucket that
has lapsed, makes the movement, and appends a row whose `balance_after` is the running total. So the sum of a learner's
rows always equals the sum of their buckets, which `LedgerAudit` checks.

A hold takes its credits out of the buckets at once and remembers where from; a release puts each allocation back in
its source bucket, except that credits whose bucket has since lapsed go to a new refund bucket and credits whose bucket
a refund revoked are forfeited (T7). Nothing here knows what an action costs: the caller gives the amount.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q, Sum

from .clock import Clock, SystemClock
from .errors import (
    HoldConflict,
    HoldNotFound,
    HoldNotHeld,
    InsufficientBalance,
    InvalidAmount,
    KeyReused,
    ReasonRequired,
)
from .models import CreditBucket, CreditHold, CreditSettings, CreditTransaction, Wallet
from .planner import SpendBucket, SpendPlanner
from .plans.activator import PeriodActivator

Type = CreditTransaction.Type
Source = CreditBucket.Source


@dataclass(frozen=True)
class Movement:
    """A row of the ledger, and whether this call wrote it (False: the key had been used, nothing changed)."""

    transaction: CreditTransaction
    created: bool


@dataclass(frozen=True)
class HoldMovement:
    hold: CreditHold
    movement: Movement


@dataclass(frozen=True)
class Clawback:
    movement: Movement
    taken: int
    shortfall: int


class _Books:
    """One movement's view of a learner's ledger while the wallet is locked: the instant, the running balance, and the
    row written for a key that was already used, if any."""

    def __init__(self, user_id, now: datetime, balance: int, seen: CreditTransaction | None):
        self.user_id = user_id
        self.now = now
        self.balance = balance
        self.seen = seen
        self.expired: list[Movement] = []  # the buckets written off at the start of this movement
        self.periods_started = 0  # plan periods started and ended at the start of this movement
        self.periods_ended = 0

    def post(
        self, type: str, amount: int, key: str, *, action="", subject_kind="", subject_id=None, hold=None,
        allocations=None, meta=None,
    ) -> CreditTransaction:  # fmt: skip
        self.balance += amount
        return CreditTransaction.objects.create(
            user_id=self.user_id, type=type, amount=amount, balance_after=self.balance, action=action,
            subject_kind=subject_kind, subject_id=subject_id, hold=hold, bucket_allocations=allocations or [],
            idempotency_key=key, meta=meta or {}, created_at=self.now,
        )  # fmt: skip


class Ledger:
    SPENDS = (Type.DEBIT, Type.REPAIR)

    def __init__(
        self, clock: Clock | None = None, planner: SpendPlanner | None = None, periods: PeriodActivator | None = None
    ):
        self.clock = clock or SystemClock()
        self.planner = planner or SpendPlanner()
        self.periods = periods or PeriodActivator()

    # --- reading (no lock, no write) -----------------------------------------------------------------------------

    def balance(self, user) -> int:
        """What the learner can spend now: live buckets only. A lapsed bucket is left out even before its expire row is
        written, so the answer never waits for the hourly job."""
        buckets = CreditBucket.objects.filter(user_id=self._id(user), revoked_at__isnull=True, amount_remaining__gt=0)
        live = buckets.filter(Q(expires_at__isnull=True) | Q(expires_at__gt=self.clock.now()))
        return live.aggregate(total=Sum("amount_remaining"))["total"] or 0

    def reserved(self, user) -> int:
        """What is set aside for work that has not finished: the holds that are still held."""
        held = CreditHold.objects.filter(user_id=self._id(user), status=CreditHold.Status.HELD)
        return held.aggregate(total=Sum("amount"))["total"] or 0

    # --- movements -----------------------------------------------------------------------------------------------

    def grant(
        self, user, source: str, amount: int, key: str, *, expires_at: datetime | None = None, purchase_id=None,
        action: str = "", meta: dict | None = None,
    ) -> Movement:  # fmt: skip
        """Credits in: a new bucket and a `grant` row."""
        self._whole(amount, 1)
        if source not in Source.values:
            raise InvalidAmount(f"{source!r} is not a source of credits.")
        with self._locked(self._id(user), key) as books:
            if books.seen:
                return Movement(books.seen, False)
            made = self._new_bucket(books, source, amount, expires_at, purchase_id)
            row = books.post(
                Type.GRANT, amount, key, action=action, allocations=[self._part(made.pk, amount)],
                meta={"source": source, **(meta or {})},
            )  # fmt: skip
        return Movement(row, True)

    def place_hold(
        self, user, amount: int, action: str, key: str, *, subject_kind: str = "", subject_id=None,
        lines: list | None = None, exempt: bool = False, hold_id=None, orphan_after: timedelta | None = None,
    ) -> HoldMovement:  # fmt: skip
        """Reserve `amount` credits for one authorized action: they leave the buckets now. A hold of 0 is still a hold
        (the action is recorded); an exempt hold is always 0 and carries the lines it would have paid."""
        self._whole(amount, 0)
        if exempt and amount:
            raise InvalidAmount("An exempt hold costs nothing.")
        with self._locked(self._id(user), key) as books:
            if books.seen:
                if books.seen.hold_id is None or books.seen.type != Type.HOLD:
                    raise KeyReused(f"{key!r} was used for something other than a hold.")
                return HoldMovement(books.seen.hold, Movement(books.seen, False))
            if subject_id is not None and self._held_for(action, subject_id):
                raise HoldConflict(f"{action} is already held for {subject_id}.")
            allocations = self._take(books, amount)
            deadline = books.now + (orphan_after or timedelta(minutes=CreditSettings.load().orphan_minutes))
            hold = CreditHold.objects.create(
                id=hold_id or uuid.uuid4(), user_id=books.user_id, action=action, subject_kind=subject_kind,
                subject_id=subject_id, amount=amount, lines=lines or [], allocations=allocations, exempt=exempt,
                idempotency_key=key, orphan_deadline=deadline, created_at=books.now,
            )  # fmt: skip
            row = books.post(
                Type.HOLD, -amount, key, action=action, subject_kind=subject_kind, subject_id=subject_id, hold=hold,
                allocations=allocations,
            )  # fmt: skip
        return HoldMovement(hold, Movement(row, True))

    def commit(self, hold_id, key: str | None = None) -> Movement:
        """The work was done: settle the hold. The credits stay spent, so the row moves nothing."""
        return self._settle(hold_id, Type.COMMIT, key or f"commit:{hold_id}")

    def release(self, hold_id, key: str | None = None) -> Movement:
        """The work was not done: give the credits back, each to the bucket it came from (T7)."""
        return self._settle(hold_id, Type.RELEASE, key or f"release:{hold_id}")

    def debit(
        self, user, amount: int, action: str, key: str, *, type: str = Type.DEBIT, subject_kind: str = "",
        subject_id=None, meta: dict | None = None,
    ) -> Movement:  # fmt: skip
        """Credits out at once, with no hold (a streak repair, say)."""
        self._whole(amount, 1)
        if type not in self.SPENDS:
            raise InvalidAmount(f"{type!r} is not a kind of spend.")
        with self._locked(self._id(user), key) as books:
            if books.seen:
                return Movement(books.seen, False)
            allocations = self._take(books, amount)
            row = books.post(
                type, -amount, key, action=action, subject_kind=subject_kind, subject_id=subject_id,
                allocations=allocations, meta=meta,
            )  # fmt: skip
        return Movement(row, True)

    def activate_periods(self, user) -> tuple[int, int]:
        """Start the plan periods that are due and end those that are over, if there are any. -> how many of each. Every
        movement does this itself; this is for a read that should show the new week's credits and for the hourly job. It
        makes no wallet for a learner with nothing due."""
        uid = self._id(user)
        if not self.periods.has_due(uid, self.clock.now()):
            return 0, 0
        with self._locked(uid, None) as books:
            return books.periods_started, books.periods_ended

    def expire_due(self, user) -> list[Movement]:
        """Write off every bucket that has lapsed. Any other movement does this first, so the hourly job only makes the
        books say so sooner."""
        with self._locked(self._id(user), None) as books:
            return books.expired

    def adjust(self, user, amount: int, key: str, *, reason: str, actor: str) -> Movement:
        """An administrator gives or takes credits. A positive amount is a bucket that never expires; a negative one
        is taken in spend order and never exceeds the balance. The reason is required and kept on the row."""
        if not isinstance(reason, str) or not reason.strip():
            raise ReasonRequired("Say why the credits are being given or taken.")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount == 0:
            raise InvalidAmount(f"{amount!r} is not a whole, non-zero number of credits.")
        meta = {"reason": reason.strip(), "actor": actor}
        with self._locked(self._id(user), key) as books:
            if books.seen:
                return Movement(books.seen, False)
            if amount > 0:
                made = self._new_bucket(books, Source.ADMIN_GRANT, amount, None, None)
                allocations = [self._part(made.pk, amount)]
            else:
                allocations = self._take(books, -amount)
            row = books.post(Type.ADMIN_ADJUST, amount, key, allocations=allocations, meta=meta)
        return Movement(row, True)

    def forfeit(self, user, key: str, *, reason: str) -> Movement:
        """Write off everything the learner has left, for an account that is closed: every bucket is emptied and one
        row of
        `forfeit` takes the whole balance (0 if there is none, so the closing is on the record). Holds are not part
        of the
        balance and are not touched: release them first."""
        with self._locked(self._id(user), key) as books:
            if books.seen:
                return Movement(books.seen, False)
            taken = []
            for bucket in self._buckets(books):
                taken.append(self._part(bucket.pk, bucket.amount_remaining))
                bucket.amount_remaining = 0
                bucket.save(update_fields=["amount_remaining"])
            total = sum(part["amount"] for part in taken)
            row = books.post(Type.FORFEIT, -total, key, allocations=taken, meta={"reason": reason})
        return Movement(row, True)

    @contextmanager
    def exclusive(self, user) -> Iterator[None]:
        """Hold the learner's wallet lock across several steps, so a rule can be checked and then acted on with no other
        movement of theirs in between. Makes the wallet if it is new. Ledger calls inside nest in the same
        transaction."""
        with transaction.atomic():
            Wallet.objects.bulk_create(
                [Wallet(user_id=self._id(user), created_at=self.clock.now())], ignore_conflicts=True
            )
            Wallet.objects.select_for_update().get(pk=self._id(user))
            yield

    def claw_back(self, user, purchase_id, credits: int, key: str, *, meta: dict | None = None) -> Clawback:
        """A purchase was refunded: take back up to `credits` of its credits that are still unspent, never going below
        zero, and say how many could not be taken. A bucket of the purchase left empty is revoked, so a hold that is
        released later does not put the refunded credits back (T7, T32)."""
        self._whole(credits, 1)
        with self._locked(self._id(user), key) as books:
            if books.seen:
                seen = books.seen
                return Clawback(Movement(seen, False), -seen.amount, seen.meta.get("shortfall", 0))
            bought = list(
                CreditBucket.objects.select_for_update()
                .filter(user_id=books.user_id, purchase_id=purchase_id)
                .order_by("id")
            )
            plan = self.planner.plan(self._spendables(bought), credits, books.now)
            by_id = {b.pk: b for b in bought}
            for part in plan.allocations:
                by_id[part.bucket_id].amount_remaining -= part.amount
            for bucket in bought:  # one left empty, even by spending, must not be refilled by a late release
                if bucket.amount_remaining == 0 and bucket.revoked_at is None:
                    bucket.revoked_at = books.now
            for bucket in bought:
                bucket.save(update_fields=["amount_remaining", "revoked_at"])
            row = books.post(
                Type.REFUND, -plan.total, key, action="payment_refund",
                allocations=[self._part(a.bucket_id, a.amount) for a in plan.allocations],
                meta={"purchase": str(purchase_id), "requested": credits, "shortfall": plan.shortfall, **(meta or {})},
            )  # fmt: skip
        return Clawback(Movement(row, True), plan.total, plan.shortfall)

    # --- the pieces ----------------------------------------------------------------------------------------------

    @contextmanager
    def _locked(self, user_id, key: str | None) -> Iterator[_Books]:
        """One transaction with the learner's wallet locked. The wallet row is made if it is new (a concurrent first
        movement does nothing the second time), then locked; a key already used is found before anything is changed;
        otherwise lapsed buckets are written off."""
        with transaction.atomic():
            now = self.clock.now()
            Wallet.objects.bulk_create([Wallet(user_id=user_id, created_at=now)], ignore_conflicts=True)
            Wallet.objects.select_for_update().get(pk=user_id)
            seen = self._seen(user_id, key) if key else None
            books = _Books(user_id, now, self._running_balance(user_id), seen)
            if seen is None:
                # Start the plan periods that are due first, so their credits are spendable now, and so a period that
                # has already passed is granted and then written off by the expiry just below.
                self.periods.start_due(books, self._new_bucket)
                books.expired = self._expire_lapsed(books)
            yield books

    def _settle(self, hold_id, type: str, key: str) -> Movement:
        owner = CreditHold.objects.filter(pk=hold_id).values_list("user_id", flat=True).first()
        if owner is None:
            raise HoldNotFound(f"There is no hold {hold_id}.")
        with self._locked(owner, key) as books:
            if books.seen:
                return Movement(books.seen, False)
            hold = CreditHold.objects.select_for_update().get(pk=hold_id)
            if hold.status != CreditHold.Status.HELD:
                raise HoldNotHeld(f"Hold {hold_id} is already {hold.status}.")
            if type == Type.COMMIT:
                amount, parts, meta, status = 0, [], {}, CreditHold.Status.COMMITTED
            else:
                amount, parts, meta = self._give_back(books, hold)
                status = CreditHold.Status.RELEASED
            row = books.post(
                type, amount, key, action=hold.action, subject_kind=hold.subject_kind, subject_id=hold.subject_id,
                hold=hold, allocations=parts, meta=meta,
            )  # fmt: skip
            hold.status, hold.settled_at = status, books.now
            hold.save(update_fields=["status", "settled_at"])
        return Movement(row, True)

    def _give_back(self, books: _Books, hold: CreditHold) -> tuple[int, list, dict]:
        """Where a hold's credits go: back to the bucket they came from, unless it has lapsed (a refund bucket, so they
        are not lost to a late failure) or was revoked (forfeited). → the amount that returns, the parts, the meta."""
        ids = [part["bucket"] for part in hold.allocations]
        buckets = {str(b.pk): b for b in CreditBucket.objects.select_for_update().filter(pk__in=ids).order_by("id")}
        returned = pooled = forfeited = 0
        parts = []
        for part in hold.allocations:
            bucket, amount = buckets[part["bucket"]], part["amount"]
            if bucket.revoked_at is not None:
                forfeited, outcome = forfeited + amount, "forfeited"
            elif bucket.expires_at is not None and bucket.expires_at <= books.now:
                pooled, outcome = pooled + amount, "refund_bucket"
            else:
                bucket.amount_remaining += amount
                bucket.save(update_fields=["amount_remaining"])
                returned, outcome = returned + amount, "returned"
            parts.append({**part, "outcome": outcome})
        refund_id = None
        if pooled:
            days = CreditSettings.load().refund_valid_days
            refund_id = str(self._new_bucket(books, Source.REFUND, pooled, books.now + timedelta(days=days), None).pk)
        return returned + pooled, parts, {"forfeited": forfeited, "refund_bucket": refund_id}

    def _take(self, books: _Books, amount: int) -> list[dict]:
        """Take `amount` out of the buckets in spend order and say where from, or refuse if there is not enough."""
        buckets = list(self._buckets(books))
        plan = self.planner.plan(self._spendables(buckets), amount, books.now)
        if not plan.ok:
            raise InsufficientBalance(amount, plan.total)
        by_id = {b.pk: b for b in buckets}
        for part in plan.allocations:
            bucket = by_id[part.bucket_id]
            bucket.amount_remaining -= part.amount
            bucket.save(update_fields=["amount_remaining"])
        return [self._part(a.bucket_id, a.amount) for a in plan.allocations]

    def _expire_lapsed(self, books: _Books) -> list[Movement]:
        lapsed = self._buckets(books).filter(expires_at__lte=books.now).order_by("expires_at", "id")
        done = []
        for bucket in lapsed:
            left, bucket.amount_remaining = bucket.amount_remaining, 0
            bucket.save(update_fields=["amount_remaining"])
            row = books.post(
                Type.EXPIRE, -left, f"expire:{bucket.pk}", allocations=[self._part(bucket.pk, left)],
                meta={"source": bucket.source, "expired_at": bucket.expires_at.isoformat()},
            )  # fmt: skip
            done.append(Movement(row, True))
        return done

    @staticmethod
    def _buckets(books: _Books):
        """The learner's buckets that still hold credits, locked, in id order."""
        return (
            CreditBucket.objects.select_for_update()
            .filter(user_id=books.user_id, amount_remaining__gt=0)
            .order_by("id")
        )

    @staticmethod
    def _spendables(buckets) -> list[SpendBucket]:
        return [
            SpendBucket(b.pk, b.amount_remaining, b.expires_at, b.created_at, b.revoked_at is not None) for b in buckets
        ]

    @staticmethod
    def _new_bucket(books: _Books, source: str, amount: int, expires_at, purchase_id) -> CreditBucket:
        return CreditBucket.objects.create(
            user_id=books.user_id, source=source, amount_granted=amount, amount_remaining=amount,
            expires_at=expires_at, purchase_id=purchase_id, created_at=books.now,
        )  # fmt: skip

    @staticmethod
    def _seen(user_id, key: str) -> CreditTransaction | None:
        found = CreditTransaction.objects.filter(idempotency_key=key).first()
        if found is not None and found.user_id != user_id:
            raise KeyReused(f"{key!r} belongs to another learner's movement.")
        return found

    @staticmethod
    def _running_balance(user_id) -> int:
        last = CreditTransaction.objects.filter(user_id=user_id).order_by("-id").values_list("balance_after", flat=True)
        return last.first() or 0

    @staticmethod
    def _held_for(action: str, subject_id) -> bool:
        return CreditHold.objects.filter(action=action, subject_id=subject_id, status=CreditHold.Status.HELD).exists()

    @staticmethod
    def _part(bucket_id, amount: int) -> dict:
        return {"bucket": str(bucket_id), "amount": amount}

    @staticmethod
    def _whole(amount, minimum: int) -> None:
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < minimum:
            raise InvalidAmount(f"{amount!r} is not a whole number of credits of at least {minimum}.")

    @staticmethod
    def _id(user):
        return getattr(user, "pk", user)
