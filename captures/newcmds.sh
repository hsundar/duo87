#!/bin/bash
# newcmds.sh LOG SINCE(HH:MM:SS) [WIDTH] -- traffic after a time: all R/IO lines, plus W lines that are CRT commands (no heartbeats, no JPEG chunks)
awk -v s="$2" '$1 >= s' "$1" | awk '$2 != "W" || $4 ~ /^0043525400/' | grep -v '434f4e4e454354' | grep -vE 'W len=65 ' | cut -c1-${3:-160}
