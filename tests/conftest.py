"""Global test setup."""

import os

from tests.support.settings import TEST_DATABASE_URL

# The API refuses to start without its secrets. Importing insumap.main builds the
# app from the environment, so give it a local database URL with no password.
os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
