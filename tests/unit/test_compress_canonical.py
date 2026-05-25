#!/usr/bin/env python3
"""
Tests for compress_canonical.py - Caveman-style canonical doc compression helper.

Covers:
- Preservation of technical content (code fences, inline code, URLs, paths, headers)
- Backup creation and restoration
- Dry-run mode
- Idempotency
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.compress_canonical import (
    _compress_redundant_phrases,
    _compress_whitespace,
    compress_markdown,
    create_backup,
    process_file,
    restore_from_backup,
)


class TestPreservation:
    """Test that technical content is preserved exactly."""

    def test_code_fence_preserved(self):
        """Code fences must not be modified."""
        content = """# Title

Some text before.

```python
def hello():
    print("Hello, World!")
```

Some text after.
"""
        result = compress_markdown(content)
        assert "```python" in result
        assert "def hello():" in result
        assert 'print("Hello, World!")' in result
        assert "```" in result

    def test_inline_code_preserved(self):
        """Inline code must not be modified."""
        content = "Use the `--dry-run` flag for preview."
        result = compress_markdown(content)
        assert "`--dry-run`" in result

    def test_url_preserved(self):
        """URLs must not be modified."""
        content = "See https://example.com/path?query=value for details."
        result = compress_markdown(content)
        assert "https://example.com/path?query=value" in result

    def test_windows_path_preserved(self):
        """Windows paths must not be modified."""
        content = r"The file is at C:\Users\name\file.txt"
        result = compress_markdown(content)
        assert r"C:\Users\name\file.txt" in result

    def test_unix_path_preserved(self):
        """Unix paths must not be modified."""
        content = "The config is at ./config/settings.json"
        result = compress_markdown(content)
        assert "./config/settings.json" in result

    def test_header_preserved(self):
        """Markdown headers must not be modified."""
        content = """# Main Header

## Sub Header

### Deep Header
"""
        result = compress_markdown(content)
        assert "# Main Header" in result
        assert "## Sub Header" in result
        assert "### Deep Header" in result

    def test_table_row_preserved(self):
        """Table rows must not be modified."""
        content = """| Column 1 | Column 2 |
|----------|----------|
| Cell 1   | Cell 2   |
"""
        result = compress_markdown(content)
        assert "| Column 1 | Column 2 |" in result
        assert "| Cell 1   | Cell 2   |" in result

    def test_frontmatter_preserved(self):
        """YAML frontmatter must not be modified."""
        content = """---
title: Test Document
author: Test Author
---

Content here.
"""
        result = compress_markdown(content)
        assert "---" in result
        assert "title: Test Document" in result
        assert "author: Test Author" in result

    def test_mixed_technical_content(self):
        """Mixed technical content must all be preserved."""
        content = """---
title: API Guide
---

# API Reference

See the endpoint `https://api.example.com/v1/users` for user data.

```bash
curl -X GET "https://api.example.com/v1/users" \\
  -H "Authorization: Bearer TOKEN"
```

The config file is at `C:\\Config\\app.json` or `./config/app.json`.

| Method | Endpoint |
|--------|----------|
| GET    | /users   |
"""
        result = compress_markdown(content)
        # Check frontmatter
        assert "title: API Guide" in result
        # Check header
        assert "# API Reference" in result
        # Check URL
        assert "https://api.example.com/v1/users" in result
        # Check inline code
        assert "`https://api.example.com/v1/users`" in result
        # Check code fence
        assert "```bash" in result
        assert "curl -X GET" in result
        # Check paths
        assert "C:\\Config\\app.json" in result or "C:\\\\Config\\\\app.json" in result
        # Check table
        assert "| Method | Endpoint |" in result


class TestCompression:
    """Test that compression actually reduces content."""

    def test_whitespace_compression(self):
        """Excessive whitespace should be compressed."""
        content = "Line 1\n\n\n\n\nLine 2"
        result = _compress_whitespace(content)
        assert result.count("\n") < content.count("\n")
        # Should have exactly 3 newlines (2 blank lines = \n\n\n between content lines)
        assert result == "Line 1\n\n\nLine 2"

    def test_trailing_whitespace_removed(self):
        """Trailing whitespace should be removed."""
        content = "Line with spaces   \nAnother line\t\t\n"
        result = _compress_whitespace(content)
        assert "   \n" not in result
        assert "\t\t\n" not in result

    def test_redundant_phrase_compression(self):
        """Redundant phrases should be compressed."""
        content = "This is very important and basically useful."
        result = _compress_redundant_phrases(content)
        assert "very important" not in result
        assert "basically" not in result

    def test_in_order_to_compression(self):
        """'in order to' should become 'to'."""
        content = "We do this in order to achieve the goal."
        result = _compress_redundant_phrases(content)
        assert "in order to" not in result
        assert "to achieve" in result

    def test_space_before_punctuation_removed(self):
        """Spaces before punctuation should be removed."""
        content = "This is wrong , and so is this !"
        result = _compress_redundant_phrases(content)
        assert " ," not in result
        assert " !" not in result


class TestIdempotency:
    """Test that compression is idempotent."""

    def test_idempotent_compression(self):
        """compress(compress(x)) == compress(x)."""
        content = """# Title

This is   very   important and basically useful.



Some more text with trailing spaces

```python
code here
```
"""
        first_pass = compress_markdown(content)
        second_pass = compress_markdown(first_pass)
        assert first_pass == second_pass

    def test_idempotent_on_technical_content(self):
        """Idempotency holds even with technical content."""
        content = """## API

Use `https://api.example.com` with the `--token` flag.

```bash
curl https://api.example.com
```
"""
        first_pass = compress_markdown(content)
        second_pass = compress_markdown(first_pass)
        assert first_pass == second_pass


class TestBackup:
    """Test backup creation and restoration."""

    def test_create_backup(self, tmp_path: Path):
        """Backup file should be created with .original.md extension."""
        original = tmp_path / "test.md"
        original.write_text("Original content", encoding="utf-8")

        backup_path = create_backup(original)

        assert backup_path.exists()
        assert backup_path.name == "test.original.md"
        assert backup_path.read_text(encoding="utf-8") == "Original content"

    def test_restore_from_backup(self, tmp_path: Path):
        """Restore should recover original content from backup."""
        backup = tmp_path / "test.original.md"
        backup.write_text("Backup content", encoding="utf-8")

        restored_path = restore_from_backup(backup)

        assert restored_path.exists()
        assert restored_path.name == "test.md"
        assert restored_path.read_text(encoding="utf-8") == "Backup content"

    def test_restore_invalid_backup_path(self, tmp_path: Path):
        """Restore should reject non-backup paths."""
        not_backup = tmp_path / "test.md"
        not_backup.write_text("Not a backup", encoding="utf-8")

        with pytest.raises(ValueError, match="Not a valid backup path"):
            restore_from_backup(not_backup)

    def test_backup_preserves_encoding(self, tmp_path: Path):
        """Backup should preserve UTF-8 encoding."""
        original = tmp_path / "unicode.md"
        original.write_text("Content with unicode: 你好世界 🌍", encoding="utf-8")

        backup_path = create_backup(original)

        assert (
            backup_path.read_text(encoding="utf-8")
            == "Content with unicode: 你好世界 🌍"
        )


class TestDryRun:
    """Test dry-run mode."""

    def test_dry_run_no_modification(self, tmp_path: Path):
        """Dry-run should not modify the file."""
        file_path = tmp_path / "test.md"
        original_content = "Original content   \n\n\n\nMore content"
        file_path.write_text(original_content, encoding="utf-8")

        success, message, _ = process_file(file_path, dry_run=True)

        assert success
        assert "Would compress" in message
        assert file_path.read_text(encoding="utf-8") == original_content

    def test_dry_run_reports_changes(self, tmp_path: Path):
        """Dry-run should report expected changes."""
        file_path = tmp_path / "test.md"
        file_path.write_text("This is very important   \n\n\n\n", encoding="utf-8")

        success, message, change_count = process_file(file_path, dry_run=True)

        assert success
        assert change_count > 0
        assert "chars saved" in message

    def test_dry_run_no_changes(self, tmp_path: Path):
        """Dry-run should report when no changes needed."""
        file_path = tmp_path / "test.md"
        content = "# Title\n\nSimple content.\n"
        file_path.write_text(content, encoding="utf-8")

        success, message, change_count = process_file(file_path, dry_run=True)

        assert success
        assert change_count == 0
        assert "No changes needed" in message


class TestProcessFile:
    """Test file processing end-to-end."""

    def test_process_nonexistent_file(self, tmp_path: Path):
        """Processing nonexistent file should fail."""
        file_path = tmp_path / "nonexistent.md"

        success, message, change_count = process_file(file_path)

        assert not success
        assert "not found" in message.lower()
        assert change_count == 0

    def test_process_non_markdown_file(self, tmp_path: Path):
        """Processing non-markdown file should fail."""
        file_path = tmp_path / "test.txt"
        file_path.write_text("Not markdown", encoding="utf-8")

        success, message, change_count = process_file(file_path)

        assert not success
        assert "not a markdown file" in message.lower()
        assert change_count == 0

    def test_process_with_backup(self, tmp_path: Path):
        """Processing with backup should create backup file."""
        file_path = tmp_path / "test.md"
        original_content = "Original content   \n\n\n\nMore content"
        file_path.write_text(original_content, encoding="utf-8")

        success, _, _ = process_file(file_path, backup=True)

        assert success
        backup_path = tmp_path / "test.original.md"
        assert backup_path.exists()
        assert backup_path.read_text(encoding="utf-8") == original_content

    def test_process_actual_compression(self, tmp_path: Path):
        """Processing should actually compress content."""
        file_path = tmp_path / "test.md"
        original_content = "This is very important   \n\n\n\nMore content here"
        file_path.write_text(original_content, encoding="utf-8")

        success, _, change_count = process_file(file_path, backup=True)

        assert success
        compressed_content = file_path.read_text(encoding="utf-8")
        assert len(compressed_content) < len(original_content)
        assert change_count > 0


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_file(self, tmp_path: Path):
        """Empty file should be handled gracefully."""
        file_path = tmp_path / "empty.md"
        file_path.write_text("", encoding="utf-8")

        success, _, change_count = process_file(file_path, dry_run=True)

        assert success
        assert change_count == 0

    def test_only_whitespace(self, tmp_path: Path):
        """File with only whitespace should be handled."""
        file_path = tmp_path / "whitespace.md"
        file_path.write_text("   \n\n\n   \n", encoding="utf-8")

        success, _, _ = process_file(file_path, dry_run=True)

        assert success

    def test_nested_code_fences(self):
        """Nested code fences should be preserved."""
        content = """```markdown
This is a code block with ``` inline ticks ```
```
"""
        result = compress_markdown(content)
        assert "```markdown" in result
        assert "``` inline ticks ```" in result

    def test_mixed_line_endings(self):
        """Mixed line endings should be normalized."""
        content = "Line 1\r\nLine 2\rLine 3\nLine 4"
        result = compress_markdown(content)
        assert "\r" not in result
        assert result.count("\n") == 3

    def test_long_url_with_special_chars(self):
        """Long URLs with special characters should be preserved."""
        url = "https://example.com/path?a=1&b=2#section"
        content = f"See {url} for details."
        result = compress_markdown(content)
        assert url in result
