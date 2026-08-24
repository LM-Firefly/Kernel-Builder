from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.kernel_builder import compress_core, fetch_source, release_version


class KernelBuilderTests(unittest.TestCase):
    def test_official_version_uses_channel_and_source_commit(self) -> None:
        commit = "988295c7" + "0" * 32

        self.assertEqual(release_version("ebpf", commit), "ebpf-988295c7")

    def test_custom_version_override_is_preserved(self) -> None:
        commit = "01234567" + "0" * 32

        self.assertEqual(release_version("custom", commit, "v1.2.3"), "v1.2.3")

    def test_compression_is_streamed_and_reversible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "core.so"
            target = root / "core.so.xz"
            content = b"kernel-data-" * 100_000
            source.write_bytes(content)

            digest, size = compress_core(source, target, 6)

            self.assertEqual(digest, hashlib.sha256(target.read_bytes()).hexdigest())
            self.assertEqual(size, target.stat().st_size)
            with lzma.open(target, "rb") as compressed:
                self.assertEqual(compressed.read(), content)

    def test_fetch_source_uses_locked_commit_after_branch_moves(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            upstream = root / "upstream"
            upstream.mkdir()
            self.run_git(upstream, "init", "--quiet")
            self.run_git(upstream, "config", "user.email", "test@example.com")
            self.run_git(upstream, "config", "user.name", "Kernel Builder Test")
            source_file = upstream / "source.txt"
            source_file.write_text("first\n", encoding="utf-8")
            self.run_git(upstream, "add", "source.txt")
            self.run_git(upstream, "commit", "--quiet", "-m", "first")
            locked_commit = self.run_git(upstream, "rev-parse", "HEAD")

            source_file.write_text("second\n", encoding="utf-8")
            self.run_git(upstream, "commit", "--quiet", "-am", "second")

            lock_file = root / "upstream.json"
            lock_file.write_text(
                json.dumps({"commit": locked_commit}) + "\n", encoding="utf-8"
            )
            template = root / "template"
            fetch_source(
                argparse.Namespace(
                    root=str(template),
                    repository=str(upstream),
                    ref="main",
                    token="",
                    expected=str(lock_file),
                )
            )

            fetched = self.run_git(
                template / "lib/mihomo/mihomo", "rev-parse", "HEAD"
            )
            self.assertEqual(fetched, locked_commit)

    @staticmethod
    def run_git(directory: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(directory), *args],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return result.stdout.strip()


if __name__ == "__main__":
    unittest.main()
