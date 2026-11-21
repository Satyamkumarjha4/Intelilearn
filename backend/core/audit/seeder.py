"""`AuditSeeder`: makes the synthetic personas of the pre-launch audit, safely and repeatably.

`SeedGuard` refuses to run anywhere real: outside DEBUG, or with Supabase as the database, or with no password to
give the personas. Seeding twice changes nothing but the passwords (they are set again, so they always match the
file the audit keeps). The report names personas and addresses, never a password.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass, field

from django.conf import settings

from .accounts import PersonaAccounts, PersonaProfiles
from .personas import AuditPersonas, Persona, SeedWorld


class SeedRefused(Exception):
    """The seed will not run here; the message says why and never holds a secret."""


class SeedGuard:
    PASSWORD_ENV = "AUDIT_PERSONA_PASSWORD"
    MIN_PASSWORD_LENGTH = 12

    def password(self) -> str:
        """The shared persona password from the environment; raises `SeedRefused` anywhere the seed must not run."""
        if not settings.DEBUG:
            raise SeedRefused("audit_seed runs only with DJANGO_DEBUG=true: it makes accounts with a known password.")
        if getattr(settings, "USING_SUPABASE", False):
            raise SeedRefused("audit_seed will not write to Supabase: unset SUPABASE_DATABASE_URL for the audit stack.")
        password = os.environ.get(self.PASSWORD_ENV, "")
        if len(password) < self.MIN_PASSWORD_LENGTH:
            raise SeedRefused(f"Set {self.PASSWORD_ENV} (at least {self.MIN_PASSWORD_LENGTH} characters).")
        return password


@dataclass
class PersonaResult:
    persona: Persona
    created: bool
    applied: list[str] = field(default_factory=list)  # what this run did that was not already so


@dataclass
class SeedReport:
    results: list[PersonaResult] = field(default_factory=list)


class AuditSeeder:
    def __init__(
        self,
        world: SeedWorld,
        *,
        personas: list[Persona] | None = None,
        accounts: PersonaAccounts | None = None,
        profiles: PersonaProfiles | None = None,
        guard: SeedGuard | None = None,
    ):
        self.world = world
        self.personas = personas if personas is not None else AuditPersonas.all()
        self.accounts = accounts or PersonaAccounts()
        self.profiles = profiles or PersonaProfiles()
        self.guard = guard or SeedGuard()

    def seed(
        self,
        *,
        only: set[str] | None = None,
        skip: set[str] | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> SeedReport:
        """`only` limits the run to those slugs; `skip` leaves out a kind of step by class name (e.g. HaveHistory)."""
        password = self.guard.password()
        report = SeedReport()
        for persona in self.personas:
            if only and persona.slug not in only:
                continue
            if progress:
                progress(persona.slug)
            user, created = self.accounts.ensure(persona, password)
            self.profiles.apply(user, persona)
            result = PersonaResult(persona, created)
            for step in persona.steps:
                if skip and type(step).__name__ in skip:
                    continue
                if step.apply(user, self.world):
                    result.applied.append(step.label)
            report.results.append(result)
        return report
