"""Real mail providers that must never be refused as "disposable".

A blocklist is maintained by strangers: one mistaken line would stop every Gmail user from signing up. So the snapshot's
refresh drops these names, and a test proves the snapshot holds none of them (plan D8). The list is the major providers
and the common Indian mailbox providers; adding a name is always safe, removing one needs a reason."""


class MajorProviders:
    DOMAINS = frozenset(
        {
            # Google
            "gmail.com", "googlemail.com", "google.com",
            # Microsoft
            "outlook.com", "outlook.in", "outlook.co.uk", "hotmail.com", "hotmail.co.in", "hotmail.co.uk", "hotmail.in",
            "live.com", "live.in", "live.co.uk", "msn.com",
            # Yahoo
            "yahoo.com", "yahoo.co.in", "yahoo.in", "yahoo.co.uk", "ymail.com", "rocketmail.com",
            # Apple
            "icloud.com", "me.com", "mac.com",
            # Others in wide use
            "aol.com", "proton.me", "protonmail.com", "pm.me", "zoho.com", "zohomail.in", "gmx.com", "mail.com",
            "yandex.com", "fastmail.com", "tutanota.com",
            # India
            "rediffmail.com", "rediff.com", "sify.com", "in.com", "bsnl.in", "vsnl.com", "vsnl.net",
        }
    )  # fmt: skip
