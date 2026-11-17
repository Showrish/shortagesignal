"""Checks that a redesigned dashboard changed only how things look, not what they say or do.

  git show main:app/streamlit_app.py > /tmp/old_app.py
  python check_ui_safety.py /tmp/old_app.py app/streamlit_app.py

It compares the two files' code, not their screenshots: every SQL query must be unchanged, the
data files, passcode gate and daily cap must be intact, the caveats must still be there, and
nothing deprecated or new may sneak in. Anything it can't judge, it lists for a person to look at.
"""
import ast
import re
import sys

MUST_KEEP = [
    "watch list, not a prediction",
    "That's a fact, not a prediction.",
    "A same-drug-name match is a lead to check, not a confirmed overlap.",
    "From drugs recalled since 2020 that have had a full year since their report",
    "FDA drops resolved shortages after a while",
    "How Claude read the question",
    "Data as of",
    "questions left today",
    "A failed run that",
]


def strings(tree):
    """Every string in the file, with f-strings reduced to their fixed text."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            out.append("".join(v.value for v in node.values
                               if isinstance(v, ast.Constant) and isinstance(v.value, str)))
    return out


def sql_of(texts):
    return {" ".join(t.split()) for t in texts if re.search(r"\bSELECT\b", t) and re.search(r"\bFROM\b", t)}


def assigned(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            try:
                return ast.literal_eval(node.value)
            except ValueError:
                return ast.unparse(node.value)
    return None


def imports(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    return names


def main(old_path, new_path):
    old_src, new_src = open(old_path, encoding="utf-8").read(), open(new_path, encoding="utf-8").read()
    try:
        old, new = ast.parse(old_src), ast.parse(new_src)
    except SyntaxError as e:
        sys.exit(f"FAIL  the new file doesn't parse: {e}")
    new_text = " ".join(" ".join(t.split()) for t in strings(new))
    results = []

    old_sql, new_sql = sql_of(strings(old)), sql_of(strings(new))
    results.append(("Every SQL query unchanged", old_sql == new_sql,
                    [f"removed or changed: {q[:100]}" for q in old_sql - new_sql]
                    + [f"added: {q[:100]}" for q in new_sql - old_sql]))
    for name in ("VIEWS", "DAILY_QUESTIONS"):
        results.append((f"{name} unchanged", assigned(old, name) == assigned(new, name),
                        [f"was {assigned(old, name)!r}, now {assigned(new, name)!r}"]))
    results.append(("Passcode check still uses hmac.compare_digest", "compare_digest" in new_src, []))
    results.append(("Secrets still read by name", all(s in new_src for s in ('"ASK_PASSCODE"', '"ANTHROPIC_API_KEY"')), []))
    results.append(("Data still cached", new_src.count("@st.cache_data") >= old_src.count("@st.cache_data")
                    and new_src.count("@st.cache_resource") >= old_src.count("@st.cache_resource"), []))
    results.append(("60 days still the default window", "[30, 60, 90, 365]" in new_src and "index=1" in new_src, []))
    missing = [p for p in MUST_KEEP if " ".join(p.split()) not in new_text]
    results.append(("Every caveat and safeguard sentence kept", not missing, [f"missing: {p}" for p in missing]))
    added = sorted(imports(new) - imports(old))
    results.append(("No new imports", not added, [f"new: {a}" for a in added]))
    banned = [w for w in ("use_container_width", "localStorage", "sessionStorage", "unsafe_allow_html=True")
              if w in new_src and w not in old_src]
    results.append(("Nothing deprecated or risky added", not banned, [f"added: {w}" for w in banned]))

    failed = 0
    for name, ok, details in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            failed += 1
            for d in details[:8]:
                print(f"        {d}")
    print(f"\n{len(results) - failed} of {len(results)} checks passed.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("python check_ui_safety.py OLD_APP NEW_APP")
    main(sys.argv[1], sys.argv[2])
