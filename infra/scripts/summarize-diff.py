#!/usr/bin/env python3
"""Summarize `cdk diff` output without printing any property value.

Used by .github/workflows/cdk-deploy.yml (the repository is public, so the Job Summary must
never contain template values). The summary is built only from allowlisted tokens:

- stack names            (``[A-Za-z0-9-]+``)
- resource types         (``AWS::...`` / ``Custom::...``)
- logical IDs            (``[A-Za-z0-9]+``)
- the change action      (add / modify / replace / may-replace / remove / orphan / import)
- counts, yes/no flags, the commit SHA and hashes

Property trees, IAM tables, Parameters/Outputs lines and anything that fails the allowlist are
never copied into the output. If the input cannot be parsed with confidence, the summary says
so ("parse uncertain") instead of guessing.

Usage:
  summarize-diff.py --diff diff.txt --sha <commit> --env dev --targets "base observability" \
      [--exit-code N]

The change fingerprint is a sha256 over the sorted (stack, type, logical ID, action) tuples, so
the owner can run the script on a local `cdk diff --method template --no-color` capture and
compare it with the CI summary. The raw diff.txt hash also covers npm/tsc noise and will not
match a local run.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
STACK_RE = re.compile(r"^Stack (\S+)")
STACK_NAME_RE = re.compile(r"^[A-Za-z0-9-]{1,128}$")
RESOURCE_RE = re.compile(r"^\[(\+|~|-|←)\] (\S+) (.+)$")
TYPE_RE = re.compile(r"^(AWS|Custom)::[A-Za-z0-9:]{1,200}$")
LOGICAL_ID_RE = re.compile(r"^[A-Za-z0-9]{1,255}$")
MOVE_RE = re.compile(r"\s*\(OR move .*\)\s*$")
CHILD_ENV_RE = re.compile(r"^ [├└]─ \[.\] Environment\b")
SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")
ENV_RE = re.compile(r"^[a-z]{2,8}$")
TARGET_RE = re.compile(r"^[a-z][a-z-]{0,30}$")

SECTION_HEADERS = {
    "Template",
    "IAM Statement Changes",
    "IAM Policy Changes",
    "Security Group Changes",
    "Parameters",
    "Metadata",
    "Mappings",
    "Conditions",
    "Resources",
    "Outputs",
    "Other Changes",
}
SECURITY_SECTIONS = {"IAM Statement Changes", "IAM Policy Changes", "Security Group Changes"}
# Trailing impact words printed by @aws-cdk/cloudformation-diff (formatImpact).
IMPACTS = ("may be replaced", "replace", "destroy", "orphan", "import")
DATA_TYPES = {
    "AWS::DynamoDB::Table",
    "AWS::S3::Bucket",
    "AWS::Cognito::UserPool",
    "AWS::SSM::Parameter",
}
DATA_RISK_ACTIONS = {"replace", "may-replace", "remove", "orphan"}
ACTION_ORDER = ("add", "modify", "replace", "may-replace", "remove", "orphan", "import")
NO_DIFF_MARKER = "There were no differences"
NO_STACKS_MARKER = "No CDK stacks selected"
UNPARSED = "(unparsed)"


@dataclass
class Change:
    type: str
    logical_id: str
    action: str


@dataclass
class StackDiff:
    name: str
    changes: list[Change] = field(default_factory=list)
    security_section: bool = False
    lambda_env_changed: bool = False
    no_differences: bool = False
    saw_section: bool = False
    unparsed_lines: int = 0


def _action(prefix: str, impact: str) -> str:
    if prefix == "+":
        return "add"
    if prefix == "←":
        return "import"
    if prefix == "-":
        return "orphan" if impact == "orphan" else "remove"
    if impact == "replace":
        return "replace"
    if impact == "may be replaced":
        return "may-replace"
    return "modify"


def _parse_resource(line: str) -> Change | None:
    match = RESOURCE_RE.match(line)
    if not match:
        return None
    prefix, rtype, rest = match.groups()
    if not TYPE_RE.match(rtype):
        return None
    rest = MOVE_RE.sub("", rest).rstrip()
    impact = ""
    for word in IMPACTS:
        if rest.endswith(" " + word) or rest == word:
            impact = word
            rest = rest[: -len(word)].rstrip()
            break
    tokens = rest.split()
    logical_id = tokens[-1] if tokens else ""
    if not LOGICAL_ID_RE.match(logical_id):
        logical_id = UNPARSED
    return Change(type=rtype, logical_id=logical_id, action=_action(prefix, impact))


def parse(text: str) -> tuple[list[StackDiff], bool]:
    """Return the per-stack diffs and whether the "no stacks selected" marker was seen."""
    stacks: list[StackDiff] = []
    current: StackDiff | None = None
    section = ""
    last_change: Change | None = None
    no_stacks = False
    for raw in text.splitlines():
        line = ANSI_RE.sub("", raw).rstrip("\r")
        if NO_STACKS_MARKER in line:
            no_stacks = True
        stack_match = STACK_RE.match(line)
        if stack_match:
            name = stack_match.group(1)
            current = StackDiff(name=name if STACK_NAME_RE.match(name) else UNPARSED)
            stacks.append(current)
            section = ""
            last_change = None
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith(NO_DIFF_MARKER):
            current.no_differences = True
            continue
        if stripped in SECTION_HEADERS and line == stripped:
            section = stripped
            current.saw_section = True
            if section in SECURITY_SECTIONS:
                current.security_section = True
            last_change = None
            continue
        if section != "Resources":
            continue
        if line.startswith("["):
            change = _parse_resource(line)
            if change is None:
                current.unparsed_lines += 1
                last_change = None
            else:
                current.changes.append(change)
                last_change = change
            continue
        if (
            last_change is not None
            and last_change.type == "AWS::Lambda::Function"
            and CHILD_ENV_RE.match(line)
        ):
            current.lambda_env_changed = True
    return stacks, no_stacks


def fingerprint(stacks: list[StackDiff]) -> str:
    rows = sorted(
        f"{stack.name}|{change.type}|{change.logical_id}|{change.action}"
        for stack in stacks
        for change in stack.changes
    )
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def _safe(value: str, pattern: re.Pattern[str]) -> str:
    return value if pattern.match(value) else UNPARSED


def render(
    text: str,
    raw: bytes,
    sha: str,
    env: str,
    targets: list[str],
    exit_code: int,
) -> str:
    sha = _safe(sha, SHA_RE)
    env = _safe(env, ENV_RE)
    target_label = ", ".join(_safe(t, TARGET_RE) for t in targets) or "(none)"
    out = [
        f"## CDK plan: {env} ({target_label})",
        "",
        f"- Commit: `{sha}`",
        f"- diff.txt sha256: `{hashlib.sha256(raw).hexdigest()}`",
    ]
    if exit_code != 0:
        out += [
            f"- deploy.sh --diff-only exit code: `{exit_code}`",
            "",
            "**Plan failed.** Error details are not shown here because this repository is "
            "public. Run `deploy.sh <env> <targets> --diff-only` locally to see them.",
        ]
        return "\n".join(out) + "\n"

    stacks, no_stacks = parse(text)
    if not stacks and no_stacks:
        out += [
            "",
            "No CDK stacks selected (frontend only). The deploy job will build and sync the "
            "frontend from this commit.",
        ]
        return "\n".join(out) + "\n"

    uncertain = not stacks or any(
        stack.unparsed_lines
        or any(change.logical_id == UNPARSED for change in stack.changes)
        or stack.name == UNPARSED
        or not (stack.no_differences or stack.saw_section)
        for stack in stacks
    )
    iam_stacks = [
        stack.name
        for stack in stacks
        if stack.security_section
        or any(change.type.startswith("AWS::IAM::") for change in stack.changes)
    ]
    data_risks = [
        f"{stack.name}/{change.logical_id} ({change.type}, {change.action})"
        for stack in stacks
        for change in stack.changes
        if change.type in DATA_TYPES and change.action in DATA_RISK_ACTIONS
    ]
    lambda_env = any(stack.lambda_env_changed for stack in stacks)

    out += [
        f"- Change fingerprint: `{fingerprint(stacks)}`",
        "",
        "### Flags",
        "",
        "| Check | Result |",
        "| --- | --- |",
        f"| IAM / security changes | {'**yes** (' + ', '.join(iam_stacks) + ')' if iam_stacks else 'no'} |",
        f"| Data resources replaced or removed | {'**yes**: ' + '; '.join(data_risks) if data_risks else 'no'} |",
        f"| Lambda environment changed | {'**yes**' if lambda_env else 'no'} |",
        f"| Parse uncertain | {'**yes**: read the full diff locally' if uncertain else 'no'} |",
        "",
    ]
    for stack in stacks:
        counts = {action: 0 for action in ACTION_ORDER}
        for change in stack.changes:
            counts[change.action] += 1
        summary = " / ".join(f"{action} {counts[action]}" for action in ACTION_ORDER if counts[action])
        if stack.no_differences and not stack.changes:
            summary = "no differences"
        elif not stack.changes:
            summary = "no resource changes (non-resource sections changed)"
        out += [f"### {stack.name}: {summary}", ""]
        if stack.changes:
            out += ["| Action | Type | Logical ID |", "| --- | --- | --- |"]
            out += [
                f"| {change.action} | {change.type} | {change.logical_id} |"
                for change in stack.changes
            ]
            out.append("")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--diff", required=True, type=Path)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--env", required=True)
    parser.add_argument("--targets", default="")
    parser.add_argument("--exit-code", type=int, default=0)
    args = parser.parse_args(argv)
    raw = args.diff.read_bytes() if args.diff.exists() else b""
    sys.stdout.write(
        render(
            raw.decode("utf-8", errors="replace"),
            raw,
            args.sha,
            args.env,
            args.targets.split(),
            args.exit_code,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
