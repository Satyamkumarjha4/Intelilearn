"""Copy rows from the local docker Postgres to Supabase, insert-only.

The sync is safe to run on every start:
- It only inserts rows whose primary key is missing on the target. It never updates or deletes,
  so data created directly in Supabase is never overwritten.
- It walks models in dependency order (the same ordering `dumpdata` uses). Foreign keys and
  many-to-many links to models with natural keys, such as content types and permissions, are
  resolved by natural key on the target, because their ids differ between databases.
- Many-to-many links are copied only together with a newly inserted object.
- If a row clashes with a different row on a unique column (e.g. the same email under another id),
  it is skipped and reported as a conflict instead of aborting the sync.
- Afterwards it resets primary-key sequences on the target, so new rows don't collide with copied ids.
"""

import logging
from dataclasses import dataclass, field

from django.apps import apps
from django.core import serializers
from django.core.management.color import no_style
from django.db import IntegrityError, connections, transaction

logger = logging.getLogger(__name__)

# Created by `migrate` on the target, ephemeral, or tied to the ids of excluded models.
EXCLUDED = {"contenttypes.contenttype", "auth.permission", "sessions.session", "admin.logentry"}


@dataclass
class ModelResult:
    inserted: int = 0
    skipped: int = 0
    conflicts: int = 0


@dataclass
class SyncReport:
    models: dict[str, ModelResult] = field(default_factory=dict)

    @property
    def inserted(self) -> int:
        return sum(r.inserted for r in self.models.values())

    @property
    def conflicts(self) -> int:
        return sum(r.conflicts for r in self.models.values())


def _models_in_dependency_order() -> list:
    # Many-to-many links are not copied as separate tables: each object carries them and they are
    # saved with it (resolved by natural key where the related model has one, e.g. permissions).
    app_list = [(config, None) for config in apps.get_app_configs() if config.models_module is not None]
    ordered = serializers.sort_dependencies(app_list, allow_cycles=True)
    return [m for m in ordered if m._meta.label_lower not in EXCLUDED and m._meta.managed and not m._meta.proxy]


def _is_migrated(alias: str) -> bool:
    return "django_migrations" in connections[alias].introspection.table_names()


def sync_databases(source: str = "local", target: str = "default") -> SyncReport:
    report = SyncReport()
    if not _is_migrated(source):
        logger.info("sync: source database %r has no tables yet; nothing to copy", source)
        return report

    models = _models_in_dependency_order()
    deferred = []
    for model in models:
        label = model._meta.label
        result = report.models.setdefault(label, ModelResult())
        source_qs = model._default_manager.using(source).order_by("pk")
        if not source_qs.exists():
            continue

        existing = set(model._default_manager.using(target).values_list("pk", flat=True))
        payload = serializers.serialize("json", source_qs, use_natural_foreign_keys=True)
        for item in serializers.deserialize("json", payload, using=target, handle_forward_references=True):
            if item.object.pk in existing:
                result.skipped += 1
                continue
            try:
                with transaction.atomic(using=target):
                    item.save(using=target)
                result.inserted += 1
                if item.deferred_fields:
                    deferred.append(item)
            except IntegrityError as exc:
                result.conflicts += 1
                logger.warning("sync: %s pk=%s skipped (conflict: %s)", label, item.object.pk, exc)

    for item in deferred:
        item.save_deferred_fields(using=target)

    _reset_sequences(target, models)
    return report


def _reset_sequences(alias: str, models: list) -> None:
    connection = connections[alias]
    statements = connection.ops.sequence_reset_sql(no_style(), models)
    if statements:
        with connection.cursor() as cursor:
            for sql in statements:
                cursor.execute(sql)
