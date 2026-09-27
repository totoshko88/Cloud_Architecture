"""Property tests for the shared secret vocabulary (`rule_engine.secret_safety`).

Feature: honest-gates (release 1.7.0), task 3.2 (and 3.3, 3.4 which append here).

These properties pin the contract the design records for `secret_safety`
(design.md → *Correctness Properties*, Properties 11–14). Each uses Hypothesis
with ``max_examples >= 100`` via the ``honest-gates`` profile loaded in
``tests/conftest.py``.
"""

from __future__ import annotations

from hypothesis import given

from rule_engine.secret_safety import find_secrets, redact
from tests.strategies import benign_json, plant_secret


# Feature: honest-gates, Property 11: Planted secrets are found where they were planted
@given(planted=plant_secret())
def test_planted_secret_is_found_at_its_pointer(planted):
    """A secret planted at a known JSON pointer is reported at that pointer.

    ``plant_secret`` embeds either a string value under a credential-named key
    (rendered in a random case/separator style — R3.2) or a value of a
    recognized secret shape under a benign key (R3.3), inside an otherwise
    benign JSON object. ``find_secrets`` must return at least one hit, and one
    of those hits must be located at exactly the planted pointer (R3.1).
    """
    value, pointer = planted

    hits = find_secrets(value)

    assert hits, f"expected a secret hit at {pointer!r}, got none"
    locations = [hit.location for hit in hits]
    assert pointer in locations, (
        f"expected a hit at planted pointer {pointer!r}; "
        f"got locations {locations!r}"
    )

# Feature: honest-gates, Property 12: Metadata is never reported
@given(benign=benign_json())
def test_metadata_is_never_reported(benign):
    """A JSON value built only from benign generators yields no secret hits.

    ``benign_json`` composes dicts, lists and scalars using only the benign
    vocabulary the design enumerates for Property 12 (R3.4): identifiers, ARNs,
    regions, the ``[REDACTED]`` literal, the bare ``SecureString`` label, a
    public ``CERTIFICATE`` PEM block, and the metadata-key names that merely
    *contain* a credential marker substring (``AccessKeyId``, ``SecretArn``,
    ``PasswordLastUsed``, ``privateKeyType``, ``CustomerMasterKeySpec``,
    ``publicKey``, ``partitionKey`` …). None of these is a leak, so
    ``find_secrets`` must return the empty list for every generated object.
    """
    hits = find_secrets(benign)

    assert hits == [], (
        f"expected no secret hits for benign metadata; got "
        f"{[(h.location, h.kind) for h in hits]!r}"
    )


# --------------------------------------------------------------------------- #
# Property 13 helpers
# --------------------------------------------------------------------------- #


def _changed_pointers(original, redacted, prefix=""):
    """Return the set of RFC 6901 pointers where ``redact`` changed a value.

    Walks the original and redacted objects in lockstep (they share shape, since
    ``redact`` only rewrites string/bytes leaf values, never keys or structure),
    yielding the pointer of every leaf whose value the redactor replaced.
    """
    changed = set()
    if isinstance(original, dict) and isinstance(redacted, dict):
        for key in original:
            token = str(key).replace("~", "~0").replace("/", "~1")
            changed |= _changed_pointers(
                original[key], redacted.get(key), f"{prefix}/{token}"
            )
        return changed
    if isinstance(original, (list, tuple)) and isinstance(redacted, (list, tuple)):
        for index, item in enumerate(original):
            sub = redacted[index] if index < len(redacted) else None
            changed |= _changed_pointers(item, sub, f"{prefix}/{index}")
        return changed
    if original != redacted:
        changed.add(prefix or "")
    return changed


# Feature: honest-gates, Property 13: The redactor and the Linter agree
@given(planted=plant_secret())
def test_redactor_output_has_no_secrets_and_agrees_with_finder(planted):
    """The redactor and the Linter's ``find_secrets`` agree on every input.

    The design's *Soundness link* (design.md → §5) states two properties, since
    both share one predicate (R3.6, R3.4):

    1. ``find_secrets(redact(x)) == []`` — a redacted object never leaks; the
       redaction is complete and idempotent.
    2. Every value the redactor would change is reported by ``find_secrets``
       before redaction — the redactor never silently rewrites a value the
       Linter would have passed, so the finder is a sound witness for the
       redactor.

    ``plant_secret`` supplies a benign object carrying exactly one planted
    secret (by credential key or by secret value shape), so there is at least
    one real change to check agreement against.
    """
    value, _pointer = planted

    # (1) A redacted object carries no secrets the finder can see.
    redacted = redact(value)
    assert find_secrets(redacted) == [], (
        "redact() left a secret find_secrets can still see: "
        f"{[(h.location, h.kind) for h in find_secrets(redacted)]!r}"
    )

    # (2) Every location the redactor changed was reported by find_secrets.
    changed = _changed_pointers(value, redacted)
    reported = {hit.location for hit in find_secrets(value)}
    assert changed <= reported, (
        f"redactor changed {sorted(changed - reported)!r} but find_secrets did "
        f"not report those locations (reported {sorted(reported)!r})"
    )


# Feature: honest-gates, Property 13: The redactor and the Linter agree
@given(benign=benign_json())
def test_redactor_is_a_noop_on_benign_input(benign):
    """On benign input the redactor changes nothing and the finder sees nothing.

    The agreement holds trivially but importantly at the benign end: if
    ``find_secrets`` reports no leak, ``redact`` must leave the object
    unchanged (no over-redaction), and the redacted object still has no secrets
    (R3.6, R3.4).
    """
    reported = find_secrets(benign)
    assert reported == [], (
        f"benign input unexpectedly reported secrets: "
        f"{[(h.location, h.kind) for h in reported]!r}"
    )

    redacted = redact(benign)
    assert redacted == benign, "redact() altered a benign object (over-redaction)"
    assert find_secrets(redacted) == []

# --------------------------------------------------------------------------- #
# Property 14 helpers (task 13.2)
# --------------------------------------------------------------------------- #

from hypothesis import strategies as st

from rule_engine.normalizer import normalize
from rule_engine.schema import validate_resource
from tests.strategies import (
    CREDENTIAL_KEYS,
    SECRET_SHAPES,
    recase_key,
    _CASE_STYLES,
)


@st.composite
def _native_resource_with_secret(draw):
    """Generate a normalizable native resource carrying a planted secret.

    The resource has every mandatory field the Normalizer requires (``name``,
    ``boundary``, ``region``, a mappable ``resourceType``) so ``normalize``
    succeeds, and a secret is planted one of two ways (mirroring
    ``plant_secret``):

    * a secret-shaped value under a benign tag/string field, or
    * a credential-named tag key (rendered in a random case/separator style)
      whose value is an arbitrary non-``[REDACTED]`` string.

    Returns ``(resource, provider)``.
    """
    provider = draw(st.sampled_from(["aws", "azure", "gcp", "oci", "generic"]))
    identifier = draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_", min_size=1, max_size=12))
    resource = {
        "resourceType": draw(
            st.sampled_from(
                ["compute_instance", "object_store", "serverless_fn", "file_system"]
            )
        ),
        "name": "res-" + identifier,
        "boundary": "boundary-" + identifier,
        "region": draw(st.sampled_from(["us-east-1", "eu-central-1", "global"])),
        "id": "id-" + identifier,
        "tags": {"env": "prod", "team": "platform"},
    }

    by_key = draw(st.booleans())
    if by_key:
        # A credential-named tag key with a non-empty secret value.
        base = draw(st.sampled_from(CREDENTIAL_KEYS))
        cred_key = recase_key(base, draw(st.sampled_from(_CASE_STYLES)))
        secret_value = draw(
            st.text(min_size=1, max_size=24).filter(lambda s: s != "[REDACTED]")
        )
        resource["tags"] = dict(resource["tags"], **{cred_key: secret_value})
    else:
        # A secret-shaped value planted in a string field or a benign tag value.
        _, secret_value = draw(st.sampled_from(SECRET_SHAPES))
        where = draw(st.sampled_from(["name", "id", "boundary", "tag-value"]))
        if where == "tag-value":
            resource["tags"] = dict(resource["tags"], leak=secret_value)
        else:
            resource[where] = secret_value

    return resource, provider


# Feature: honest-gates, Property 14: Normalized resources carry no secrets
@given(planted=_native_resource_with_secret())
def test_normalized_resource_carries_no_secret(planted):
    """`normalize` produces a secret-free, schema-valid Normalized Resource.

    A native resource with a secret planted in a tag (credential-named key or
    secret-shaped value) or in a string field (``name``/``id``/``boundary``)
    is normalized. Because the Normalizer routes tags and extracted string
    fields through ``secret_safety.redact`` (task 13.1), the resulting
    Normalized Resource must carry no secret ``find_secrets`` can see, and it
    must still validate against the Inventory Schema (R3.7).
    """
    resource, provider = planted

    normalized = normalize(resource, provider)

    hits = find_secrets(normalized)
    assert hits == [], (
        f"normalized resource leaked a secret: "
        f"{[(h.location, h.kind) for h in hits]!r}"
    )

    # The redacted resource still conforms to the Inventory Schema.
    validate_resource(normalized)
