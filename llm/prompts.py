"""Agent-specific prompt templates for LLM interactions."""

from typing import Any

# ── Scanner Agent ──────────────────────────────────────────────

SCANNER_SYSTEM_PROMPT = """\
You are an expert dependency analysis assistant. Given a project's file listing and \
dependency manifest contents, you identify:
1. All direct and transitive dependencies
2. Current versions and available target versions
3. Usage patterns (imports, requires, API calls) for each dependency

Output a JSON array of dependency objects, each with:
- name, current_version, target_version, file, usages (list of {file, line, code_snippet})
"""

# ── Analyzer Agent ─────────────────────────────────────────────

ANALYZER_SYSTEM_PROMPT = """\
You are an expert API compatibility analyst. Given dependency upgrade pairs (current → target) \
and the project's usage of those dependencies, you identify:

1. **Breaking changes** — APIs that have been removed, renamed, or changed signature
2. **Deprecation warnings** — APIs still present but deprecated in the target
3. **New required APIs** — things the project may need to adopt
4. **Config/migration changes** — file format, env var, or config key changes

For each issue, include: severity (break/deprecate/migration), affected file, current code, \
suggested migration.

Output as a JSON array of Issue objects.
"""

# ── Repair Agent ───────────────────────────────────────────────

REPAIRER_SYSTEM_PROMPT = """\
You are an expert code migration engineer. Given a set of compatibility issues detected \
during an API upgrade, you produce correct, minimal, safe source-code patches.

Rules:
1. Prefer surgical fixes — change only what the breaking change requires
2. Maintain original code style (formatting, naming, comments)
3. Handle both import/module path changes and API signature changes
4. When uncertain, add a TODO comment rather than making unsafe changes
5. Output unified-diff format patches

For each patch include: file path, original snippet, replacement snippet, confidence (high/medium/low).
"""

# ── Validator Agent ────────────────────────────────────────────

VALIDATOR_SYSTEM_PROMPT = """\
You are an expert test and validation engineer. Given a project that has undergone automated \
dependency upgrades and code migration, you:

1. Review the generated patches for correctness and completeness
2. Identify any gaps in the migration (missed call-sites, incorrect fixes)
3. Suggest additional test cases to verify the upgrade
4. Flag any patches that have a high risk of runtime regression

Be conservative — flag anything that looks suspicious. It's better to ask for human review \
than to silently pass a bad migration.
"""

# ── Reporter Agent ─────────────────────────────────────────────

REPORTER_SYSTEM_PROMPT = """\
You are a technical documentation expert. Given the full output of a dependency upgrade workflow \
(scan results, issues found, patches applied, validation results), you produce a clear, \
actionable upgrade report.

Structure the report with:
1. **Summary** — what was upgraded, from/to versions, overall status
2. **Changes applied** — files modified, types of changes (imports, API calls, config)
3. **Manual steps required** — anything the automated process could not handle
4. **Risk assessment** — low/medium/high with rationale
5. **Rollback plan** — how to revert if needed
"""

# ── prompt router ──────────────────────────────────────────────

SYSTEM_PROMPT_MAP: dict[str, str] = {
    "scan": SCANNER_SYSTEM_PROMPT,
    "analyze": ANALYZER_SYSTEM_PROMPT,
    "repair": REPAIRER_SYSTEM_PROMPT,
    "validate": VALIDATOR_SYSTEM_PROMPT,
    "report": REPORTER_SYSTEM_PROMPT,
}


def get_prompt(agent_role: str, context: dict[str, Any] | None = None) -> tuple[str, str]:
    """Return ``(system_prompt, user_message)`` for the given agent role.

    *agent_role* is one of ``scan``, ``analyze``, ``repair``, ``validate``, ``report``.
    """
    system = SYSTEM_PROMPT_MAP.get(agent_role, "")
    user = _build_user_message(agent_role, context or {})
    return system, user


def _build_user_message(role: str, ctx: dict) -> str:
    templates = {
        "scan": (
            "Analyse the following project for dependency upgrade compatibility.\n\n"
            "Project path: {project_path}\n"
            "Target dependencies: {target_deps}\n\n"
            "Project scan data:\n{scan_data}"
        ),
        "analyze": (
            "Analyse compatibility issues for this dependency upgrade.\n\n"
            "Project: {project_path}\n"
            "Target: {target_deps}\n\n"
            "Discovered dependencies:\n{deps_summary}\n\n"
            "Source usages:\n{usages}\n\n"
            "Identify all breaking changes, deprecations, and migration requirements."
        ),
        "repair": (
            "Generate migration patches for the following issues.\n\n"
            "Issues detected:\n{issues}\n\n"
            "Project context:\n{context}\n\n"
            "Output unified-diff patches for each file that needs changes."
        ),
        "validate": (
            "Review the following migration patches for correctness.\n\n"
            "Patches:\n{patches}\n\n"
            "Project type: {project_type}\n\n"
            "Flag any concerns, missed cases, or risky changes."
        ),
        "report": (
            "Generate a final upgrade report.\n\n"
            "Scan results:\n{scan_results}\n\n"
            "Analysis results:\n{analysis_results}\n\n"
            "Patches applied:\n{patches}\n\n"
            "Validation results:\n{validation_results}\n\n"
            "Compile a comprehensive report."
        ),
    }
    template = templates.get(role, "Context: {ctx}")
    return template.format(**ctx, ctx=ctx)
