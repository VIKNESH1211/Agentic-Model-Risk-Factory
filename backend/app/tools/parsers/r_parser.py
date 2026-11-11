"""Static parser for legacy R scripts: header metadata, I/O lineage, methods and code smells."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.guardrails.injection import scan

ID_RE = re.compile(r"\b([A-Z]{2}-\d{3})\b")


ACRONYMS = {"PD", "LGD", "EAD", "GLM", "RF", "SAS"}


def _smart_title(s: str) -> str:
    return " ".join(w if w in ACRONYMS else w.capitalize() for w in s.split())


def parse(path: Path) -> dict:
    text = path.read_text()
    lines = text.splitlines()
    header = [l.lstrip("# ").rstrip() for l in lines[:12] if l.startswith("#") and not l.startswith("#!")]
    header = [h for h in header if h and not set(h) <= {"="}]
    model_id = next((m.group(1) for h in header for m in [ID_RE.search(h)] if m), path.stem.upper())
    title_line = next((h for h in header if model_id in h), header[0] if header else path.stem)
    name = re.sub(r"\s+v[\d.]+$", "", title_line.replace(model_id, "").strip(" -:")).strip()
    owner = next((re.split(r"owner\s*:\s*", h, flags=re.I)[1].split(";")[0].strip()
                  for h in header if re.search(r"owner\s*:", h, re.I)), "")

    reads = re.findall(r'read\.csv\(\s*"([^"]+)"', text)
    writes = re.findall(r'write\.csv\([^;]*?"([^"]+\.csv)"', text)
    writes += re.findall(r'file\.path\([^,]+,\s*"([^"]+\.csv)"\)', text)
    libs = re.findall(r"library\((\w+)\)", text)
    families = re.findall(r"family\s*=\s*(\w+)", text)
    methods = []
    if "glm(" in text:
        methods.append(f"GLM ({', '.join(sorted(set(families))) or 'gaussian'})")
    if "ranger(" in text:
        methods.append("Random forest (ranger)")
    if "woe" in text.lower():
        methods.append("Weight-of-evidence binning")
    if "offset" in text:
        methods.append("Exposure offset")

    smells = []
    for i, l in enumerate(lines, 1):
        s = l.strip()
        if re.search(r'"(?:[A-Za-z]:/|//)[^"]+"', s):
            smells.append({"line": i, "kind": "hardcoded_path", "text": s[:160]})
        if re.search(r"ifelse\([^)]*[<>]=?\s*0\.\d+", s) or re.search(r"\bp\s*>\s*0\.\d+", s):
            smells.append({"line": i, "kind": "hardcoded_cutoff", "text": s[:160]})
        if re.search(r"is\.na\([^)]*\)\]\s*<-\s*0", s):
            smells.append({"line": i, "kind": "na_imputed_zero", "text": s[:160]})
        if re.search(r"breaks\s*=\s*c\(", s):
            smells.append({"line": i, "kind": "magic_numbers", "text": s[:160]})
        if re.search(r"TODO|never done|temporary", s, re.I):
            smells.append({"line": i, "kind": "stale_todo", "text": s[:160]})
    # comment vs code cutoff contradiction
    cmt = re.search(r"#.*cutoff\s*(0\.\d+)", text, re.I)
    code = re.search(r"ifelse\(\s*pd\s*>\s*(0\.\d+)", text)
    if cmt and code and cmt.group(1) != code.group(1):
        smells.append({"line": text[:code.start()].count("\n") + 1, "kind": "comment_code_mismatch",
                       "text": f"comment says cutoff {cmt.group(1)}, code uses {code.group(1)}"})

    return {
        "id": model_id, "name": _smart_title(name) if name.isupper() else name, "path": str(path), "language": "R",
        "owner": owner, "header": header, "reads": reads, "writes": writes, "libraries": libs,
        "methods": methods, "smells": smells, "injection": scan(text),
        "code_hash": hashlib.sha256(text.encode()).hexdigest(), "loc": len(lines), "source": text,
    }
