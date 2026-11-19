"""Global test setup."""

import os

from tests.support.settings import TEST_DATABASE_URL, TEST_SECRET_ENV

# The API refuses to start without its secrets. Importing insumap.main builds the
# app from the environment, so give it a local database URL with no password.
os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
for _name, _value in TEST_SECRET_ENV.items():
    os.environ.setdefault(_name, _value)
os.environ.setdefault("ARGON2_MEMORY_KIB", "8")
os.environ.setdefault("ARGON2_TIME_COST", "1")
