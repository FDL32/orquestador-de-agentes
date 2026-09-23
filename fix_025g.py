import pathlib


# Fix test file - add restored tests at end
test_file = pathlib.Path("tests/unit/test_install_agent_system.py")
content = test_file.read_text(encoding="utf-8")

new_test = '''

def test_merge_empty_source_returns_dest(tmp_path):
    """Merge with empty source should preserve existing destination content."""
    dest_content = "## Wing: project\\n### Domain: test\\n- Rule\\n"
    result = merge_memory_rules("", dest_content)
    assert "## Wing: project" in result
    assert "- Rule" in result


def test_merge_empty_source_returns_dest_canonical(tmp_path):
    """Merge with empty source should preserve destination content under project wing."""
    dest_content = "## Domain: legacy\\n- rule\\n"
    result = merge_memory_rules("", dest_content)
    assert "## Wing: project" in result
    assert "legacy" in result
'''
content = content.rstrip() + new_test
test_file.write_text(content, encoding="utf-8")
print("Added restored tests")
