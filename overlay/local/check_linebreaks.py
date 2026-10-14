"""Repair LaTeX line breaks that lost a backslash: a line ending in a lone "\" becomes "\\".

Eval helpers sometimes write .tex through shells or escaping layers that turn "\\" into "\", which makes the
CV's education lines and the cover letter's header/sign-off run together. Run this on every .tex you write,
BEFORE compiling, then check the PDF is still one page (trim coursework/skills if not; never experience bullets).

  python local/check_linebreaks.py output/cv-....tex output/cover-....tex
Prints how many lines it fixed in each file (0 = already fine).
"""
import re, sys

BS = chr(92)
PAT = re.compile("(?<!" + BS * 2 + ")" + BS * 2 + r"(\s*)$")
# a spaced break that lost a backslash mid-line: "\[3pt]" should be "\\[3pt]"
PAT2 = re.compile("(?<!" + BS * 2 + ")" + BS * 2 + r"(\[\d+(\.\d+)?(pt|em|ex|mm)\])")

for f in sys.argv[1:]:
    raw = open(f, encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.split(nl)
    out = [PAT2.sub(lambda m: BS * 2 + m.group(1), PAT.sub(lambda m: BS * 2 + m.group(1), l)) for l in lines]
    n = sum(a != b for a, b in zip(lines, out))
    if n:
        with open(f, "w", encoding="utf-8", newline="") as fh:
            fh.write(nl.join(out))
    print(f"{f}: {n} line break(s) fixed")
