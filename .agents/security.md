# Implementación de los controles de seguridad del backend

> Guía operativa de [Seguridad](../docs/Seguridad.md). Responde: cómo se implementa cada control en este repositorio, con esqueletos en Python 3.13, y qué prueba lo protege. La política y las cifras canónicas están en `docs/Seguridad.md`; esta guía no inventa valores: donde la política no fija una cifra, se marca "propuesto". Si esta guía y la política no coinciden, gana la política y se corrige esta guía. Los paquetes y los nombres siguen [`architecture.md`](architecture.md); los patrones (P09, P11, P13, P17, P18) están en [`design-patterns.md`](design-patterns.md).

Los números de sección de este archivo están enlazados desde `docs/Seguridad.md` (sección 2 para los valores por defecto, 5 para la rotación del refresh, 10 para la prueba de denegación por defecto y 19 para las pruebas) y entre sí (la 15 para las llaves y las columnas cifradas, la 20 para las diferencias con el código). No se renumeran.

## 1. Alcance y reglas que no se rompen

| Control | Sección | Capa | Paquete |
|---|---|---|---|
| Argon2id, política de contraseña, login genérico | 3 | `infrastructure`, `domain` | `infrastructure/security`, `domain/identity` |
| JWT de acceso | 4 | `infrastructure`, `api` | `infrastructure/security`, `api/security` |
| Refresh rotativo con detección de reutilización | 5 | `application`, `infrastructure` | `application/identity`, `infrastructure/persistence` |
| Cookie del refresh y CSRF | 6 | `api`, `application` | `api/security`, `application/identity` |
| MFA TOTP y códigos de respaldo | 7 | `infrastructure`, `application` | `infrastructure/security` |
| Códigos de activación | 8 | `domain`, `infrastructure` | `domain/identity`, `infrastructure/security` |
| Límites de tasa y bloqueos | 9 | `application`, `infrastructure` | `infrastructure/security` |
| Permisos y denegación por defecto | 10 | `application`, `api` | `application/common`, `api/security` |
| Contexto de la RLS | 11 | `infrastructure` | `infrastructure/persistence` |
| `PatientRecordAccessProxy` | 12 | `infrastructure`, `domain` | `infrastructure/access`, `domain/access` |
| Auditoría y eventos de seguridad | 13 | `infrastructure`, `application` | `infrastructure/access`, `application/commands` |
| Redacción de logs | 14 | `infrastructure` | `infrastructure/logging` |
| Llaves y columnas cifradas | 15 | `shared`, `infrastructure`, `application` | `shared/key_material`, `infrastructure/security` |
| Rotación con `*_PREVIOUS`, secretos y configuración | 16 | `shared`, `application`, `infrastructure` | `application/jobs`, `shared/config` |
| Cabeceras, CORS, hosts y tamaño de cuerpo | 17 | `api`, `infrastructure` | `api/middleware`, `api/body_limits` |
| Minimización y token de servicio hacia la IA | 18 | `domain`, `application`, `infrastructure` | `domain/ai`, `infrastructure/ai` |
| Pruebas de seguridad | 19 | `tests` | `tests/support`, `tests/unit`, `tests/api`, `tests/integration` |
| Diferencias con el código actual y pendientes | 20 | | |

Reglas transversales (de [`architecture.md`](architecture.md), sección 3, y de la política):

1. **Los valores salen de `Settings`.** Nada de `19456`, `15` ni `30` escritos en una clase de seguridad: cada parámetro de la sección 2 llega por un dataclass de configuración que arma `container.py`. El dominio y la aplicación no leen `Settings`.
2. **La hora llega por `Clock`.** Incluida la validación de `exp`, `nbf` e `iat` del JWT (sección 4): PyJWT lee el reloj del sistema, por eso se verifica la vigencia a mano con el `Clock` inyectado.
3. **Los secretos son `SecretStr`** y se leen solo en el punto de uso (`get_secret_value()`). Nunca en `repr`, logs, `detail` ni mensajes de excepción.
4. **Comparar secretos con `hmac.compare_digest`**, nunca con `==`.
5. **Lo que debe sobrevivir a un error va en una transacción propia** (`UnitOfWorkFactory.begin_independent()`): contadores de bloqueo, `login_attempts`, `security_events`, la fila `DENIED` de `data_access_log` y los contadores de tasa. La transacción de la petición se revierte cuando se propaga el error.
6. **Solo consultas parametrizadas** (`select()`, `update()`, `insert()`, `func.set_config()`); `text()` solo con una cadena literal y `:parámetros`.
7. **Una respuesta de error nunca distingue** correo inexistente de contraseña incorrecta, código vencido de usado, ni recurso ajeno de inexistente.

## 2. Parámetros y valores por defecto

Cada fila es un campo de `Settings` (`insumap/shared/config.py`) en minúsculas, con el nombre de la variable en mayúsculas. Los que tienen valor por defecto lo traen de `docs/Seguridad.md`; los marcados "propuesto" no los fija la política. Los secretos **no tienen valor por defecto**: si faltan, la API no arranca. `.env.example` lleva cada variable con su marcador `cambia-esto-...` o el valor por defecto, y [`configuration.md`](configuration.md) tabla 6.1 las repite en el mismo PR.

### 2.1 Contraseñas, bloqueos y sesiones

| Variable | Defecto | Notas |
|---|---|---|
| `ARGON2_MEMORY_KIB` | `19456` | Mínimo de OWASP; `Field(ge=...)` con la cota que fije la prueba de arranque |
| `ARGON2_TIME_COST` | `2` | |
| `ARGON2_PARALLELISM` | `1` | |
| `PASSWORD_HASH_MAX_CONCURRENCY` | `4` | Hashes simultáneos por proceso (19 MiB × 4 de pico) |
| `PASSWORD_HISTORY_SIZE` | `5` | |
| `LOGIN_PAIR_MAX_FAILURES` | `5` | Por pareja (correo, IP) |
| `LOGIN_FAILURE_WINDOW_MINUTES` | `15` | |
| `LOGIN_LOCK_BASE_MINUTES` | `15` | ×2 por nivel |
| `LOGIN_LOCK_MAX_HOURS` | `24` | Tope |
| `LOGIN_ACCOUNT_MAX_FAILURES` | `20` | Por correo, desde cualquier IP |
| `LOGIN_ACCOUNT_WINDOW_MINUTES` | `60` | |
| `LOGIN_ACCOUNT_LOCK_MINUTES` | `60` | |
| `JWT_ISSUER`, `JWT_AUDIENCE` | propuesto | La política exige el claim pero no el valor |
| `JWT_ACCESS_MINUTES` | `15` | |
| `JWT_LEEWAY_SECONDS` | `30` | `exp`, `nbf` e `iat` |
| `REFRESH_TOKEN_DAYS` | `30` | Pacientes: inactividad máxima de cada refresh |
| `REFRESH_FAMILY_MAX_DAYS` | `90` | Pacientes: vida absoluta de la familia |
| `REFRESH_TOKEN_STAFF_HOURS` | `12` | Personal: un turno; luego login con MFA |
| `REFRESH_COOKIE_SAMESITE` | `Strict` | Solo `Strict`, salvo la excepción de la política (sección 2.5) |
| `PERMISSION_CACHE_TTL_SECONDS` | `60` | |

### 2.2 Activación, restablecimiento y MFA

| Variable | Defecto | Notas |
|---|---|---|
| `ACTIVATION_CODE_TTL_HOURS` | `168` | 7 días |
| `ACTIVATION_MAX_ATTEMPTS` | `5` | Fallos de fecha de nacimiento con código válido |
| `ACTIVATION_SESSION_TTL_MINUTES` | `15` | |
| `EMAIL_VERIFICATION_TTL_HOURS` | `24` | |
| `PASSWORD_RESET_TTL_MINUTES` | `30` | |
| `MFA_TOTP_VALID_WINDOW` | `1` | ±1 paso |
| `MFA_CHALLENGE_TTL_SECONDS` | `300` | |
| `MFA_CHALLENGE_MAX_ATTEMPTS` | `5` | |
| `MFA_RECOVERY_CODE_COUNT` | `10` | |

### 2.3 Límites de tasa (sección 12 de la política)

| Variable | Defecto | Clave | Almacenamiento |
|---|---|---|---|
| `RATE_LIMIT_LOGIN_PER_IP_PER_MINUTE` | `20` | IP | PostgreSQL |
| `RATE_LIMIT_MFA_PER_IP_PER_MINUTE` | `20` | IP | PostgreSQL |
| `RATE_LIMIT_ACTIVATION_PER_IP_PER_MINUTE` | `10` | IP | PostgreSQL |
| `RATE_LIMIT_ACTIVATION_PER_IP_PER_HOUR` | `50` | IP | PostgreSQL |
| `RATE_LIMIT_RESET_REQUEST_PER_IP_PER_HOUR` | `5` | IP | PostgreSQL |
| `RATE_LIMIT_RESET_REQUEST_PER_ACCOUNT_PER_HOUR` | `3` | Correo | PostgreSQL |
| `RATE_LIMIT_RESET_COMPLETE_PER_IP_PER_MINUTE` | `10` | IP | PostgreSQL |
| `RATE_LIMIT_REFRESH_PER_USER_PER_MINUTE` | `30` | Usuario | PostgreSQL |
| `RATE_LIMIT_CREDENTIAL_ISSUE_PER_CLINIC_PER_HOUR` | `300` | Clínica | PostgreSQL |
| `RATE_LIMIT_CREDENTIAL_BATCH_PER_CLINIC_PER_HOUR` | `10` | Clínica | PostgreSQL |
| `RATE_LIMIT_IMPORT_PER_CLINIC_PER_HOUR` | `10` | Clínica | PostgreSQL |
| `RATE_LIMIT_ASSISTANT_PER_PATIENT_PER_HOUR` | `20` | Paciente | PostgreSQL |
| `RATE_LIMIT_ASSISTANT_PER_PATIENT_PER_DAY` | `100` | Paciente | PostgreSQL |
| `RATE_LIMIT_AI_SUMMARY_PER_DOCTOR_PER_HOUR` | `30` | Médico | PostgreSQL |
| `RATE_LIMIT_REPORTS_PER_USER_PER_HOUR` | `20` | Usuario | PostgreSQL |
| `RATE_LIMIT_RECORDS_PER_USER_PER_MINUTE` | `120` | Usuario | Memoria |
| `RATE_LIMIT_MESSAGES_PER_USER_PER_MINUTE` | `30` | Usuario | Memoria |
| `RATE_LIMIT_API_PER_USER_PER_MINUTE` | `300` | Usuario | Memoria |
| `RATE_LIMIT_PUBLIC_PER_IP_PER_MINUTE` | `60` | IP | Memoria |

### 2.4 Llaves y otros

| Variable | Secreta | Defecto | Notas |
|---|---|---|---|
| `JWT_SECRET`, `JWT_SECRET_PREVIOUS` | Sí | Ninguno | 32 bytes o más decodificados; la anterior es opcional y solo verifica |
| `FIELD_ENCRYPTION_KEY`, `FIELD_ENCRYPTION_KEY_PREVIOUS` | Sí | Ninguno | AES-256-GCM del documento |
| `MFA_ENCRYPTION_KEY`, `MFA_ENCRYPTION_KEY_PREVIOUS` | Sí | Ninguno | AES-256-GCM del secreto TOTP |
| `CODE_HMAC_KEY`, `CODE_HMAC_KEY_PREVIOUS` | Sí | Ninguno | Activación y códigos de respaldo |
| `LOOKUP_HMAC_KEY` | Sí | Ninguno | `document_hash`; sin `_PREVIOUS` (se recalcula con un job) |
| `APP_HMAC_KEY` | Sí | Ninguno | Subllaves HKDF `ip`, `subject-ref` y `cursor` |
| `AI_SERVICE_TOKEN` | Sí | Ninguno | Y `AI_SERVICE_TOKEN_PREVIOUS` en `insumap-ai` |
| `ALLOWED_HOSTS` | No | Ninguno | `TrustedHostMiddleware` |
| `LLM_REAL_DATA_ALLOWED` | No | `false` | |
| `PUSH_ENDPOINT_ALLOWED_HOSTS` | No | propuesto | Lista de la sección 13.4 de la política |
| `AI_ENABLED` | No | propuesto `true` | |

### 2.5 Cómo llegan al código

`Settings` tiene los campos planos de las tablas anteriores. `container.py` los convierte en dataclasses congeladas por área, y son estas las que reciben las clases de seguridad:

```python
# insumap/infrastructure/security/config.py
from dataclasses import dataclass
from datetime import timedelta

from insumap.shared.config import Settings


@dataclass(frozen=True, slots=True, kw_only=True)
class PasswordHashingConfig:
    memory_kib: int
    time_cost: int
    parallelism: int
    max_concurrency: int

    @classmethod
    def from_settings(cls, settings: Settings) -> PasswordHashingConfig:
        return cls(
            memory_kib=settings.argon2_memory_kib,
            time_cost=settings.argon2_time_cost,
            parallelism=settings.argon2_parallelism,
            max_concurrency=settings.password_hash_max_concurrency,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class JwtConfig:
    issuer: str
    audience: str
    access_ttl: timedelta
    leeway: timedelta

    @classmethod
    def from_settings(cls, settings: Settings) -> JwtConfig:
        return cls(
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            access_ttl=timedelta(minutes=settings.jwt_access_minutes),
            leeway=timedelta(seconds=settings.jwt_leeway_seconds),
        )
```

El perfil de pruebas usa parámetros bajos de Argon2 (por ejemplo `memory_kib` de un dígito de MiB) y **una sola** prueba verifica los de producción ([`testing-plan.md`](testing-plan.md), sección 4.2). Las pruebas arman `Settings` con `tests/support/settings.py::make_settings(**overrides)`; los secretos de prueba son constantes de `tests/support/`, nunca valores reales.

## 3. Argon2id, política de contraseña y login genérico

- **Dónde vive:** `Argon2PasswordHasher` en `insumap/infrastructure/security/password_hasher.py`; `PasswordPolicy` en `insumap/domain/identity/password_policy.py`; el puerto `PasswordHasher` en `insumap/application/identity/ports.py`.
- **Parámetros:** `m`, `t` y `p` de `PasswordHashingConfig`; sal de 16 bytes y hash de 32 bytes (valores de `argon2-cffi`, fijados explícitamente). Perfil `Type.ID`.
- **Concurrencia:** `PASSWORD_HASH_MAX_CONCURRENCY` hashes a la vez. Los endpoints son `def` síncronos y FastAPI ya los ejecuta en un hilo de trabajo (ADR-02), así que el límite es un `threading.BoundedSemaphore`, no un `anyio.CapacityLimiter` (ver sección 20).
- **Normalización:** NFKC antes de hashear y de verificar; la longitud (12 a 128 puntos de código, `FieldLimits.PASSWORD_MIN_LENGTH` y `PASSWORD_MAX_LENGTH`) se mide **después** de normalizar y **antes** de hashear.
- **Rehash:** al iniciar sesión, si `needs_rehash()` es verdadero se guarda un hash nuevo en la misma transacción.

```python
# insumap/application/identity/ports.py (fragmento)
from abc import ABC, abstractmethod


class PasswordHasher(ABC):
    @abstractmethod
    def hash(self, plain: str) -> str: ...

    @abstractmethod
    def verify(self, password_hash: str, plain: str) -> bool: ...

    @abstractmethod
    def needs_rehash(self, password_hash: str) -> bool: ...
```

```python
# insumap/infrastructure/security/password_hasher.py
import threading
import unicodedata
from typing import final, override

from argon2 import PasswordHasher as Argon2Hasher
from argon2 import Type
from argon2.exceptions import InvalidHashError, VerificationError

from insumap.application.identity.ports import PasswordHasher
from insumap.infrastructure.security.config import PasswordHashingConfig

SALT_BYTES = 16
HASH_BYTES = 32
NORMALIZATION_FORM = "NFKC"


def normalize_password(plain: str) -> str:
    return unicodedata.normalize(NORMALIZATION_FORM, plain)


@final
class Argon2PasswordHasher(PasswordHasher):
    """Argon2id with the parameters of the configuration; bounded concurrency."""

    def __init__(self, config: PasswordHashingConfig) -> None:
        self._hasher = Argon2Hasher(
            time_cost=config.time_cost,
            memory_cost=config.memory_kib,
            parallelism=config.parallelism,
            hash_len=HASH_BYTES,
            salt_len=SALT_BYTES,
            type=Type.ID,
        )
        self._slots = threading.BoundedSemaphore(config.max_concurrency)

    @override
    def hash(self, plain: str) -> str:
        with self._slots:
            return self._hasher.hash(normalize_password(plain))

    @override
    def verify(self, password_hash: str, plain: str) -> bool:
        with self._slots:
            try:
                return self._hasher.verify(password_hash, normalize_password(plain))
            except (VerificationError, InvalidHashError):
                return False

    @override
    def needs_rehash(self, password_hash: str) -> bool:
        return self._hasher.check_needs_rehash(password_hash)
```

`VerifyMismatchError` hereda de `VerificationError`, por eso un solo `except` cubre contraseña incorrecta y verificación fallida. Un hash malformado (`InvalidHashError`) también devuelve `False`: nunca lanza al llamador.

### 3.1 Política de contraseña (dominio puro)

Devuelve **todos** los códigos que incumple (van en `detail.errors[].code` bajo `VALIDATION_ERROR`, ver [`input-validation.md`](input-validation.md)). Los fragmentos de datos personales son de 4 caracteres o más; la lista de comunes (100.000 entradas, propuesta SecLists con licencia por verificar) se carga una vez al arrancar desde un archivo del paquete y se compara tras NFKC y `casefold()`.

```python
# insumap/domain/identity/password_policy.py
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import final

MIN_PERSONAL_FRAGMENT = 4


@dataclass(frozen=True, slots=True, kw_only=True)
class PersonalData:
    email_local_part: str
    given_name: str
    family_name: str
    document_number: str | None


@final
class PasswordPolicy:
    """Length and content rules; history is checked by the use case with the hasher."""

    def __init__(self, *, min_length: int, max_length: int, common_passwords: frozenset[str]) -> None:
        self._min = min_length
        self._max = max_length
        self._common = common_passwords

    def violations(self, candidate: str, personal: PersonalData) -> tuple[str, ...]:
        normalized = unicodedata.normalize("NFKC", candidate)
        found: list[str] = []
        if len(normalized) < self._min:
            found.append("PASSWORD_TOO_SHORT")
        if len(normalized) > self._max:
            found.append("PASSWORD_TOO_LONG")
        folded = normalized.casefold()
        if folded in self._common:
            found.append("PASSWORD_TOO_COMMON")
        if self._contains_personal_data(folded, personal):
            found.append("PASSWORD_CONTAINS_PERSONAL_DATA")
        return tuple(found)

    @staticmethod
    def _contains_personal_data(folded: str, personal: PersonalData) -> bool:
        sources: Iterable[str | None] = (
            personal.email_local_part,
            personal.given_name,
            personal.family_name,
            personal.document_number,
        )
        for source in sources:
            text = unicodedata.normalize("NFKC", source or "").casefold()
            for start in range(0, max(len(text) - MIN_PERSONAL_FRAGMENT + 1, 0)):
                if text[start : start + MIN_PERSONAL_FRAGMENT] in folded:
                    return True
        return False
```

`PASSWORD_REUSED` lo agrega el caso de uso: compara la contraseña nueva con los últimos `PASSWORD_HISTORY_SIZE` hashes de `iam.password_history` con `hasher.verify()`.

### 3.2 Login genérico, tiempo constante y bloqueo

Reglas del caso de uso `LoginUseCase.execute()` (política 2.2):

1. Normalizar el correo (NFKC, recortar, minúsculas). Si la contraseña mide más de `FieldLimits.PASSWORD_MAX_LENGTH`, `422` **antes** de hashear.
2. Consultar bloqueos (contadores por HMAC del correo normalizado, **exista o no la cuenta**). Bloqueado: `429 RATE_LIMITED` con `Retry-After`, **sin** verificar la contraseña.
3. Buscar la identidad con la función `SECURITY DEFINER` `iam.lookup_login_identity(email)` (antes de conocer la clínica).
4. **Exactamente un Argon2id por intento:** con identidad, se verifica contra su hash; sin identidad (o `IMPORTED`/`INVITED`, que no tienen contraseña), contra el hash señuelo (`DecoyPasswordHash`), calculado al arrancar con los mismos parámetros.
5. Fallo: registrar el intento en una transacción propia y responder `401 INVALID_CREDENTIALS` con el mismo cuerpo en todos los casos.
6. Solo con la contraseña correcta se informa `ACCOUNT_NOT_ACTIVE` o `CLINIC_SUSPENDED`.

```python
# insumap/application/identity/login.py (núcleo de la verificación; el resto orquesta puertos)
from dataclasses import dataclass
from typing import final

from insumap.application.identity.ports import PasswordHasher


@dataclass(frozen=True, slots=True, kw_only=True)
class LoginIdentity:
    user_id: str
    password_hash: str | None
    status: str


@final
class DecoyPasswordHash:
    """A real hash of a random password, computed at startup with the same parameters."""

    def __init__(self, hasher: PasswordHasher, random_password: str) -> None:
        self.value = hasher.hash(random_password)


@final
class PasswordVerifier:
    """Runs exactly one Argon2id verification per attempt, whether or not the account exists."""

    def __init__(self, hasher: PasswordHasher, decoy: DecoyPasswordHash) -> None:
        self._hasher = hasher
        self._decoy = decoy

    def check(self, identity: LoginIdentity | None, plain: str) -> bool:
        stored = identity.password_hash if identity and identity.password_hash else None
        matched = self._hasher.verify(stored or self._decoy.value, plain)
        return matched and stored is not None
```

**Pruebas (sección 19):** `test_password_hasher.py` (formato PHC con los parámetros de producción verificado una sola vez; rehash al cambiar parámetros; hash malformado devuelve `False`), `test_password_policy.py` (11 falla, 12 pasa, 129 falla; ancho completo equivale a ASCII; comunes; datos personales; todos los códigos juntos), `test_password_verifier.py` (un doble de `PasswordHasher` que cuenta llamadas: correo inexistente y contraseña incorrecta llaman a `verify` **una vez** y devuelven lo mismo) y la prueba de API de que ambos casos responden el mismo cuerpo.

**Antipatrones**
- `bcrypt` o `hashlib` para contraseñas; usar los parámetros por defecto de `argon2-cffi` (64 MiB y `p=4`).
- Calcular el hash en el *event loop* o sin cota de concurrencia.
- Devolver `ACCOUNT_NOT_ACTIVE` antes de verificar la contraseña.
- Saltarse Argon2id cuando el correo no existe: el tiempo delata la cuenta.

## 4. JWT de acceso

- **Dónde vive:** `JwtTokenService` en `insumap/infrastructure/security/jwt_service.py`; `CurrentActor` y el límite de la cabecera en `insumap/api/security.py` (hoy solo declara el esquema `bearerAuth`); la verificación contra la BD en `AuthenticateActorUseCase` (`application/identity`).
- **Algoritmo:** HS256 con `algorithms=["HS256"]` explícito: `none` y cualquier otro se rechazan. `kid` = huella de la llave (sección 15.2). La llave actual firma; la anterior (`JWT_SECRET_PREVIOUS`) solo verifica.
- **Vigencia con `Clock`:** PyJWT valida `exp`, `nbf` e `iat` con el reloj del sistema, que `ARCH-09` prohíbe usar fuera de `SystemClock`. Se le apagan esas tres verificaciones (`verify_exp`, `verify_nbf`, `verify_iat` en `False`) y se comprueban a mano con el `Clock` inyectado y la tolerancia `JWT_LEEWAY_SECONDS`. Así las pruebas avanzan el `FixedClock` en vez de dormir.
- **Claims obligatorios:** `iss`, `aud`, `sub`, `role`, `clinic_id`, `tv`, `sid`, `amr`, `jti`, `iat`, `nbf`, `exp` (`require` de PyJWT). Los permisos **no** van en el token.
- **Cabecera:** si `Authorization` mide más de `FieldLimits.AUTH_HEADER_MAX_BYTES` (propuesto, 2.048), se rechaza con `401` **antes** de decodificar.
- Todo fallo de token es `401 UNAUTHORIZED` con el mismo cuerpo (el código `UNAUTHENTICATED` actual del enum se discute en la sección 20).

```python
# insumap/application/identity/claims.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessClaims:
    user_id: UUID
    role: str
    clinic_id: UUID | None
    token_version: int
    session_id: UUID | None
    amr: tuple[str, ...]
    token_id: str


class AccessTokenDecoder(ABC):
    """Port: validates an access token and returns its claims; any failure is UNAUTHENTICATED."""

    @abstractmethod
    def decode(self, token: str) -> AccessClaims: ...
```

```python
# insumap/infrastructure/security/jwt_service.py
import uuid
from collections.abc import Mapping
from typing import Final, final, override

import jwt
from jwt import InvalidTokenError

from insumap.application.identity.claims import AccessClaims, AccessTokenDecoder
from insumap.infrastructure.security.config import JwtConfig
from insumap.infrastructure.security.keys import KeyRing
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.time import Clock

ALGORITHM: Final = "HS256"
REQUIRED_CLAIMS: Final = (
    "iss", "aud", "sub", "role", "clinic_id", "tv", "sid", "amr", "jti", "iat", "nbf", "exp",
)  # fmt: skip
NO_TIME_VERIFICATION: Final = {"verify_exp": False, "verify_nbf": False, "verify_iat": False}


def _unauthorized() -> InsumapError:
    return InsumapError(ErrorCode.UNAUTHENTICATED)


@final
class JwtTokenService(AccessTokenDecoder):
    def __init__(self, *, keys: KeyRing, config: JwtConfig, clock: Clock) -> None:
        self._keys = keys
        self._config = config
        self._clock = clock

    def issue(
        self,
        *,
        user_id: uuid.UUID,
        role: str,
        clinic_id: uuid.UUID | None,
        token_version: int,
        session_id: uuid.UUID | None,
        amr: tuple[str, ...],
        token_id: str,
    ) -> str:
        now = self._clock.now()
        claims: dict[str, object] = {
            "iss": self._config.issuer,
            "aud": self._config.audience,
            "sub": str(user_id),
            "role": role,
            "clinic_id": str(clinic_id) if clinic_id else None,
            "tv": token_version,
            "sid": str(session_id) if session_id else None,
            "amr": list(amr),
            "jti": token_id,
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int((now + self._config.access_ttl).timestamp()),
        }
        return jwt.encode(
            claims, self._keys.current_key(), algorithm=ALGORITHM,
            headers={"kid": self._keys.current_key_id},
        )  # fmt: skip

    @override
    def decode(self, token: str) -> AccessClaims:
        try:
            header = jwt.get_unverified_header(token)
            key = self._keys.verification_key(header.get("kid"))
            payload = jwt.decode(
                token,
                key,
                algorithms=[ALGORITHM],
                issuer=self._config.issuer,
                audience=self._config.audience,
                options={"require": list(REQUIRED_CLAIMS), **NO_TIME_VERIFICATION},
            )
            self._check_times(payload)
            return self._claims(payload)
        except (InvalidTokenError, KeyError, ValueError, TypeError):
            raise _unauthorized() from None

    def _check_times(self, payload: Mapping[str, object]) -> None:
        now = self._clock.now().timestamp()
        leeway = self._config.leeway.total_seconds()
        exp, nbf, iat = (_number(payload[name]) for name in ("exp", "nbf", "iat"))
        if now - leeway >= exp or nbf - leeway > now or iat - leeway > now:
            raise _unauthorized()

    @staticmethod
    def _claims(payload: Mapping[str, object]) -> AccessClaims:
        clinic = payload["clinic_id"]
        session = payload["sid"]
        amr = payload["amr"]
        if not isinstance(amr, list):
            raise TypeError("amr must be a list")
        return AccessClaims(
            user_id=uuid.UUID(str(payload["sub"])),
            role=str(payload["role"]),
            clinic_id=uuid.UUID(str(clinic)) if clinic else None,
            token_version=int(str(payload["tv"])),
            session_id=uuid.UUID(str(session)) if session else None,
            amr=tuple(str(item) for item in amr),
            token_id=str(payload["jti"]),
        )


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("time claims must be numbers")
    return float(value)
```

`KeyRing` está en la sección 15.2 y expone `current_key()`, `current_key_id` y `verification_key(kid)`; un `kid` desconocido lanza `KeyError` (se vuelve `401`).

### 4.1 Verificación por petición y MFA

`CurrentActor` (único uso de `Depends` junto con la paginación) hace tres cosas, en este orden:

1. Lee `Authorization: Bearer`, rechaza la cabecera larga y llama a `JwtTokenService.decode()`.
2. Llama a `AuthenticateActorUseCase.execute(claims)`, que **dentro de la transacción de la petición** compara con la BD: `iam.users.status = 'ACTIVE'` (o `is_active` para el personal), `token_version == tv` y clínica activa. Falla con `401 SESSION_REVOKED` o `403 CLINIC_SUSPENDED`. Carga los permisos del rol (sección 10) y arma el `Actor`.
3. Si el rol es de personal y `"otp"` no está en `amr`, solo deja pasar a las rutas de enrolamiento, `GET /auth/current-user` y `/auth/logout`: `403 MFA_REQUIRED` en el resto.

El paso 3 se resuelve con **tres** dependencias de actor, no con una lista de rutas dentro del middleware: `CurrentActor` (sesión completa; rechaza `MFA_REQUIRED`), `EnrollmentActor` (acepta el token de enrolamiento) y `AnySessionActor` (`/auth/current-user` y logout). Una ruta nueva usa `CurrentActor` por defecto, así que la denegación también es el valor por defecto del MFA.

`api` no importa `infrastructure` (`ARCH-05`): `CurrentActor` recibe un puerto de `application` (`ActorAuthenticator`) que el contenedor arma con `JwtTokenService` y `AuthenticateActorUseCase`.

```python
# insumap/api/security.py
from collections.abc import Callable
from typing import Annotated, Final

from fastapi import Depends, Request

from insumap.application.common.actor import Actor
from insumap.application.identity.authenticate import ActorAuthenticator, SessionScope
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.field_limits import FieldLimits

BEARER_PREFIX: Final = "bearer "


def _bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if len(header.encode()) > FieldLimits.AUTH_HEADER_MAX_BYTES:
        raise InsumapError(ErrorCode.UNAUTHENTICATED)
    if not header.lower().startswith(BEARER_PREFIX):
        raise InsumapError(ErrorCode.UNAUTHENTICATED)
    return header[len(BEARER_PREFIX) :].strip()


def _actor_dependency(scope: SessionScope) -> Callable[[Request], Actor]:
    def dependency(request: Request) -> Actor:
        authenticator: ActorAuthenticator = request.app.state.actor_authenticator
        return authenticator.authenticate(_bearer_token(request), scope)

    return dependency


CurrentActor = Annotated[Actor, Depends(_actor_dependency(SessionScope.FULL))]
EnrollmentActor = Annotated[Actor, Depends(_actor_dependency(SessionScope.ENROLLMENT))]
AnySessionActor = Annotated[Actor, Depends(_actor_dependency(SessionScope.ANY))]
```

(`request.app.state.actor_authenticator` lo fija `create_app` desde el contenedor; es la única lectura de `app.state`. Ver la nota de la sección 20 sobre `Depends` y `app.state`.)

**Pruebas:** `test_jwt_token_service.py` (`alg: none` y `HS512` rechazados; falta cada claim obligatorio; `iss` y `aud` ajenos; `exp` vencido con la tolerancia, avanzando el `FixedClock`; la llave anterior verifica pero no firma; un `kid` desconocido; una llave de menos de 32 bytes impide el arranque), `test_actor_authenticator.py` (`tv` distinto da `SESSION_REVOKED`; cuenta suspendida; clínica suspendida; personal sin `"otp"` da `MFA_REQUIRED` salvo con `EnrollmentActor`) y la de API de la cabecera de 2.049 bytes.

**Antipatrones**
- `jwt.decode(token, key)` sin `algorithms`, o con `verify_signature=False`.
- Poner permisos, nombre o correo en el token.
- Guardar el access token en `localStorage` o en una cookie (la política lo prohíbe).
- Confiar en `exp` sin consultar `tv`: una sesión robada no se podría cortar.

## 5. Refresh token: rotación atómica y detección de reutilización

- **Dónde vive:** el caso de uso `RotateRefreshTokenUseCase` en `insumap/application/identity/refresh.py`; el puerto `RefreshTokenPort` en `application/identity/ports.py`; `SqlRefreshTokenRepository` y `RefreshTokenOrm` en `infrastructure/persistence`; la generación y el hash en `OpaqueTokenService` (`infrastructure/security/tokens.py`).
- **Formato y almacenamiento:** 256 bits aleatorios (`secrets.token_urlsafe(32)`, 43 caracteres). La BD guarda solo el SHA-256 en hexadecimal; con 256 bits de entropía no hace falta un hash lento ni una llave.
- **Familia:** cada login crea una `family_id` (viaja como `sid` en el JWT). Cada uso emite un token nuevo de la misma familia y deja el anterior con `revoked_reason = 'ROTATED'` y `replaced_by_id`.
- **Vida del token nuevo:** la del token que se rota (`expires_at - issued_at`, que el login fijó según la población) recortada por el fin absoluto de la familia (`family_expires_at`: 90 días para el paciente, 12 horas para el personal). Las columnas `issued_at` y `family_expires_at` son **supuestas**: confirmar con `insumap-database` ([`Modelo-de-datos.md`](../docs/Modelo-de-datos.md)).
- **Sin ventana de gracia.** El frontend serializa el refresh entre pestañas con Web Locks.

### 5.1 Algoritmo

1. Calcular el SHA-256 del token presentado.
2. **Reclamar** el token con una sola sentencia atómica (el paso que impide que dos peticiones roten el mismo token):

   ```sql
   UPDATE iam.refresh_tokens
      SET revoked_at = :now, revoked_reason = 'ROTATED'
    WHERE token_hash = :hash AND revoked_at IS NULL AND expires_at > :now
   RETURNING id, user_id, family_id, issued_at, expires_at, family_expires_at;
   ```

3. Si devolvió una fila (**ganó**): insertar el token nuevo en la misma familia, enlazar `replaced_by_id` y emitir el access token. Todo en la transacción de la petición. Si `now >= family_expires_at`: `401 UNAUTHORIZED` (la familia terminó).
4. Si no devolvió filas, buscar el token por hash (función `SECURITY DEFINER` `iam.lookup_refresh_token`, porque aún no hay contexto de clínica):
   - No existe, o existe y **no** está revocado (vencido): `401 UNAUTHORIZED`, sin más detalle.
   - Existe y **está revocado** (reutilización): en una **transacción propia** revocar toda la familia (`REUSE_DETECTED`), `token_version + 1`, registrar `REFRESH_TOKEN_REUSE_DETECTED` (alta) y responder `401 SESSION_REVOKED`.

Por qué una transacción propia: la respuesta es un error y la de la petición se revierte; sin ella, la revocación no quedaría.

```python
# insumap/application/identity/refresh.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import final
from uuid import UUID

from insumap.application.common.ids import IdGenerator
from insumap.application.identity.ports import OpaqueTokenService
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.time import Clock

REASON_ROTATED = "ROTATED"
REASON_REUSE_DETECTED = "REUSE_DETECTED"


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredRefreshToken:
    token_id: UUID
    user_id: UUID
    family_id: UUID
    token_hash: str
    issued_at: datetime
    expires_at: datetime
    family_expires_at: datetime
    revoked_at: datetime | None


class RefreshTokenPort(ABC):
    @abstractmethod
    def claim(self, token_hash: str, now: datetime) -> StoredRefreshToken | None:
        """The atomic UPDATE ... WHERE revoked_at IS NULL RETURNING. None if it lost."""

    @abstractmethod
    def find_by_hash(self, token_hash: str) -> StoredRefreshToken | None:
        """SECURITY DEFINER lookup: it runs before the clinic context exists."""

    @abstractmethod
    def insert(self, token: StoredRefreshToken) -> None: ...

    @abstractmethod
    def link_replacement(self, old_id: UUID, new_id: UUID) -> None: ...


class SessionRevoker(ABC):
    @abstractmethod
    def revoke_family_for_reuse(self, token: StoredRefreshToken, now: datetime) -> None:
        """Own transaction: revoke the family, token_version + 1 and the HIGH event."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RotatedSession:
    user_id: UUID
    family_id: UUID
    refresh_token: str
    refresh_expires_at: datetime


@final
class RotateRefreshTokenUseCase:
    def __init__(
        self,
        tokens: RefreshTokenPort,
        revoker: SessionRevoker,
        opaque: OpaqueTokenService,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._tokens = tokens
        self._revoker = revoker
        self._opaque = opaque
        self._ids = ids
        self._clock = clock

    def execute(self, presented: str) -> RotatedSession:
        now = self._clock.now()
        token_hash = self._opaque.hash(presented)
        claimed = self._tokens.claim(token_hash, now)
        if claimed is None:
            raise self._rejection(token_hash, now)
        if now >= claimed.family_expires_at:
            raise InsumapError(ErrorCode.UNAUTHENTICATED)
        issued = self._opaque.new_token()
        expires_at = min(now + (claimed.expires_at - claimed.issued_at), claimed.family_expires_at)
        new = StoredRefreshToken(
            token_id=self._ids.new_id(),
            user_id=claimed.user_id,
            family_id=claimed.family_id,
            token_hash=issued.token_hash,
            issued_at=now,
            expires_at=expires_at,
            family_expires_at=claimed.family_expires_at,
            revoked_at=None,
        )
        self._tokens.insert(new)
        self._tokens.link_replacement(claimed.token_id, new.token_id)
        return RotatedSession(
            user_id=new.user_id,
            family_id=new.family_id,
            refresh_token=issued.plain,
            refresh_expires_at=expires_at,
        )

    def _rejection(self, token_hash: str, now: datetime) -> InsumapError:
        stored = self._tokens.find_by_hash(token_hash)
        if stored is None or stored.revoked_at is None:
            return InsumapError(ErrorCode.UNAUTHENTICATED)
        self._revoker.revoke_family_for_reuse(stored, now)
        return InsumapError(ErrorCode.SESSION_REVOKED)
```

```python
# insumap/application/identity/ports.py (fragmento)
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class IssuedToken:
    plain: str  # shown once, never stored
    token_hash: str  # SHA-256 hex, the only thing stored


class OpaqueTokenService(ABC):
    @abstractmethod
    def new_token(self) -> IssuedToken: ...

    @abstractmethod
    def hash(self, plain: str) -> str: ...
```

```python
# insumap/infrastructure/security/tokens.py
import hashlib
import secrets
from typing import final, override

from insumap.application.identity.ports import IssuedToken, OpaqueTokenService

TOKEN_ENTROPY_BYTES = 32


@final
class Sha256OpaqueTokenService(OpaqueTokenService):
    """256-bit random tokens; only their SHA-256 is stored (a slow hash adds nothing)."""

    @override
    def new_token(self) -> IssuedToken:
        plain = secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)
        return IssuedToken(plain=plain, token_hash=self.hash(plain))

    @override
    def hash(self, plain: str) -> str:
        return hashlib.sha256(plain.encode()).hexdigest()
```

La sentencia atómica con SQLAlchemy (el `*Orm` solo mapea la tabla de `insumap-database`):

```python
# insumap/infrastructure/persistence/repositories/refresh_tokens.py
from datetime import datetime
from typing import final, override
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from insumap.application.identity.refresh import (
    REASON_ROTATED,
    RefreshTokenPort,
    StoredRefreshToken,
)
from insumap.infrastructure.persistence.orm.iam import RefreshTokenOrm


@final
class SqlRefreshTokenRepository(RefreshTokenPort):
    def __init__(self, session: Session) -> None:
        self._session = session

    @override
    def claim(self, token_hash: str, now: datetime) -> StoredRefreshToken | None:
        statement = (
            update(RefreshTokenOrm)
            .where(
                RefreshTokenOrm.token_hash == token_hash,
                RefreshTokenOrm.revoked_at.is_(None),
                RefreshTokenOrm.expires_at > now,
            )
            .values(revoked_at=now, revoked_reason=REASON_ROTATED)
            .returning(RefreshTokenOrm)
        )
        row = self._session.execute(statement).scalar_one_or_none()
        return None if row is None else _to_stored(row)

    @override
    def find_by_hash(self, token_hash: str) -> StoredRefreshToken | None:
        # In production this is the SECURITY DEFINER function iam.lookup_refresh_token.
        row = self._session.execute(
            select(RefreshTokenOrm).where(RefreshTokenOrm.token_hash == token_hash)
        ).scalar_one_or_none()
        return None if row is None else _to_stored(row)

    @override
    def insert(self, token: StoredRefreshToken) -> None:
        self._session.add(_to_orm(token))
        self._session.flush()

    @override
    def link_replacement(self, old_id: UUID, new_id: UUID) -> None:
        self._session.execute(
            update(RefreshTokenOrm)
            .where(RefreshTokenOrm.id == old_id)
            .values(replaced_by_id=new_id)
        )


def _to_stored(row: RefreshTokenOrm) -> StoredRefreshToken:
    return StoredRefreshToken(
        token_id=row.id,
        user_id=row.user_id,
        family_id=row.family_id,
        token_hash=row.token_hash,
        issued_at=row.issued_at,
        expires_at=row.expires_at,
        family_expires_at=row.family_expires_at,
        revoked_at=row.revoked_at,
    )


def _to_orm(token: StoredRefreshToken) -> RefreshTokenOrm:
    return RefreshTokenOrm(
        id=token.token_id,
        user_id=token.user_id,
        family_id=token.family_id,
        token_hash=token.token_hash,
        issued_at=token.issued_at,
        expires_at=token.expires_at,
        family_expires_at=token.family_expires_at,
        revoked_at=token.revoked_at,
    )
```

Los `*Orm` solo mapean tablas que ya existen en `insumap-database`; las columnas de este fragmento son **supuestas** (la política nombra `token_hash`, `family_id`, `revoked_at`, `revoked_reason` y `replaced_by_id`; `issued_at` y `family_expires_at` son propuestas) y se confirman con el modelo de datos:

```python
# insumap/infrastructure/persistence/orm/iam.py (fragmento)
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Maps tables; it never creates them (no metadata.create_all)."""


class RefreshTokenOrm(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = {"schema": "iam"}

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID]
    family_id: Mapped[UUID]
    token_hash: Mapped[str] = mapped_column(String)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    family_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String)
    replaced_by_id: Mapped[UUID | None]


class RateLimitBucketOrm(Base):
    __tablename__ = "rate_limit_buckets"
    __table_args__ = {"schema": "iam"}

    bucket_key: Mapped[str] = mapped_column(String, primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    hits: Mapped[int] = mapped_column(Integer)
```


**Pruebas:**
- Unitaria (`test_rotate_refresh_token_use_case.py`) con un `RefreshTokenPort` en memoria cuyo `claim` es atómico (un `threading.Lock`): el token nuevo funciona y el anterior no; el hash del token nuevo es SHA-256 (la BD de la prueba no contiene el token en claro); reutilizar un token rotado llama a `revoke_family_for_reuse` y da `SESSION_REVOKED`; un token vencido o desconocido da `UNAUTHENTICATED` sin revocar la familia; la familia vencida (`family_expires_at`) da `UNAUTHENTICATED`; el token nuevo nunca vive más que la familia; con dos hilos rotando el mismo token, **uno** gana.
- Integración (Testcontainers, `insumap_app`): las mismas dos rotaciones simultáneas con dos conexiones reales; tras la reutilización, `iam.users.token_version` subió, la familia quedó `REUSE_DETECTED` y hay una fila `REFRESH_TOKEN_REUSE_DETECTED` en `iam.security_events`, aunque la petición respondió `401`.

**Antipatrones**
- `SELECT` seguido de `UPDATE` (dos peticiones pasan el `SELECT`): el `UPDATE ... RETURNING` es la guarda.
- Guardar el refresh en claro o con una llave reversible.
- Una "ventana de gracia" de unos segundos en el servidor: la política la prohíbe.
- Revocar la familia dentro de la transacción de la petición (se revierte con el error).

## 6. Cookie del refresh y CSRF

- **Dónde vive:** `RefreshCookie` en `insumap/api/security.py` (es HTTP); `RefreshRequestGuard` en `insumap/application/identity/csrf.py`.
- **La cookie** (política 2.4): `__Secure-insumap_rt`, `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/api/v1/auth`, **sin** `Domain`, `Max-Age` = vida del token en segundos. El prefijo `__Secure-` obliga al navegador a exigir `Secure`. No se usa `__Host-` porque exige `Path=/`. `SameSite` viene de `REFRESH_COOKIE_SAMESITE`; solo vale `Strict` salvo la excepción documentada.
- **CSRF** en `POST /auth/refresh`, `/logout` y `/logout-all`, los únicos que usan la cookie: la cabecera `X-Requested-With: insumap-web` es obligatoria; si `Origin` está presente debe estar en `CORS_ORIGINS`; `Sec-Fetch-Site: cross-site` se rechaza. Si falla: `403 FORBIDDEN` y `CSRF_CHECK_FAILED` (media).

```python
# insumap/api/security.py (se agrega)
from datetime import datetime
from typing import Final, Literal

from fastapi import Response

REFRESH_COOKIE_NAME: Final = "__Secure-insumap_rt"
REFRESH_COOKIE_PATH: Final = "/api/v1/auth"


class RefreshCookie:
    """Builds and clears the refresh cookie; the attributes are not negotiable."""

    def __init__(self, *, samesite: Literal["strict", "none"]) -> None:
        self._samesite = samesite

    def set(self, response: Response, *, token: str, expires_at: datetime, now: datetime) -> None:
        response.set_cookie(
            key=REFRESH_COOKIE_NAME,
            value=token,
            max_age=max(int((expires_at - now).total_seconds()), 0),
            path=REFRESH_COOKIE_PATH,
            secure=True,
            httponly=True,
            samesite=self._samesite,
        )

    def clear(self, response: Response) -> None:
        response.delete_cookie(
            key=REFRESH_COOKIE_NAME,
            path=REFRESH_COOKIE_PATH,
            secure=True,
            httponly=True,
            samesite=self._samesite,
        )
```

```python
# insumap/application/identity/csrf.py
from abc import ABC, abstractmethod
from collections.abc import Collection
from dataclasses import dataclass
from typing import Final, final

from insumap.shared.errors import ErrorCode, InsumapError

REQUIRED_REQUESTED_WITH: Final = "insumap-web"
CROSS_SITE: Final = "cross-site"


@dataclass(frozen=True, slots=True, kw_only=True)
class RefreshRequestOrigin:
    requested_with: str | None
    origin: str | None
    sec_fetch_site: str | None


class SecurityEventSink(ABC):
    @abstractmethod
    def csrf_check_failed(self) -> None:
        """Own transaction: CSRF_CHECK_FAILED, severity MEDIUM."""


@final
class RefreshRequestGuard:
    def __init__(self, allowed_origins: Collection[str], events: SecurityEventSink) -> None:
        self._allowed = frozenset(allowed_origins)
        self._events = events

    def ensure_allowed(self, request: RefreshRequestOrigin) -> None:
        if (
            request.requested_with != REQUIRED_REQUESTED_WITH
            or (request.origin is not None and request.origin not in self._allowed)
            or request.sec_fetch_site == CROSS_SITE
        ):
            self._events.csrf_check_failed()
            raise InsumapError(ErrorCode.FORBIDDEN)
```

**Pruebas:** `test_refresh_request_guard.py` (sin `X-Requested-With`, con `Origin` ajeno y con `Sec-Fetch-Site: cross-site` dan `FORBIDDEN` y registran el evento; la petición correcta pasa); `test_refresh_cookie.py` sobre el `Set-Cookie` real de una `Response` (los seis atributos, sin `Domain`, el nombre con prefijo); en API, los tres endpoints rechazan la petición sin la cabecera.

**Antipatrones:** guardar el access token en una cookie (la API general quedaría expuesta a CSRF); `SameSite=None` sin la excepción documentada; aceptar `Origin: null`.

## 7. MFA TOTP del personal

- **Dónde vive:** `TotpVerifier` y `MfaRecoveryCodes` en `insumap/infrastructure/security/`; el cifrado del secreto con `ColumnCipher` (sección 15); los retos en `iam.auth_challenges`. Biblioteca: `pyotp` (RFC 6238; propuesta de [`Stack-tecnologico.md`](../docs/Stack-tecnologico.md), por confirmar en la fase 3).
- **Parámetros fijos** (política 4): HMAC-SHA1, 6 dígitos, paso de 30 segundos, secreto de 20 bytes (32 caracteres base32). Ventana ±`MFA_TOTP_VALID_WINDOW`. Reto de login de 256 bits (`MFA_CHALLENGE_TTL_SECONDS`, `MFA_CHALLENGE_MAX_ATTEMPTS`).
- **Anti-repetición:** se rechaza un paso menor o igual a `last_used_step`, y el paso aceptado se guarda con una sentencia condicional (`UPDATE ... WHERE last_used_step IS NULL OR last_used_step < :step RETURNING`) para que dos verificaciones simultáneas no acepten el mismo código.
- **Todos los fallos** (TOTP, código de respaldo, reto agotado) responden `401 INVALID_CREDENTIALS`, registran `MFA_FAILED` y cuentan para el bloqueo de la sección 9.

```python
# insumap/infrastructure/security/totp.py
import base64
import hmac
import secrets
from datetime import datetime
from typing import Final, final

import pyotp

SECRET_BYTES = 20
DIGITS: Final = 6
STEP_SECONDS: Final = 30
ISSUER: Final = "Insumap"


def new_totp_secret() -> str:
    """160 bits as base32 (32 characters)."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode()


def provisioning_uri(secret: str, email: str) -> str:
    """otpauth://totp/Insumap:<email>?secret=...&issuer=Insumap (the QR is drawn in the browser)."""
    return pyotp.TOTP(secret, digits=DIGITS, interval=STEP_SECONDS).provisioning_uri(
        name=email, issuer_name=ISSUER
    )


@final
class TotpVerifier:
    def __init__(self, *, valid_window: int) -> None:
        self._window = valid_window

    @staticmethod
    def step_at(moment: datetime) -> int:
        return int(moment.timestamp()) // STEP_SECONDS

    def verify(self, secret: str, code: str, *, now: datetime, last_used_step: int | None) -> int | None:
        """Return the accepted step, or None. Every step of the window is compared."""
        totp = pyotp.TOTP(secret, digits=DIGITS, interval=STEP_SECONDS)
        current = self.step_at(now)
        accepted: int | None = None
        for step in range(current - self._window, current + self._window + 1):
            candidate_matches = hmac.compare_digest(totp.generate_otp(step), code)
            replayed = last_used_step is not None and step <= last_used_step
            if candidate_matches and not replayed and accepted is None:
                accepted = step
        return accepted
```

**Códigos de respaldo.** `MFA_RECOVERY_CODE_COUNT` códigos de 10 caracteres Crockford (50 bits), mostrados como `XXXXX-XXXXX`, de un solo uso. Se generan con el mismo `CrockfordCodec` de la sección 8 (`FieldLimits.MFA_RECOVERY_CODE_LENGTH`, propuesto) y se guardan con `HMAC-SHA256(HKDF(CODE_HMAC_KEY, "insumap/recovery-code/v1"), código)`, `key_id` y `used_at`. Se consumen con `UPDATE ... SET used_at = :now WHERE code_hash = :hash AND used_at IS NULL RETURNING id`. Regenerarlos invalida los anteriores; usar uno registra `MFA_RECOVERY_CODE_USED` (media) y avisa al titular.

**Flujo:** el login con MFA devuelve `MFA_CHALLENGE` con un `challenge_token` opaco (solo su SHA-256 vive en `iam.auth_challenges`, propósito `MFA`); `POST /auth/mfa/verify` lo consume. El enrolamiento devuelve el secreto y el URI **una sola vez**, con `Cache-Control: no-store`; el factor queda activo solo tras confirmar un TOTP válido, y esa confirmación devuelve la sesión completa (`amr: ["pwd", "otp"]`). Restablecer el MFA de otra persona exige motivo, hace `tv + 1`, revoca las familias y registra `MFA_RESET` (alta); nadie restablece el suyo.

**Pruebas:** `test_totp_verifier.py` con `FixedClock` y un secreto de prueba (el código del paso actual pasa; ±1 pasa y ±2 no; un código de un paso ya usado se rechaza; un código incorrecto da `None`), `test_mfa_enrollment_use_case.py` (el factor no queda activo antes de confirmar; el secreto se guarda cifrado y se descifra solo con su AAD), `test_mfa_recovery_codes.py` (un solo uso; regenerar invalida los anteriores) y las de API del reto (vence a los 5 minutos o con 5 intentos).

**Antipatrones:** comparar el código con `==`; aceptar el mismo paso dos veces; guardar el secreto TOTP en claro o en un hash (el sistema necesita leerlo); dibujar el QR en el servidor; mostrar los códigos de respaldo más de una vez.

## 8. Códigos de activación y de respaldo

- **Dónde vive:** `CrockfordCodec` y `CodeHasher` en `insumap/infrastructure/security/codes.py`; `CredentialInvitation` en `insumap/domain/identity/invitation.py`; los casos de uso en `application/identity/` y `application/onboarding/` (`IssueCredentialsCommand` es P13).
- **Código:** alfabeto Crockford base32 `0123456789ABCDEFGHJKMNPQRSTVWXYZ`; 16 caracteres (80 bits, `FieldLimits.ACTIVATION_CODE_LENGTH`, propuesto); `secrets.choice` carácter por carácter (nunca `random`); presentación `XXXX-XXXX-XXXX-XXXX`.
- **Normalización de la entrada:** recortar, mayúsculas, quitar espacios y guiones, `O` a `0`, `I` y `L` a `1`. Si no queda un código del largo y alfabeto correctos, es `INVITATION_INVALID` (y el intento cuenta para la tasa por IP).
- **Almacenamiento:** `HMAC-SHA256(k, código_normalizado)` en hexadecimal, con `k = HKDF-SHA256(CODE_HMAC_KEY, info="insumap/activation-code/v1")`, más `code_key_id`. Es determinista, así que permite buscar la invitación por el código; con la llave, quien robe la tabla no puede probar códigos fuera de línea. Durante una rotación se calcula el HMAC con la llave actual y con la anterior y se busca por ambos.
- **Se muestra una sola vez** (respuesta de la emisión con `no-store`); nunca se registra en logs, `security_events` ni `audit_log` (solo el `invitation_id`).

```python
# insumap/infrastructure/security/codes.py
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Final, final

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from insumap.infrastructure.security.keys import KeyRing

ALPHABET: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CONFUSABLE: Final = str.maketrans({"O": "0", "I": "1", "L": "1"})
ACTIVATION_INFO: Final = b"insumap/activation-code/v1"
RECOVERY_INFO: Final = b"insumap/recovery-code/v1"
SUBKEY_BYTES = 32


@final
class CrockfordCodec:
    def __init__(self, *, length: int, group_size: int) -> None:
        self._length = length
        self._group = group_size

    def generate(self) -> str:
        return "".join(secrets.choice(ALPHABET) for _ in range(self._length))

    def format(self, code: str) -> str:
        return "-".join(code[i : i + self._group] for i in range(0, len(code), self._group))

    def normalize(self, raw: str) -> str | None:
        """Return the canonical code, or None if it cannot be one."""
        cleaned = "".join(raw.split()).replace("-", "").upper().translate(CONFUSABLE)
        if len(cleaned) != self._length or any(ch not in ALPHABET for ch in cleaned):
            return None
        return cleaned


@dataclass(frozen=True, slots=True, kw_only=True)
class KeyedHash:
    key_id: str
    value: str


@final
class CodeHasher:
    """HMAC-SHA256 of a normalized code with an HKDF subkey of CODE_HMAC_KEY."""

    def __init__(self, keys: KeyRing, *, info: bytes) -> None:
        self._keys = keys
        self._info = info

    def hash_for_storage(self, code: str) -> KeyedHash:
        return self._hash_with(self._keys.current_key_id, self._keys.current_key(), code)

    def hashes_for_lookup(self, code: str) -> list[KeyedHash]:
        """Current key first, then the previous one while a rotation is in progress."""
        return [self._hash_with(key_id, key, code) for key_id, key in self._keys.all_keys()]

    def _hash_with(self, key_id: str, key: bytes, code: str) -> KeyedHash:
        subkey = HKDF(algorithm=hashes.SHA256(), length=SUBKEY_BYTES, salt=None, info=self._info).derive(key)
        digest = hmac.new(subkey, code.encode(), hashlib.sha256).hexdigest()
        return KeyedHash(key_id=key_id, value=digest)
```

### 8.1 La invitación como máquina de estados del dominio

`PENDING`, `VERIFIED`, `USED`, `EXPIRED`, `REVOKED` y `LOCKED` (política 3.1). La entidad es inmutable y decide, sin leer la BD ni el reloj:

```python
# insumap/domain/identity/invitation.py
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import final
from uuid import UUID

from insumap.shared.errors import ErrorCode, InsumapError


class InvitationStatus(StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    USED = "USED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    LOCKED = "LOCKED"


@final
class InvitationInvalidError(InsumapError):
    """The one error of every activation failure: nothing tells the cause apart."""

    def __init__(self) -> None:
        super().__init__(ErrorCode.INVITATION_INVALID)


@dataclass(frozen=True, slots=True, kw_only=True)
class CredentialInvitation:
    invitation_id: UUID
    status: InvitationStatus
    expires_at: datetime
    failed_attempts: int

    def verify_birth_date(self, *, matches: bool, now: datetime, max_attempts: int) -> CredentialInvitation:
        """Step 1 of the activation. Returns the new invitation; raises the generic error."""
        if self.status is not InvitationStatus.PENDING or now >= self.expires_at:
            raise InvitationInvalidError
        if matches:
            return replace(self, status=InvitationStatus.VERIFIED)
        attempts = self.failed_attempts + 1
        locked = attempts >= max_attempts
        return replace(
            self,
            failed_attempts=attempts,
            status=InvitationStatus.LOCKED if locked else InvitationStatus.PENDING,
        )
```

Un fallo de fecha devuelve una invitación nueva (con un intento más o `LOCKED`) en vez de lanzar: **el caso de uso** la guarda en una transacción propia y **después** responde `410 INVITATION_INVALID`, porque el contador debe sobrevivir al error. Al llegar a `ACTIVATION_MAX_ATTEMPTS` se registra `ACTIVATION_LOCKED` (media). Una invitación `LOCKED` no se desbloquea: el admin emite una nueva.

### 8.2 Un solo error y tiempo uniforme

Todo fallo (código mal formado, inexistente, vencido, usado, reemplazado, revocado, bloqueado; fecha incorrecta; `activation_token` inválido) responde `410 INVITATION_INVALID` con el mismo cuerpo. El tiempo de respuesta no depende del motivo: el caso de uso **siempre** normaliza, calcula el HMAC y consulta, aunque el formato sea inválido (con un código de relleno), y compara la fecha con `hmac.compare_digest` sobre las cadenas ISO. Un código inventado no se puede atribuir a una invitación, así que esos fallos solo cuentan por IP; los de fecha con un código real cuentan por invitación.

**Pruebas:** `test_crockford_codec.py` (largo y alfabeto; `O`, `I`, `L` normalizados; con guiones y espacios; `U` y minúsculas con caracteres ajenos rechazados; 1.000 códigos generados son distintos y del alfabeto), `test_code_hasher.py` (determinista; cambia con la llave y con `info`; la llave anterior produce un segundo hash para la búsqueda), `test_credential_invitation.py` (la tabla de transiciones: vencida, usada, revocada y bloqueada lanzan el mismo error; 5 fechas incorrectas dan `LOCKED`; el contador no sube con fecha correcta), y de integración que el código no aparece en claro en ninguna tabla ni en los logs capturados.

**Antipatrones:** `random` en lugar de `secrets`; SHA-256 sin llave (80 bits se prueban fuera de línea); un mensaje distinto para "vencido" y "usado"; devolver el nombre del paciente al verificar el código; guardar o reimprimir el código en claro.

## 9. Límites de tasa y bloqueo de login

- **Dónde vive:** `RateLimitGuard` y las reglas en `insumap/application/security/rate_limit.py`; `PostgresFixedWindowRateLimiter` y `InMemoryTokenBucketLimiter` en `infrastructure/security/`; `LoginLockPolicy` en `domain/identity/login_lock.py`.
- **Dos almacenes (política 12):** las familias críticas (autenticación, MFA, activación, restablecimiento, refresh, emisión de credenciales, importación, IA y reportes) usan **contadores de ventana fija en PostgreSQL** (`iam.rate_limit_buckets`, tabla propuesta para `insumap-database`): compartidos entre instancias, sobreviven a un reinicio y corren en una **transacción propia**. El resto usa un **token bucket en memoria** por proceso.
- **Clave:** HMAC con la subllave de `APP_HMAC_KEY` de `familia:valor` (la IP, el correo o el id nunca se guardan en claro). La subllave `rate-limit` es propuesta; la política nombra `ip`, `subject-ref` y `cursor`.
- **IP del cliente:** `request.client.host`, que uvicorn calcula con `--proxy-headers` y `FORWARDED_ALLOW_IPS`. Hay que verificar en el despliegue que un `X-Forwarded-For` falso no cambia la IP contada (también a través de la reescritura de Vercel). Si la cambia, `ClientIpResolver` toma la IP que agrega el último proxy de confianza contando desde la derecha (propuesta de la política).
- **Respuesta:** `429 RATE_LIMITED` con `Retry-After` en segundos. Se registra `RATE_LIMITED` (baja) **una vez por clave y ventana**.

```python
# insumap/application/security/rate_limit.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import timedelta
from typing import final

from insumap.shared.errors import ErrorCode, InsumapError


@dataclass(frozen=True, slots=True, kw_only=True)
class RateLimitRule:
    family: str
    limit: int
    window: timedelta


@dataclass(frozen=True, slots=True, kw_only=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int


@dataclass(frozen=True, slots=True, kw_only=True)
class RateLimitRules:
    """Built once in container.py from Settings (section 2.3); two of the sixteen shown."""

    login_per_ip: RateLimitRule
    activation_per_ip_per_minute: RateLimitRule
    # ... one field per row of the table in section 2.3


class RateLimiter(ABC):
    @abstractmethod
    def hit(self, rule: RateLimitRule, subject: str) -> RateLimitDecision:
        """Count one request for ``subject`` and say whether it is allowed."""


@final
class RateLimitedError(InsumapError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            ErrorCode.RATE_LIMITED, headers={"Retry-After": str(retry_after_seconds)}
        )


@final
class RateLimitGuard:
    def __init__(self, limiter: RateLimiter) -> None:
        self._limiter = limiter

    def ensure(self, rule: RateLimitRule, subject: str) -> None:
        decision = self._limiter.hit(rule, subject)
        if not decision.allowed:
            raise RateLimitedError(decision.retry_after_seconds)
```

```python
# insumap/infrastructure/security/rate_limiters.py
import math
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import final, override

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from insumap.application.security.rate_limit import RateLimiter, RateLimitDecision, RateLimitRule
from insumap.infrastructure.persistence.orm.iam import RateLimitBucketOrm
from insumap.infrastructure.security.keys import SubkeyHasher
from insumap.shared.time import Clock

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

type IndependentSession = Callable[[], AbstractContextManager[Session]]
"""Opens a transaction apart from the request's: it commits even if the request fails."""


def window_start(now: datetime, window: timedelta) -> datetime:
    """Start of the clock-aligned fixed window that contains ``now``."""
    seconds = (now - EPOCH).total_seconds()
    return EPOCH + timedelta(seconds=seconds - seconds % window.total_seconds())


@final
class PostgresFixedWindowRateLimiter(RateLimiter):
    """One atomic INSERT ... ON CONFLICT DO UPDATE ... RETURNING per request."""

    def __init__(self, session: IndependentSession, hasher: SubkeyHasher, clock: Clock) -> None:
        self._session = session
        self._hasher = hasher
        self._clock = clock

    @override
    def hit(self, rule: RateLimitRule, subject: str) -> RateLimitDecision:
        now = self._clock.now()
        start = window_start(now, rule.window)
        key = self._hasher.hexdigest(f"{rule.family}:{subject}")
        statement = (
            insert(RateLimitBucketOrm)
            .values(bucket_key=key, window_start=start, hits=1)
            .on_conflict_do_update(
                index_elements=[RateLimitBucketOrm.bucket_key, RateLimitBucketOrm.window_start],
                set_={"hits": RateLimitBucketOrm.hits + 1},
            )
            .returning(RateLimitBucketOrm.hits)
        )
        with self._session() as session:
            hits = session.execute(statement).scalar_one()
            session.commit()
        retry_after = math.ceil((start + rule.window - now).total_seconds())
        return RateLimitDecision(allowed=hits <= rule.limit, retry_after_seconds=max(retry_after, 1))


@final
class InMemoryTokenBucketLimiter(RateLimiter):
    """Per-process bucket for the non-critical families; it amortizes abuse, it is not a barrier."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, datetime]] = {}

    @override
    def hit(self, rule: RateLimitRule, subject: str) -> RateLimitDecision:
        now = self._clock.now()
        refill_per_second = rule.limit / rule.window.total_seconds()
        key = f"{rule.family}:{subject}"
        with self._lock:
            tokens, updated = self._buckets.get(key, (float(rule.limit), now))
            tokens = min(float(rule.limit), tokens + (now - updated).total_seconds() * refill_per_second)
            allowed = tokens >= 1.0
            self._buckets[key] = (tokens - 1.0 if allowed else tokens, now)
        wait = 0 if allowed else math.ceil((1.0 - tokens) / refill_per_second)
        return RateLimitDecision(allowed=allowed, retry_after_seconds=max(wait, 1))
```

`window_start()` calcula el inicio de la ventana fija alineada al reloj (la hora UTC dividida en bloques del tamaño de la ventana) con aritmética de `timedelta` sobre el `Clock`. La ventana fija permite hasta el doble del límite en el borde entre dos ventanas: se acepta porque los bloqueos de login cubren los ataques sostenidos.

`Retry-After` necesita que el manejador de errores copie las cabeceras de la excepción. `InsumapError` hoy no las lleva: se propone un parámetro opcional `headers` (vacío por defecto) y que `ApiExceptionHandlers.handle_insumap_error` lo pase a `ErrorResponseFactory.create(headers=...)`, que ya lo acepta (sección 20).

### 9.1 Bloqueo escalonado de login

La política (2.2) se deriva del registro de intentos (`iam.login_attempts`, que se escribe en transacción propia): con las fallas **consecutivas desde el último éxito**, cada `LOGIN_PAIR_MAX_FAILURES` fallas abren un nivel que dura `LOGIN_LOCK_BASE_MINUTES × 2^(nivel−1)`, con tope de `LOGIN_LOCK_MAX_HOURS`. Un ingreso exitoso reinicia el contador. El bloqueo global del correo (`LOGIN_ACCOUNT_*`) es una segunda instancia de la misma política sobre los fallos de cualquier IP. Los contadores se guardan por **HMAC del correo normalizado, exista o no la cuenta**, así el `429` es igual para un correo inexistente.

```python
# insumap/domain/identity/login_lock.py
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import final


@final
class LoginLockPolicy:
    """Pure policy: from the failures since the last success, until when is it locked?"""

    def __init__(self, *, max_failures: int, base: timedelta, cap: timedelta) -> None:
        self._max_failures = max_failures
        self._base = base
        self._cap = cap

    def locked_until(self, failures: Sequence[datetime]) -> datetime | None:
        """``failures``: consecutive failures since the last success, oldest first."""
        levels = len(failures) // self._max_failures
        if levels == 0:
            return None
        trigger = failures[levels * self._max_failures - 1]
        return trigger + min(self._base * 2 ** (levels - 1), self._cap)
```

Derivar el nivel del registro evita una tabla de bloqueos, pero ignora la ventana de `LOGIN_FAILURE_WINDOW_MINUTES` al escalar (sección 20); la consulta que alimenta la política puede limitarse a esa ventana para el primer nivel.

**Pruebas:** `test_login_lock_policy.py` (4 fallas no bloquean; 5 bloquean 15 minutos; 10 bloquean 30; tope de 24 horas con niveles altos; sin fallas, nada), `test_rate_limit_guard.py` (excede el límite: `RateLimitedError` con `Retry-After`; exactamente en el límite pasa), `test_in_memory_token_bucket_limiter.py` (con `FixedClock`: se agota y se recupera al avanzar el reloj), integración del limitador PostgreSQL (el contador se comparte entre **dos** sesiones de la app y sobrevive a un `rollback` de la petición) y de API: **cada fila** de la tabla 2.3 devuelve `429` con `Retry-After` al exceder el límite leído de `Settings`, un correo inexistente recibe el mismo `429` y un `X-Forwarded-For` falso no cambia la IP contada.

**Antipatrones:** un límite escrito en el router o en el decorador; contar en la transacción de la petición (se pierde con el error); guardar la IP o el correo en la clave; verificar la contraseña durante un bloqueo; un solo nivel de bloqueo por IP (un hospital sale por una sola IP).

## 10. Permisos, denegación por defecto y el `Actor`

- **Reglas:** los roles, los permisos y su matriz viven en `iam.roles`, `iam.permissions` e `iam.role_permissions` (semillas de `insumap-database`). El código solo verifica **códigos de permiso**, nunca nombres de rol (RF-07). Lo que no está concedido está denegado. Un `403` registra `PERMISSION_DENIED` (media).
- **Dónde se verifica:** en el caso de uso o el handler, con `actor.require(PermissionCode.X)`, **antes** de buscar el recurso (por eso el `403` no revela existencia). El router no autoriza; solo declara su permiso como metadato (sección 10.2) para que una prueba pueda recorrer todas las rutas. El único uso de `Depends` es el actor y la paginación (ADR-07).
- **Caché:** los permisos por rol se cachean `PERMISSION_CACHE_TTL_SECONDS` (60). Un cambio de la matriz surte efecto en 60 segundos; un cambio de rol o membresía de una persona sube su `tv` y surte efecto de inmediato.

### 10.1 `Actor`, caché de permisos y autenticación

```python
# insumap/application/common/actor.py (forma completa; design-patterns.md muestra la mínima)
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.errors import ErrorCode, InsumapError


class Role(StrEnum):
    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    CLINIC_ADMIN = "CLINIC_ADMIN"
    DOCTOR = "DOCTOR"
    PATIENT = "PATIENT"


@dataclass(frozen=True, slots=True, kw_only=True)
class Actor:
    user_id: UUID
    clinic_id: UUID | None
    role: Role
    patient_id: UUID | None = None
    permissions: frozenset[PermissionCode] = field(default=frozenset())
    mfa_verified: bool = False
    session_id: UUID | None = None

    def require(self, permission: PermissionCode) -> None:
        """Deny by default: the permission must have been granted by the database."""
        if permission not in self.permissions:
            raise InsumapError(ErrorCode.FORBIDDEN)

    def own_patient_id(self) -> UUID:
        """The patient of the token, never one received in the path or the body (V3)."""
        if self.patient_id is None:
            raise InsumapError(ErrorCode.FORBIDDEN)
        return self.patient_id
```

```python
# insumap/application/identity/authenticate.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import final, override
from uuid import UUID

from insumap.application.common.actor import Actor, Role
from insumap.application.identity.claims import AccessTokenDecoder
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.errors import ErrorCode, InsumapError

OTP_FACTOR = "otp"


class SessionScope(StrEnum):
    FULL = "FULL"  # every route that is not the enrollment or the session basics
    ENROLLMENT = "ENROLLMENT"  # /auth/mfa/enrollment*
    ANY = "ANY"  # GET /auth/current-user and /auth/logout


class ActorAuthenticator(ABC):
    @abstractmethod
    def authenticate(self, token: str, scope: SessionScope) -> Actor: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionState:
    is_active: bool
    token_version: int
    clinic_active: bool
    patient_id: UUID | None


class SessionStatePort(ABC):
    @abstractmethod
    def load(self, user_id: UUID) -> SessionState | None:
        """Read by primary key inside the request's transaction."""


class PermissionLookupPort(ABC):
    @abstractmethod
    def permissions_for_role(self, role: Role) -> frozenset[PermissionCode]: ...


@final
class AuthenticateActorUseCase(ActorAuthenticator):
    def __init__(
        self, decoder: AccessTokenDecoder, sessions: SessionStatePort, permissions: PermissionLookupPort
    ) -> None:
        self._decoder = decoder
        self._sessions = sessions
        self._permissions = permissions

    @override
    def authenticate(self, token: str, scope: SessionScope) -> Actor:
        claims = self._decoder.decode(token)
        state = self._sessions.load(claims.user_id)
        if state is None or not state.is_active or state.token_version != claims.token_version:
            raise InsumapError(ErrorCode.SESSION_REVOKED)
        if claims.clinic_id is not None and not state.clinic_active:
            raise InsumapError(ErrorCode.CLINIC_SUSPENDED)
        role = Role(claims.role)
        mfa_verified = OTP_FACTOR in claims.amr
        if scope is SessionScope.FULL and role is not Role.PATIENT and not mfa_verified:
            raise InsumapError(ErrorCode.MFA_REQUIRED)
        return Actor(
            user_id=claims.user_id,
            clinic_id=claims.clinic_id,
            role=role,
            patient_id=state.patient_id,
            permissions=self._permissions.permissions_for_role(role),
            mfa_verified=mfa_verified,
            session_id=claims.session_id,
        )
```

```python
# insumap/infrastructure/security/permission_cache.py
import threading
from datetime import datetime, timedelta
from typing import final, override

from insumap.application.common.actor import Role
from insumap.application.identity.authenticate import PermissionLookupPort
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.time import Clock


@final
class TtlCachedPermissionLookup(PermissionLookupPort):
    """Caches the permissions of a role for ``ttl`` (PERMISSION_CACHE_TTL_SECONDS)."""

    def __init__(self, inner: PermissionLookupPort, *, ttl: timedelta, clock: Clock) -> None:
        self._inner = inner
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: dict[Role, tuple[datetime, frozenset[PermissionCode]]] = {}

    @override
    def permissions_for_role(self, role: Role) -> frozenset[PermissionCode]:
        now = self._clock.now()
        with self._lock:
            cached = self._cache.get(role)
            if cached is not None and cached[0] > now:
                return cached[1]
        fresh = self._inner.permissions_for_role(role)
        with self._lock:
            self._cache[role] = (now + self._ttl, fresh)
        return fresh
```

El repositorio real convierte cada `permission_code` de la BD con `PermissionCode(value)` y **ignora** los códigos que el enum no conoce (denegación por defecto: un permiso sembrado pero sin código que lo use no concede nada).

### 10.2 Metadato de ruta y la prueba de denegación por defecto

La política (6.1) pide una prueba que recorra todas las rutas de FastAPI y falle si una no declara su permiso o su excepción. La política menciona `require_permission("dominio.accion")`; aquí **no** es una dependencia (ADR-07 solo permite `Depends` para el actor y la paginación) sino un metadato de la operación, que se publica en OpenAPI como extensión `x-security`:

```python
# insumap/api/security.py (se agrega)
from typing import Final

from insumap.domain.identity.permissions import PermissionCode

X_SECURITY: Final = "x-security"


def requires(permission: PermissionCode) -> dict[str, object]:
    return {X_SECURITY: {"permission": permission.value}}


def authenticated_only() -> dict[str, object]:
    """Actions on the own account (change password, logout, /auth/current-user): no permission."""
    return {X_SECURITY: {"authenticated_only": True}}


def public() -> dict[str, object]:
    """Login, activation, reset, field limits, health. Each one is reviewed (política 19)."""
    return {X_SECURITY: {"public": True}}
```

Cada operación lo declara en el registro de la ruta (`openapi_extra=requires(PermissionCode.PATIENTS_READ_ASSIGNED)`). El metadato **documenta**; quien impone el permiso es `actor.require()` en el caso de uso, y la prueba de matriz de [`testing-plan.md`](testing-plan.md), sección 6, comprueba el comportamiento real con los cinco actores.

```python
# tests/api/test_route_security.py
from fastapi import FastAPI
from fastapi.routing import APIRoute

from insumap.api.security import X_SECURITY
from insumap.domain.identity.permissions import PermissionCode

PUBLIC_ROUTES = frozenset(
    {
        ("POST", "/api/v1/auth/login"),
        ("GET", "/health"),
        ("GET", "/ready"),
        # ... only the public routes of Seguridad.md section 2.6; adding one needs review
    }
)
KNOWN_PERMISSIONS = frozenset(permission.value for permission in PermissionCode)


def _declaration(route: APIRoute) -> dict[str, object] | None:
    extra = route.openapi_extra or {}
    value = extra.get(X_SECURITY)
    return value if isinstance(value, dict) else None


def _operations(app: FastAPI) -> list[tuple[str, APIRoute]]:
    return [
        (method, route)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in sorted(route.methods)
    ]


def test_every_route_declares_a_permission_or_an_exception(app: FastAPI) -> None:
    undeclared = [f"{m} {r.path}" for m, r in _operations(app) if _declaration(r) is None]

    assert undeclared == []


def test_declared_permissions_exist_in_the_catalog(app: FastAPI) -> None:
    unknown = [
        f"{m} {r.path}"
        for m, r in _operations(app)
        if (d := _declaration(r)) and "permission" in d and d["permission"] not in KNOWN_PERMISSIONS
    ]

    assert unknown == []


def test_only_reviewed_routes_are_public(app: FastAPI) -> None:
    public = {(m, r.path) for m, r in _operations(app) if (d := _declaration(r)) and d.get("public")}

    assert public <= PUBLIC_ROUTES
```

La fixture `app` es `create_app(container_de_prueba)`. Las rutas de documentación (`/docs`, `/openapi.json`) no son `APIRoute` de la aplicación y quedan fuera del recorrido.

**Pruebas:** las tres de arriba, más `test_actor.py` (`require` deniega un permiso no concedido y concede uno concedido; `own_patient_id` sin paciente da `FORBIDDEN`), `test_ttl_cached_permission_lookup.py` (con `FixedClock`: dentro de 60 s no consulta; al avanzar, sí) y la de integración de que un cambio en `iam.role_permissions` surte efecto tras la caché. En API, la matriz (`testing-plan.md`, sección 6): un rol sin el permiso recibe `403` y no `404`.

**Antipatrones:** `if actor.role == Role.DOCTOR` (comparar nombres de rol: RF-07); permisos dentro del JWT; autorizar en el router; un endpoint sin declaración "porque es interno"; `Depends(require_permission(...))` por ruta.

## 11. Contexto de la RLS con `set_config`

- **Dónde vive:** `SqlAlchemyUnitOfWorkFactory` en `insumap/infrastructure/persistence/unit_of_work.py`. **Solo** la unidad de trabajo fija el contexto.
- **Regla:** justo después de abrir cada transacción se ejecuta `set_config('app.clinic_id', ..., true)`, `app.user_id` y `app.role` (la tercera es propuesta de la política, sección 6.2). El tercer parámetro `true` equivale a `SET LOCAL`: el valor dura hasta el `COMMIT` o el `ROLLBACK` y no se filtra entre peticiones que comparten una conexión del pool; además es compatible con el pooler de Neon en modo transacción. `set_config` acepta parámetros enlazados; `SET LOCAL` no. **Nunca** a nivel de conexión ni de sesión.
- **El contexto sale solo del JWT validado**, nunca de la ruta, el cuerpo, la consulta ni una cabecera.
- **Fallo cerrado:** si la transacción no fija el contexto, la política no devuelve filas.
- **Roles de BD:** la API se conecta como `insumap_app` (sin DDL y sin `BYPASSRLS`). El login dueño de Neon salta la RLS por diseño de la plataforma: la aplicación nunca lo usa.
- **`PLATFORM_ADMIN`** no tiene `clinic_id`: no se fija `app.clinic_id` (queda sin valor y no ve filas clínicas).

```python
# insumap/infrastructure/persistence/unit_of_work.py
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Final, final
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from insumap.application.common.actor import Actor

SETTING_CLINIC_ID: Final = "app.clinic_id"
SETTING_USER_ID: Final = "app.user_id"
SETTING_ROLE: Final = "app.role"


@dataclass(frozen=True, slots=True, kw_only=True)
class RlsContext:
    clinic_id: UUID | None
    user_id: UUID
    role: str

    @classmethod
    def for_actor(cls, actor: Actor) -> RlsContext:
        return cls(clinic_id=actor.clinic_id, user_id=actor.user_id, role=actor.role.value)

    def settings(self) -> list[tuple[str, str]]:
        pairs = [(SETTING_USER_ID, str(self.user_id)), (SETTING_ROLE, self.role)]
        if self.clinic_id is not None:
            pairs.insert(0, (SETTING_CLINIC_ID, str(self.clinic_id)))
        return pairs


def apply_rls_context(session: Session, context: RlsContext) -> None:
    """SELECT set_config(:name, :value, true), ... as bound parameters (never SET)."""
    session.execute(
        select(*[func.set_config(name, value, True) for name, value in context.settings()])
    )


@final
class SqlAlchemyUnitOfWorkFactory:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    @contextmanager
    def begin(self, actor: Actor) -> Iterator[Session]:
        """The request's transaction: the context is the first statement after BEGIN."""
        with self._sessions() as session, session.begin():
            apply_rls_context(session, RlsContext.for_actor(actor))
            yield session

    @contextmanager
    def begin_independent(self) -> Iterator[Session]:
        """Own transaction for what must survive an error (counters, DENIED rows, events)."""
        with self._sessions() as session, session.begin():
            yield session
```

`begin_independent()` no fija el contexto de la clínica: las tablas que escribe (`iam.rate_limit_buckets`, `iam.login_attempts`, `iam.security_events`, `audit.data_access_log` denegado) necesitan una política o una función `SECURITY DEFINER` que lo permita (propuesta para `insumap-database`). Para la fila `DENIED`, la política de inserción acepta el `clinic_id` del actor, así que esa transacción sí puede recibir el contexto del actor: `begin_independent(actor)` (ver sección 20).

El contexto de la **autenticación** se arma con los claims del JWT ya validado (`RlsContext` desde `AccessClaims`) antes de leer `iam.users` por clave primaria; las consultas previas a conocer la clínica (login, activación, refresh) usan las funciones `SECURITY DEFINER` de la política (6.2, punto 8).

**Pruebas de integración** (Testcontainers; sesiones con `insumap_app`, nunca con el superusuario de la imagen; la suite se detiene si `rolsuper` o `rolbypassrls` son verdaderos, `testing-plan.md` 4.2):

```python
# tests/integration/test_rls_context.py
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.integration


def test_without_context_no_rows_are_visible(app_session_factory, seeded_two_clinics) -> None:
    with app_session_factory() as session, session.begin():
        rows = session.execute(text("SELECT count(*) FROM monitoring.glucose_readings")).scalar_one()

    assert rows == 0


def test_context_of_one_clinic_hides_the_other(app_session_factory, seeded_two_clinics) -> None:
    uow = SqlAlchemyUnitOfWorkFactory(app_session_factory)
    with uow.begin(seeded_two_clinics.actor_a) as session:
        clinics = session.execute(
            text("SELECT DISTINCT clinic_id FROM monitoring.glucose_readings")
        ).scalars().all()

    assert clinics == [seeded_two_clinics.clinic_a_id]


def test_context_does_not_leak_to_the_next_transaction_of_the_same_connection(
    single_connection_session_factory, seeded_two_clinics
) -> None:
    uow = SqlAlchemyUnitOfWorkFactory(single_connection_session_factory)
    with uow.begin(seeded_two_clinics.actor_a):
        pass
    with single_connection_session_factory() as session, session.begin():
        leaked = session.execute(text("SELECT count(*) FROM monitoring.glucose_readings")).scalar_one()

    assert leaked == 0


def test_insert_for_another_clinic_fails_with_check(app_session_factory, seeded_two_clinics) -> None:
    uow = SqlAlchemyUnitOfWorkFactory(app_session_factory)
    with pytest.raises(DBAPIError), uow.begin(seeded_two_clinics.actor_a) as session:
        session.execute(seeded_two_clinics.insert_reading_statement(seeded_two_clinics.clinic_b_id))
```

Las fixtures (`app_session_factory`, `single_connection_session_factory` con `pool_size=1`, `seeded_two_clinics`) son de la fase de integración. Nota: tras la primera vez que una conexión usa `set_config(..., true)`, `current_setting('app.clinic_id', true)` devuelve **cadena vacía** (no `NULL`) fuera de la transacción; las políticas de `insumap-database` deben tratar `''` como "sin contexto" (`NULLIF(current_setting('app.clinic_id', true), '')`). Hay que verificarlo en la imagen de PostgreSQL 18 de las pruebas (sección 20).

**Pruebas unitarias** (sin BD): `test_rls_context.py` compila la sentencia con el dialecto de PostgreSQL y comprueba que contiene `set_config` con tres parámetros enlazados por variable y **ningún** `SET`, y que el contexto de un `PLATFORM_ADMIN` no incluye `app.clinic_id`.

**Antipatrones:** `SET app.clinic_id = ...` o `set_config(..., false)` (sobrevive al `COMMIT` y se filtra por el pool); fijar el contexto en un evento de conexión del pool; un `f"SET LOCAL app.clinic_id = '{clinic_id}'"`; usar `neondb_owner` o un rol con `BYPASSRLS`; leer el `clinic_id` de la ruta o del cuerpo.

## 12. `PatientRecordAccessProxy`: el equipo de atención

El esqueleto del proxy, de `PatientAccessPolicy` y del decorador de auditoría está en [`design-patterns.md`](design-patterns.md), P09 y P11. Esta sección fija las reglas de seguridad que deben cumplir y lo que se prueba.

| Rol del actor | Acceso concedido | Si se niega |
|---|---|---|
| `PATIENT` | Solo si `patient.user_id = actor.user_id` (permisos `*_own`) | `404 NOT_FOUND` |
| `DOCTOR` | Solo con una asignación vigente en `clinic.care_team_assignments` (sin `ended_at`, o con `ended_at` en el futuro) | `404 NOT_FOUND` (no revela que el paciente existe) |
| `CLINIC_ADMIN` | Solo la vista administrativa (`PatientAdministrativeView`, permiso `patients.read_roster`). Nunca datos H | `403 FORBIDDEN` en un método clínico |
| `PLATFORM_ADMIN` | Ninguno | `403 FORBIDDEN` |
| Cualquiera sobre un paciente de otra clínica | La RLS no devuelve la fila | `404 NOT_FOUND` |

Reglas:

1. El contenedor entrega **solo** `PatientRecordPort` armado como `PhiAccessAuditDecorator(PatientRecordAccessProxy(PatientRecordRepository))`. Ningún caso de uso ni fachada recibe el repositorio.
2. Un `404` por aislamiento es **idéntico** al de un recurso inexistente: mismo cuerpo, mismas cabeceras y tiempo comparable (la prueba compara los cuerpos byte a byte).
3. El `403` se decide **antes** de buscar el recurso (el permiso); el `404` después. Por eso un `CLINIC_ADMIN` que pide un endpoint clínico recibe `403` aunque el paciente no exista.
4. No hay acceso de emergencia (*break-glass*) en el MVP: un médico no asignado pide la asignación al admin.
5. Una asignación terminada deja de dar acceso en la siguiente lectura (V10); las decisiones previas del médico quedan en la auditoría.

La vista administrativa se lee por **otro** puerto, para que el admin nunca pase por el puerto clínico:

```python
# insumap/application/clinic/roster.py
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import final
from uuid import UUID

from insumap.application.common.actor import Actor
from insumap.domain.identity.permissions import PermissionCode


@dataclass(frozen=True, slots=True, kw_only=True)
class PatientAdministrativeView:
    """What a CLINIC_ADMIN may see: identity and account state, never clinical data (class H)."""

    patient_id: UUID
    full_name: str
    mrn: str
    document_last4: str
    account_state: str
    assigned_doctor_ids: tuple[UUID, ...]
    invitation_status: str | None


class PatientRosterPort(ABC):
    @abstractmethod
    def list_roster(self, actor: Actor) -> Sequence[PatientAdministrativeView]: ...


@final
class ListPatientRosterUseCase:
    def __init__(self, roster: PatientRosterPort) -> None:
        self._roster = roster

    def execute(self, actor: Actor) -> Sequence[PatientAdministrativeView]:
        actor.require(PermissionCode.PATIENTS_READ_ROSTER)
        return self._roster.list_roster(actor)
```

La lectura del listado registra **una fila por petición** (`resource_type = 'PATIENT_LIST'`), no una por paciente.

**Pruebas** (sección 19): las de `test_patient_record_access_proxy.py` de `design-patterns.md` y, en integración con dos clínicas, que un médico asignado ve, uno no asignado recibe `404` con el **mismo cuerpo** que un paciente inexistente, el admin recibe `403` en un endpoint clínico y solo la vista administrativa en el listado, y que una asignación terminada deja de dar acceso.

**Antipatrones:** verificar la asignación dentro de cada caso de uso; responder `403` a un médico no asignado; que el admin lea con `PatientRecordPort` "porque tiene permiso de lectura" (no lo tiene); sacar el `clinic_id` de la ruta.

## 13. Auditoría y eventos de seguridad

Tres registros con propósitos distintos (política 7):

| Registro | Qué guarda | Quién lo escribe | Transacción |
|---|---|---|---|
| `audit.data_access_log` | Cada **lectura** de datos H: quién, a quién, qué recurso, propósito, resultado, `request_id`, `ip_hmac` | `PhiAccessAuditDecorator` (P09) | Concedido: la **misma** de la lectura, antes de responder (fallo cerrado: si falla, la lectura falla). Denegado (`DENIED`): una **propia**, porque la de la petición se revierte |
| `audit.audit_log` | Cada **acción** que cambia seguridad o decisiones clínicas, con cadena de hashes por clínica | `AuditingCommandHandler` (P09) | La misma de la acción |
| `iam.security_events` | Hechos de seguridad con severidad (incluso sin clínica) | `SecurityEventRecorder` | **Propia** |

- **Minimización:** `audit_log` no copia valores clínicos: guarda `entity_type`, `entity_id`, versión, motivo y los **nombres** de los campos cambiados. `details` de un evento se escribe ya redactado (sección 14). El código de activación, los tokens y las contraseñas nunca se guardan ahí: solo el `invitation_id`.
- La cadena de hashes (`row_hash = sha256(prev_hash || contenido)`, con `pg_advisory_xact_lock` por clínica) la calcula un trigger de `insumap-database`; el backend solo la verifica con un trabajo diario (`audit.verify_chain`, propuesta) que registra `AUDIT_CHAIN_BROKEN` (crítica) si no coincide.
- Los eventos sin clínica (por ejemplo, un login fallido con un correo inexistente) van a `security_events` con `clinic_id` nulo y **nunca** a `audit_log`.
- Los esqueletos de P09 están en [`design-patterns.md`](design-patterns.md). Aquí está el de los eventos de seguridad y la huella de la IP.

```python
# insumap/application/security/events.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, final
from uuid import UUID


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SecurityEventType(StrEnum):
    AUDIT_CHAIN_BROKEN = "AUDIT_CHAIN_BROKEN"
    REFRESH_TOKEN_REUSE_DETECTED = "REFRESH_TOKEN_REUSE_DETECTED"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    MFA_RESET = "MFA_RESET"
    LLM_DATA_POLICY_BLOCKED = "LLM_DATA_POLICY_BLOCKED"
    MFA_FAILED = "MFA_FAILED"
    MFA_RECOVERY_CODE_USED = "MFA_RECOVERY_CODE_USED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    PHI_ACCESS_DENIED = "PHI_ACCESS_DENIED"
    ACTIVATION_LOCKED = "ACTIVATION_LOCKED"
    PUSH_ENDPOINT_REJECTED = "PUSH_ENDPOINT_REJECTED"
    CSRF_CHECK_FAILED = "CSRF_CHECK_FAILED"
    LOGIN_FAILED = "LOGIN_FAILED"
    ACCOUNT_UNLOCKED = "ACCOUNT_UNLOCKED"
    ACTIVATION_FAILED = "ACTIVATION_FAILED"
    ACCOUNT_ACTIVATED = "ACCOUNT_ACTIVATED"
    ROLE_CHANGED = "ROLE_CHANGED"
    RATE_LIMITED = "RATE_LIMITED"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"
    PASSWORD_RESET_REQUESTED = "PASSWORD_RESET_REQUESTED"
    SESSIONS_REVOKED = "SESSIONS_REVOKED"
    IMPORT_REJECTED = "IMPORT_REJECTED"
    SECRET_ROTATED = "SECRET_ROTATED"


SEVERITY_BY_EVENT: Final[dict[SecurityEventType, Severity]] = {
    SecurityEventType.AUDIT_CHAIN_BROKEN: Severity.CRITICAL,
    SecurityEventType.REFRESH_TOKEN_REUSE_DETECTED: Severity.HIGH,
    SecurityEventType.ACCOUNT_LOCKED: Severity.HIGH,
    SecurityEventType.MFA_RESET: Severity.HIGH,
    SecurityEventType.LLM_DATA_POLICY_BLOCKED: Severity.HIGH,
    SecurityEventType.MFA_FAILED: Severity.MEDIUM,
    SecurityEventType.MFA_RECOVERY_CODE_USED: Severity.MEDIUM,
    SecurityEventType.PERMISSION_DENIED: Severity.MEDIUM,
    SecurityEventType.PHI_ACCESS_DENIED: Severity.MEDIUM,
    SecurityEventType.ACTIVATION_LOCKED: Severity.MEDIUM,
    SecurityEventType.PUSH_ENDPOINT_REJECTED: Severity.MEDIUM,
    SecurityEventType.CSRF_CHECK_FAILED: Severity.MEDIUM,
    SecurityEventType.LOGIN_FAILED: Severity.LOW,
    SecurityEventType.ACCOUNT_UNLOCKED: Severity.LOW,
    SecurityEventType.ACTIVATION_FAILED: Severity.LOW,
    SecurityEventType.ACCOUNT_ACTIVATED: Severity.LOW,
    SecurityEventType.ROLE_CHANGED: Severity.LOW,
    SecurityEventType.RATE_LIMITED: Severity.LOW,
    SecurityEventType.PASSWORD_CHANGED: Severity.LOW,
    SecurityEventType.PASSWORD_RESET_REQUESTED: Severity.LOW,
    SecurityEventType.SESSIONS_REVOKED: Severity.LOW,
    SecurityEventType.IMPORT_REJECTED: Severity.LOW,
    SecurityEventType.SECRET_ROTATED: Severity.LOW,
}


@dataclass(frozen=True, slots=True, kw_only=True)
class SecurityEvent:
    event_type: SecurityEventType
    user_id: UUID | None
    clinic_id: UUID | None
    ip: str | None
    details: dict[str, object]


class SecurityEventPort(ABC):
    @abstractmethod
    def write(
        self,
        event: SecurityEvent,
        severity: Severity,
        ip_truncated: str | None,
        ip_hmac: str | None,
    ) -> None:
        """Own transaction. ``details`` arrive already redacted."""


@final
class SecurityEventRecorder:
    """Looks up the severity, fingerprints the IP and writes the event in its own transaction."""

    def __init__(self, port: SecurityEventPort, fingerprints: "IpFingerprinter") -> None:
        self._port = port
        self._fingerprints = fingerprints

    def record(self, event: SecurityEvent) -> None:
        ip = event.ip
        self._port.write(
            event,
            SEVERITY_BY_EVENT[event.event_type],
            self._fingerprints.truncate(ip) if ip else None,
            self._fingerprints.hmac(ip) if ip else None,
        )
```

```python
# insumap/application/security/ip.py
import ipaddress
from abc import ABC, abstractmethod

IPV4_PREFIX = 24
IPV6_PREFIX = 48


class IpFingerprinter(ABC):
    """``ip_hmac`` correlates attempts without storing the IP; ``ip_truncated`` is for the console."""

    @abstractmethod
    def hmac(self, ip: str) -> str: ...

    def truncate(self, ip: str) -> str:
        """/24 for IPv4 and /48 for IPv6 (política 7.3)."""
        address = ipaddress.ip_address(ip)
        prefix = IPV4_PREFIX if address.version == 4 else IPV6_PREFIX
        return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False))
```

`HmacIpFingerprinter` implementa `hmac()` con el `SubkeyHasher` de la subllave `ip` (sección 15.3). Un `SecurityEventPort` real aplica `SensitiveDataRedactor` a `details` antes de insertar.

**Pruebas:** `test_phi_access_audit_decorator.py` y `test_auditing_command_handler.py` (en `design-patterns.md`), `test_security_event_severity.py` (cada `SecurityEventType` tiene una severidad y la tabla coincide con la de la política 7.3), `test_ip_fingerprinter.py` (`203.0.113.77` queda `203.0.113.0/24`; IPv6 a /48; el HMAC cambia con la llave y no contiene la IP) y de integración: cada lectura H deja una fila en `data_access_log`; si la escritura de auditoría falla, la lectura falla; una acción sensible deja fila en `audit_log` y, si la acción falla, no deja la fila de éxito; `verify_chain` detecta una fila alterada (esta última prueba vive en `insumap-database`).

**Antipatrones:** auditar en un middleware HTTP (no ve al paciente); escribir la fila `DENIED` en la transacción de la petición (se pierde); registrar la IP en claro; poner valores clínicos o el cuerpo en `details`; que un fallo de auditoría se ignore.

## 14. Redacción de logs

- **Dónde vive:** `insumap/infrastructure/logging.py` (ya existe: `SensitiveDataRedactor`, `RedactionFilter`, `RequestIdFilter`, `JsonLogFormatter` y `JsonLoggingConfigurator`). El filtro está en el handler, así que cubre también los registros de las bibliotecas.
- **Nunca se registra:** cuerpos de petición ni de respuesta, ni la cadena de consulta; `Authorization`, `Cookie` y `Set-Cookie`; contraseñas, códigos, tokens, secretos ni llaves; datos C o H (nombres, documento, correo, teléfono, fecha de nacimiento, valores clínicos junto a un paciente, notas, mensajes, prompts y respuestas del LLM); IP en claro.
- **Campos del log** (política 11.1): `timestamp` (UTC), `level`, `logger`, `message`, `request_id`, `method`, `route` (la **plantilla**), `status`, `duration_ms`, `user_id`, `clinic_id` y `role`.

### 14.1 Lo que la política pide y el código aún no hace

La política (11.4) manda reemplazar por `[REDACTED]` el valor de toda clave que contenga `password`, `passwd`, `secret`, `token`, `authorization`, `cookie`, `code`, `otp`, `api_key`, `document`, `email`, `phone` o `birth` (sin distinguir mayúsculas) y enmascarar por patrón los JWT, `Bearer ...`, correos, los códigos Crockford con guiones y las secuencias de 6 o más dígitos. Hoy `SENSITIVE_KEY_PARTS` no tiene `code`, `otp`, `phone`, `birth` y tiene `document_number` en vez de `document`, y `redact_text` no enmascara los dos últimos patrones. El cambio mínimo:

```python
# insumap/infrastructure/logging.py (cambios propuestos)
SENSITIVE_KEY_PARTS: Final = (
    "password", "passwd", "secret", "token", "authorization", "cookie",
    "code", "otp", "api_key", "document", "email", "phone", "birth",
)  # fmt: skip
CROCKFORD_CODE_PATTERN: Final = re.compile(r"\b[0-9A-HJKMNP-TV-Z]{4,5}(?:-[0-9A-HJKMNP-TV-Z]{4,5})+\b")
LONG_DIGITS_PATTERN: Final = re.compile(r"(?<![\w-])\d{6,}(?![\w-])")


def redact_text(self, text: str) -> str:  # method of SensitiveDataRedactor
    text = JWT_PATTERN.sub(REDACTED_JWT, text)
    text = BEARER_PATTERN.sub(rf"\1 {REDACTED}", text)
    text = CROCKFORD_CODE_PATTERN.sub(REDACTED, text)
    text = LONG_DIGITS_PATTERN.sub(REDACTED, text)
    return EMAIL_PATTERN.sub(REDACTED_EMAIL, text)
```

`LONG_DIGITS_PATTERN` excluye los dígitos pegados a un guion o a una letra para **no** romper los UUID (`request_id`, `user_id`) que se registran en claro. La coincidencia por subcadena de `code` también enmascara claves como `status_code` o `error_code`: los campos del log usan `status` y los de error `error`, y un campo nuevo no debe llamarse con una de esas partes. La lista de [`Arquitectura.md`](../docs/Arquitectura.md) (sección 15) es distinta de la de la política (ver sección 20); esta guía sigue la de la política, que es la canónica para seguridad.

### 14.2 Configuración que completa el control

- **Access log propio:** el de uvicorn se desactiva (`--no-access-log`) porque registra la ruta con la consulta. Lo reemplaza un middleware ASGI de `infrastructure/logging` que registra la **plantilla** de la ruta (`scope["route"].path`), el método, el estado y `duration_ms`. `time.perf_counter` solo se permite en `infrastructure` para medir duraciones (`ARCH-09`).
- **SQLAlchemy:** `create_engine(url, echo=False, hide_parameters=True)`. Así los parámetros de las consultas, que pueden traer datos H, no salen en logs ni en los mensajes de las excepciones.
- **Errores de validación:** el manejador global ya quita `input` y `ctx` (`api/errors.py`); nunca se registran con esos campos. Una excepción no esperada registra la traza con el `request_id` y responde `500 INTERNAL_ERROR` sin traza ni nombre de clase; las excepciones de dominio no incluyen valores de entrada en su mensaje.
- **`request_id`:** la política (11.2) acepta el `X-Request-ID` entrante solo si es un UUID válido; `REQUEST_ID_PATTERN` lo exige y `REQUEST_ID_MAX_LENGTH` es 36.

**Pruebas:** `test_logging.py` (ya existe) crece con una tabla `parametrize` por cada parte de la lista (`Authorization`, `Cookie`, contraseña, código de activación, token, correo, documento, teléfono, fecha de nacimiento salen como `[REDACTED]`), con `caplog` en una petición real a la app de prueba y con las cuatro formas de enmascarar por patrón; una prueba de que un UUID no se altera; un error de validación no registra `input`; y `engine.hide_parameters` es verdadero.

```python
# tests/unit/infrastructure/test_logging.py (casos que se agregan)
import pytest

from insumap.infrastructure.logging import REDACTED, SensitiveDataRedactor


@pytest.mark.parametrize(
    "key",
    ["activation_code", "otp", "phone", "birth_date", "document", "Authorization", "Set-Cookie"],
)
def test_sensitive_keys_are_redacted(key: str) -> None:
    assert SensitiveDataRedactor().redact(key, "value") == REDACTED


@pytest.mark.parametrize("text", ["code 7K3F-9QXM-2D8H-WV4T", "otp 123456 sent", "id 12345678901"])
def test_sensitive_patterns_are_masked_in_free_text(text: str) -> None:
    masked = SensitiveDataRedactor().redact_text(text)

    assert "7K3F" not in masked and "123456" not in masked and "12345678901" not in masked


def test_uuid_is_not_altered() -> None:
    value = "request 3f2b8c1e-1234-4a5b-8c9d-0123456789ab done"

    assert SensitiveDataRedactor().redact_text(value) == value
```

**Antipatrones:** `logger.info("body=%s", await request.body())`; registrar `request.headers`; un `print` de depuración con datos; usar el access log de uvicorn; incluir el valor de glucosa en el mensaje (`"reading %s"`); un `extra={"email": ...}` "porque el filtro lo enmascara" (el filtro es la red de seguridad, no el control).


## 15. Columnas sensibles y gestión de llaves

- **Dónde vive:** las funciones puras de formato de llave en `insumap/shared/key_material.py` (solo `base64` y `hashlib`, para que `Settings` pueda validar sin importar otra capa); `KeyRing`, `SubkeyHasher` y `ColumnCipher` en `insumap/infrastructure/security/keys.py` y `column_cipher.py`; el puerto `ColumnCipherPort` en `insumap/application/security/ports.py`. `container.py` arma un `KeyRing` por cada llave de la tabla 2.4 y los entrega por constructor.
- **Qué se protege y cómo** (política 8): el documento del paciente (`ColumnCipher` con `FIELD_ENCRYPTION_KEY` más `document_hash` con `LOOKUP_HMAC_KEY`), el secreto TOTP (`ColumnCipher` con `MFA_ENCRYPTION_KEY`), los códigos de activación y de respaldo (`CodeHasher`, sección 8, con `CODE_HMAC_KEY`) y la IP y las claves de los contadores (`SubkeyHasher` con `APP_HMAC_KEY`). Contraseña y tokens opacos no usan llaves de aplicación (secciones 3 y 5).
- **Regla de la huella:** toda fila protegida guarda el `key_id` de la llave que la protegió. Sin él no hay rotación posible.

### 15.1 Formato de la llave y huella

Cada llave son 32 bytes en base64 (estándar o url-safe). El cargador exige exactamente 32 bytes decodificados y **nunca** repite el valor en el error. La huella son los primeros 16 caracteres hexadecimales de `SHA-256("insumap-key-id|" ‖ llave)`: identifica la llave sin revelarla y es lo que va en `kid`, en `*_key_id` y en los logs de rotación.

```python
# insumap/shared/key_material.py
import base64
import binascii
import hashlib
from typing import Final

KEY_BYTES: Final = 32
FINGERPRINT_PREFIX: Final = b"insumap-key-id|"
FINGERPRINT_HEX_CHARS: Final = 16
STANDARD_ALPHABET_FIX: Final = str.maketrans("-_", "+/")


def decode_key(encoded: str) -> bytes:
    """Decode standard or url-safe base64 into exactly KEY_BYTES; the error never echoes the value."""
    text = encoded.strip().translate(STANDARD_ALPHABET_FIX)
    text += "=" * (-len(text) % 4)
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("the key is not valid base64") from None
    if len(raw) != KEY_BYTES:
        raise ValueError(f"the key must decode to {KEY_BYTES} bytes")
    return raw


def key_fingerprint(key: bytes) -> str:
    """Public identifier of a key (``key_id``, JWT ``kid``)."""
    return hashlib.sha256(FINGERPRINT_PREFIX + key).hexdigest()[:FINGERPRINT_HEX_CHARS]
```

El marcador `cambia-esto-...` de `.env.example` **no** es base64 de 32 bytes: copiarlo tal cual hace que la API no arranque, que es lo que se quiere. Cada persona genera sus llaves de desarrollo con el comando del comentario de `.env.example` (sección 16.2).

### 15.2 `KeyRing`: actual y anterior

Un `KeyRing` agrupa la llave **actual** y, si existe, la **anterior** de una misma variable (`<NOMBRE>` y `<NOMBRE>_PREVIOUS`). La actual firma, cifra o hashea; las dos verifican, descifran o buscan.

- `current_key()` y `current_key_id`: lo que se usa para escribir.
- `verification_key(kid)`: la llave cuya huella es `kid`. Un `kid` desconocido o ausente lanza `KeyError`; `JwtTokenService.decode` lo convierte en `401` (sección 4). Una huella que ya no está en el anillo es una llave retirada: sus tokens y sus filas dejan de ser válidos.
- `all_keys()`: pares `(key_id, key)` con la actual primero, para búsquedas deterministas durante una rotación (`CodeHasher.hashes_for_lookup`, sección 8).
- La anterior no puede ser igual a la actual: se rechaza al construir (una rotación que no cambia nada es un error de despliegue).

```python
# insumap/infrastructure/security/keys.py
from typing import final

from pydantic import SecretStr

from insumap.shared.key_material import decode_key, key_fingerprint


@final
class KeyRing:
    def __init__(self, *, current: SecretStr, previous: SecretStr | None = None) -> None:
        current_key = decode_key(current.get_secret_value())
        self._current_id = key_fingerprint(current_key)
        self._keys: dict[str, bytes] = {self._current_id: current_key}
        if previous is not None:
            previous_key = decode_key(previous.get_secret_value())
            previous_id = key_fingerprint(previous_key)
            if previous_id == self._current_id:
                raise ValueError("the previous key must differ from the current one")
            self._keys[previous_id] = previous_key

    @property
    def current_key_id(self) -> str:
        return self._current_id

    def current_key(self) -> bytes:
        return self._keys[self._current_id]

    def verification_key(self, key_id: str | None) -> bytes:
        """The key with this fingerprint; unknown or missing raises KeyError (a retired key)."""
        if key_id is None or key_id not in self._keys:
            raise KeyError("unknown key id")
        return self._keys[key_id]

    def all_keys(self) -> tuple[tuple[str, bytes], ...]:
        """Current key first, then the previous one."""
        return tuple(self._keys.items())
```

(`dict` conserva el orden de inserción, así que la actual queda primero.) El contenedor construye `KeyRing(current=settings.jwt_secret, previous=settings.jwt_secret_previous)`; `LOOKUP_HMAC_KEY` y `APP_HMAC_KEY` no tienen anterior y usan `KeyRing(current=...)`.

### 15.3 `SubkeyHasher`: subllaves de `APP_HMAC_KEY`

`APP_HMAC_KEY` es una llave raíz: nunca se usa directa. Cada propósito deriva su subllave con HKDF-SHA256 y un `info` propio, así que una huella calculada para uno (por ejemplo la `ip`) no sirve para otro (el `subject_ref`). Las subllaves de la política son `ip`, `subject-ref` y `cursor`; `rate-limit` es propuesta (sección 9).

```python
# insumap/infrastructure/security/keys.py (se agrega)
import hashlib
import hmac
from enum import StrEnum

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

SUBKEY_BYTES = 32


def derive_subkey(root_key: bytes, info: bytes) -> bytes:
    """HKDF-SHA256 without salt; the same helper serves CodeHasher (sección 8)."""
    return HKDF(algorithm=hashes.SHA256(), length=SUBKEY_BYTES, salt=None, info=info).derive(root_key)


class Subkey(StrEnum):
    IP = "ip"
    SUBJECT_REF = "subject-ref"
    CURSOR = "cursor"
    RATE_LIMIT = "rate-limit"  # propuesto


@final
class SubkeyHasher:
    """HMAC-SHA256 with the subkey of one purpose; derived once, at construction."""

    def __init__(self, root_key: bytes, *, subkey: Subkey) -> None:
        self._subkey = derive_subkey(root_key, f"insumap/app-hmac/{subkey.value}/v1".encode())

    def hexdigest(self, message: str) -> str:
        return hmac.new(self._subkey, message.encode(), hashlib.sha256).hexdigest()
```

`HmacIpFingerprinter` (sección 13) recibe un `SubkeyHasher(Subkey.IP)` y calcula `hexdigest(str(ipaddress.ip_address(ip)))`: la forma canónica evita que dos escrituras de la misma IPv6 den huellas distintas. El `subject_ref` de la IA usa `Subkey.SUBJECT_REF` (sección 18).

### 15.4 `ColumnCipher`: AES-256-GCM con AAD

Formato de la política (8.1): `nonce (12 bytes) ‖ texto cifrado ‖ tag (16 bytes)` en `bytea`, nonce aleatorio por cifrado, y la AAD ata el valor a su fila. `AESGCM.encrypt` de `cryptography` ya devuelve `texto cifrado ‖ tag`, así que solo se antepone el nonce.

```python
# insumap/application/security/ports.py (se agrega)
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class SealedValue:
    """What is stored: the ciphertext blob and the fingerprint of the key that sealed it."""

    key_id: str
    blob: bytes


class ColumnDecryptionError(Exception):
    """Wrong AAD, altered blob or retired key. The message never carries the value."""


class ColumnCipherPort(ABC):
    @abstractmethod
    def encrypt(self, plaintext: str, *, aad: str) -> SealedValue: ...

    @abstractmethod
    def decrypt(self, value: SealedValue, *, aad: str) -> str: ...

    @abstractmethod
    def needs_reencryption(self, value: SealedValue) -> bool: ...
```

```python
# insumap/infrastructure/security/column_cipher.py
import secrets
from typing import Final, final, override
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from insumap.application.security.ports import ColumnCipherPort, ColumnDecryptionError, SealedValue
from insumap.infrastructure.security.keys import KeyRing

NONCE_BYTES: Final = 12
TAG_BYTES: Final = 16


def document_aad(*, patient_id: UUID, clinic_id: UUID) -> str:
    return f"clinic.patients.document|{patient_id}|{clinic_id}"


def mfa_secret_aad(*, factor_id: UUID, user_id: UUID) -> str:
    return f"iam.mfa_factors.secret|{factor_id}|{user_id}"


@final
class ColumnCipher(ColumnCipherPort):
    def __init__(self, keys: KeyRing) -> None:
        self._keys = keys

    @override
    def encrypt(self, plaintext: str, *, aad: str) -> SealedValue:
        nonce = secrets.token_bytes(NONCE_BYTES)
        sealed = AESGCM(self._keys.current_key()).encrypt(nonce, plaintext.encode(), aad.encode())
        return SealedValue(key_id=self._keys.current_key_id, blob=nonce + sealed)

    @override
    def decrypt(self, value: SealedValue, *, aad: str) -> str:
        if len(value.blob) < NONCE_BYTES + TAG_BYTES:
            raise ColumnDecryptionError
        try:
            key = self._keys.verification_key(value.key_id)
            nonce, sealed = value.blob[:NONCE_BYTES], value.blob[NONCE_BYTES:]
            return AESGCM(key).decrypt(nonce, sealed, aad.encode()).decode()
        except (KeyError, InvalidTag, UnicodeDecodeError):
            raise ColumnDecryptionError from None

    @override
    def needs_reencryption(self, value: SealedValue) -> bool:
        return value.key_id != self._keys.current_key_id
```

Reglas de uso:

- **Una instancia por llave**, no una compartida: el contenedor crea `ColumnCipher(field_keys)` para el documento y `ColumnCipher(mfa_keys)` para el TOTP. Una fila cifrada con la llave del documento no se descifra con la del MFA aunque alguien se equivoque de instancia.
- **La AAD sale de la fila ya guardada** (`patient_id`, `clinic_id`), nunca de la petición. Cambiarla al descifrar es exactamente lo que detecta GCM.
- **Cada descifrado del documento queda en `audit.data_access_log` con `action = 'DECRYPT'`** (política 8.1), dentro de la misma transacción: si la auditoría falla, el descifrado falla (sección 13). Solo se descifra para exportar los datos del propio paciente o devolverlos a la clínica; ninguna respuesta incluye el documento completo (se muestra `document_last4`).
- `ColumnDecryptionError` es un error interno: llega a `500 INTERNAL_ERROR` y se registra con el `key_id` y el nombre de la columna, **nunca** con el blob ni el texto.

### 15.5 `document_hash` y `document_last4`

`document_hash` es `HMAC-SHA256(LOOKUP_HMAC_KEY, clinic_id ‖ 0x1F ‖ document_type ‖ 0x1F ‖ número_normalizado)` en hexadecimal; sirve para buscar y deduplicar sin descifrar. La llave se usa **directa**, sin HKDF (así lo fija la política); el `clinic_id` dentro del mensaje impide correlacionar a una persona entre clínicas. El número llega ya normalizado por la validación de entrada: el hash y la comparación deben ver exactamente la misma cadena.

```python
# insumap/infrastructure/security/document_protector.py
import hashlib
import hmac
from dataclasses import dataclass
from typing import Final, final
from uuid import UUID

from insumap.application.security.ports import ColumnCipherPort, SealedValue
from insumap.infrastructure.security.column_cipher import document_aad
from insumap.infrastructure.security.keys import KeyRing

FIELD_SEPARATOR: Final = b"\x1f"
LAST_CHARS: Final = 4


@dataclass(frozen=True, slots=True, kw_only=True)
class ProtectedDocument:
    """The five columns of ``clinic.patients`` that replace the plain document."""

    document_hash: str
    document_hash_key_id: str
    document_sealed: SealedValue
    document_last4: str


@final
class DocumentProtector:
    def __init__(self, *, cipher: ColumnCipherPort, lookup_keys: KeyRing) -> None:
        self._cipher = cipher
        self._lookup = lookup_keys

    def lookup_hash(self, *, clinic_id: UUID, document_type: str, number: str) -> str:
        message = FIELD_SEPARATOR.join([str(clinic_id).encode(), document_type.encode(), number.encode()])
        return hmac.new(self._lookup.current_key(), message, hashlib.sha256).hexdigest()

    def protect(
        self, *, patient_id: UUID, clinic_id: UUID, document_type: str, number: str
    ) -> ProtectedDocument:
        return ProtectedDocument(
            document_hash=self.lookup_hash(clinic_id=clinic_id, document_type=document_type, number=number),
            document_hash_key_id=self._lookup.current_key_id,
            document_sealed=self._cipher.encrypt(
                number, aad=document_aad(patient_id=patient_id, clinic_id=clinic_id)
            ),
            document_last4=number[-LAST_CHARS:],
        )
```

**Pruebas (sección 19):** `test_key_material.py` (31, 32 y 33 bytes; base64 estándar y url-safe equivalentes; texto que no es base64; el mensaje de error no contiene el valor; la huella tiene 16 caracteres hexadecimales y cambia con un byte), `test_key_ring.py` (la actual firma; la anterior verifica; `kid` desconocido o `None` lanza `KeyError`; anterior igual a actual se rechaza; `all_keys()` pone la actual primero), `test_subkey_hasher.py` (determinista; dos subllaves dan resultados distintos para el mismo mensaje; cambia con la llave raíz), `test_column_cipher.py` (el mismo texto da dos blobs distintos; descifrar con otra AAD falla; un byte alterado falla; blob corto falla; una llave retirada falla; la fila sellada con la anterior se descifra y `needs_reencryption` es verdadero), `test_document_protector.py` (mismo documento en dos clínicas: hashes distintos; el hash no cambia con el orden de llamadas; `document_last4` son los cuatro últimos) y de integración que `clinic.patients` no contiene el documento en claro.

**Antipatrones:** usar `AESGCM` o `Fernet` directo en un repositorio; un nonce derivado del contenido o de un contador sin llave; AAD vacía; guardar el texto cifrado sin `key_id`; usar `APP_HMAC_KEY` o `JWT_SECRET` sin derivar, o la misma llave para dos propósitos; comparar huellas con `==` cuando son secretos (los `key_id` no lo son); capturar `InvalidTag` y devolver un valor por defecto; registrar el blob o el texto en un mensaje de error.

## 16. Rotación de llaves, secretos y configuración de arranque

### 16.1 Rotación con `*_PREVIOUS`

La política (8.3) fija el procedimiento por llave; el código lo respalda así:

| Llave | Qué debe hacer el código | Cuándo se retira la anterior |
|---|---|---|
| `JWT_SECRET` | `JwtTokenService` firma con la actual y acepta la anterior por `kid` (sección 4). Sin trabajo extra | Pasados `JWT_ACCESS_MINUTES` más `JWT_LEEWAY_SECONDS` |
| `FIELD_ENCRYPTION_KEY`, `MFA_ENCRYPTION_KEY` | Job de recifrado (abajo) | Cuando ninguna fila tenga la huella de la anterior |
| `CODE_HMAC_KEY` | `CodeHasher.hashes_for_lookup` busca con las dos (sección 8); los códigos de respaldo con la huella vieja se invalidan y la UI pide regenerarlos | Cuando no queden invitaciones vigentes con esa huella (7 días) |
| `LOOKUP_HMAC_KEY` (sin anterior) | `RecomputeDocumentHashesJob`: descifra, recalcula con la llave nueva y actualiza `document_hash_key_id`. Hasta terminar, la búsqueda por documento falla para las filas pendientes; se corre en una ventana acordada (propuesto) | No aplica |
| `APP_HMAC_KEY` (sin anterior) | Nada: los `ip_hmac` dejan de ser comparables, los cursores vencen y cambian los `subject_ref`. Se documenta la discontinuidad | No aplica |

El recifrado es un caso de uso de `application/jobs` que habla con un puerto por columna, así que no importa SQLAlchemy ni `cryptography`:

```python
# insumap/application/jobs/reencrypt_column.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import final
from uuid import UUID

from insumap.application.security.ports import ColumnCipherPort, SealedValue


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredCiphertext:
    row_id: UUID
    aad: str
    value: SealedValue


class EncryptedColumnPort(ABC):
    """One encrypted column, e.g. clinic.patients.document or iam.mfa_factors.secret."""

    name: str

    @abstractmethod
    def fetch_stale(self, *, current_key_id: str, limit: int) -> list[StoredCiphertext]:
        """Rows whose key_id is not the current one (FOR UPDATE SKIP LOCKED, propuesto)."""

    @abstractmethod
    def replace(self, row_id: UUID, value: SealedValue) -> None: ...

    @abstractmethod
    def count_sealed_with(self, key_id: str) -> int: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ReencryptionReport:
    column: str
    rows_reencrypted: int
    rows_left_with_previous_key: int


@final
class ReencryptColumnUseCase:
    def __init__(self, *, column: EncryptedColumnPort, cipher: ColumnCipherPort, current_key_id: str,
                 previous_key_id: str, batch_size: int) -> None:  # fmt: skip
        self._column = column
        self._cipher = cipher
        self._current_key_id = current_key_id
        self._previous_key_id = previous_key_id
        self._batch_size = batch_size

    def execute(self) -> ReencryptionReport:
        done = 0
        while batch := self._column.fetch_stale(current_key_id=self._current_key_id, limit=self._batch_size):
            for stored in batch:
                plain = self._cipher.decrypt(stored.value, aad=stored.aad)
                self._column.replace(stored.row_id, self._cipher.encrypt(plain, aad=stored.aad))
                done += 1
        return ReencryptionReport(
            column=self._column.name,
            rows_reencrypted=done,
            rows_left_with_previous_key=self._column.count_sealed_with(self._previous_key_id),
        )
```

Reglas del job: **idempotente** (se puede repetir y retomar tras un corte), **por lotes** con una transacción por lote (nunca una gigante), sin registrar el texto en claro y sin que la fila quede sin cifrar en ningún momento. La BD necesita que `insumap_app` pueda leer y actualizar esas columnas de **todas** las clínicas sin contexto: es una función `SECURITY DEFINER` o una política de mantenimiento de `insumap-database` (propuesta; ver sección 21 de la política). El job devuelve el informe y **un comando de la aplicación** (`RotateSecretCommand`, P13, auditado) registra `SECRET_ROTATED` con el nombre de la llave y las huellas, nunca con los valores. La anterior se retira cuando `rows_left_with_previous_key` es `0`.

### 16.2 Secretos y configuración (política 14)

- **`Settings` valida las llaves al arrancar.** Cada llave es un `SecretStr` **sin valor por defecto** con un validador que llama a `decode_key`; la anterior es opcional (`None`, y una cadena vacía cuenta como ausente). Con `hide_input_in_errors=True` (ya activo) el error nombra el campo y nunca el valor. Si una llave falta o no mide 32 bytes, la API no arranca.
- **`KeyRing` y `Settings` no duplican la validación:** ambos usan `decode_key`; `Settings` rechaza además que la anterior sea igual a la actual y que dos propósitos compartan la misma llave (propuesto).
- **El contenedor es el único que abre los `SecretStr`** para armar los `KeyRing`; nada más llama a `get_secret_value()` sobre una llave.

```python
# insumap/shared/config.py (se agrega)
from pydantic import AfterValidator, BeforeValidator, model_validator

from insumap.shared.key_material import decode_key


def require_key(value: SecretStr) -> SecretStr:
    decode_key(value.get_secret_value())
    return value


def blank_to_none(value: object) -> object:
    return None if isinstance(value, str) and not value.strip() else value


type KeySecret = Annotated[SecretStr, AfterValidator(require_key)]
type PreviousKeySecret = Annotated[KeySecret | None, BeforeValidator(blank_to_none)]

# dentro de Settings (sin valor por defecto: ninguna llave tiene uno)
#     jwt_secret: KeySecret
#     jwt_secret_previous: PreviousKeySecret = None
#     field_encryption_key: KeySecret
#     field_encryption_key_previous: PreviousKeySecret = None
#     mfa_encryption_key: KeySecret
#     mfa_encryption_key_previous: PreviousKeySecret = None
#     code_hmac_key: KeySecret
#     code_hmac_key_previous: PreviousKeySecret = None
#     lookup_hmac_key: KeySecret
#     app_hmac_key: KeySecret
#     allowed_hosts: Annotated[list[str], NoDecode]   # sin valor por defecto (sección 17)
#     llm_real_data_allowed: bool = False
```

```python
# insumap/container.py (fragmento)
self.jwt_keys = KeyRing(current=settings.jwt_secret, previous=settings.jwt_secret_previous)
self.document_cipher = ColumnCipher(
    KeyRing(current=settings.field_encryption_key, previous=settings.field_encryption_key_previous)
)
self.ip_fingerprinter = HmacIpFingerprinter(
    SubkeyHasher(decode_key(settings.app_hmac_key.get_secret_value()), subkey=Subkey.IP)
)
```

- **`.env.example`** lista cada variable con `cambia-esto-...` y, en un comentario, el comando que la genera (`openssl rand -base64 32`; el token de servicio, `python -c "import secrets; print(secrets.token_urlsafe(32))"`). Nunca lleva un valor real, y `.env` y `.env.*` (salvo el ejemplo) están en `.gitignore`.
- **Secreto o llave nueva, en el mismo PR:** campo en `Settings`, fila en `.env.example`, fila en la tabla 6.1 de [`configuration.md`](configuration.md), fila en la tabla 2.4 de esta guía y, si es llave, fila en la 8.3 de la política y una entrada en 16.1.
- **Dónde viven:** variables de Render con `sync: false` en `render.yaml`; en Vercel solo `VITE_*` públicas; en los secretos de GitHub Actions solo lo que la CI necesite (las pruebas con Testcontainers no necesitan ninguno). La imagen Docker nunca los contiene: `.dockerignore` excluye `.env*` y el contenedor corre sin privilegios ([`deployment.md`](deployment.md)).
- **Perfil de pruebas:** `tests/support/keys.py` define constantes de llaves de prueba (32 bytes en base64, claramente falsas) y `make_settings` las incluye por defecto, para que agregar un campo secreto no rompa las pruebas existentes.
- **Filtración:** se rota de inmediato (16.1), se revoca lo que dependa de la llave y se abre un incidente (política 17).

**Pruebas:** `test_settings.py` crece con una prueba por secreto de que **falta** (`ValidationError` que nombra el campo y no contiene un valor sembrado), una de longitud incorrecta, una de la anterior igual a la actual y una de que `repr(settings)` no muestra ninguna llave; `test_reencrypt_column_use_case.py` con un puerto en memoria (recifra todo, es idempotente, se retoma tras un corte simulado, el informe cuenta las filas que quedan con la anterior); y una prueba de integración de la rotación completa: sellar con A, rotar a B con A como anterior, recifrar y descifrar solo con B.

**Antipatrones:** un valor por defecto en un secreto "para desarrollo"; `os.getenv("JWT_SECRET")` fuera de `Settings`; `get_secret_value()` en un log o en un `f-string`; retirar la anterior sin contar las filas; recifrar dentro de la transacción de una petición; el job registrando texto en claro; una llave de desarrollo reutilizada en producción.

## 17. Superficie HTTP: cabeceras, CORS, hosts y tamaño de cuerpo

- **Dónde vive:** `insumap/api/middleware.py` (ya tiene `RequestIdMiddleware` y `BodySizeLimitMiddleware`) y `create_app` en `insumap/main.py`. Los valores fijos de la política (13) son constantes con nombre; los que cambian por entorno (`CORS_ORIGINS`, `ALLOWED_HOSTS`) salen de `Settings`.
- **Un solo lugar por control:** un middleware ASGI por cabecera o límite, no código repetido en los routers. Un router nunca pone una cabecera de seguridad.

### 17.1 Cabeceras de seguridad

`SecurityHeadersMiddleware` agrega las cabeceras de la tabla 13.1 de la política a **toda** respuesta HTTP, incluidos los errores y las respuestas de los demás middleware (por eso es el más externo). Usa `setdefault`: una ruta que necesita otro valor lo fija ella misma (`GET /meta/field-limits` envía `Cache-Control: public, max-age=300`).

| Cabecera | Valor en la API |
|---|---|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` (sin `preload`) |
| `Content-Security-Policy` | `default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'` |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `no-referrer` |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=(), payment=(), usb=()` |
| `Cross-Origin-Resource-Policy` | `same-site` |
| `Cache-Control` | `no-store` en toda respuesta de `/api/v1` |
| `Server`, `X-Powered-By` | Ausentes (uvicorn con `--no-server-header`; el middleware además borra `server`) |

`/docs` carga recursos de `cdn.jsdelivr.net` y usa un script en línea, así que la CSP estricta lo rompe. La política propone servir esos recursos desde la API con un *nonce* y, mientras tanto, una CSP relajada **solo** en las rutas de Swagger (por verificar al integrarla). El esqueleto no pone CSP en esas rutas y deja el valor relajado como pendiente.

```python
# insumap/api/middleware.py (se agrega)
from collections.abc import Mapping
from typing import Final, final

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from insumap.api.openapi import DOCS_URL, OPENAPI_URL

API_PREFIX: Final = "/api/v1"
HSTS_MAX_AGE_SECONDS: Final = 31_536_000
DOCS_PATHS: Final = frozenset({DOCS_URL, OPENAPI_URL})
SERVER_HEADER: Final = "server"
API_CONTENT_SECURITY_POLICY: Final = (
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)
FIXED_HEADERS: Final[Mapping[str, str]] = {
    "Strict-Transport-Security": f"max-age={HSTS_MAX_AGE_SECONDS}; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Resource-Policy": "same-site",
}


@final
class SecurityHeadersMiddleware:
    """Adds the security headers of política 13.1 to every response; routes may override one."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != HTTP_SCOPE:
            await self._app(scope, receive, send)
            return
        path = str(scope["path"])

        async def send_with_headers(message: Message) -> None:
            if message["type"] == HTTP_RESPONSE_START_MESSAGE:
                headers = MutableHeaders(scope=message)
                for name, value in FIXED_HEADERS.items():
                    headers.setdefault(name, value)
                if path not in DOCS_PATHS:  # Swagger gets its own, relaxed CSP (pending)
                    headers.setdefault("Content-Security-Policy", API_CONTENT_SECURITY_POLICY)
                if path.startswith(API_PREFIX):
                    headers.setdefault("Cache-Control", "no-store")
                del headers[SERVER_HEADER]
            await send(message)

        await self._app(scope, receive, send_with_headers)
```

### 17.2 CORS y hosts

`create_app` ya monta `CORSMiddleware` con la lista explícita y `Settings` rechaza `*`. Lo que la política pide y el código aún no tiene está en la sección 20. La configuración completa:

```python
# insumap/main.py (cambios propuestos)
from starlette.middleware.trustedhost import TrustedHostMiddleware

CORS_ALLOWED_HEADERS: Final = [
    "Authorization", "Content-Type", "X-Requested-With", REQUEST_ID_HEADER, "Idempotency-Key",
]  # fmt: skip
CORS_EXPOSED_HEADERS: Final = [REQUEST_ID_HEADER, "Retry-After"]
CORS_MAX_AGE_SECONDS: Final = 600

# Orden de montaje: el último que se agrega es el más externo.
app.add_middleware(BodySizeLimitMiddleware, responses=container.error_responses, limits=container.body_limits)
app.add_middleware(RequestIdMiddleware)
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=CORS_ALLOWED_METHODS,
        allow_headers=CORS_ALLOWED_HEADERS,
        expose_headers=CORS_EXPOSED_HEADERS,
        max_age=CORS_MAX_AGE_SECONDS,
    )
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.add_middleware(SecurityHeadersMiddleware)
```

- `allow_credentials=True` solo con esa lista. En producción la lista tiene únicamente el origen del frontend (despliegue en el mismo sitio, política 2.5).
- `ALLOWED_HOSTS` no tiene valor por defecto (sin él, cualquier `Host` pasaría). En desarrollo se declara `localhost,127.0.0.1` en `.env`.
- El orden importa: `SecurityHeadersMiddleware` envuelve a todos, `TrustedHostMiddleware` rechaza el `Host` ajeno antes de gastar trabajo, CORS envuelve a `RequestIdMiddleware` y al límite de cuerpo (así el navegador lee también el `413`) y el límite de cuerpo va pegado a la app.
- TLS 1.2 o superior y `sslmode=verify-full` hacia Neon son de despliegue ([`deployment.md`](deployment.md)); aquí solo se valida que `DATABASE_URL` en producción lo traiga (propuesto: el validador de `Settings` lo exige cuando `APP_ENV=production`).

### 17.3 Tamaño del cuerpo por ruta

El límite de la política no es uno solo: 64 KiB en general, 512 KiB y 500 elementos en el lote offline, y 2 MiB a 10 MiB en las importaciones, que se leen como cuerpo crudo contando bytes. `BodySizeLimitMiddleware` ya cuenta el *stream* aunque falte o mienta `Content-Length`; lo que falta es que el tope dependa de la ruta. Se resuelve con una tabla de reglas que arma el contenedor con constantes de `FieldLimits` (las del lote y las importaciones son propuestas: hoy solo existe `MAX_REQUEST_BODY_BYTES`).

```python
# insumap/api/body_limits.py
import re
from dataclasses import dataclass
from typing import final


@dataclass(frozen=True, slots=True, kw_only=True)
class BodyLimitRule:
    method: str
    path_pattern: re.Pattern[str]
    max_bytes: int


@final
class BodyLimitResolver:
    """First matching rule wins; anything else gets the general limit."""

    def __init__(self, rules: tuple[BodyLimitRule, ...], *, default_max_bytes: int) -> None:
        self._rules = rules
        self._default = default_max_bytes

    def limit_for(self, method: str, path: str) -> int:
        for rule in self._rules:
            if rule.method == method and rule.path_pattern.fullmatch(path):
                return rule.max_bytes
        return self._default
```

El middleware recibe el `BodyLimitResolver` en lugar de `max_body_bytes` y pregunta `limits.limit_for(scope["method"], scope["path"])`. Una ruta nueva con un cuerpo grande **debe** agregar su regla: sin ella se aplica el tope general. Las reglas de importación de la política (13.3) completan el control en el router: `Content-Type` exacto (`application/fhir+json`, `text/csv`) o `415 UNSUPPORTED_MEDIA_TYPE`, sin multipart, solo UTF-8 y sin archivos comprimidos. La cabecera `Authorization` de más de `AUTH_HEADER_MAX_BYTES` se rechaza en `CurrentActor` (sección 4).

### 17.4 Salidas: CSV, push, PDF y correo

- **CSV exportado:** toda **celda de texto** que empiece con `=`, `+`, `-`, `@`, tabulador o retorno de carro se prefija con `'`. Los números se escriben como números, no como texto (un `-5` numérico no es una fórmula).
- **Endpoint de push** (lo manda el navegador, es dato no confiable): solo `https`, host en `PUSH_ENDPOINT_ALLOWED_HOSTS`, sin IP literales ni credenciales en la URL, sin seguir redirecciones y con timeout de 5 segundos (`PUSH_TIMEOUT_SECONDS`, propuesto; la política fija el 5). Un rechazo registra `PUSH_ENDPOINT_REJECTED`.
- **PDF y HTML:** plantillas con autoescape y un `url_fetcher` que solo admite recursos empaquetados (sin SSRF ni lectura de archivos). **Correo:** Jinja2 con `autoescape=True`, `email.message.EmailMessage` (ningún encabezado con datos del usuario) y asunto y cuerpo sin valores clínicos ni documento. **Web Push:** carga visible sin valores clínicos.

```python
# insumap/infrastructure/export/csv_cells.py
from typing import Final

FORMULA_PREFIXES: Final = ("=", "+", "-", "@", "\t", "\r")
ESCAPE_PREFIX: Final = "'"


def neutralize_text_cell(value: str) -> str:
    """Stop spreadsheets from reading a text cell as a formula (CSV injection)."""
    return f"{ESCAPE_PREFIX}{value}" if value.startswith(FORMULA_PREFIXES) else value
```

```python
# insumap/infrastructure/notifications/push_endpoint_policy.py
import fnmatch
import ipaddress
from typing import final
from urllib.parse import urlsplit


@final
class PushEndpointPolicy:
    """Decides whether a browser-supplied push endpoint may be called."""

    def __init__(self, allowed_hosts: tuple[str, ...]) -> None:
        self._allowed = tuple(host.lower() for host in allowed_hosts)

    def is_allowed(self, endpoint: str) -> bool:
        try:
            parts = urlsplit(endpoint)
            host = (parts.hostname or "").lower()
        except ValueError:
            return False
        if parts.scheme != "https" or not host or parts.username or parts.password:
            return False
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return any(fnmatch.fnmatchcase(host, pattern) for pattern in self._allowed)
        return False  # IP literals are never accepted
```

`*.notify.windows.com` coincide con subdominios, no con el dominio desnudo: esa es la lista de la política y no se amplía. El cliente HTTP del envío se crea con `follow_redirects=False` y `timeout` desde `Settings`.

**Pruebas (sección 19):** `test_security_headers.py` (una petición a un endpoint y a una ruta inexistente trae todas las cabeceras de la tabla; un error `413` y un `500` también; `Cache-Control: no-store` bajo `/api/v1`, y `public, max-age=300` en `meta/field-limits`; no hay `Server`), `test_cors.py` (un origen fuera de `CORS_ORIGINS` no recibe `Access-Control-Allow-Origin`; el *preflight* de uno permitido devuelve los métodos, las cabeceras y `max_age` de la política; `Retry-After` está expuesta; `*` en la lista impide el arranque), `test_trusted_host.py` (un `Host` ajeno se rechaza), `test_body_limit_resolver.py` y `test_middleware.py` (64 KiB pasa y 64 KiB + 1 da `413`, con y sin `Content-Length`, con `Content-Length` mentiroso; el lote acepta 512 KiB; el `413` lleva `X-Request-ID` y las cabeceras CORS), `test_csv_cells.py` (`=HYPERLINK(...)`, `+1`, `@x`, tabulador y retorno de carro quedan con `'`; un texto normal no cambia) y `test_push_endpoint_policy.py` (`http://`, IP literal, `https://fcm.googleapis.com@evil.test`, host fuera de la lista y `*.notify.windows.com` sin subdominio se rechazan; los hosts de la lista pasan).

**Antipatrones:** poner cabeceras de seguridad en un router; `allow_origins=["*"]` o `allow_origin_regex=".*"`; `allow_credentials=True` con una lista que no controlamos; confiar en `Content-Length` sin contar los bytes; subir el límite global para que quepa una importación (una regla por ruta); aceptar el `endpoint` de push y llamarlo con `follow_redirects=True`; construir un CSV con `f"{a},{b}"` en vez de `csv.writer`; relajar la CSP de toda la API por culpa de Swagger.

## 18. Minimización y token de servicio hacia `insumap-ai`

- **Dónde vive:** `SubjectRef` y `KnownIdentifierRedactor` en `insumap/domain/ai/`; `HmacPseudonymizer` y `ServiceTokenAuth` en `insumap/infrastructure/ai/`; `LlmDataPolicy` y la validación de la salida en `insumap/application/ai/`. `AiServiceClientAdapter` (P06) es la **única** clase que conoce el JSON de `insumap-ai` ([`architecture.md`](architecture.md)); `RemoteAiServiceProxy` (P11) aplica el circuit breaker y el respaldo. El contrato es [`Contrato-IA.md`](../docs/Contrato-IA.md).
- **Principio** (política 9): `insumap-ai` es un servicio sin estado que recibe lo mínimo y **nunca** un identificador directo. El control es una lista blanca: el adaptador arma el cuerpo campo por campo desde un modelo de entrada propio; no serializa una entidad ni un `*Orm`.

### 18.1 `subject_ref`: el seudónimo

`"sub_"` más los primeros 32 caracteres hexadecimales de `HMAC-SHA256(subllave "subject-ref" de APP_HMAC_KEY, patient_id)`. Es determinista (la IA puede correlacionar llamadas del mismo paciente) y no reversible sin la llave. Rotar `APP_HMAC_KEY` cambia todos los seudónimos (sección 16.1).

```python
# insumap/domain/ai/subject_ref.py
import re
from dataclasses import dataclass
from typing import Final

SUBJECT_REF_PATTERN: Final = re.compile(r"sub_[0-9a-f]{32}")
SUBJECT_REF_PREFIX: Final = "sub_"
SUBJECT_REF_HEX_CHARS: Final = 32


@dataclass(frozen=True, slots=True)
class SubjectRef:
    value: str

    def __post_init__(self) -> None:
        if not SUBJECT_REF_PATTERN.fullmatch(self.value):
            raise ValueError("a subject ref must match ^sub_[0-9a-f]{32}$")
```

```python
# insumap/infrastructure/ai/pseudonymizer.py
from typing import final
from uuid import UUID

from insumap.domain.ai.subject_ref import SUBJECT_REF_HEX_CHARS, SUBJECT_REF_PREFIX, SubjectRef
from insumap.infrastructure.security.keys import SubkeyHasher


@final
class HmacPseudonymizer:
    def __init__(self, hasher: SubkeyHasher) -> None:  # built with Subkey.SUBJECT_REF
        self._hasher = hasher

    def subject_ref(self, patient_id: UUID) -> SubjectRef:
        digest = self._hasher.hexdigest(str(patient_id))
        return SubjectRef(f"{SUBJECT_REF_PREFIX}{digest[:SUBJECT_REF_HEX_CHARS]}")
```

### 18.2 Qué sale y qué nunca sale

| Se envía | Nunca se envía |
|---|---|
| `subject_ref`; series en mg/dL, dosis, carbohidratos, actividad, códigos de síntomas, métricas, metas y `clinic_timezone`; marcas de tiempo ISO-8601 con offset | Nombres, documento, MRN, correo, teléfono, dirección, `patient_id`, `user_id`, fecha de nacimiento, nombre de la clínica o del personal, IP y datos de sesión, notas y mensajes en texto libre (salvo los campos redactados) |

- **Texto libre redactado dos veces** (IA6 y los `detail` o `description` que viajen). Primero el backend reemplaza con marcadores los identificadores **conocidos** de ese paciente; después `insumap-ai` aplica `PhiRedactingTextGenerator`. La validación de entrada ya rechazó los caracteres de formato, incluidos los *tag* Unicode U+E0000 a U+E007F (*ASCII smuggling*).
- **Capa gratuita = solo datos simulados o seudonimizados.** `LlmDataPolicy` decide: una clínica con `is_demo = false` **no** se envía a los endpoints que usan el LLM (IA5 e IA6) mientras `LLM_REAL_DATA_ALLOWED=false`; se usa el respaldo determinista y se registra `LLM_DATA_POLICY_BLOCKED` (alta) en `security_events`.
- **Consentimiento:** IA6 con LLM externo exige `ai_external_processing`; sin él, respuestas predefinidas.
- **Cada envío de datos de un paciente a `insumap-ai` queda auditado** (`purpose = 'AI_PROCESSING'` en `data_access_log`, política 7.1; sección 13).

```python
# insumap/domain/ai/identifier_redactor.py
import re
import unicodedata
from dataclasses import dataclass
from typing import Final, final

NAME_MARKER: Final = "[NAME]"
DOCUMENT_MARKER: Final = "[DOCUMENT]"
CONTACT_MARKER: Final = "[CONTACT]"
MIN_NAME_PART_LENGTH: Final = 3  # shorter parts ("de", "la") are not identifiers on their own


@dataclass(frozen=True, slots=True, kw_only=True)
class PatientIdentifiers:
    name_parts: tuple[str, ...]
    document: str
    mrn: str
    email: str | None
    phone: str | None


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


@final
class KnownIdentifierRedactor:
    """Replaces the patient's own identifiers in free text with neutral markers."""

    def __init__(self, identifiers: PatientIdentifiers) -> None:
        names = [p for p in identifiers.name_parts if len(p) >= MIN_NAME_PART_LENGTH]
        contacts = [v for v in (identifiers.email, identifiers.phone) if v]
        groups = (
            (names, NAME_MARKER),
            ([identifiers.document, identifiers.mrn], DOCUMENT_MARKER),
            (contacts, CONTACT_MARKER),
        )
        self._rules = [
            (re.compile(re.escape(_normalize(value)), re.IGNORECASE), marker)
            for values, marker in groups
            for value in values
        ]

    def redact(self, text: str) -> str:
        redacted = _normalize(text)
        for pattern, marker in self._rules:
            redacted = pattern.sub(marker, redacted)
        return redacted
```

La comparación es por NFKC e ignorando mayúsculas, así que `JOSÉ` y la forma de ancho completo coinciden con `José`. No cubre variantes sin tilde ni errores de tipeo: por eso el segundo filtro de `insumap-ai` y la regla de no enviar texto libre que no haga falta.

```python
# insumap/application/ai/llm_data_policy.py
from typing import final


@final
class LlmDataPolicy:
    def __init__(self, *, real_data_allowed: bool) -> None:  # from LLM_REAL_DATA_ALLOWED
        self._real_data_allowed = real_data_allowed

    def allows(self, *, clinic_is_demo: bool) -> bool:
        return clinic_is_demo or self._real_data_allowed
```

### 18.3 Salida del LLM y de la IA: dato no confiable

El adaptador valida cada respuesta con un modelo Pydantic **estricto**: números finitos (`allow_inf_nan=False`), cuantiles ordenados (p10 ≤ p50 ≤ p90), longitudes máximas de `FieldLimits` y campos desconocidos ignorados (como fija el contrato). El texto del LLM se entrega al frontend como **texto plano**: sin HTML, sin imágenes y sin enlaces externos (evita la exfiltración por URLs de imágenes Markdown). La IA nunca da dosis al paciente: IA4 es una propuesta que el médico aprueba, modifica o rechaza con motivo (P13).

### 18.4 Token de servicio (lado backend)

La política (10) y el contrato (sección 2) fijan el protocolo; al backend le toca:

- **`AI_SERVICE_TOKEN`** es un `SecretStr` sin valor por defecto, de **32 bytes o más** (`secrets.token_urlsafe(32)`): `Settings` lo valida igual que las llaves (sección 16.2), con una longitud mínima en lugar de base64. `AI_SERVICE_URL` debe ser `https://` cuando `APP_ENV=production` (propuesto: validador de `Settings`).
- **Transporte:** `Authorization: Bearer <token>` y `X-Request-Id` en cada llamada; el token se aplica con un `httpx.Auth` para que nunca esté en una cadena que se pueda registrar. El cliente no sigue redirecciones.
- **`401 INVALID_SERVICE_TOKEN`** (con `WWW-Authenticate: Bearer`) se trata como `AI_ERROR`: respaldo determinista y alerta operativa; no se reintenta con otro token.
- **Rotación sin corte:** (1) `insumap-ai` recibe el nuevo como actual y el viejo como anterior; (2) el backend recibe el nuevo; (3) se retira el anterior de `insumap-ai`. Cada rotación registra `SECRET_ROTATED` mediante `RotateSecretCommand` (sección 16.1).

```python
# insumap/infrastructure/ai/service_token_auth.py
from collections.abc import Generator
from typing import final, override

import httpx
from pydantic import SecretStr


@final
class ServiceTokenAuth(httpx.Auth):
    def __init__(self, token: SecretStr) -> None:
        self._token = token

    @override
    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["Authorization"] = f"Bearer {self._token.get_secret_value()}"
        yield request
```

**Pruebas (sección 19):** `test_hmac_pseudonymizer.py` (cumple `^sub_[0-9a-f]{32}$`; es determinista; cambia con la llave y con otro `patient_id`; no contiene el UUID), `test_known_identifier_redactor.py` (nombre con tilde y en mayúsculas, documento, MRN, correo y teléfono desaparecen; "de" no se enmascara), `test_llm_data_policy.py` (los cuatro casos de `is_demo` por `LLM_REAL_DATA_ALLOWED`), y las del adaptador con un servidor simulado (`httpx.MockTransport`): **minimización**, con un paciente cuyos datos son valores centinela (`SENTINEL-NOMBRE`, un UUID real, un correo, un documento) y la comprobación de que el cuerpo serializado no contiene ninguno de ellos ni la fecha de nacimiento; el encabezado `Authorization` y `X-Request-Id` viajan; un `401` activa el respaldo y no reintenta; un `NaN`, cuantiles desordenados o un campo de texto con `![x](https://...)` se rechazan o se entregan como texto plano; una clínica no demo con `LLM_REAL_DATA_ALLOWED=false` no hace la llamada y deja `LLM_DATA_POLICY_BLOCKED`.

**Antipatrones:** serializar un `Patient` o un `*Orm` hacia la IA; enviar `patient_id` "porque es un UUID"; construir el cuerpo con `**vars(entity)`; mandar notas libres sin redactar; el token en la URL, en un log, en `repr` o en un mensaje de excepción; comparar el token con `==` (eso es del lado de `insumap-ai`: `hmac.compare_digest` contra el actual y el anterior, siempre los dos); activar `LLM_REAL_DATA_ALLOWED` en un entorno sin la base legal y el proveedor que la política exige; mostrar la respuesta del LLM como HTML.

## 19. Pruebas de seguridad

La política (18) exige que cada control tenga **al menos una prueba que falle si el control se rompe**. Esta sección dice cómo escribirlas; las pruebas concretas de cada control están al final de su sección (3 a 18). El plan general está en [`testing-plan.md`](testing-plan.md) (secciones 4.2 y 6) y esta guía no lo reemplaza.

### 19.1 Reglas

1. **Tres niveles, el más barato que pruebe el control.**
   - *Unitaria* (`tests/unit/`): una clase con sus puertos en memoria y `FixedClock`. Aquí viven el hasher, el `KeyRing`, `ColumnCipher`, las políticas y los casos de uso.
   - *API* (`tests/api/`): `create_app(Container(settings=make_settings(...)))` con fakes y `TestClient`. Aquí vive todo lo que depende de la forma HTTP: cabeceras, CORS, tamaño, el cuerpo idéntico de los errores y la matriz de rutas.
   - *Integración* (`tests/integration/`, `@pytest.mark.integration`): Testcontainers con PostgreSQL 18, las migraciones de la etiqueta de `db-schema.lock` y sesiones con `insumap_app`. Obligatoria para RLS, auditoría, atomicidad del refresh y contadores compartidos. **La suite se detiene** si el rol de la sesión es `rolsuper` o `rolbypassrls` (un superusuario salta la RLS y la prueba pasaría sin probar nada).
2. **Los límites salen de `Settings` y `FieldLimits`**, no de números escritos en la prueba. Las únicas cifras literales son las que la política **fija** y que una prueba debe congelar a propósito: los parámetros de producción de Argon2id (se verifica una sola vez), la longitud mínima de contraseña (11 falla, 12 pasa, 129 falla) y los valores de las cabeceras de la tabla 13.1.
3. **La hora la mueve el `FixedClock`** (`advance`); nada de `sleep` ni de la hora real. Tampoco se mide tiempo de pared para probar "tiempo constante": se **cuenta** el trabajo (el doble de `PasswordHasher` registra cuántas veces se llamó `verify`).
4. **Comparar respuestas completas** cuando la política exige que dos casos no se distingan: mismo estado, mismo cuerpo y mismas cabeceras (correo inexistente frente a contraseña incorrecta; paciente ajeno frente a inexistente; código vencido frente a usado).
5. **Valores centinela** para lo que no debe aparecer (logs, cuerpo hacia la IA, respuestas, la BD): se siembra un valor reconocible (`SENTINEL-...`, un UUID, un correo, un documento) y se comprueba que no está en ningún lado que no debe.
6. **Los secretos de prueba son constantes de `tests/support/`**, claramente falsas, nunca reales. Las pruebas no leen el entorno ni un `.env`: `make_settings` pasa `_env_file=None`.
7. **Una prueba, un comportamiento** (`testing-plan.md`, sección 4.1). Una `parametrize` por tabla de casos (cada cabecera, cada parte sensible de la lista de redacción, cada fila de la sección 12 de la política).
8. **Se prueba el control, no la biblioteca.** No se verifica que `AESGCM` cifre; se verifica que nuestro `ColumnCipher` ata el valor a su AAD y que el blob alterado falla.

### 19.2 Utilería compartida

```python
# tests/support/keys.py
import base64

TEST_KEY_A = base64.b64encode(bytes([1]) * 32).decode()
TEST_KEY_B = base64.b64encode(bytes([2]) * 32).decode()
TEST_KEY_C = base64.b64encode(bytes([3]) * 32).decode()
TEST_SERVICE_TOKEN = "t" * 43  # same length as secrets.token_urlsafe(32); obviously fake
```

`make_settings` (en `tests/support/settings.py`) suma por defecto una llave distinta por propósito (`jwt_secret=TEST_KEY_A`, `field_encryption_key=TEST_KEY_B`, ...), `allowed_hosts=["testserver"]` y `ai_service_token=TEST_SERVICE_TOKEN`; una prueba cambia lo que necesita con `make_settings(jwt_secret_previous=TEST_KEY_C)`. Se agrega un secreto nuevo a `make_settings` en el mismo PR que lo crea.

```python
# tests/unit/infrastructure/test_key_ring.py
import pytest
from pydantic import SecretStr

from insumap.infrastructure.security.keys import KeyRing
from tests.support.keys import TEST_KEY_A, TEST_KEY_B


def test_previous_key_verifies_but_the_current_key_signs() -> None:
    ring = KeyRing(current=SecretStr(TEST_KEY_A), previous=SecretStr(TEST_KEY_B))
    previous_id = ring.all_keys()[1][0]

    assert ring.verification_key(previous_id) != ring.current_key()
    assert ring.current_key_id != previous_id


def test_unknown_key_id_raises_key_error() -> None:
    ring = KeyRing(current=SecretStr(TEST_KEY_A))

    with pytest.raises(KeyError):
        ring.verification_key("0123456789abcdef")
```

```python
# tests/api/test_security_headers.py
import pytest
from fastapi.testclient import TestClient

from insumap.container import Container
from insumap.main import create_app
from tests.support.settings import make_settings

EXPECTED_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-site",
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Container(make_settings())))


@pytest.mark.parametrize("path", ["/api/v1/does-not-exist", "/health"])
def test_every_response_carries_the_security_headers(client: TestClient, path: str) -> None:
    response = client.get(path)

    for name, value in EXPECTED_HEADERS.items():
        assert response.headers[name] == value
    assert "server" not in response.headers
```

```python
# tests/unit/infrastructure/test_ai_adapter_minimization.py (forma de la prueba con centinelas)
SENTINELS = ("SENTINEL-FIRST-NAME", "SENTINEL-LAST-NAME", "1234567890", "sentinel@example.test")


def test_request_body_to_the_ai_service_has_no_direct_identifiers(adapter, transport, patient) -> None:
    adapter.forecast(patient)  # the patient carries every sentinel in its personal fields

    body = transport.last_request.content.decode()
    for sentinel in (*SENTINELS, str(patient.patient_id), str(patient.user_id)):
        assert sentinel not in body
    assert SUBJECT_REF_PATTERN.fullmatch(transport.last_request_json()["subject_ref"])
```

### 19.3 De la tabla de la política a los archivos

| Control (política 18) | Sección | Archivo principal | Nivel |
|---|---|---|---|
| Argon2id; política de contraseña; login genérico | 3 | `test_password_hasher.py`, `test_password_policy.py`, `test_password_verifier.py` | Unitaria y API |
| Bloqueos; cuenta o clínica inactiva | 3.2, 9.1 | `test_login_lock.py`, `test_login_use_case.py` | Unitaria, API e integración |
| JWT; `token_version`; MFA obligatorio | 4, 4.1 | `test_jwt_token_service.py`, `test_actor_authenticator.py` | Unitaria y API |
| Refresh; reutilización | 5 | `test_rotate_refresh_token_use_case.py`, `test_refresh_tokens.py` | Unitaria e integración |
| Cookie y CSRF | 6 | `test_csrf.py`, `test_refresh_cookie.py` | API |
| Activación; consentimiento | 8 | `test_credential_invitation.py`, `test_code_hasher.py` | Unitaria y API |
| MFA | 7 | `test_totp_verifier.py`, `test_mfa_recovery_codes.py` | Unitaria y API |
| Límites de tasa | 9 | `test_rate_limiters.py` | Unitaria e integración (dos instancias) |
| Permisos y denegación por defecto | 10 | `test_route_security.py` | API |
| RLS | 11 | `test_rls_context.py` | Integración |
| Proxy (P11) | 12 | `test_patient_record_access_proxy.py` | Unitaria e integración |
| Auditoría (P09) y eventos | 13 | `test_phi_access_audit_decorator.py`, `test_security_event_severity.py` | Unitaria e integración |
| Logs | 14 | `test_logging.py` | Unitaria y API |
| Columnas cifradas; llaves; rotación | 15, 16 | `test_column_cipher.py`, `test_key_ring.py`, `test_reencrypt_column_use_case.py`, `test_settings.py` | Unitaria e integración |
| Cabeceras y CORS; tamaño e importación; salidas | 17 | `test_security_headers.py`, `test_cors.py`, `test_middleware.py`, `test_csv_cells.py`, `test_push_endpoint_policy.py` | Unitaria y API |
| Minimización IA; token de servicio | 18 | `test_hmac_pseudonymizer.py`, `test_ai_adapter_minimization.py` | Unitaria (con `httpx.MockTransport`) |
| Errores | `api/errors.py` | `test_error_handlers.py` (ya existe) | API |

El "token de servicio" **en `insumap-ai`** (el actual y el anterior pasan, 31 bytes impide el arranque, uno incorrecto da `401 INVALID_SERVICE_TOKEN`) se prueba en ese repositorio; aquí solo se prueba lo del backend (18.4).

### 19.4 Que falle sin el cambio

La lista de verificación de la política (19) pide que la prueba "falle sin el cambio". Para comprobarlo antes de abrir el PR:

1. Escribir la prueba y ver que **pasa** con el control puesto.
2. Anular el control de la forma más pequeña posible (comentar la línea, devolver el valor sin proteger, quitar el `middleware`) y ver que **falla** por el motivo correcto, no por un error de importación.
3. Restaurar y dejar en la descripción del PR qué se anuló y qué prueba falló.

Dos trampas frecuentes: una prueba que pasa también sin el control (se comparó con un valor que el control no cambia) y una prueba de integración que corre con un superusuario (pasa sin RLS). La de arquitectura y las pruebas de deriva (`testing-plan.md`, secciones 7 y 8) completan estas: `ARCH-09` prohíbe la hora del sistema, `S608` el SQL armado con texto.

**Antipatrones:** una prueba que lee `.env` o variables del entorno; un secreto real en una fixture; `time.sleep` para esperar un vencimiento; asertar solo el estado HTTP cuando la política exige un cuerpo idéntico; probar el control con un doble que no lo ejecuta (un `Mock` del `RateLimiter` en la prueba del límite); `@pytest.mark.skip` en una prueba de seguridad "hasta que haya BD" (se marca `integration`, no se salta).

## 20. Diferencias con el código actual y pendientes

La guía describe el diseño que se implementa; el código del repositorio hoy solo tiene el esqueleto (configuración, errores canónicos, `RequestIdMiddleware`, `BodySizeLimitMiddleware`, CORS, logging y `/health`). Esta sección dice en qué difieren la guía, la política y el código, y quién decide. Las tablas se actualizan en el mismo PR que cierra cada diferencia.

### 20.1 Diferencias entre la guía, la política y el código

| # | Tema | Qué dicen los documentos | Qué hace el código hoy | Decisión o pendiente |
|---|---|---|---|---|
| 1 | Límite de hashes concurrentes (sección 3) | La política 2.1 dice `anyio.to_thread.run_sync` con `CapacityLimiter`. ADR-02 fija endpoints y puertos síncronos (`def`) | Aún no hay hasher | La guía sigue **ADR-02**: `threading.BoundedSemaphore`. Corregir la frase de la política 2.1. Pendiente de decidir (propuesto): si el que espera el semáforo lo hace con un tiempo máximo, porque cada espera ocupa un hilo del pool de FastAPI |
| 2 | Código del `401` (secciones 4, 4.1, 5) | Política, `API.md`, `Actores-y-permisos.md` y las historias de usuario usan `UNAUTHORIZED` | El enum, `STATUS_BY_CODE`, `CODE_BY_HTTP_STATUS`, `messages_es.json` y dos pruebas usan `UNAUTHENTICATED` | Renombrar a `UNAUTHORIZED` (enum, clave `unauthorized`, mapeos y pruebas) en el PR que agrega la primera ruta autenticada. Mientras tanto, los esqueletos dicen `UNAUTHENTICATED` y el JSON que ve el cliente debe decir `UNAUTHORIZED`. Los demás códigos de la política 2.6 (`SESSION_REVOKED`, `MFA_REQUIRED`, ...) se agregan con su clave y su estado ([`design-patterns.md`](design-patterns.md), sección 2.3) |
| 3 | `Depends` y `app.state` (sección 4.1) | [`architecture.md`](architecture.md) admite `Depends` solo para `CurrentActor` y la paginación; `container.py` es el único lugar donde se arman las dependencias | No hay autenticación ni uso de `app.state` | El esqueleto de 4.1 lee `request.app.state.actor_authenticator`, que es un localizador. Opción recomendada abajo (20.2): `ActorDependencies` que recibe el autenticador por constructor. Si el equipo prefiere `app.state`, se anota como **única** excepción en `architecture.md` |
| 4 | Cabeceras en errores de negocio (sección 9, `Retry-After`) | `429` lleva `Retry-After` (política 12) | `InsumapError.headers` existe y `handle_insumap_error` lo pasa a la respuesta | **Cerrada.** `InsumapError.headers` y el manejador ya existían; un `RateLimitedError` puede enviar `Retry-After` |
| 5 | Ventana del bloqueo de login (sección 9.1) | Política 2.2: 5 fallos **en 15 minutos** (`LOGIN_FAILURE_WINDOW_MINUTES`); cada nivel duplica el bloqueo | Aún no hay registro de intentos | La derivación de 9.1 cuenta fallos consecutivos desde el último éxito y no usa la ventana al escalar. Propuesto: el nivel 1 solo cuenta los fallos dentro de la ventana; los niveles siguientes usan el historial de bloqueos. Lo confirma el dueño de la política |
| 6 | Contexto de las transacciones independientes (sección 11) | La fila `DENIED` de `data_access_log` acepta el `clinic_id` del actor; `login_attempts`, `rate_limit_buckets` y eventos sin clínica no tienen actor | Aún no hay `UnitOfWorkFactory` | `begin_independent(actor)` fija el contexto del actor para la fila `DENIED`. Para el resto hacen falta funciones `SECURITY DEFINER` o políticas de inserción en `insumap-database` (política 21, puntos 10 y 11) |
| 7 | `''` o `NULL` tras `set_config` (sección 11) | Las políticas de `insumap-database` deben tratar la cadena vacía como "sin contexto" (`NULLIF(current_setting('app.clinic_id', true), '')`) | Sin BD aún | Verificarlo con `test_rls_context.py` en la imagen de PostgreSQL 18 y pedir el `NULLIF` en `insumap-database` si falta |
| 8 | Lista de redacción de logs (sección 14) | Política 11.4: `password`, `passwd`, `secret`, `token`, `authorization`, `cookie`, `code`, `otp`, `api_key`, `document`, `email`, `phone`, `birth`. [`Arquitectura.md`](../docs/Arquitectura.md) (sección 15) lista otra: `activation_code`, `name`, `mrn`, `note`, `message`, `value` y no tiene `secret`, `otp` ni `birth` | `SENSITIVE_KEY_PARTS` tiene `document_number` y no tiene `code`, `otp`, `phone` ni `birth`; la clase se llama `RedactionFilter` (Arquitectura dice `PhiRedactionFilter`) | Gana la **política**. Corregir `Arquitectura.md` para que remita a ella. No se agregan `name`, `message` ni `value`: la coincidencia es por subcadena y enmascararía campos legítimos (`logger_name`, `message`); los datos con esos nombres se evitan en origen (14.1) |
| 9 | `X-Request-ID` entrante (sección 14.2) | Política 11.2: solo un UUID válido | Solo acepta un UUID (36 caracteres) | **Cerrada.** `REQUEST_ID_PATTERN` exige un UUID y `REQUEST_ID_MAX_LENGTH` es 36; la prueba usa UUID |
| 10 | Tamaño del cuerpo (sección 17.3) | Política 13.3: 64 KiB en general, y límites propios por ruta | 64 KiB general y topes propios por ruta con `path_limits` | **Cerrada.** `MAX_REQUEST_BODY_BYTES` es 64 KiB; `path_limits` de `main.py` da su tope a `imports/fhir`, `imports/csv`, `readings/batch` y `readings/cgm-import`. El `BodyLimitResolver` queda para cuando un tope dependa del método o de un parámetro de la ruta |
| 11 | CORS, hosts y cabeceras (sección 17) | Política 13.1 y 13.2 | CORS completo, `TrustedHostMiddleware` propio con `ALLOWED_HOSTS` y `SecurityHeadersMiddleware` (HSTS solo en producción) | **Cerrada.** CORS con `Idempotency-Key`, `max_age=600` y `Retry-After` expuesto; `TrustedHostMiddleware` propio (formato canónico) con `ALLOWED_HOSTS`; `SecurityHeadersMiddleware`. **Decisión abierta:** un `Host` ajeno responde `400 VALIDATION_ERROR` (la política no fija código). Swagger (`/docs`) no lleva CSP hasta que se defina la relajada; HSTS solo con `APP_ENV=production` |
| 12 | `Settings` (sección 16.2) | Todas las llaves de la tabla 2.4 y los parámetros de la sección 2 | `app_env` acepta `local`, `test` y `production`, igual que [`configuration.md`](configuration.md); `allowed_hosts` ya existe | Crecen campo a campo con cada PR que los usa. **Nombre del entorno unificado:** `local`, `test` y `production` (`configuration.md` ya dice `local`). `allowed_hosts` ya existe |
| 13 | Dependencias (secciones 3 a 8, 15) | `argon2-cffi`, `PyJWT`, `cryptography` y `pyotp` (esta última por confirmar en la fase 3) | `pyproject.toml` no las tiene | Cada una entra fijada (`==`) en el PR que la usa, con `pip-audit` limpio |
| 14 | Alarma en mensajes (RF-85, HU-49) y límite de envíos (API.md 5 y 8.12) | Un mensaje con palabras de alarma sugiere llamar a urgencias y avisa al equipo sin el texto; el correo y el Web Push no llevan el texto. El límite de `POST /messages` es 30 por minuto por usuario, en memoria | Detector puro `ALARM_KEYWORDS` (dominio), aviso `MessageAlarmNotification` (P07) en la app y por Web Push, límite `messages_user_minute` con `RateLimitCheck` y `Retry-After` | Lista pendiente de validación clínica (`docs/API.md`, G33). Sin correo: no hay canal de correo conectado a mensajería. Solo mensajes del paciente avisan al equipo. El límite es de memoria por proceso, como el resto de las familias de `iam`

### 20.2 Detalle de las propuestas

**Dependencias del actor sin `app.state` (diferencia 3).** El contenedor crea un objeto con el autenticador y los routers reciben sus `Depends` por constructor, como reciben sus casos de uso:

```python
# insumap/api/security.py (alternativa a leer app.state)
from collections.abc import Callable
from typing import final

from fastapi import Request

from insumap.application.common.actor import Actor
from insumap.application.identity.authenticate import ActorAuthenticator, SessionScope


@final
class ActorDependencies:
    """Built once in container.py; routers take ``.current`` (or the other two) in their constructor."""

    def __init__(self, authenticator: ActorAuthenticator) -> None:
        self._authenticator = authenticator
        self.current = self._for(SessionScope.FULL)
        self.enrollment = self._for(SessionScope.ENROLLMENT)
        self.any_session = self._for(SessionScope.ANY)

    def _for(self, scope: SessionScope) -> Callable[[Request], Actor]:
        def dependency(request: Request) -> Actor:
            return self._authenticator.authenticate(bearer_token(request), scope)

        return dependency
```

Un router usa `Depends(self._actors.current)` y la prueba de denegación por defecto de la sección 10.2 sigue funcionando, porque la dependencia sigue siendo un `Depends` verificable en `app.routes`.

**Cabeceras en `InsumapError` (diferencia 4).**

```python
# insumap/shared/errors.py (cambio propuesto)
def __init__(self, code: ErrorCode, *, message_key: str | None = None,
             params: Mapping[str, object] | None = None, detail: Mapping[str, object] | None = None,
             headers: Mapping[str, str] | None = None) -> None:  # fmt: skip
    ...
    self.headers: Mapping[str, str] = MappingProxyType(dict(headers or {}))

# insumap/api/errors.py (cambio propuesto en handle_insumap_error)
return self._responses.create(
    error.code, message_key=error.message_key, params=error.params,
    detail=error.detail, headers=error.headers,
)  # fmt: skip
```

`shared` sigue sin depender de ninguna capa: las cabeceras son un `Mapping[str, str]`, no un tipo de Starlette. Un `RateLimitedError` (por ejemplo) pone `Retry-After` con los segundos que calculó la política.

**Pruebas:** cada diferencia que se cierra agrega la prueba que la fija: el renombrado de `UNAUTHORIZED` actualiza `test_error_status_mapping.py` y `test_error_handlers.py`; las cabeceras de errores, un caso con `Retry-After` en `test_error_handlers.py`; el `X-Request-ID`, los casos `parametrize` de `test_middleware.py`.

**Antipatrones:** cerrar una diferencia solo en la guía sin tocar la política o el código que corresponde; dejar un esqueleto de esta guía que contradiga al código sin una fila en 20.1; resolver la diferencia 1 con un `anyio.CapacityLimiter` en un endpoint `def` (el limitador no se comparte con el semáforo de hilos y ADR-02 prohíbe volver `async` al puerto).

### 20.3 Pendientes que viven en otros repositorios o documentos

| Pendiente | Dónde se resuelve |
|---|---|
| Funciones `SECURITY DEFINER` para el login, la invitación y el refresh; RLS por rol; `NULLIF` en las políticas; tablas `rate_limit_buckets` y `auth_challenges`; columnas de documento y de `key_id` | `insumap-database` (política 21, puntos 7 a 11) |
| Recifrado y recálculo de `document_hash` sobre todas las clínicas (16.1) | `insumap-database` (privilegio de mantenimiento) y este repositorio (los jobs) |
| Sección 2.1 de la política (`CapacityLimiter`) y la lista de redacción de `Arquitectura.md` | Documentos canónicos de este repositorio |
| Campo `data_origin` y días relativos en IA5; rotación del token de servicio en `insumap-ai` | [`Contrato-IA.md`](../docs/Contrato-IA.md) e `insumap-ai` |
| CSP de `/docs` (Swagger) con *nonce* | Este repositorio, antes de `v1.0.0` (política 13.1 y 20) |
| `SECURITY.md` con el canal de reporte de vulnerabilidades | Este repositorio (política 21, punto 19) |
