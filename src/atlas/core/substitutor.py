from __future__ import annotations

import re

from ..models import Param


def substitute_placeholders(
    sql: str,
    params: list[Param],
    overrides: dict[str, str] | None = None,
    default_domain_account: str = "",
) -> str:
    """Substitute ${inputs.x} / ${monthFlag} / ${domainAccount} placeholders in SQL.

    Handles:
    - enum: bare token (column name reference, e.g. date_bylw)
    - dynamic_enum: string literal (quoted, e.g. '总部')
    - derived: bare token (empty string or suffix)
    - identity: string literal (quoted)
    - Suffix macros: ${inputs.x}_former → value_former (column name)
    """
    overrides = overrides or {}
    result = sql

    for p in params:
        placeholder = "${" + p.name + "}"

        # Determine value
        if p.name in overrides:
            value = overrides[p.name]
        elif p.default is not None:
            value = p.default
        else:
            continue

        # All types substitute as bare token.
        # Quoting is handled by the SQL itself (e.g. '${inputs.x.value}' in SQL
        # becomes 'value' after substitution). This matches evidence's runtime
        # behavior where placeholder replacement is pure text substitution.
        result = result.replace(placeholder, value)

    # Handle domainAccount if not in params
    if "${domainAccount}" in result:
        result = result.replace(
            "${domainAccount}", default_domain_account
        )

    return result


def extract_placeholders(sql: str) -> list[str]:
    """Extract all ${...} placeholders from SQL."""
    return re.findall(r"\$\{([^}]+)\}", sql)
