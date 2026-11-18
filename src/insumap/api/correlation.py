"""Names shared by the request id middleware and the error handlers."""

from typing import Final

REQUEST_ID_HEADER: Final = "X-Request-ID"
"""Header that carries the correlation id, in the request and the response."""

REQUEST_ID_STATE_KEY: Final = "request_id"
"""Key of the correlation id in ``request.state``."""
