from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from pycodehygiene.config import Config
from pycodehygiene.models import Finding, RepoIndex, ReachabilitySummary, UsageSummary
from pycodehygiene.suppressions import SuppressionIndex


CATEGORY_TAGS = {
    "unused-import": {"unused-import", "unused-imports"},
    "unused-private-function": {"unused-function", "unused-functions"},
    "unused-private-class": {"unused-class", "unused-classes"},
    "unused-public-symbol": {"unused-public", "unused-public-symbol"},
    "unused-local": {"unused-local", "unused-variable", "unused-variables"},
    "unreachable": {"unreachable"},
}


@dataclass
class RuleContext:
    index: RepoIndex
    usage: UsageSummary
    reachability: ReachabilitySummary
    config: Config
    suppressions: SuppressionIndex


class BaseRule:
    name = "base"

    def apply(self, ctx: RuleContext) -> List[Finding]:
        raise NotImplementedError


class UnusedImportsRule(BaseRule):
    name = "unused-imports"

    def apply(self, ctx: RuleContext) -> List[Finding]:
        findings: List[Finding] = []

        for binding in ctx.index.imports.values():
            if "future_import" in binding.reasons:
                continue

            if binding.symbol_id in ctx.usage.used_imports:
                continue

            contexts = ctx.usage.import_contexts.get(binding.symbol_id, set())
            # Typing-only imports are intentional and should not be reported as dead code,
            # even when users opt in to low-confidence reporting.
            if contexts and contexts <= {"annotation", "type_checking"}:
                continue
            if binding.in_type_checking:
                continue

            evidence: List[str] = []
            reasons = set(binding.reasons)

            if contexts:
                evidence.append("Import referenced in non-runtime context")

            if "exported_in_all" in reasons:
                evidence.append("Import name re-exported via __all__")
            if "reexport_in_init" in reasons:
                evidence.append("Import re-exported by package __init__")
            if "side_effect_import" in reasons:
                evidence.append("Import may be for side effects")
            if "side_effect_module_hint" in reasons:
                evidence.append("Imported module name suggests registry/plugin side effects")
            if "imported_by_other_module" in reasons:
                evidence.append("Imported by another module in this repository")
            if "imported_by_star" in reasons:
                evidence.append("Module is imported via star import in another module")
            if "star_import" in reasons:
                evidence.append("Star import prevents reliable usage tracing")

            if not evidence:
                evidence.append("No inbound references found in repository index")

            confidence = "high"
            if reasons or contexts:
                confidence = "low"

            risk = "needs-review" if confidence == "high" else "do-not-auto-fix"

            findings.append(
                Finding(
                    finding_id=binding.symbol_id,
                    category="unused-import",
                    kind="import",
                    confidence=confidence,
                    risk=risk,
                    file=binding.file,
                    line_start=binding.line,
                    line_end=binding.end_line,
                    symbol=binding.report_name,
                    qualname=binding.report_name,
                    message="Unused import",
                    evidence=evidence,
                    suggested_action="Review before removing",
                    autofix_allowed=False,
                )
            )

        return findings


class UnusedSymbolsRule(BaseRule):
    name = "unused-symbols"

    def apply(self, ctx: RuleContext) -> List[Finding]:
        findings: List[Finding] = []
        base_usage = _compute_base_class_usage(ctx.index)
        hard_live_reasons = {
            "framework_decorator",
            "known_base_class",
            "exported_in_all",
            "reexport_in_init",
            "public_api",
            "test_file",
            "entrypoint_name",
        }

        for symbol in ctx.index.symbols.values():
            if symbol.kind not in {"function", "class"}:
                continue
            if symbol.is_method:
                continue
            if ctx.config.ignore_magic_methods and symbol.is_magic:
                continue
            if symbol.symbol_id in ctx.usage.used_symbols:
                continue
            if symbol.in_test_file and ctx.config.ignore_test_files:
                continue
            if symbol.in_type_checking:
                continue

            is_private = symbol.is_private
            is_public = not is_private

            if is_public and ctx.config.treat_public_api_as_live:
                continue

            if symbol.kind == "class" and symbol.symbol_id in base_usage:
                continue

            module_info = ctx.index.modules.get(symbol.module)
            if module_info and "dynamic_usage" in module_info.flags:
                continue

            reasons = set(symbol.reasons)
            reasons.update(ctx.usage.potential_symbol_reasons.get(symbol.symbol_id, set()))

            if reasons.intersection(hard_live_reasons):
                continue

            evidence = ["No inbound references found in repository index"]
            evidence.append("Symbol is private" if is_private else "Symbol is public")

            for reason in sorted(reasons):
                evidence.append(_reason_to_evidence(reason))

            confidence = "high"
            risk = "needs-review"

            if not is_private:
                confidence = "low"
                risk = "do-not-auto-fix"

            if reasons:
                confidence = "low"
                risk = "do-not-auto-fix"

            category = "unused-private-function" if symbol.kind == "function" else "unused-private-class"
            if not is_private:
                category = "unused-public-symbol"

            findings.append(
                Finding(
                    finding_id=symbol.symbol_id,
                    category=category,
                    kind=symbol.kind,
                    confidence=confidence,
                    risk=risk,
                    file=symbol.file,
                    line_start=symbol.line,
                    line_end=symbol.end_line,
                    symbol=symbol.name,
                    qualname=symbol.qualname,
                    message="Unused symbol",
                    evidence=evidence,
                    suggested_action="Review before removing",
                    autofix_allowed=False,
                )
            )

        return findings


class UnusedLocalsRule(BaseRule):
    name = "unused-locals"

    def apply(self, ctx: RuleContext) -> List[Finding]:
        findings: List[Finding] = []

        for file_path, locals_info in ctx.usage.unused_locals.items():
            for line, name, safe in locals_info:
                evidence = ["Assigned but never read in function scope"]
                if safe:
                    evidence.append("Assignment appears side-effect free")
                else:
                    evidence.append("Assignment may have side effects")

                confidence = "high" if safe else "low"
                risk = "needs-review" if safe else "do-not-auto-fix"

                findings.append(
                    Finding(
                        finding_id=f"{file_path}:{line}:{name}",
                        category="unused-local",
                        kind="variable",
                        confidence=confidence,
                        risk=risk,
                        file=file_path,
                        line_start=line,
                        line_end=line,
                        symbol=name,
                        qualname=name,
                        message="Unused local variable",
                        evidence=evidence,
                        suggested_action="Review before removing",
                        autofix_allowed=False,
                    )
                )

        return findings


class UnreachableRule(BaseRule):
    name = "unreachable"

    def apply(self, ctx: RuleContext) -> List[Finding]:
        findings: List[Finding] = []

        for file_path, items in ctx.reachability.unreachable.items():
            for line_start, line_end, reason in items:
                findings.append(
                    Finding(
                        finding_id=f"{file_path}:{line_start}:{reason}",
                        category="unreachable",
                        kind="statement",
                        confidence="high",
                        risk="needs-review",
                        file=file_path,
                        line_start=line_start,
                        line_end=line_end,
                        symbol="",
                        qualname="",
                        message="Unreachable code",
                        evidence=[reason],
                        suggested_action="Review and remove unreachable statements",
                        autofix_allowed=False,
                    )
                )

        return findings


class RuleEngine:
    def __init__(
        self,
        index: RepoIndex,
        usage: UsageSummary,
        reachability: ReachabilitySummary,
        config: Config,
        suppressions: SuppressionIndex,
        extra_rules: Optional[List[BaseRule]] = None,
    ):
        self.ctx = RuleContext(
            index=index,
            usage=usage,
            reachability=reachability,
            config=config,
            suppressions=suppressions,
        )
        self.rules: List[BaseRule] = [
            UnusedImportsRule(),
            UnusedSymbolsRule(),
            UnusedLocalsRule(),
            UnreachableRule(),
        ]
        if extra_rules:
            self.rules.extend(extra_rules)

    def run(self) -> Tuple[List[Finding], List[Finding]]:
        findings: List[Finding] = []
        suppressed: List[Finding] = []

        for rule in self.rules:
            findings.extend(rule.apply(self.ctx))

        final_findings: List[Finding] = []
        for finding in findings:
            suppression_reason = self._suppression_reason(finding)
            if suppression_reason:
                finding.suppressed = True
                finding.suppression_reason = suppression_reason
                suppressed.append(finding)
                continue

            if not self.ctx.config.confidence_allows(finding.confidence):
                finding.suppressed = True
                finding.suppression_reason = "below minimum confidence"
                suppressed.append(finding)
                continue

            final_findings.append(finding)

        return final_findings, suppressed

    def _suppression_reason(self, finding: Finding) -> Optional[str]:
        tags = CATEGORY_TAGS.get(finding.category, set())
        return self.ctx.suppressions.is_suppressed(finding.file, finding.line_start, tags)


def _compute_base_class_usage(index: RepoIndex) -> Set[str]:
    used: Set[str] = set()
    name_to_symbol: Dict[str, str] = {}
    for symbol_id, symbol in index.symbols.items():
        if symbol.kind == "class":
            name_to_symbol[symbol.qualname] = symbol_id
            name_to_symbol[symbol.name] = symbol_id

    for _class_id, bases in index.class_bases.items():
        for base in bases:
            base_name = base.split(".")[-1]
            symbol_id = name_to_symbol.get(base) or name_to_symbol.get(base_name)
            if symbol_id:
                used.add(symbol_id)

    return used


def _reason_to_evidence(reason: str) -> str:
    labels = {
        "decorated": "Symbol has decorators (may register at runtime)",
        "framework_decorator": "Decorator matches known framework registration pattern",
        "known_base_class": "Class inherits from known framework base",
        "exported_in_all": "Exported via __all__",
        "reexport_in_init": "Re-exported by package __init__",
        "public_api": "Treated as public API",
        "test_file": "Defined in test file",
        "entrypoint_name": "Matches common entry point name",
        "unresolved_attribute_call": "Matched unresolved attribute call",
    }
    return labels.get(reason, reason.replace("_", " "))
