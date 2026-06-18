import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from llm_bidding.actor import (
    ContextEntry,
    build_patch_prompt,
    read_context_files,
    request_patch_proposal,
)
from llm_bidding.models import AgentProfile


class ActorPromptTests(unittest.TestCase):
    def test_patch_prompt_contains_supervisor_contract_and_context(self):
        prompt = build_patch_prompt(
            task_text="Make the README honest about supervised execution.",
            context_entries=[
                ContextEntry(path="README.md", text="# llm-bidding-system\n")
            ],
            actor_name="qwen-coder",
            supervisor_name="Codex",
            auction_summary="qwen-coder won with utility 0.72.",
        )

        self.assertIn("qwen-coder", prompt)
        self.assertIn("Codex", prompt)
        self.assertIn("unified diff", prompt)
        self.assertIn("qwen-coder won with utility 0.72.", prompt)
        self.assertIn("README.md", prompt)
        self.assertIn("# llm-bidding-system", prompt)

    def test_context_reader_limits_file_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "example.txt"
            path.write_text("abcdef", encoding="utf-8")

            entries = read_context_files([str(path)], max_bytes_per_file=3)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].text, "abc\n[truncated after 3 bytes]\n")

    def test_patch_proposal_supports_ollama_actor(self):
        agent = AgentProfile(
            name="spark",
            provider="ollama",
            model_id="spark",
            input_cost_per_mtok=0.0,
            output_cost_per_mtok=0.0,
        )

        with patch("llm_bidding.actor.request_ollama_chat", return_value="diff") as chat:
            result = request_patch_proposal(
                agent=agent,
                prompt="Propose a README patch.",
                env={"OLLAMA_BASE_URL": "http://localhost:11434"},
            )

        self.assertEqual(result, "diff")
        chat.assert_called_once()


if __name__ == "__main__":
    unittest.main()
