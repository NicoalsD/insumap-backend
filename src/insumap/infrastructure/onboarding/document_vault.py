"""Identity documents: keyed lookup hash and AES-256-GCM seal (class S).

The lookup hash uses the ``patient-document`` subkey of ``APP_HMAC_KEY``; the
seal uses the MFA encryption ring, the only AES-GCM key the settings define
(there is no ``FIELD_ENCRYPTION_KEY`` yet, see the report of this module).
The associated data binds each ciphertext to its patient row, as the dictionary
states (``clinic.patients.document|<patient_id>|<clinic_id>``).
"""

from __future__ import annotations

from typing import final, override
from uuid import UUID

from insumap.application.onboarding.ports import (
    KeyedDigest,
    PatientDocumentVaultPort,
    SealedDocument,
)
from insumap.domain.onboarding.vocabulary import DocumentType
from insumap.infrastructure.security.keys import KeyRing
from insumap.infrastructure.security.secret_cipher import AesGcmSecretCipher
from insumap.infrastructure.security.subkey_hasher import Subkey, SubkeyHasher
from insumap.shared.key_material import key_fingerprint

ASSOCIATED_DATA_PREFIX = "clinic.patients.document"
FIELD_SEPARATOR = "|"


@final
class PatientDocumentVault(PatientDocumentVaultPort):
    """The only class that sees a plain document number; it never returns one.

    Pattern: P06 Adapter (the port of the import over the security primitives)
    """

    def __init__(self, *, app_hmac_key: bytes, encryption: KeyRing) -> None:
        self._hasher = SubkeyHasher(app_hmac_key, subkey=Subkey.PATIENT_DOCUMENT)
        self._hash_key_id = key_fingerprint(app_hmac_key)
        self._cipher = AesGcmSecretCipher(encryption)

    @override
    def hash_document(
        self, *, clinic_id: UUID, document_type: DocumentType, document_number: str
    ) -> KeyedDigest:
        message = FIELD_SEPARATOR.join(
            (str(clinic_id), document_type.value, document_number)
        )
        return KeyedDigest(
            value=self._hasher.hexdigest(message), key_id=self._hash_key_id
        )

    @override
    def hash_key_id(self) -> str:
        return self._hash_key_id

    @override
    def seal_document(
        self, *, patient_id: UUID, clinic_id: UUID, document_number: str
    ) -> SealedDocument:

        associated = FIELD_SEPARATOR.join(
            (ASSOCIATED_DATA_PREFIX, str(patient_id), str(clinic_id))
        )
        sealed = self._cipher.encrypt(document_number, associated_data=associated)
        return SealedDocument(ciphertext=sealed.ciphertext, key_id=sealed.key_id)
