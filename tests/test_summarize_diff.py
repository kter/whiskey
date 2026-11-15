"""infra/scripts/summarize-diff.py must never copy template values into the Job Summary.

The repository is public, so the plan job of .github/workflows/cdk-deploy.yml only publishes
stack names, resource types, logical IDs, actions and flags. The fixture is hand-built from the
@aws-cdk/cloudformation-diff formatter (aws-cdk 2.1144.0) and carries values in every place the
real output does: the IAM table, Parameters, a Lambda Environment subtree and Outputs.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "infra" / "scripts" / "summarize-diff.py"
FIXTURE = ROOT / "tests" / "fixtures" / "cdk_diff_sample.txt"

LEAK_CANARIES = [
    "sk-live-SUPERSECRET-0123456789",
    "PLACES_API_KEY",
    "FAKE-IAM-TABLE-VALUE",
    "secretsmanager",
    "oldParamValueXYZ",
    "newParamValueXYZ",
    "old-output-value",
    "new-output-value",
    "DrinkLogs-dev-v2",
    "aaaa.zip",
    "bbbb.zip",
    "TableName",
]


def run(diff: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--diff", str(diff), "--sha", "3c77880abc",
         "--env", "dev", "--targets", "base observability", *extra],
        check=True,
        capture_output=True,
        text=True,
    )


def test_summary_never_contains_property_values():
    out = run(FIXTURE).stdout
    for canary in LEAK_CANARIES:
        assert canary not in out, canary
    assert "\x1b" not in out


def test_summary_lists_resources_and_flags():
    out = run(FIXTURE).stdout
    assert "| add | AWS::IAM::Policy | DrinkLogsRoleDefaultPolicyAB12CD34 |" in out
    assert "| modify | AWS::Lambda::Function | DrinkLogsFunction5E6F7A8B |" in out
    assert "| replace | AWS::DynamoDB::Table | DrinkLogsTable1234ABCD |" in out
    assert "| orphan | AWS::S3::Bucket | OldBucketDEADBEEF |" in out
    assert "| may-replace | AWS::Cognito::UserPool | UserPool6BA7E5F2 |" in out
    assert "| remove | AWS::SSM::Parameter | LegacyParamC0FFEE00 |" in out
    assert "| IAM / security changes | **yes** (WhiskeyApp-Dev) |" in out
    assert "| Lambda environment changed | **yes** |" in out
    assert "| Parse uncertain | no |" in out
    data_row = next(line for line in out.splitlines() if "Data resources" in line)
    for logical_id in ("DrinkLogsTable1234ABCD", "OldBucketDEADBEEF",
                       "UserPool6BA7E5F2", "LegacyParamC0FFEE00"):
        assert logical_id in data_row
    assert "### WhiskeyObservability-Dev: no differences" in out
    assert "`3c77880abc`" in out


def test_fingerprint_ignores_colour_and_build_noise(tmp_path):
    plain = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", FIXTURE.read_text())
    plain = "\n".join(line for line in plain.splitlines() if not line.startswith(("added ", "Bundling")))
    stripped = tmp_path / "plain.txt"
    stripped.write_text(plain + "\n")

    def fingerprint(text: str) -> str:
        return re.search(r"Change fingerprint: `([0-9a-f]{64})`", text).group(1)

    assert fingerprint(run(FIXTURE).stdout) == fingerprint(run(stripped).stdout)


def test_failure_prints_only_a_fixed_message(tmp_path):
    diff = tmp_path / "diff.txt"
    diff.write_text("AccessDenied: User arn:aws:sts::123:assumed-role/x is not authorized SECRETERR\n")
    out = run(diff, "--exit-code", "1").stdout
    assert "Plan failed" in out
    assert "exit code: `1`" in out
    assert "SECRETERR" not in out
    assert "AccessDenied" not in out


def test_frontend_only_summary(tmp_path):
    diff = tmp_path / "diff.txt"
    diff.write_text("No CDK stacks selected; there is no infrastructure diff for --frontend.\n")
    out = run(diff).stdout
    assert "frontend only" in out
    assert "Parse uncertain" not in out


def test_unrecognised_output_is_flagged_not_echoed(tmp_path):
    diff = tmp_path / "diff.txt"
    diff.write_text(
        "Stack WhiskeyApp-Dev\n"
        "Resources\n"
        "[~] AWS::Lambda::Function Fn weird/logical:id=hunter2\n"
        "[?] something odd hunter3\n"
    )
    out = run(diff).stdout
    assert "hunter2" not in out
    assert "hunter3" not in out
    assert "| Parse uncertain | **yes**" in out


def test_empty_input_is_uncertain(tmp_path):
    diff = tmp_path / "diff.txt"
    diff.write_text("")
    assert "| Parse uncertain | **yes**" in run(diff).stdout
