"""Sign in with an identity provider (phase 11.3): the port, the registry, Google and the test stand-in, the ID token
check, the signed cookies of the dance and the rule for linking to an account. Importing the package registers the
providers and the system checks."""

from . import checks, fake, google  # noqa: F401,E402  (each registers itself)
from .registry import IdentityProviders  # noqa: F401
