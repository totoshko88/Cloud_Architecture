"""One secret vocabulary for the Collector, Normalizer and Linter (design §5, R3).

Before 1.7.0 the secret-detection logic lived in three places that had drifted
apart: ``collector.redact_secrets`` (key-name + value-content + pair rules),
``normalizer._is_secret_key`` (a digest drop list) and the Linter's content
scan (built from ``constants.SECRET_CONTENT_MARKERS``). This module is the
single home. Every consumer keys off the same three predicates, so the redactor
and the Linter cannot disagree about what a secret is:

* :func:`is_credential_key` — is a *key name* credential-bearing?
* :func:`value_secret_kind` — does a *string value* embed secret material?
* :func:`pair_redactions` — how is a ``{name, value}`` record redacted?

The two callable entry points are :func:`redact` (returns a redacted copy of an
object, replacing every leak with :data:`REDACTED`) and the two finders,
:func:`find_secrets` (parsed JSON/YAML, RFC 6901 pointers) and :func:`scan_text`
(non-JSON text, ``line:<n>`` locations). The soundness link the design records
holds by construction: ``find_secrets(redact(x)) == []`` for every input.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Tuple

__all__ = [
    "REDACTED",
    "normalize_key",
    "CREDENTIAL_SUFFIXES",
    "METADATA_KEYS",
    "PAIR_NAME_KEYS",
    "PAIR_VALUE_KEYS",
    "SecretHit",
    "is_credential_key",
    "value_secret_kind",
    "pair_redactions",
    "redact",
    "find_secrets",
    "scan_text",
]


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

#: Redaction placeholder written in place of a stripped secret value. Contains
#: no secret material, so a file carrying this string is still secret-free. A
#: value equal to :data:`REDACTED` is never treated as a leak (idempotent
#: redaction: ``redact(redact(x)) == redact(x)``).
REDACTED = "[REDACTED]"


def normalize_key(name: str) -> str:
    """Lowercase ``name`` and drop every character outside ``[a-z0-9]``.

    ``AccessKeyId``, ``access_key_id`` and ``access-key-id`` all normalise to
    ``accesskeyid``, so the suffix rule below is spelling-insensitive.
    """
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


#: Normalized suffixes that mark a key name as credential-bearing (design §5).
#: Matched as a **suffix** of the normalized name (not a substring, as the 1.6.1
#: rule did), so ``AccessKeyId`` (``accesskeyid``), ``SecretArn`` (``secretarn``),
#: ``PasswordLastUsed`` (``passwordlastused``), ``privateKeyType``
#: (``privatekeytype``) and ``CustomerMasterKeySpec`` (``customermasterkeyspec``)
#: stay metadata (R3.4).
CREDENTIAL_SUFFIXES: Tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "secretstring",
    "secretvalue",
    "token",
    "sessiontoken",
    "accesstoken",
    "refreshtoken",
    "clientsecret",
    "accountkey",
    "sharedaccesskey",
    "primarykey",
    "secondarykey",
    "primarymasterkey",
    "secondarymasterkey",
    "readonlymasterkey",
    "adminkey",
    "connectionstring",
    "privatekey",
    "apikey",
    "accesskey",
    "secretaccesskey",
    "keymaterial",
    "credential",
    "credentials",
)

#: Normalized names that end with a :data:`CREDENTIAL_SUFFIXES` marker but are
#: plain identifiers, not key material (design §5, D3). A ``partition_key`` /
#: ``sortKey`` / ``objectKey`` / ``s3Key`` names a record field; a ``publicKey``
#: / ``sshPublicKey`` is public material; a ``keyPairName`` names a key pair.
#: The key rule consults this allow-list first, so none of them is ever redacted.
METADATA_KEYS: frozenset[str] = frozenset(
    {
        "publickey",
        "sshpublickey",
        "partitionkey",
        "sortkey",
        "hashkey",
        "rangekey",
        "objectkey",
        "s3key",
        "keypairname",
    }
)

#: Name/value pair record shapes (moved from ``collector``). Several provider
#: APIs carry configuration as a list of ``{name, value}`` records rather than a
#: mapping: AWS tags (``{Key, Value}``), ECS/Batch container environment
#: (``{name, value}``), CloudFormation parameters
#: (``{ParameterKey, ParameterValue}``), Elastic Beanstalk option settings
#: (``{OptionName, Value}``). Key-name redaction cannot see the secret in that
#: shape — its NAME is a value and its VALUE sits under a benign key — so a pair
#: is judged by its name (:func:`pair_redactions`).
PAIR_NAME_KEYS = frozenset(
    {"key", "name", "parameterkey", "parametername", "optionname", "variablename"}
)
PAIR_VALUE_KEYS = frozenset({"value", "parametervalue"})


# ---------------------------------------------------------------------------
# Key rule
# ---------------------------------------------------------------------------


def is_credential_key(name: str) -> bool:
    """Return True when a *key name* is credential-bearing (design §5, D3).

    The rule, in order (``n = normalize_key(name)``):

    1. ``n in METADATA_KEYS`` → not a secret (``publicKey``, ``partition_key``);
    2. ``n in {"key", "keys"}`` → secret (the bare-``key`` rule; the
       ``{Key, Value}`` exemption is applied at the pair level, not here);
    3. the raw ``name`` ends with ``_key`` or ``-key`` → secret;
    4. ``n`` ends with any :data:`CREDENTIAL_SUFFIXES` marker → secret.
    """
    n = normalize_key(name)
    if n in METADATA_KEYS:
        return False
    if n in {"key", "keys"}:
        return True
    raw = str(name).lower()
    if raw.endswith("_key") or raw.endswith("-key"):
        return True
    return n.endswith(CREDENTIAL_SUFFIXES)


def _is_leaking_value(value: Any) -> bool:
    """Return True when a value under a credential key is an actual leak.

    A matched key counts as a leak only when its value is a **non-empty string
    or bytes that is not** :data:`REDACTED`. Booleans, numbers and ``null``
    under a credential key (``"PasswordEnabled": true``) are metadata, and an
    already-redacted value is not a fresh leak.
    """
    if isinstance(value, str):
        return bool(value) and value != REDACTED
    if isinstance(value, (bytes, bytearray)):
        if not value:
            return False
        decoded = _decode_bytes(bytes(value))
        return decoded is None or decoded != REDACTED
    return False


# ---------------------------------------------------------------------------
# Value rule
# ---------------------------------------------------------------------------

# Ordered (kind, pattern) list. Matching is case-insensitive. The kinds are the
# ``value:<kind>`` suffix used in a SecretHit. Deliberately conservative and
# anchored so ordinary metadata (a region, an ARN, a description) is not
# over-matched. Public material is explicitly *not* here (see
# :func:`value_secret_kind`): a CERTIFICATE / PUBLIC KEY block and the bare
# label ``SecureString`` do not match (R3.4).
_VALUE_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    # PEM / OpenSSH / PGP PRIVATE KEY blocks. ``[A-Z]*`` covers RSA/EC/DSA/etc;
    # OPENSSH and PGP are spelled out. A PUBLIC KEY block does not match.
    (
        "pem-private-key",
        re.compile(
            r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----"
            r"|-----BEGIN OPENSSH PRIVATE KEY-----"
            r"|-----BEGIN PGP PRIVATE KEY BLOCK-----",
            re.IGNORECASE,
        ),
    ),
    # Azure connection-string components (the key/signature is the secret).
    (
        "azure-connection-key",
        re.compile(
            r"\b(?:AccountKey|SharedAccessKey|SharedAccessSignature)\s*=\s*\S",
            re.IGNORECASE,
        ),
    ),
    # A SAS signature query parameter.
    ("sas-signature", re.compile(r"[?&]sig=[^&\s]+", re.IGNORECASE)),
    # A URL whose userinfo carries a password other than REDACTED
    # (``postgres://app:pw@db``). The redacted spelling
    # (``app:[REDACTED]@db``) is intentionally excluded.
    (
        "url-userinfo-password",
        re.compile(
            r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:(?!\[REDACTED\]@)[^/\s@]+@",
            re.IGNORECASE,
        ),
    ),
    # A JWT (three base64url segments, the first two starting ``eyJ``).
    ("jwt", re.compile(r"eyJ[\w-]+\.eyJ[\w-]+\.[\w-]+")),
    # The 1.6.1 inline assignments: ``password=…`` / ``token=…`` / an
    # ``api-key: …`` and friends. A trailing non-space char after the separator
    # means a value is present.
    (
        "inline-assignment",
        re.compile(
            r"\b(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|"
            r"session[_-]?token|client[_-]?secret)\s*[:=]\s*\S",
            re.IGNORECASE,
        ),
    ),
    # ``export AWS_SECRET_ACCESS_KEY=…`` — ``\b`` never fires after the ``_``
    # before SECRET, so the inline rule above misses the most common spelling of
    # the most common cloud secret. A dedicated anchor catches it.
    (
        "inline-assignment",
        re.compile(
            r"(?<![A-Za-z0-9])(?:aws_)?secret_access_key\s*[:=]\s*\S",
            re.IGNORECASE,
        ),
    ),
)


def value_secret_kind(value: str) -> Optional[str]:
    """Return the secret *kind* a string value embeds, or ``None``.

    Recognises, case-insensitively: PEM/OpenSSH/PGP ``PRIVATE KEY`` blocks;
    ``AccountKey=`` / ``SharedAccessKey=`` / ``SharedAccessSignature=``; a SAS
    ``sig=``; a URL whose userinfo has a non-redacted password; a JWT; and the
    1.6.1 inline assignments. Public certificates, ``PUBLIC KEY`` blocks and the
    bare label ``SecureString`` do **not** match (R3.4) — a ``SecureString``
    value is caught through the pair rule, not here.
    """
    if not isinstance(value, str) or not value:
        return None
    for kind, pattern in _VALUE_PATTERNS:
        if pattern.search(value):
            return kind
    return None


def _decode_bytes(value: bytes) -> Optional[str]:
    """Best-effort UTF-8 decode of a byte value (else ``None``)."""
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return None


# ---------------------------------------------------------------------------
# AWS access-key pair detection (mapping level)
# ---------------------------------------------------------------------------

_AWS_ACCESS_KEY_ID_RE = re.compile(r"^(?:AKIA|ASIA)[A-Z0-9]{16}$")
_AWS_SECRET_RE = re.compile(r"^[A-Za-z0-9/+=]{40}$")


def _aws_key_pair_secret_keys(mapping: Mapping[Any, Any]) -> frozenset:
    """Return the keys whose 40-char value is an AWS secret access key.

    An AWS key pair is detected at the *mapping* level: a value matching an
    ``AKIA``/``ASIA`` access-key id, with a sibling string value matching the
    40-character secret shape, means that sibling is the secret. Only fires when
    an access-key id is actually present, so a lone 40-char token elsewhere is
    not swept up.
    """
    values = list(mapping.values())
    has_id = any(
        isinstance(v, str) and _AWS_ACCESS_KEY_ID_RE.match(v) for v in values
    )
    if not has_id:
        return frozenset()
    return frozenset(
        k
        for k, v in mapping.items()
        if isinstance(v, str)
        and _AWS_SECRET_RE.match(v)
        and not _AWS_ACCESS_KEY_ID_RE.match(v)
    )


# ---------------------------------------------------------------------------
# Pair rule
# ---------------------------------------------------------------------------


def pair_redactions(mapping: Mapping[Any, Any]) -> Tuple[frozenset, frozenset]:
    """Decide how a name/value-pair record is redacted (moved from collector).

    Returns ``(redact, passthrough)`` as sets of **lowercased** key names:

    * ``redact`` — value entries replaced with :data:`REDACTED` outright, plus a
      secret-looking name entry so the name never reaches a file either;
    * ``passthrough`` — the ``Key`` field of a pure ``{Key, Value}`` record,
      which names the tag rather than holding key material (the 1.6.1
      exemption); it is exempt from the bare-``key`` rule but still walked for
      secret content.

    Value entries are redacted when the name entry names a secret
    (``DB_PASSWORD``, ``ApiToken``), when the record is an SSM parameter whose
    ``Type`` is ``SecureString``, or when it carries a ``keyName`` (the Azure
    ``keys list`` shape). A mapping with no value entry is not a pair.
    """
    lowered = {k.lower(): v for k, v in mapping.items() if isinstance(k, str)}
    value_keys = PAIR_VALUE_KEYS & lowered.keys()
    if not value_keys:
        return frozenset(), frozenset()
    redact: set = set()
    type_label = lowered.get("type")
    if isinstance(type_label, str) and type_label.strip().lower() == "securestring":
        redact |= value_keys
    if "keyname" in lowered:
        redact |= value_keys
    for name_key in sorted(PAIR_NAME_KEYS & lowered.keys()):
        name = lowered[name_key]
        if isinstance(name, str) and (
            is_credential_key(name) or value_secret_kind(name) is not None
        ):
            redact |= value_keys | {name_key}
    passthrough: frozenset = frozenset()
    if set(lowered) <= {"key", "value"} and "key" in lowered and "key" not in redact:
        passthrough = frozenset({"key"})
    return frozenset(redact), passthrough


# ---------------------------------------------------------------------------
# SecretHit and finders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SecretHit:
    """A single detected secret, located but carrying no secret material.

    Attributes
    ----------
    location:
        An RFC 6901 JSON pointer (``/a/0/Value``) for :func:`find_secrets`, or a
        ``line:<n>`` marker for :func:`scan_text`.
    kind:
        ``credential-key:<normalized>``, ``value:<kind>`` or ``pair:<name>``.
    """

    location: str
    kind: str


def _escape_pointer_token(token: str) -> str:
    """RFC 6901 escaping: ``~`` -> ``~0`` and ``/`` -> ``~1``."""
    return token.replace("~", "~0").replace("/", "~1")


def _find(obj: Any, pointer: str, hits: List[SecretHit]) -> None:
    if isinstance(obj, Mapping):
        redact, passthrough = pair_redactions(obj)
        aws_secret_keys = _aws_key_pair_secret_keys(obj)
        for k, v in obj.items():
            child_ptr = f"{pointer}/{_escape_pointer_token(str(k))}"
            low = k.lower() if isinstance(k, str) else None
            if low is not None and low in redact:
                # A pair whose value is redacted-by-name; report the value entry
                # only when it actually holds a leak.
                if _is_leaking_value(v):
                    hits.append(SecretHit(location=child_ptr, kind=f"pair:{low}"))
                continue
            if isinstance(k, str) and k in aws_secret_keys and _is_leaking_value(v):
                hits.append(SecretHit(location=child_ptr, kind="value:aws-secret-key"))
                continue
            if (
                low is not None
                and low in passthrough
            ):
                _find(v, child_ptr, hits)
                continue
            if isinstance(k, str) and is_credential_key(k) and _is_leaking_value(v):
                hits.append(
                    SecretHit(
                        location=child_ptr,
                        kind=f"credential-key:{normalize_key(k)}",
                    )
                )
                continue
            _find(v, child_ptr, hits)
        return
    if isinstance(obj, (list, tuple)):
        for i, item in enumerate(obj):
            _find(item, f"{pointer}/{i}", hits)
        return
    if isinstance(obj, str):
        kind = value_secret_kind(obj)
        if kind is not None:
            hits.append(SecretHit(location=pointer or "", kind=f"value:{kind}"))
        return
    if isinstance(obj, (bytes, bytearray)):
        decoded = _decode_bytes(bytes(obj))
        if decoded is not None:
            kind = value_secret_kind(decoded)
            if kind is not None:
                hits.append(SecretHit(location=pointer or "", kind=f"value:{kind}"))
        return


def find_secrets(obj: Any) -> List[SecretHit]:
    """Return every secret in a parsed JSON/YAML object, with RFC 6901 pointers.

    Walks mappings and sequences recursively. A credential key with a leaking
    value, an AWS access-key/secret sibling pair, a ``{name, value}`` pair whose
    name names a secret, a ``SecureString`` parameter, and any string value that
    :func:`value_secret_kind` recognises are all reported. The root pointer is
    ``""``.
    """
    hits: List[SecretHit] = []
    _find(obj, "", hits)
    return hits


# ---------------------------------------------------------------------------
# Text scan
# ---------------------------------------------------------------------------

# ``key: value`` (YAML/prose) and ``key=value`` (env/ini) assignment shapes.
_ASSIGN_RE = re.compile(r"^\s*(?P<key>[A-Za-z0-9_.\-]+)\s*[:=]\s*(?P<val>.+?)\s*$")
# A Markdown table row ``| key | value |`` (exactly two data cells).
_TABLE_ROW_RE = re.compile(r"^\s*\|(?P<cells>[^|].*)\|\s*$")


def _table_cells(line: str) -> Optional[List[str]]:
    m = _TABLE_ROW_RE.match(line)
    if not m:
        return None
    return [c.strip() for c in m.group("cells").split("|")]


def scan_text(text: str) -> List[SecretHit]:
    """Scan non-JSON text for secrets, locating each as ``line:<n>`` (1-based).

    Handles three shapes per line, plus a bare value scan:

    * ``key: value`` and ``key=value`` — the key rule against ``key`` and the
      value rule against ``val``;
    * ``| key | value |`` Markdown rows — the key rule against the first cell;
    * any line whose raw text embeds a secret value (a PEM block line, an inline
      assignment) via :func:`value_secret_kind`.
    """
    hits: List[SecretHit] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        loc = f"line:{idx}"
        reported = False

        cells = _table_cells(line)
        if cells is not None and len(cells) >= 2:
            key, val = cells[0], cells[1]
            if is_credential_key(key) and val and val != REDACTED:
                hits.append(
                    SecretHit(location=loc, kind=f"credential-key:{normalize_key(key)}")
                )
                reported = True
        else:
            m = _ASSIGN_RE.match(line)
            if m:
                key, val = m.group("key"), m.group("val")
                if is_credential_key(key) and val and val != REDACTED:
                    hits.append(
                        SecretHit(
                            location=loc,
                            kind=f"credential-key:{normalize_key(key)}",
                        )
                    )
                    reported = True

        if not reported:
            kind = value_secret_kind(line)
            if kind is not None:
                hits.append(SecretHit(location=loc, kind=f"value:{kind}"))
    return hits


# ---------------------------------------------------------------------------
# Redactor
# ---------------------------------------------------------------------------


def redact(obj: Any) -> Any:
    """Return a redacted copy of ``obj`` with every leak replaced by REDACTED.

    Applies the same three rules the finders use — key name, value content and
    pair name — so ``find_secrets(redact(x)) == []`` for every input. Nested
    mappings and sequences are walked recursively; non-secret metadata is kept
    unchanged. Never mutates the input.
    """
    if isinstance(obj, Mapping):
        redact_keys, passthrough = pair_redactions(obj)
        aws_secret_keys = _aws_key_pair_secret_keys(obj)
        result: dict = {}
        for k, v in obj.items():
            low = k.lower() if isinstance(k, str) else None
            if low is not None and low in redact_keys:
                result[k] = REDACTED
            elif isinstance(k, str) and k in aws_secret_keys:
                result[k] = REDACTED
            elif low is not None and low in passthrough:
                result[k] = redact(v)
            elif isinstance(k, str) and is_credential_key(k):
                result[k] = REDACTED
            else:
                result[k] = redact(v)
        return result
    if isinstance(obj, (list, tuple)):
        return [redact(item) for item in obj]
    if isinstance(obj, str):
        return REDACTED if value_secret_kind(obj) is not None else obj
    if isinstance(obj, (bytes, bytearray)):
        decoded = _decode_bytes(bytes(obj))
        if decoded is not None and value_secret_kind(decoded) is not None:
            return REDACTED
    return obj
