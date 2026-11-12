import { execSync } from "node:child_process";
import { fileURLToPath } from "node:url";

/**
 * Puts credits where a test needs them, the way the stack's own setup does (a Django shell in the backend container). The
 * credit screens have no way to make a bucket that is about to run out, or to leave a learner nearly empty, so a test seeds
 * it. Nothing here is a product feature: it runs the same `Ledger` an administrator's action does.
 *
 * `make e2e` passes the compose command it started the stack with in `E2E_COMPOSE`; run by hand it falls back to the
 * stack's default project and files.
 */
export class Seed {
  private static readonly REPO = fileURLToPath(new URL("../..", import.meta.url));
  private static readonly FALLBACK = "docker compose -p socra-e2e -f docker-compose.yml -f docker-compose.e2e.yml --profile e2e";

  /** Credits that run out in `days` days, of a source the notices know ("daily", "purchase", "weekly_streak"…). */
  static grantExpiring(email: string, credits: number, days: number, source = "daily"): void {
    Seed.run(`
from datetime import timedelta
from django.utils import timezone
from credits.ledger import Ledger
Ledger().grant(user, ${JSON.stringify(source)}, ${credits}, key, expires_at=timezone.now() + timedelta(days=${days}))
`, email);
  }

  /** Credits that never run out (an administrator's gift). */
  static give(email: string, credits: number): void {
    Seed.run(`Ledger().adjust(user, ${credits}, key, reason="e2e seed", actor="e2e")`, email, "from credits.ledger import Ledger");
  }

  /** Takes credits away until `keep` are left. */
  static leave(email: string, keep: number): void {
    Seed.run(`
ledger = Ledger()
extra = ledger.balance(user) - ${keep}
if extra > 0:
    ledger.adjust(user, -extra, key, reason="e2e seed", actor="e2e")
`, email, "from credits.ledger import Ledger");
  }

  /** An account from before verification existed (`legacy`: the migration's mark), made verified or, after
   *  `require_reverification`, asking for a code at its next password sign-in. */
  static legacyAccount(email: string, password: string, opts: { reverify: boolean }): void {
    const script = `
from django.core.management import call_command
from django.utils import timezone
from accounts.models import User
user = User.objects.create_user(${JSON.stringify(email)}, password=${JSON.stringify(password)}, name="Old Account",
    email_verified_at=timezone.now(), email_verification_source="legacy")
${opts.reverify ? 'call_command("require_reverification")' : ""}
`;
    const compose = process.env.E2E_COMPOSE || Seed.FALLBACK;
    execSync(`${compose} exec -T backend python manage.py shell`, { cwd: Seed.REPO, input: script, stdio: ["pipe", "pipe", "pipe"] });
  }

  /** Three placeholder testimonials (samples: unpublished, never shown), made by the command a developer runs. */
  static sampleTestimonials(): void {
    const compose = process.env.E2E_COMPOSE || Seed.FALLBACK;
    execSync(`${compose} exec -T backend python manage.py seed_sample_testimonials`, { cwd: Seed.REPO, stdio: ["pipe", "pipe", "pipe"] });
  }

  private static run(code: string, email: string, imports = ""): void {
    const script = `
import uuid
from accounts.models import User
${imports}
user = User.objects.get(email=${JSON.stringify(email)})
key = "e2e-seed-" + uuid.uuid4().hex
${code}
`;
    const compose = process.env.E2E_COMPOSE || Seed.FALLBACK;
    execSync(`${compose} exec -T backend python manage.py shell`, { cwd: Seed.REPO, input: script, stdio: ["pipe", "pipe", "pipe"] });
  }
}
