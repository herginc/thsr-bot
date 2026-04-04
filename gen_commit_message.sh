#!/bin/bash

#
# Purpose: Support generating a diff file OR auto-generating conventional commit messages using Gemini AI
#

DIFF_FILE="changes.diff"
MODE="auto" # Default mode is auto-commit

usage() {
    echo "Usage: $0 [options]"
    echo "Options:"
    echo "  -d, --diff-only    Only generate $DIFF_FILE and exit (do not call AI)."
    echo "  -h, --help         Show this help message."
    exit 0
}

# 1. Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -d|--diff-only) MODE="diff"; shift ;;
        -h|--help) usage ;;
        *) echo "Unknown parameter: $1"; usage ;;
    esac
done

# 2. Interactive staging if nothing is staged
if [ -z "$(git diff --cached)" ]; then
    echo "No staged changes found. Starting interactive staging..."
    git add -p
fi

# 2. Capture the staged diff
DIFF_CONTENT=$(git diff --cached)

if [ -z "$DIFF_CONTENT" ]; then
    echo "No changes staged. Aborting."
    exit 1
fi

if [ "$MODE" == "diff" ]; then
    echo "$DIFF_CONTENT" > "$DIFF_FILE"
    echo "Success: Staged changes saved to $DIFF_FILE"
    exit 0
fi

# --- From here: Auto-commit mode ---

# 4. API Configuration
# Ensure you have 'export GEMINI_API_KEY=your_key_here' in your .bashrc or environment
if [ -z "$GEMINI_API_KEY" ]; then
    echo "Error: GEMINI_API_KEY environment variable is not set."
    exit 1
fi

MODEL="${GEMINI_MODEL:-gemini-3-flash-preview}"
API_URL="https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:generateContent?key=${GEMINI_API_KEY}"

echo "Generating conventional commit message using $MODEL..."

# 5. Construct the AI Prompt
PROMPT="Generate a conventional commit message.

Rules:
- Use one of: feat, fix, docs, style, refactor, perf, test, chore
- Subject line <= 144 chars
- Use imperative mood ("add", "update", "fix")
- No emojis
- Bullet list for body
- Explain reason when possible
- Do not repeat file names unless necessary
- No markdown headings

Format:

<type>: <summary>

- change 1
- change 2
- change 3

Git diff:
$DIFF_CONTENT"

# 6. Call Gemini API
# We use jq to safely escape the prompt and parse the JSON response
PAYLOAD=$(jq -n --arg p "$PROMPT" '{contents: [{parts: [{text: $p}]}]}')
RESPONSE=$(curl -s -X POST "$API_URL" -H "Content-Type: application/json" -d "$PAYLOAD")

# 7. Extract the generated message
# 移除 xargs 以保留換行，改用 printf 顯示
COMMIT_MSG=$(echo "$RESPONSE" | jq -r '.candidates[0].content.parts[0].text' | sed 's/^`*//;s/`*$//')

if [ "$COMMIT_MSG" == "null" ] || [ -z "$COMMIT_MSG" ]; then
    echo "Error: Failed to generate commit message."
    echo "API Response: $RESPONSE"
    exit 1
fi

echo -e "\nProposed Commit Message:"
echo "--------------------------------------------------"
printf "%s\n" "$COMMIT_MSG"
echo "--------------------------------------------------"
