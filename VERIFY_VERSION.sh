#!/bin/bash
# Portable version verifier for orquestador_de_agentes/

set -e

echo "==============================================="
echo "  PORTABLE VERSION VERIFIER - orquestador_de_agentes/"
echo "==============================================="
echo ""

if [ ! -f "scripts/detect_version.py" ] && [ ! -f "scripts/detect_agent_system_version.py" ]; then
    echo "ERROR: not running inside orquestador_de_agentes"
    exit 1
fi

echo "OK: project root detected"
echo ""

DETECTOR="scripts/detect_version.py"
if [ ! -f "$DETECTOR" ]; then
    DETECTOR="scripts/detect_agent_system_version.py"
fi

echo "Detecting core version..."
VERSION=$(python "$DETECTOR" . 2>/dev/null | grep "Detected Version:" | awk '{print $3}')

if [ -z "$VERSION" ]; then
    echo "ERROR: version could not be detected"
    exit 1
fi

echo "Detected core version: $VERSION"

PACKAGE_VERSION=$(grep -m1 '^version = ' pyproject.toml 2>/dev/null | awk -F'"' '{print $2}')
if [ -n "$PACKAGE_VERSION" ]; then
    echo "Portable package version: $PACKAGE_VERSION"
else
    echo "WARNING: portable package version could not be read"
fi

echo ""
echo "Checking critical files..."
CRITICAL_FILES=(
    "scripts/detect_version.py"
    "scripts/upgrade.py"
    "scripts/rollback.py"
    "scripts/detect_agent_system_version.py"
    "scripts/upgrade_agent_system.py"
    ".agent/UPGRADE_GUIDE.md"
    "AGENTS.md"
    "CLAUDE.md"
    "CHANGELOG.md"
)

MISSING=0
for file in "${CRITICAL_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "  OK  $file"
    else
        echo "  MISS $file"
        MISSING=$((MISSING + 1))
    fi
done

if [ $MISSING -ne 0 ]; then
    echo ""
    echo "ERROR: $MISSING critical file(s) missing"
    exit 1
fi

echo ""
echo "Checking test inventory..."
TEST_COUNT=$(pytest tests/ -q --co 2>/dev/null | tail -1 | grep -o '[0-9]*' | head -1)
if [ -n "$TEST_COUNT" ]; then
    echo "Detected tests: $TEST_COUNT"
else
    echo "WARNING: could not determine test count"
fi

echo ""
echo "STATUS: VERIFICATION COMPLETE"
echo ""
echo "Ready for:"
echo "  - Copy to a new project"
echo "  - Legacy project upgrades with compatibility aliases"
