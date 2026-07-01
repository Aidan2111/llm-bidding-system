"""Keep AGENTS.md and the capability docs honest.

Parses the YAML-ish front matter (flat string keys, stdlib only — no PyYAML
dependency) from each docs/capabilities/*.md file and asserts:
  - every capability doc has the required front-matter keys,
  - each referenced module path exists,
  - AGENTS.md links to every capability doc (the index cannot silently drift).
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAPABILITIES_DIR = ROOT / "docs" / "capabilities"
AGENTS_FILE = ROOT / "AGENTS.md"

REQUIRED_KEYS = ("name", "summary", "module", "read_when")


def parse_front_matter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise AssertionError("file does not start with a '---' front-matter fence")
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    raise AssertionError("front matter was not closed with a '---' fence")


class CapabilityDocTests(unittest.TestCase):
    def setUp(self):
        self.docs = sorted(CAPABILITIES_DIR.glob("*.md"))

    def test_capability_docs_exist(self):
        self.assertTrue(self.docs, "no capability docs found")

    def test_front_matter_is_complete(self):
        for doc in self.docs:
            fm = parse_front_matter(doc.read_text(encoding="utf-8"))
            for key in REQUIRED_KEYS:
                self.assertIn(key, fm, f"{doc.name} missing front-matter key {key!r}")
                self.assertTrue(fm[key], f"{doc.name} has empty {key!r}")

    def test_module_paths_exist(self):
        for doc in self.docs:
            fm = parse_front_matter(doc.read_text(encoding="utf-8"))
            module_path = ROOT / fm["module"]
            self.assertTrue(
                module_path.exists(), f"{doc.name} points at missing module {fm['module']}"
            )

    def test_agents_md_references_every_capability(self):
        agents_text = AGENTS_FILE.read_text(encoding="utf-8")
        for doc in self.docs:
            rel = f"docs/capabilities/{doc.name}"
            self.assertIn(
                rel, agents_text, f"AGENTS.md does not reference {rel}"
            )

    def test_agents_md_only_links_real_capabilities(self):
        import re

        agents_text = AGENTS_FILE.read_text(encoding="utf-8")
        linked = set(re.findall(r"docs/capabilities/([\w-]+\.md)", agents_text))
        on_disk = {doc.name for doc in self.docs}
        self.assertEqual(
            linked, on_disk, "AGENTS.md links and capability docs are out of sync"
        )


class FacadePolicyTests(unittest.TestCase):
    """Top-level façade modules re-export the layers; they must hold no logic.

    Enforces the "Public API and the shim layer" policy in AGENTS.md: a `def`
    or `class` appearing in a façade means the code belongs in domain/,
    application/, infrastructure/, or interfaces/ instead.
    """

    FACADES = (
        "auction.py",
        "calibration.py",
        "config.py",
        "history.py",
        "models.py",
        "policy.py",
        "scoring.py",
        "utility.py",
    )

    def test_facades_contain_no_definitions(self):
        import re

        package_dir = ROOT / "src" / "llm_bidding"
        pattern = re.compile(r"^(def |class )", re.MULTILINE)
        offenders = [
            name
            for name in self.FACADES
            if (package_dir / name).exists()
            and pattern.search((package_dir / name).read_text(encoding="utf-8"))
        ]
        self.assertEqual(
            offenders,
            [],
            "façade modules must only re-export from the layered packages",
        )


if __name__ == "__main__":
    unittest.main()
