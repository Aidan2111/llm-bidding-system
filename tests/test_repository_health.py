"""Repository-level product and OSS readiness guardrails."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


class RepositoryHealthTests(unittest.TestCase):
    def _read(self, relative_path: str) -> str:
        return (REPO_ROOT / relative_path).read_text(encoding="utf-8")

    def test_community_and_support_files_exist_and_are_linked(self):
        required_files = [
            "CONTRIBUTING.md",
            "SECURITY.md",
            "SUPPORT.md",
            "CODE_OF_CONDUCT.md",
            "GOVERNANCE.md",
            "CHANGELOG.md",
            "docs/oss-readiness.md",
            "docs/operations.md",
        ]
        for relative_path in required_files:
            with self.subTest(path=relative_path):
                path = REPO_ROOT / relative_path
                self.assertTrue(path.is_file(), f"{relative_path} is missing")
                self.assertGreater(
                    len(path.read_text(encoding="utf-8").strip()),
                    250,
                    f"{relative_path} is too thin to guide outside users",
                )

        readme = self._read("README.md")
        for relative_path in required_files:
            with self.subTest(readme_link=relative_path):
                self.assertIn(f"]({relative_path})", readme)

    def test_pyproject_exposes_distribution_metadata_for_integrators(self):
        pyproject = self._read("pyproject.toml")

        for field in (
            '[project.urls]',
            'Homepage = "https://github.com/Aidan2111/llm-bidding-system"',
            'Repository = "https://github.com/Aidan2111/llm-bidding-system"',
            'Issues = "https://github.com/Aidan2111/llm-bidding-system/issues"',
            'Documentation = "https://github.com/Aidan2111/llm-bidding-system#readme"',
            'Changelog = "https://github.com/Aidan2111/llm-bidding-system/blob/main/CHANGELOG.md"',
            '[project.optional-dependencies]',
            'dev = [',
        ):
            with self.subTest(field=field):
                self.assertIn(field, pyproject)

    def test_distribution_manifest_includes_user_facing_docs(self):
        manifest = self._read("MANIFEST.in")
        for line in (
            "include CHANGELOG.md CODE_OF_CONDUCT.md CONTRIBUTING.md GOVERNANCE.md SECURITY.md SUPPORT.md",
            "include llm-bidding.config.json",
            "recursive-include docs *.md",
            "recursive-include examples *.json *.sh",
            "recursive-include .github *.md *.yml",
        ):
            with self.subTest(line=line):
                self.assertIn(line, manifest)

    def test_package_is_typed_for_downstream_consumers(self):
        self.assertTrue((REPO_ROOT / "src/llm_bidding/py.typed").is_file())
        pyproject = self._read("pyproject.toml")
        self.assertIn('[tool.setuptools.package-data]', pyproject)
        self.assertIn('"llm_bidding" = ["py.typed"]', pyproject)

    def test_ci_has_build_security_and_dependency_update_gates(self):
        test_workflow = self._read(".github/workflows/test.yml")
        self.assertIn("python -m build", test_workflow)
        self.assertIn("python -m pip install", test_workflow)
        self.assertIn("dist/*.whl", test_workflow)
        self.assertIn("llm-bid --help", test_workflow)
        self.assertIn("windows-latest", test_workflow)

        security_workflow = self._read(".github/workflows/security.yml")
        self.assertIn("pip-audit", security_workflow)
        self.assertIn("gitleaks", security_workflow)
        self.assertIn("permissions:", security_workflow)
        self.assertIn("contents: read", security_workflow)

        dependabot = self._read(".github/dependabot.yml")
        self.assertIn("package-ecosystem: \"pip\"", dependabot)
        self.assertIn("package-ecosystem: \"github-actions\"", dependabot)

    def test_contributor_templates_exist(self):
        required_templates = [
            ".github/PULL_REQUEST_TEMPLATE.md",
            ".github/ISSUE_TEMPLATE/bug_report.md",
            ".github/ISSUE_TEMPLATE/feature_request.md",
            ".github/ISSUE_TEMPLATE/config.yml",
        ]
        for relative_path in required_templates:
            with self.subTest(path=relative_path):
                self.assertTrue((REPO_ROOT / relative_path).is_file())

    def test_architecture_docs_define_public_contract_and_boundaries(self):
        architecture = self._read("docs/architecture.md")
        for heading in (
            "## Public Contracts",
            "## Compatibility Policy",
            "## Dependency Rules",
            "## Well-Architected Mapping",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, architecture)

        operations = self._read("docs/operations.md")
        for term in (
            "Exit Codes",
            "History Database",
            "Failure Modes",
            "Production Integration Checklist",
        ):
            with self.subTest(term=term):
                self.assertIn(term, operations)

    def test_layering_rules_are_machine_checked(self):
        prohibited_domain_imports = re.compile(
            r"^\s*from\s+\.\.(application|infrastructure|interfaces|providers)\b|"
            r"^\s*from\s+llm_bidding\.(application|infrastructure|interfaces|providers)\b",
            re.MULTILINE,
        )
        domain_dir = REPO_ROOT / "src/llm_bidding/domain"
        offenders = [
            str(path.relative_to(REPO_ROOT))
            for path in domain_dir.rglob("*.py")
            if prohibited_domain_imports.search(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
