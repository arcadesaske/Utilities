#!/usr/bin/env python3
import random as rd
import time
import os

rd.seed(time.time())

# 10k extractions
count = {i: 0 for i in range(1, 6)}
for _ in range(10_000):
    count[rd.randint(1, 5)] += 1

# Most extracted number
winner = max(count, key=lambda k: count[k])

# Ranking sorted by occurrences (descending)
ranking = sorted(count.items(), key=lambda x: x[1], reverse=True)

# Dialog text
lines = [f"Pick {winner} and GG!", ""]
for number, occurrences in ranking:
    lines.append(f"# {number}: {occurrences}")

text = "\\n".join(lines)
os.system(f'osascript -e \'display dialog "{text}" with title "Pick Number:" buttons {{"OK"}}\'' )