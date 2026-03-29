"""
Federation Crawler v8 — kimeisele agent stack
==============================================
Läuft ohne Flags. Liefert optimalen LLM-Kontext.

python3 federation_crawler_v8.py                   # alles
python3 federation_crawler_v8.py --token ghp_xxx   # mit Auth (empfohlen!)
python3 federation_crawler_v8.py --save out.json   # in Datei speichern
python3 federation_crawler_v8.py --node steward    # ein Node

Requires: pip install requests pyyaml
"""

import sys
import argparse
import json
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from pathlib import PurePosixPath

import requests
import yaml

REGISTRY_URL = (
    "https://raw.githubusercontent.com/kimeisele/agent-world/main/"
    "config/world_registry.yaml"
)
BRANCH = "main"

# Binaries — nie relevant
SKIP_EXT = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib",
    ".zip", ".tar", ".gz", ".bz2", ".xz",
    ".db", ".sqlite", ".sqlite3", ".bin", ".exe", ".lock",
})

# Verzeichnisse die niemals relevant sind
SKIP_DIRS = frozenset({
    "__pycache__", ".git", "node_modules",
    ".venv", "venv", "dist", "build",
})

# Size-Limits (v6 Fix)
MAX_FILE_BYTES = 100_000   # 100KB — keine RAG-Bomben
MIN_FILE_BYTES = 10        # nur komplett leere Files raus

# Anchor-Files: machine-readable HOCH, Prosa-Doku NIEDRIG
# Begründung: bei 20-File-Budget darf Doku nicht Source verdrängen
ANCHOR_FILES = {
    # Machine-readable federation identity — immer top
    ".well-known/agent-federation.json":  95,
    ".well-known/agent.json":             90,
    ".introspection.json":                85,
    # Doku — wichtig aber NICHT budget-dominant
    "AGENTS.md":                          60,  # war 100 — zu hoch
    "CLAUDE.md":                          55,  # war 100 — verdrängte Source-Files
    "README.md":                          40,  # war 90
    "PLAN.md":                            45,  # war 85
    "CHANGELOG.md":                       20,  # war 70 — fast nie architektonisch relevant
}

# Pro Role: welche Pfad-Fragmente sind besonders wichtig
ROLE_SIGNALS: Dict[str, Dict[str, int]] = {
    "substrate": {
        "schema": 40, "manifest": 40, "config": 35,
        "kernel": 40, "identity": 35, "capability": 35,
        "agents.yaml": 50, "manifestation": 45,
        "section_main": 35, "plugin_main": 35,
        "cartridge_main": 35,
    },
    "operator": {
        "agent.py": 50, "agent_bus": 45, "__main__": 40,
        "sub_agent": 40, "tools/": 35, "interfaces/": 35,
        "personas/": 30, "config/": 30,
    },
    "world_architect": {
        "world": 50, "registry": 45, "policies": 45,
        "config/": 35, "schema": 35, "heartbeat": 40,
    },
    "city_runtime": {
        "agent_runtime": 50, "city_registry": 45, "agent_nadi": 40,
        "config/": 35, "census": 35, "governance": 30,
    },
    "transport_hub": {
        "nadi_kit": 55, "nadi_inbox": 45, "nadi_outbox": 45,
        "peer.json": 50, "pyproject": 30,
    },
    "projection_layer": {
        "transport": 45, "control_plane": 45, "router": 40,
        "trust": 40, "models": 35, "memory_registry": 35,
        "agent_web": 35, "authority": 35,
    },
    "research_faculty": {
        "phases/": 40, "pipeline/": 40, "faculty/": 40,
        "models.py": 35, "cli.py": 30,
    },
    "scaffolding": {
        "head_agent": 55,
        "render_agent_card": 35, "discover_federation": 35,
        "authority-descriptor-seeds": 40,
    },
    "external_gateway": {
        "gateway": 40, "proxy": 35, "ingress": 35,
    },
}

# Universal — gilt für alle Rollen
UNIVERSAL_SIGNALS: Dict[str, int] = {
    "nadi_kit.py": 50,
    "pyproject.toml": 25,
    "data/federation/peer.json": 40,
    "data/federation/nadi_inbox": 30,
}

# Core-Engine Keywords — diese Files sind das Gehirn, egal in welchem Repo
ENGINE_NAMES = frozenset({
    "engine", "jiva", "runtime", "kernel", "brain", "pipeline",
    "knowledge", "factory", "orchestrator", "dispatcher", "router",
    "agent_bus", "control_plane", "transport", "registry",
})

# Hard-Kill: niemals im Output — Laufzeit-Artefakte, generierte Reports, CI
NOISE_PATHS = [
    "site-packages",
    ".gitkeep",
    "migrations/",
    "/nadi/",                # Routing-Mailboxen: agent-X_to_agent-Y.json — hard kill
    ".github/",              # CI/CD
    "data/models/",          # HuggingFace Weights
    "data/knowledge_graph",  # RAG-Dumps
    "data/federation/reports/",  # generierte historische Berichte — kein Architektur-Wert
    "data/inquiry_ledger",   # Laufzeit-Ledger
    ".gitignore",            # niemals architektonisch relevant
    "LICENSE",               # niemals architektonisch relevant
]

# Test-Verzeichnisse komplett raus
TEST_DIRS = frozenset({"tests", "test", "spec", "specs"})

import os
import subprocess

def _load_token() -> Optional[str]:
    # 1. Env var
    t = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if t:
        return t
    # 2. gh CLI fallback
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            t = result.stdout.strip()
            if t:
                return t
    except Exception:
        pass
    return None

TOKEN: Optional[str] = _load_token()


def gh_headers() -> dict:
    h = {"Accept": "application/vnd.github.v3+json"}
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    return h


def fetch_json(url: str) -> dict:
    r = requests.get(url, headers=gh_headers(), timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_text(url: str) -> str:
    r = requests.get(url, headers=gh_headers(), timeout=15)
    r.raise_for_status()
    return r.text


@dataclass
class FileEntry:
    path: str
    raw_url: str
    file_type: str
    ext: str
    size: int
    score: int


@dataclass
class Node:
    agent_id: str
    repo: str
    role: str
    status: str
    trust: str
    files: List[FileEntry] = field(default_factory=list)
    truncated: bool = False
    error: Optional[str] = None


def load_nodes() -> List[Node]:
    text = fetch_text(REGISTRY_URL)
    data = yaml.safe_load(text)
    return [
        Node(
            agent_id=a["agent_id"],
            repo=a["repo"],
            role=a.get("role", ""),
            status=a.get("status", ""),
            trust=a.get("trust_level", ""),
        )
        for a in data.get("agents", [])
    ]


def get_file_type(path: str) -> str:
    p = path.lower()
    name = PurePosixPath(p).name
    if name in ("agents.md", "claude.md", "readme.md", "plan.md", "changelog.md"):
        return "documentation_anchor"
    if ".well-known" in p or name in ("agent-federation.json", "agent.json", ".introspection.json"):
        return "manifest_anchor"
    if p.endswith((".yaml", ".yml")):
        if any(k in p for k in ("manifest", "federation", "registry", "agents", "schema")):
            return "manifest"
        return "config"
    if p.endswith(".json"):
        if any(k in p for k in ("manifest", "federation", "registry", "schema", "peer", "seeds")):
            return "manifest"
        return "config"
    if p.endswith(".toml"):
        return "config"
    if p.endswith((".md", ".txt", ".rst")):
        return "documentation"
    if p.endswith((".py", ".js", ".ts", ".go", ".rs")):
        return "source"
    return "other"


def score_file(path: str, role: str) -> int:
    name = PurePosixPath(path).name

    # Anchor-Files — immer top, sofort zurück
    if path in ANCHOR_FILES:
        return ANCHOR_FILES[path]
    if name in ANCHOR_FILES:
        return ANCHOR_FILES[name]

    # Echter Noise — raus
    path_lower = path.lower()
    for fragment in NOISE_PATHS:
        if fragment in path_lower:
            return -100

    # Test-Verzeichnisse raus
    top = path.split("/")[0].lower()
    if top in TEST_DIRS:
        return -100

    score = 0

    # Core-Engine Boost — diese Files sind das Gehirn des Agenten
    stem = PurePosixPath(name).stem.lower()  # engine.py → "engine"
    if stem in ENGINE_NAMES:
        score += 60  # massiver Push — verdrängt .gitignore, reports, etc.

    # Role-spezifische Signals
    role_map = ROLE_SIGNALS.get(role, {})
    for fragment, bonus in role_map.items():
        if fragment in path:
            score += bonus

    # Universal Signals
    for fragment, bonus in UNIVERSAL_SIGNALS.items():
        if fragment in path:
            score += bonus

    # Tiefe — flache Files tendenziell wichtiger
    depth = len(path.split("/"))
    if depth == 1:
        score += 20
    elif depth == 2:
        score += 10
    elif depth > 4:
        score -= 8

    # Init-Files weniger informativ
    if name == "__init__.py":
        score -= 15

    return score


def crawl_node(node: Node, budget: int = 20) -> Node:
    user, repo = node.repo.split("/")
    url = (
        f"https://api.github.com/repos/{user}/{repo}/"
        f"git/trees/{BRANCH}?recursive=1"
    )
    try:
        data = fetch_json(url)
    except Exception as e:
        node.error = str(e)
        return node

    node.truncated = data.get("truncated", False)
    candidates: List[FileEntry] = []

    for entry in data.get("tree", []):
        if entry.get("type") != "blob":
            continue

        path = entry["path"]
        size = entry.get("size", 0)

        # Size-Filter (v6)
        if size > MAX_FILE_BYTES:
            continue
        if size < MIN_FILE_BYTES:
            continue

        # Skip Build-Artefakte
        if path.split("/")[0] in SKIP_DIRS:
            continue

        dot = path.rfind(".")
        ext = path[dot:].lower() if dot != -1 else ""
        if ext in SKIP_EXT:
            continue

        score = score_file(path, node.role)
        if score <= 0:  # negativ UND null raus — kein Müll im Output
            continue

        candidates.append(FileEntry(
            path=path,
            raw_url=f"https://raw.githubusercontent.com/{user}/{repo}/{BRANCH}/{path}",
            file_type=get_file_type(path),
            ext=ext,
            size=size,
            score=score,
        ))

    # Nach Score sortieren
    candidates.sort(key=lambda f: f.score, reverse=True)

    # Budget-basierte Auswahl mit Dir-Diversity
    selected: List[FileEntry] = []
    dir_counts: Dict[str, int] = {}

    # README.md spam fix: steward-protocol hatte 15x README.md aus subdirs
    # Nur das root README.md zählt als Anchor — alle anderen als normale Docs
    root_readme_seen = False

    for f in candidates:
        if len(selected) >= budget:
            break

        is_root_anchor = f.file_type in ("manifest_anchor",) or (
            f.file_type == "documentation_anchor"
            and f.path in (
                "AGENTS.md", "CLAUDE.md", "PLAN.md", "CHANGELOG.md",
                ".well-known/agent-federation.json", ".well-known/agent.json",
                ".introspection.json",
            )
        )

        # README.md nur einmal (root), nicht aus jedem Subdir
        if f.path == "README.md" and not root_readme_seen:
            root_readme_seen = True
            selected.append(f)
            continue
        elif PurePosixPath(f.path).name == "README.md" and f.path != "README.md":
            # Subdir-README: behandle wie normales Doc, kein Anchor-Bypass
            pass
        elif is_root_anchor:
            selected.append(f)
            continue

        # Dir-Diversity: 12 statt 5 — dichte Source-Ordner nicht zerhacken
        parts = f.path.split("/")
        dir_key = "/".join(parts[:-1]) if len(parts) > 1 else ""
        if dir_counts.get(dir_key, 0) >= 12:
            continue
        dir_counts[dir_key] = dir_counts.get(dir_key, 0) + 1
        selected.append(f)

    node.files = selected
    return node


def print_table(nodes: List[Node]):
    total = sum(len(n.files) for n in nodes)
    print(f"\n{'AGENT':<26} {'ROLE':<22} {'STATUS':<10} {'TRUST':<12} {'FILES':>6}", file=sys.stderr)
    print("─" * 80, file=sys.stderr)
    for n in nodes:
        warn = " ⚠ truncated" if n.truncated else ("  ✗ " + n.error[:30] if n.error else "")
        print(f"{n.agent_id:<26} {n.role:<22} {n.status:<10} {n.trust:<12} {len(n.files):>6}{warn}", file=sys.stderr)
    print("─" * 80, file=sys.stderr)
    print(f"{'TOTAL':<62} {total:>6}\n", file=sys.stderr)


SYSTEM_PROMPT = {
    "type": "system_prompt",
    "role": "WORLD_ARCHITECT",
    "instructions": (
        "You are the core dispatcher and architect of the Agent Federation. "
        "Your objective: generate traction, connect node interfaces, eliminate bottlenecks."
    ),
    "input_format": (
        "You receive JSON tickets from the Federation Crawler. Each ticket contains "
        "agent_id, role, status, trust_level, and core_raw_urls sorted by relevance score descending."
    ),
    "execution_protocol": [
        "READ BEFORE WRITE: Never generate code or guess implementations. "
        "Before touching any file, fetch its raw_url from the ticket first. No exceptions.",
        "FETCH PRIORITY: (1) manifest_anchor files first, "
        "(2) highest-score source files (engine, runtime, kernel, brain, control_plane), "
        "(3) config only if source files reference them. Max 2-3 files at once.",
        "NO YAPPING: No essays, no summaries, no thought process. "
        "Silent loop only: FETCH -> ANALYZE -> EDIT -> done.",
    ],
    "priority_signals": {
        "fetch_first": ["engine", "runtime", "kernel", "brain", "control_plane", "factory"],
        "fetch_if_referenced": ["config", "yaml", "schema"],
        "never_fetch": ["__init__.py", ".gitignore", "CHANGELOG.md", "receipts.json"],
    },
}


def emit_tickets(nodes: List[Node], dest=sys.stdout):
    output = {"system": SYSTEM_PROMPT, "tickets": []}
    for n in nodes:
        ticket = {
            "ticket_type": "federation_node_context",
            "agent_id": n.agent_id,
            "repo": n.repo,
            "role": n.role,
            "status": n.status,
            "trust_level": n.trust,
            "core_raw_urls": [
                {
                    "url": f.raw_url,
                    "type": f.file_type,
                    "ext": f.ext,
                    "size_bytes": f.size,
                    "score": f.score,
                }
                for f in n.files
            ],
        }
        if n.error:
            ticket["error"] = n.error
        if n.truncated:
            ticket["warning"] = "tree_truncated"
        output["tickets"].append(ticket)

    json.dump(output, dest, indent=2)
    dest.write("\n")


def main():
    ap = argparse.ArgumentParser(description="Federation Crawler v6")
    ap.add_argument("--node",   metavar="ID",    help="Nur einen Node crawlen")
    ap.add_argument("--save",   metavar="FILE",  help="JSON in Datei speichern")
    ap.add_argument("--token",  metavar="TOKEN", help="GitHub Token (empfohlen)")
    ap.add_argument("--budget", metavar="N", type=int, default=20,
                    help="Max Files pro Node (default: 20)")
    args = ap.parse_args()

    global TOKEN
    if args.token:
        TOKEN = args.token
    if TOKEN:
        print("auth: token active", file=sys.stderr)
    else:
        print("auth: no token — rate limit 60 req/h (set GITHUB_TOKEN env var)", file=sys.stderr)

    print("loading registry…", file=sys.stderr)
    nodes = load_nodes()

    if args.node:
        nodes = [n for n in nodes if n.agent_id == args.node]
        if not nodes:
            sys.exit(f"agent_id '{args.node}' not found")

    for n in nodes:
        print(f"  crawling {n.repo} (role={n.role})…", file=sys.stderr)
        crawl_node(n, budget=args.budget)

    print_table(nodes)

    if args.save:
        with open(args.save, "w") as f:
            emit_tickets(nodes, dest=f)
        print(f"saved → {args.save}", file=sys.stderr)
    else:
        emit_tickets(nodes)


if __name__ == "__main__":
    main()
