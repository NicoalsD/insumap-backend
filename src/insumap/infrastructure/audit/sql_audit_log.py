"""``audit.audit_log`` through ``audit.append_audit_log(...)`` (RLS-5)."""

from __future__ import annotations

from typing import final, override

from sqlalchemy import text

from insumap.application.commands.auditing import AuditEntry, AuditLogPort
from insumap.infrastructure.persistence.transactions import CurrentSession

APPEND_AUDIT_LOG = text(
    "SELECT audit.append_audit_log("
    "p_action => :action, p_entity_type => :entity_type, "
    "p_entity_id => :entity_id, p_reason => :reason, "
    "p_changed_fields => CAST(:changed_fields AS varchar[]), "
    "p_request_id => :request_id, p_clinic_id => :clinic_id)"
)
"""Parameterized call of the signature of ``insumap-database``. The function takes
the actor (user, role and type) from the session that ``apply_context`` set, so
this adapter never passes it."""


@final
class SqlAuditLog(AuditLogPort):
    """Appends a row in the transaction of the command: same commit, same rollback.

    The trigger of the table computes the hash chain; this adapter never reads
    or writes ``chain_seq``, ``prev_hash`` or ``row_hash``. Rows carry
    identifiers and field names only.
    """

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def record(self, entry: AuditEntry) -> None:
        self._current.get().execute(
            APPEND_AUDIT_LOG,
            {
                "clinic_id": entry.clinic_id,
                "action": entry.action,
                "entity_type": entry.entity_type,
                "entity_id": entry.entity_id,
                "reason": entry.reason,
                "changed_fields": list(entry.changed_fields),
                "request_id": entry.request_id,
            },
        )
