"""Real threads for race tests: each job in its own thread (and so its own database connection), released together."""

import threading
from concurrent.futures import ThreadPoolExecutor

from django.db import connections


def together(jobs):
    """Run each job in its own thread, released at the same moment; → what each returned or raised, in job order.

    Use it in a test marked `django_db(transaction=True)`: the threads must see each other's committed rows."""
    barrier = threading.Barrier(len(jobs))

    def run(job):
        try:
            barrier.wait(timeout=30)
            return job()
        except Exception as exc:  # the test looks at what each thread got
            return exc
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        return list(pool.map(run, jobs))
