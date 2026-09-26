"""Guard: the custom agents' permission rules say what their prose promises.

The three agents in ``.kiro/agents/`` encode the project's safety contracts as
Kiro permission rules. Before 1.6.1 those rules had gaps that no test could see:
``aws * get*`` admitted ``aws secretsmanager get-secret-value``, ``cat *`` read
``~/.aws/credentials``, ``python scripts/*`` ran any script, and the
diagram-author's ``git *`` pushed without asking.

These tests evaluate the rules against concrete commands with a small model of
Kiro's **documented** matching semantics (kiro.dev → Permissions):

* in a shell pattern, ``*`` matches any sequence of characters — arguments
  included — and ``?`` / ``**`` / character classes are not special;
* a compound command is split on ``;``, ``&&``, ``||`` and ``|`` and every part
  is judged; the strictest verdict wins;
* effects combine as deny > ask > allow; a command matching no rule is left to
  Kiro's default, which is never "allowed without asking".

It is a model, not Kiro's implementation — but it pins the intent, so a future
edit that re-opens one of these holes fails here rather than in a user's account.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Dict, List

import pytest
import yaml

_AGENTS = Path(__file__).resolve().parents[1] / ".kiro" / "agents"
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_SPLIT_RE = re.compile(r"\s*(?:;|&&|\|\||\|)\s*")
_RANK = {"deny": 3, "ask": 2, "allow": 1, "default": 0}


def _rules(agent: str) -> List[Dict]:
    text = (_AGENTS / f"{agent}.md").read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    assert match, f"{agent}.md has no YAML frontmatter"
    config = yaml.safe_load(match.group(1))
    return config["permissions"]["rules"]


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Kiro shell-pattern semantics: only ``*`` is special, and it spans anything."""
    return re.compile("^" + ".*".join(re.escape(part) for part in pattern.split("*")) + "$", re.S)


def _verdict_one(rules: List[Dict], capability: str, subject: str) -> str:
    best = "default"
    for rule in rules:
        if rule.get("capability") != capability:
            continue
        for pattern in rule.get("match") or []:
            if capability == "shell":
                hit = bool(_glob_to_regex(pattern).match(subject))
            else:
                hit = fnmatch.fnmatch(subject, pattern)
            if hit and _RANK[rule["effect"]] > _RANK[best]:
                best = rule["effect"]
    return best


def verdict(agent: str, command: str) -> str:
    """Return ``allow`` / ``ask`` / ``deny`` / ``default`` for a shell command."""
    rules = _rules(agent)
    parts = [p for p in _SPLIT_RE.split(command.strip()) if p]
    verdicts = [_verdict_one(rules, "shell", part) for part in parts]
    if "deny" in verdicts:
        return "deny"
    if "ask" in verdicts:
        return "ask"
    if all(v == "allow" for v in verdicts):
        return "allow"
    return "default"


def path_verdict(agent: str, capability: str, path: str) -> str:
    return _verdict_one(_rules(agent), capability, path)


# ---------------------------------------------------------------------------
# inventory-collector
# ---------------------------------------------------------------------------

# Every secret-returning / credential-minting operation, as ``(CLI command the
# agent would run, provider, the verb as the collector sees it)``. The collector
# guards the code path and the agent rules guard the shell path, so each row is
# checked against BOTH, and every collector pattern must be mirrored by a row
# (test_every_collector_secret_pattern_has_a_denied_shell_form).
_SECRET_COMMANDS = [
    ("aws secretsmanager get-secret-value --secret-id app/db", "aws", "get_secret_value"),
    ("aws secretsmanager batch-get-secret-value --secret-id-list a b", "aws", "batch_get_secret_value"),
    ("aws ssm get-parameter --name /app/db --with-decryption", "aws", "get_parameter"),
    ("aws ssm get-parameters --names /a /b", "aws", "get_parameters"),
    ("aws ssm get-parameters-by-path --path /app", "aws", "get_parameters_by_path"),
    ("aws sts get-session-token", "aws", "get_session_token"),
    ("aws sts get-federation-token --name x", "aws", "get_federation_token"),
    ("aws connect get-federation-token --instance-id i", "aws", "get_federation_token"),
    ("aws cognito-identity get-open-id-token --identity-id x", "aws", "get_open_id_token"),
    ("aws sts assume-role --role-arn arn:aws:iam::1:role/x --role-session-name s", None, None),
    ("aws ecr get-login-password --region us-east-1", "aws", "get_login_password"),
    ("aws ecr get-authorization-token", "aws", "get_authorization_token"),
    ("aws codeartifact get-authorization-token --domain d", "aws", "get_authorization_token"),
    ("aws eks get-token --cluster-name c", "aws", "get_token"),
    ("aws ec2 get-password-data --instance-id i-1", "aws", "get_password_data"),
    ("aws secretsmanager get-random-password", "aws", "get_random_password"),
    (
        "aws lightsail get-relational-database-master-user-password --relational-database-name d",
        "aws",
        "get_relational_database_master_user_password",
    ),
    ("aws lightsail get-instance-access-details --instance-name i", "aws", "get_instance_access_details"),
    ("aws redshift get-cluster-credentials --cluster-identifier c --db-user u", "aws", "get_cluster_credentials"),
    ("aws sso get-role-credentials --role-name r --account-id 1 --access-token t", "aws", "get_role_credentials"),
    ("aws configure get aws_secret_access_key", None, None),
    ("aws configure export-credentials", None, None),
    ("aws s3api get-object --bucket b --key k out.bin", "aws", "get_object"),
    ("az keyvault secret show --vault-name v --name n", "azure", "az keyvault secret show"),
    ("az keyvault secret download --vault-name v --name n --file f", None, None),
    ("az storage account keys list --account-name a", "azure", "az storage account keys list"),
    ("az storage account show-connection-string --name a", "azure", "az storage account show-connection-string"),
    ("az cosmosdb keys list --name c --resource-group g", "azure", "az cosmosdb keys list"),
    ("az redis list-keys --name r --resource-group g", None, None),
    ("az search admin-key show --service-name s --resource-group g", "azure", "az search admin-key show"),
    ("az acr credential show --name r", "azure", "az acr credential show"),
    ("az aks get-credentials --name c --resource-group g", "azure", "az aks get-credentials"),
    ("az account get-access-token", "azure", "az account get-access-token"),
    ("az webapp config appsettings list --name w --resource-group g", "azure", "az webapp config appsettings list"),
    (
        "az webapp deployment list-publishing-profiles --name w --resource-group g",
        "azure",
        "az webapp deployment list-publishing-profiles",
    ),
    ("gcloud secrets versions access latest --secret s", "gcp", "gcloud secrets versions access"),
    ("gcloud auth print-access-token", "gcp", "gcloud auth print-access-token"),
    ("gcloud auth application-default print-access-token", None, None),
    ("gcloud container clusters get-credentials c", "gcp", "gcloud container clusters get-credentials"),
    ("oci secrets secret-bundle get --secret-id ocid1.vaultsecret.x", "oci", "oci secrets secret-bundle get"),
    ("oci os object get --bucket-name b --name o --file out", "oci", "oci os object get"),
    ("terraform output -json", None, None),
    ("terraform state pull", None, None),
]


@pytest.mark.parametrize("command", [row[0] for row in _SECRET_COMMANDS])
def test_inventory_collector_denies_secret_returning_commands(command: str) -> None:
    assert verdict("inventory-collector", command) == "deny"


@pytest.mark.parametrize(
    "command,provider,verb", [row for row in _SECRET_COMMANDS if row[2] is not None]
)
def test_the_collector_rejects_the_same_operations(command: str, provider: str, verb: str) -> None:
    from rule_engine.collector import is_secret_verb

    assert is_secret_verb(verb, provider), f"collector allows {verb!r} ({command})"


def test_every_collector_secret_pattern_has_a_denied_shell_form() -> None:
    """A new collector pattern with no shell mirror here fails this test."""
    from rule_engine.collector import _SECRET_VERB_PATTERNS, _normalised_verb

    verbs = [(_normalised_verb(v), p) for _c, p, v in _SECRET_COMMANDS if v is not None]
    for pattern, providers in _SECRET_VERB_PATTERNS:
        covered = any(
            pattern.search(verb) and (providers is None or provider in providers)
            for verb, provider in verbs
        )
        assert covered, f"no denied shell command mirrors collector pattern {pattern.pattern!r}"


@pytest.mark.parametrize(
    "command",
    [
        "aws ec2 describe-instances",
        "aws s3api list-buckets",
        "aws secretsmanager list-secrets",
        "aws secretsmanager describe-secret --secret-id app/db",
        "aws ssm describe-parameters",
        "aws sts get-caller-identity",
        "aws iam get-account-password-policy",
        "aws kms list-keys",
        "aws efs describe-file-systems",
        "az vm list",
        "az keyvault list",
        "az account show",
        "gcloud compute instances list",
        "gcloud secrets list",
        "gcloud kms keys list",
        "oci compute instance list",
        "oci kms management key list",
        "az sshkey list",
        "az ad app federated-credential list",
        "aws iam list-service-specific-credentials",
        "terraform state list",
        "terraform show",
        "rule-engine-check-snapshot --root examples",
    ],
)
def test_inventory_collector_still_allows_metadata_enumeration(command: str) -> None:
    assert verdict("inventory-collector", command) == "allow"


def test_terraform_json_state_needs_confirmation() -> None:
    """``terraform show -json`` prints sensitive values in clear; it is the
    generic profile's state import, so it is asked about rather than denied."""
    assert verdict("inventory-collector", "terraform show -json") == "ask"
    assert verdict("inventory-collector", "terraform show plan.out -json") == "ask"


@pytest.mark.parametrize("agent", ["inventory-collector", "rule-engine-reviewer"])
@pytest.mark.parametrize(
    "command",
    [
        "aws ec2 describe-instances > ~/.zshrc",
        "ls ~ > listing.txt",
        "rule-engine-lint --all > ~/.zshrc",
        "pytest -q --co $(cat ~/.aws/credentials)",
        "ls `cat ~/.aws/credentials`",
        "aws ec2 describe-instances\nrm -rf ~/work",
        "rule-engine-check-snapshot --root examples < /etc/passwd",
    ],
)
def test_read_only_agents_deny_redirects_and_hidden_commands(agent: str, command: str) -> None:
    assert verdict(agent, command) == "deny"


@pytest.mark.parametrize(
    "command",
    ["python scripts/build_aws_ha_example.py --stdout-summary > ~/.zshrc", "pytest $(cat x)"],
)
def test_diagram_author_asks_before_redirects_or_substitution(command: str) -> None:
    assert verdict("diagram-author", command) == "ask"


@pytest.mark.parametrize(
    "command",
    [
        "aws ec2 describe-instances; aws s3 rb s3://bucket",
        "aws ec2 describe-instances && rm -rf /tmp/x",
        "aws ec2 describe-instances | aws s3 cp - s3://bucket/out",
        "aws ec2 run-instances --image-id ami-1 --key-name get-key",
        "aws lambda invoke --function-name get-report out.json",
        "aws ssm send-command --document-name get-info",
        "aws s3 cp s3://get-bucket/x .",
        "aws s3 mv s3://a/x s3://get-b/x",
        "aws s3 presign s3://get-bucket/x",
        "aws kms decrypt --ciphertext-blob fileb://x",
        "az storage blob download --container-name c --name list -f out",
    ],
)
def test_inventory_collector_denies_chained_or_executing_commands(command: str) -> None:
    assert verdict("inventory-collector", command) == "deny"


@pytest.mark.parametrize(
    "command",
    ["cat ~/.aws/credentials", "cat a > b", "python scripts/build_aws_ha_example.py"],
)
def test_inventory_collector_no_longer_auto_allows_cat_or_scripts(command: str) -> None:
    assert verdict("inventory-collector", command) != "allow"


# ---------------------------------------------------------------------------
# diagram-author
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command", ["git status", "git diff --stat", "git log --oneline -5", "git add examples/aws"]
)
def test_diagram_author_read_only_git_is_allowed(command: str) -> None:
    assert verdict("diagram-author", command) == "allow"


@pytest.mark.parametrize(
    "command",
    [
        "git push",
        "git push -u origin 1.6.1",
        "git commit -m x",
        "git checkout main",
        "git stash",
        "git branch feature",
        "git tag v9.9.9",
        "git rebase main",
    ],
)
def test_diagram_author_must_ask_before_changing_history_or_remotes(command: str) -> None:
    assert verdict("diagram-author", command) == "ask"


@pytest.mark.parametrize(
    "command",
    [
        "git push --force",
        "git push -f origin main",
        "git push origin main --force-with-lease",
        "git reset --hard HEAD~1",
        "git clean -fd",
        "git checkout -- .",
        "git restore .",
        "git branch -D feature",
        "git stash drop",
        "rm -rf examples",
    ],
)
def test_diagram_author_destructive_git_is_denied(command: str) -> None:
    assert verdict("diagram-author", command) == "deny"


# ---------------------------------------------------------------------------
# rule-engine-reviewer
# ---------------------------------------------------------------------------


def test_reviewer_no_longer_auto_allows_cat() -> None:
    assert verdict("rule-engine-reviewer", "cat ~/.aws/credentials") != "allow"


@pytest.mark.parametrize(
    "command",
    [
        "rule-engine-lint --all --fail-on error,critical",
        "rule-engine-check-snapshot --root examples --strict",
        "python scripts/orthogonalise_drawio.py --check examples/aws/01-aws-agent-platform.drawio",
        "pytest -q",
    ],
)
def test_reviewer_runs_the_full_gate(command: str) -> None:
    assert verdict("rule-engine-reviewer", command) == "allow"


# ---------------------------------------------------------------------------
# All agents: credential stores are never read
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "agent", ["inventory-collector", "diagram-author", "rule-engine-reviewer"]
)
@pytest.mark.parametrize(
    "path",
    [
        "/Users/someone/.aws/credentials",
        "/home/someone/.azure/accessTokens.json",
        "/home/someone/.config/gcloud/application_default_credentials.json",
        "/home/someone/.oci/oci_api_key.pem",
        "/home/someone/.kube/config",
        "/home/someone/.ssh/id_ed25519",
        "/work/project/.env",
        "/work/project/.env.production",
        "/home/someone/.aws/cli/cache/0123abcd.json",
        "/home/someone/.git-credentials",
        "/home/someone/.netrc",
        "/home/someone/.config/gh/hosts.yml",
    ],
)
def test_no_agent_reads_local_credential_stores(agent: str, path: str) -> None:
    assert path_verdict(agent, "fs_read", path) == "deny"
