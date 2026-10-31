#!/usr/bin/env python3
"""Create the GT6 port scaffold from the GT5P sibling port."""
import shutil
from pathlib import Path

SRC = Path("third_party/GT5P")
DST = Path("gt6")

if DST.exists():
    shutil.rmtree(DST)

for sub in ["src", "scripts", "config"]:
    shutil.copytree(SRC / sub, DST / sub)

shutil.copy2(SRC / "CMakeLists.txt", DST / "CMakeLists.txt")
shutil.copy2(SRC / ".gitignore", DST / ".gitignore")

for rel in ["src/gen/spu_workloads.c", "src/gen/ppu_hle_nids.cpp"]:
    p = DST / rel
    if p.exists():
        p.unlink()

for p in list(DST.rglob("*")):
    if p.is_file() and "gt5p" in p.name.lower():
        p.rename(p.with_name(p.name.lower().replace("gt5p", "gt6")))

exts = {".cpp", ".h", ".c", ".py", ".md", ".txt", ".toml", ".json",
        ".cmd", ".sh", ".yml", ".yaml"}
for p in DST.rglob("*"):
    if not p.is_file():
        continue
    if p.suffix.lower() not in exts and p.name != ".gitignore":
        continue
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = p.read_text(encoding="latin-1")
    text = (text.replace("gt5p", "gt6")
                .replace("GT5P", "GT6")
                .replace("Gran Turismo 5 Prologue", "Gran Turismo 6")
                .replace("5 Prologue", "6")
                .replace("NPUA80075", "BCUS98296")
                .replace("input/pkg", "PS3-Version/Gran Turismo 6 (USA) (En,Ja,Fr)/PS3_GAME"))
    p.write_text(text, encoding="utf-8")

(DST / "src/gen").mkdir(parents=True, exist_ok=True)
(DST / "src/gen/spu_workloads.c").write_text(
    "/* Generated later by lift_spu_jobs.py; empty until then. */\n"
    "void gt6_spu_register_all(void) {}\n", encoding="utf-8")
print("scaffold written to", DST)
