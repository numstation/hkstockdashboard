#!/bin/bash

# Version Update Helper Script
# Usage: ./update_version.sh [major|minor|patch] [description]

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Read current version
CURRENT_VERSION=$(cat version.txt 2>/dev/null || echo "1.0.0")
IFS='.' read -ra VERSION_PARTS <<< "$CURRENT_VERSION"
MAJOR=${VERSION_PARTS[0]}
MINOR=${VERSION_PARTS[1]}
PATCH=${VERSION_PARTS[2]}

# Determine version bump type
BUMP_TYPE=${1:-patch}

case $BUMP_TYPE in
    major)
        MAJOR=$((MAJOR + 1))
        MINOR=0
        PATCH=0
        ;;
    minor)
        MINOR=$((MINOR + 1))
        PATCH=0
        ;;
    patch)
        PATCH=$((PATCH + 1))
        ;;
    *)
        echo "❌ 錯誤：無效的版本類型。請使用: major, minor, 或 patch"
        exit 1
        ;;
esac

NEW_VERSION="$MAJOR.$MINOR.$PATCH"

# Update version.txt
echo "$NEW_VERSION" > version.txt

# Update app.py
sed -i '' "s/VERSION = \".*\"/VERSION = \"$NEW_VERSION\"/" app.py 2>/dev/null || \
sed -i "s/VERSION = \".*\"/VERSION = \"$NEW_VERSION\"/" app.py

echo "✅ 版本已更新: $CURRENT_VERSION → $NEW_VERSION"
echo ""
echo "請記得在 VERSION_HISTORY.md 中記錄更新內容！"
