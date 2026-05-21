"""One-shot fixer for mojibake in .claude/rules/*.md (WP-2026-076 A13)."""

from pathlib import Path


FIXES = [
    ("Ã¡", "á"),
    ("Ã©", "é"),
    ("Ã­", "í"),
    ("Ã³", "ó"),
    ("Ãº", "ú"),
    ("Ã±", "ñ"),
    ("Ã¼", "ü"),
    ("Â¿", "¿"),
    ("Â¡", "¡"),
    ("Â°", "°"),
    ("â\x80\x93", "–"),
    ("â\x80\x94", "—"),
    ("â\x80\x9c", "“"),
    ("â\x80\x9d", "”"),
    ("â\x80\x98", "‘"),
    ("â\x80\x99", "’"),
    ("â\x86\x92", "→"),
    ("â\x86", "←"),
    ("â\x9c…", "✅"),
    ("â\x9d\x8c", "❌"),
    ("â\x94\x9câ\x94\x80â\x94\x80", "├──"),
    ("â\x94\x94â\x94\x80â\x94\x80", "└──"),
    ("â\x94\x80", "─"),
    ("â\x94\x82", "│"),
]


def main() -> None:
    rules_dir = Path(".claude/rules")
    for path in sorted(rules_dir.glob("*.md")):
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        text = raw.decode("utf-8")
        before = text
        for bad, good in FIXES:
            text = text.replace(bad, good)
        if text != before:
            path.write_text(text, encoding="utf-8")
            print(f"fixed: {path}")
        else:
            print(f"unchanged: {path}")


if __name__ == "__main__":
    main()
