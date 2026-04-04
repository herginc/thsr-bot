#!/bin/bash

# ---------------------------------------------------------
# Note for Linux users: 
# If you encounter line ending issues (CRLF vs LF), 
# run 'dos2unix pack.sh' or re-paste the content 
# directly into nano/vim on your Linux machine.
# ---------------------------------------------------------

# 1. Get current date and time (Format: YYYYMMDD_HHMMSS)
# For date only, use: $(date +%Y%m%d)
# DATE_STR=$(date +%Y%m%d_%H%M%S)
DATE_STR=$(date +%Y%m%d_%H%M)

# 2. Define target filename
TARGET="thsr_bot_${DATE_STR}.tar.gz"

# 3. Check if the file already exists
if [ -f "$TARGET" ]; then
    echo "------------------------------------------"
    read -p "Warning: '$TARGET' already exists. Overwrite? (y/n): " confirm
    echo
    
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo ">>> Operation canceled."
        exit 1
    fi
fi

echo ">>> Archiving *.py files and templates/ directory to $TARGET ..."

# 4. Execute tar command
# -c: create, -z: gzip, -v: verbose, -f: file
tar -czvf "$TARGET" *.py templates/

# 5. Check execution result
if [ $? -eq 0 ]; then
    echo "------------------------------------------"
    echo ">>> Success! Backup created: $TARGET"
    echo ">>> File size: $(du -h "$TARGET" | cut -f1)"
else
    echo ">>> Error: Something went wrong during the archiving process."
fi