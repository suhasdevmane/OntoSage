"""Write the facts of the frozen OntoSage build (tag v3.0-study) that the expanded article prints, as \\fv macros.

Plan 21 (phd plan/[anonymised]/21_Draft1Nov_Writing_Plan_28Oct.md), tasks W1 and W4. Every value is READ from a file, never
typed here:
  * the tagged code, through `git show v3.0-study:<path>` (the tag must point at the commit the freeze record names);
  * the freeze record, phd plan/[anonymised]/12_OntoSage_Readiness/Freeze_2026-10-14/README.md (settings in section 3, the
    graph export in section 6) and the runbook's decision log (snapshot 2);
  * the building's counts from the graph the study used: the frozen snapshot of 14 October 2026, re-counted on
    29 October 2026 (paper/generated/frozen_2026-10-14/building-characteristics.csv, written by
    draft1Nov_work/recount_frozen_graph.py with scripts/live_building_facts.py). Keys start with "bldg_". They replace
    the live counts of 24 September 2026 (paper/generated/building-characteristics.csv, kept as a record).

Counts are made two ways where two ways exist, and the script stops if they disagree: the intents by YAML parse and
by a line count; the routing rules by parsing the tagged module (ast) and by importing it; the building table's floor
nodes and stores (frozen graph) against the same counts read from the tagged files, which its caption explains (review item
51, 29 Oct: the storeys plus the rooftop and parking level that Brick classes as floors; the store of interval records
that the registry lists and no point names).

OUTPUTS (paper/generated/freeze/)
  freeze_facts.tex          \\fv{key} values, after the \\providecommand{\\fv} header kept verbatim from the stub
  freeze_facts.csv          key,value,source
  tab_building.tex          tab:building-characteristics (Building A, frozen graph), and its .csv twin
  tab_checks_frozen.tex     tab:checks-frozen, from checks.csv, and its .csv twin
  tab_subsystems.tex        tab:subsystems, from lanes.csv, and its .csv twin

INPUTS written by hand (paper/generated/freeze/) and checked here
  checks.csv   one row per check in code. Each row names up to four lines of the tagged code (ev1..ev4: path:line)
               with a text each line must contain; a row whose line has moved or changed stops the script.
  lanes.csv    one row per lane outside the data pipeline, with the intents routed to it. Every intent named must
               exist at the tag, and every standalone intent (and every meta intent with its own node) must appear
               exactly once, so the table cannot silently miss a lane.

Exits 1 and writes nothing if any check fails.

Usage (from anywhere):  python -I paper/scripts/freeze_facts.py
"""
import ast
import csv
import importlib.util
import io
import os
import re
import subprocess
import sys
import tarfile
import tempfile

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
PAPER = os.path.dirname(HERE)
REPO = os.path.dirname(PAPER)
OUT = os.path.join(PAPER, "generated", "freeze")
TAG = "v3.0-study"
READINESS = os.path.join(PAPER, "phd plan", "[anonymised]", "12_OntoSage_Readiness")
FREEZE_README = os.path.join(READINESS, "Freeze_2026-10-14", "README.md")
FREEZE_COMMIT = os.path.join(READINESS, "Freeze_2026-10-14", "freeze_commit.txt")
RUNBOOK = os.path.join(READINESS, "Freeze_and_Session_Runbook.md")
BUILDING_CSV = os.path.join(PAPER, "generated", "frozen_2026-10-14", "building-characteristics.csv")

# Kept byte for byte from the stub that main.tex was wired against (plan 21, W0): the macro must not change.
FV_DEFINITION = (
    "\\providecommand{\\fv}[1]{\\ifcsname fv@#1\\endcsname\\csname fv@#1\\endcsname\\else\n"
    "  \\PackageError{systemfacts}{Unknown system value '\\detokenize{#1}'}{Check the key in freeze_facts.csv}%\n"
    "  \\textbf{??\\detokenize{#1}??}\\fi}\n"
)

PROBLEMS = []


def problem(msg):
    PROBLEMS.append(msg)


# ── git ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def git(*args, binary=False):
    res = subprocess.run(["git", "-C", REPO, *args], capture_output=True)
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.decode('utf-8', 'replace').strip()}")
    return res.stdout if binary else res.stdout.decode("utf-8")


def show(path):
    return git("show", f"{TAG}:{path}")


def ls(path):
    return [p for p in git("ls-tree", "-r", "--name-only", TAG, path).split("\n") if p]


# ── facts ────────────────────────────────────────────────────────────────────────────────────────────────────────

FACTS = []  # (key, raw value, source)


def fact(key, value, source):
    if any(k == key for k, _, _ in FACTS):
        problem(f"fact {key} set twice")
    FACTS.append((key, value, source))


def fact_value(key):
    for k, v, _ in FACTS:
        if k == key:
            return v
    raise KeyError(key)


def latex_value(value):
    """How a value is printed: integers with a thin comma from 1,000 up (as the article types 7{,}151)."""
    if isinstance(value, bool):
        raise TypeError("booleans are written as words")
    if isinstance(value, int):
        return f"{value:,}".replace(",", "{,}") if value >= 1000 else str(value)
    text = str(value)
    for ch, rep in (("\\", r"\textbackslash{}"), ("_", r"\_"), ("%", r"\%"), ("&", r"\&"), ("#", r"\#"),
                    ("$", r"\$")):
        text = text.replace(ch, rep)
    return text


# ── 1. the tag is the frozen commit ──────────────────────────────────────────────────────────────────────────────


REWRITE_COMMIT = os.path.join(READINESS, "Freeze_2026-10-14", "freeze_commit_after_rewrite_2026-10-29.txt")
# The only paths the 29 Oct 2026 history rewrite removed (freeze record section 10); none is code the build ran.
REWRITE_REMOVED = {f"Datasets/Survey analysis and results/inputs/{n}" for n in
                   ("topic_rankings.csv", "topic_rankings.json", "question_rankings.csv", "question_rankings.json")}


def check_tag():
    commit = git("rev-parse", f"{TAG}^{{commit}}").strip()
    with open(FREEZE_COMMIT, encoding="utf-8") as fh:
        frozen = fh.read().strip()
    source = "equals freeze_commit.txt"
    if commit != frozen:
        rewritten = open(REWRITE_COMMIT, encoding="utf-8").read().strip() if os.path.exists(REWRITE_COMMIT) else ""
        if commit != rewritten:
            problem(f"{TAG} points at {commit}, the freeze record names {frozen}")
        source = (f"the frozen commit {frozen[:7]} after the 29 Oct 2026 history rewrite "
                  "(freeze_commit_after_rewrite_2026-10-29.txt)")
        # While the original commit is still in the local object store, prove the two differ only in the removed files.
        if subprocess.run(["git", "-C", REPO, "cat-file", "-e", frozen + "^{commit}"], capture_output=True).returncode == 0:
            changed = {p for p in git("diff-tree", "-r", "--name-only", "--no-commit-id", frozen, commit).split("\n") if p}
            if not changed <= REWRITE_REMOVED:
                problem(f"{TAG} differs from the frozen commit outside the removed files: {sorted(changed - REWRITE_REMOVED)}")
            source += f"; checked: differs from {frozen[:7]} only in {len(changed)} removed data files"
    fact("tag_name", TAG, "git tag")
    fact("tag_commit_short", commit[:7], f"git rev-parse {TAG}; {source}")


# ── 2. intents ───────────────────────────────────────────────────────────────────────────────────────────────────

INTENTS_SHIPPED = "orchestrator/intents/intent_definitions.yaml"
INTENTS_OVERLAY = "bldg1/intents.yaml"  # loaded as input/intents.yaml at the freeze (input/ held bldg1/'s bytes)


def intents():
    shipped_src, overlay_src = show(INTENTS_SHIPPED), show(INTENTS_OVERLAY)
    shipped = yaml.safe_load(shipped_src)["intents"]
    overlay = yaml.safe_load(overlay_src)["intents"]
    by_lines = len(re.findall(r"(?m)^\s*-\s*name:", shipped_src))
    if by_lines != len(shipped):
        problem(f"intent count: YAML parse {len(shipped)} but {by_lines} '- name:' lines")
    names = [i["name"] for i in shipped]
    if len(set(names)) != len(names):
        problem("duplicate intent names in the shipped registry")
    clash = {i["name"] for i in overlay} & set(names)
    if clash:
        problem(f"overlay redefines shipped intents {sorted(clash)}; the total would not be a sum")
    # The overlay is merged by the registry from input/intents.yaml (registry.py, _overlay_search_paths).
    if "input/intents.yaml" not in show("orchestrator/intents/registry.py"):
        problem("registry.py at the tag no longer reads input/intents.yaml; the overlay may not have loaded")
    groups = {}
    for i in shipped:
        groups[i.get("pipeline_group", "standalone")] = groups.get(i.get("pipeline_group", "standalone"), 0) + 1
    internal = [i["name"] for i in shipped if str(i.get("description", "")).lstrip().startswith("INTERNAL")]
    src = f"git show {TAG}:{INTENTS_SHIPPED}, entries under 'intents:' (YAML parse; equals the count of '- name:' lines)"
    fact("intents_shipped", len(shipped), src)
    fact("intents_overlay", len(overlay), f"git show {TAG}:{INTENTS_OVERLAY} (the building's overlay)")
    fact("intents_total", len(shipped) + len(overlay), "intents_shipped + intents_overlay (no name in both)")
    for g in ("data", "standalone", "meta"):
        fact(f"intents_{g}", groups.get(g, 0), f"{INTENTS_SHIPPED}: entries with pipeline_group '{g}'")
    if sum(groups.values()) != len(shipped):
        problem(f"pipeline groups {groups} do not sum to {len(shipped)}")
    fact("intents_internal", len(internal),
         f"{INTENTS_SHIPPED}: descriptions starting 'INTERNAL' (reached only by a routing rule): {' '.join(internal)}")
    return shipped, overlay


# ── 3. routing rules ─────────────────────────────────────────────────────────────────────────────────────────────

CONTRACT = "orchestrator/services/routing_contract.py"
STAGES = (("parse", "PARSE_STAGE_RULES"), ("post", "POST_STAGE_RULES"), ("concept", "CONCEPT_STAGE_RULES"))


def rules_by_ast(src):
    tree = ast.parse(src)
    found = {}
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            if node.target.id in dict((v, k) for k, v in STAGES):
                problem(f"{node.target.id} is extended after its definition; a literal count would be wrong")
        for name in targets:
            if name not in [v for _, v in STAGES]:
                continue
            if name in found:
                problem(f"{name} assigned twice in {CONTRACT}")
            if not isinstance(node.value, ast.Tuple):
                problem(f"{name} is not a tuple literal; count it another way")
                continue
            names = []
            for el in node.value.elts:
                ok = (isinstance(el, ast.Call) and isinstance(el.func, ast.Name) and el.func.id == "Rule"
                      and el.args and isinstance(el.args[0], ast.Constant) and isinstance(el.args[0].value, str))
                if not ok:
                    problem(f"{name}: an element is not Rule('<name>', ...); count it another way")
                    continue
                names.append(el.args[0].value)
            found[name] = names
    return found


def rules_by_import(src):
    """Import the tagged module with the tagged shared/ package on the path, and read the tuples' lengths."""
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(fileobj=io.BytesIO(git("archive", "--format=tar", TAG, "shared", binary=True))) as tar:
            tar.extractall(tmp)
        path = os.path.join(tmp, "routing_contract_at_tag.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(src)
        saved_path, saved_mods = list(sys.path), set(sys.modules)
        sys.path.insert(0, tmp)
        try:
            spec = importlib.util.spec_from_file_location("routing_contract_at_tag", path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod  # @dataclass looks its module up here while the module executes
            spec.loader.exec_module(mod)
            return {var: [getattr(r, "name", None) for r in getattr(mod, var)] for _, var in STAGES}
        finally:
            sys.path[:] = saved_path
            for m in set(sys.modules) - saved_mods:
                if m == "shared" or m.startswith("shared.") or m == "routing_contract_at_tag":
                    del sys.modules[m]


def routing_rules():
    src = show(CONTRACT)
    by_ast = rules_by_ast(src)
    try:
        by_import = rules_by_import(src)
        method = "counted by parsing the module (ast) and by importing it; the two agree"
    except Exception as exc:  # a failed import is reported, not hidden
        problem(f"could not import the tagged routing contract to cross-check the ast count: {exc}")
        by_import = None
        method = "ast"
    total = 0
    all_names = []
    for stage, var in STAGES:
        names = by_ast.get(var)
        if names is None:
            problem(f"{var} not found in {CONTRACT}")
            continue
        if by_import is not None and by_import[var] != names:
            problem(f"{var}: ast gives {len(names)} rules, import gives {len(by_import[var])}, or the names differ")
        total += len(names)
        all_names += names
        fact(f"rules_{stage}", len(names), f"git show {TAG}:{CONTRACT}, len({var}); {method}")
    if len(set(all_names)) != len(all_names):
        problem("a routing rule name appears twice across the stages")
    fact("rules_total", total, "rules_parse + rules_post + rules_concept")


# ── 4. settings, from the tagged code and the freeze record ─────────────────────────────────────────────────────


def module_constant(src, name):
    """The value of a top-level constant: a literal, frozenset({...}), or another constant's name."""
    tree = ast.parse(src)
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    values[t.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            values[node.target.id] = node.value

    def evaluate(expr, depth=0):
        if depth > 5:
            raise ValueError(f"{name}: names nest too deep")
        if isinstance(expr, ast.Name):
            return evaluate(values[expr.id], depth + 1)
        if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id in ("frozenset", "set"):
            return frozenset(ast.literal_eval(expr.args[0])) if expr.args else frozenset()
        return ast.literal_eval(expr)

    if name not in values:
        raise KeyError(f"{name} is not a top-level constant")
    return evaluate(values[name])


def settings_defaults(src, wanted):
    """Default of each Settings field `NAME: type = Field(default=...)` in shared/config.py."""
    out = {}
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id in wanted:
            call = node.value
            if not (isinstance(call, ast.Call) and getattr(call.func, "id", "") == "Field"):
                problem(f"config {node.target.id} is not a Field(...)")
                continue
            default = [k.value for k in call.keywords if k.arg == "default"]
            if not default:
                problem(f"config {node.target.id} has no default")
                continue
            out[node.target.id] = ast.literal_eval(default[0])
    for w in wanted:
        if w not in out:
            problem(f"config field {w} not found at the tag")
    return out


def readme_settings():
    """The settings table in section 3 of the freeze record: first cell -> (value cell, note cell)."""
    with open(FREEZE_README, encoding="utf-8") as fh:
        text = fh.read()
    sec = text.split("## 3.", 1)[1].split("\n## ", 1)[0]
    rows = {}
    for line in sec.split("\n"):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and line.strip().startswith("|") and not set(cells[0]) <= set("-: "):
            rows[cells[0].strip("`")] = (cells[1], cells[2] if len(cells) > 2 else "")
    return text, rows


def settings():
    cfg = settings_defaults(show("shared/config.py"), {
        "MODEL_PROVIDER", "HOSTED_LLM_MODEL", "REFERENT_VALIDATION_ENABLED", "ANSWER_RELEVANCE_GATE",
        "ANSWER_RELEVANCE_TIMEOUT_S", "ANSWER_RELEVANCE_GATE_LANES", "ARBITER_V2_ROUTING", "COREFERENCE_REWRITE_ENABLED"})
    text, rows = readme_settings()
    readme = "Freeze_2026-10-14/README.md section 3"

    # The day of the freeze, as the record's own title states it, so the article never sends a reader elsewhere for it.
    m = re.match(r"# Freeze record, (\d{1,2} [A-Z][a-z]+ \d{4})", text)
    if not m:
        problem("freeze record title does not state the freeze date as '# Freeze record, <d Month yyyy>'")
    else:
        fact("freeze_date", m.group(1), "Freeze_2026-10-14/README.md title line (the record's own date)")

    model_row = rows.get("Model", ("", ""))[0]
    if "`gpt-oss:20b`" not in model_row or "MODEL_PROVIDER=hosted" not in model_row:
        problem(f"freeze record's model row reads {model_row!r}")
    if cfg.get("HOSTED_LLM_MODEL") != "gpt-oss:20b" or cfg.get("MODEL_PROVIDER") != "hosted":
        problem(f"config defaults at the tag: provider {cfg.get('MODEL_PROVIDER')}, model {cfg.get('HOSTED_LLM_MODEL')}")
    fact("model", "gpt-oss:20b", f"{readme} (hosted gateway); shared/config.py HOSTED_LLM_MODEL default at the tag")
    fact("model_provider", "hosted", f"{readme} (MODEL_PROVIDER=hosted); shared/config.py default at the tag")

    for key, field, row in (("referent_check", "REFERENT_VALIDATION_ENABLED", "REFERENT_VALIDATION_ENABLED"),
                            ("relevance_check", "ANSWER_RELEVANCE_GATE", "ANSWER_RELEVANCE_GATE")):
        value, note = rows.get(row, ("", ""))
        if value != "on" or "code default" not in note:
            problem(f"freeze record row {row}: {value!r} / {note!r}")
        if cfg.get(field) is not True:
            problem(f"shared/config.py {field} default at the tag is {cfg.get(field)!r}, not True")
        fact(key, "on", f"{readme} ('not in .env, so the code default applies'); shared/config.py {field} default True")

    value, _ = rows.get("Claim binding", ("", ""))
    mode = module_constant(show("orchestrator/services/claim_binder.py"), "DEFAULT_MODE")
    if value != "`record`" or mode != "record":
        problem(f"claim binding: freeze record {value!r}, claim_binder DEFAULT_MODE {mode!r}")
    fact("claim_binding", "record", f"{readme} (.env CLAIM_BINDING_ENABLED=record); claim_binder.DEFAULT_MODE")

    value, _ = rows.get("ARBITER_V2_ROUTING", ("", ""))
    if value != "`live`":
        problem(f"freeze record ARBITER_V2_ROUTING row reads {value!r}")
    fact("compound_routing", "live", f"{readme} (ARBITER_V2_ROUTING)")
    fact("compound_routing_code_default", cfg.get("ARBITER_V2_ROUTING"), "shared/config.py default at the tag")

    # Code defaults the freeze record does not list. The .env at the freeze may not be read here (plan 21 rules);
    # the article states them as code defaults, and OPEN_ITEMS asks the first author to confirm .env did not override them.
    lanes_cfg = [x.strip() for x in str(cfg.get("ANSWER_RELEVANCE_GATE_LANES", "")).split(",") if x.strip()]
    lanes_mod = [x.strip() for x in module_constant(show("orchestrator/services/answer_relevance_gate.py"),
                                                    "DEFAULT_LANES").split(",") if x.strip()]
    if lanes_cfg != lanes_mod:
        problem("the relevance check's lane list differs between shared/config.py and answer_relevance_gate.py")
    fact("relevance_lanes", len(lanes_cfg), "shared/config.py ANSWER_RELEVANCE_GATE_LANES default (code default; "
         "equals answer_relevance_gate.DEFAULT_LANES): " + " ".join(lanes_cfg))
    timeout = cfg.get("ANSWER_RELEVANCE_TIMEOUT_S")
    if float(timeout) != int(timeout):
        problem(f"relevance timeout {timeout} is not a whole number of seconds")
    fact("relevance_timeout_s", int(timeout), "shared/config.py ANSWER_RELEVANCE_TIMEOUT_S default (code default)")
    replacing = sorted(module_constant(show("orchestrator/services/answer_relevance_gate.py"), "REPLACING_LABELS"))
    fact("relevance_replacing_labels", len(replacing), "answer_relevance_gate.REPLACING_LABELS: " + " ".join(replacing))
    pub = sorted(module_constant(show("orchestrator/services/publication_gate.py"), "GATED_INTENTS"))
    fact("publication_lanes", len(pub), "publication_gate.GATED_INTENTS (a constant, no setting): " + " ".join(pub))
    if cfg.get("COREFERENCE_REWRITE_ENABLED") is not True:
        problem("COREFERENCE_REWRITE_ENABLED default is not True at the tag")
    fact("coref_rewrite", "on", "shared/config.py COREFERENCE_REWRITE_ENABLED default True (code default)")

    # The graph as frozen (section 6) and unchanged at the end of collection (runbook decision log, snapshot 2).
    m = re.search(r"([\d,]+) quads in (\d+) named graphs", text)
    if not m:
        problem("freeze record section 6: graph export size not found")
        return
    statements, graphs = int(m.group(1).replace(",", "")), int(m.group(2))
    with open(RUNBOOK, encoding="utf-8") as fh:
        m2 = re.search(r"graph export ([\d,]+) explicit statements = snapshot #1", fh.read())
    if not m2 or int(m2.group(1).replace(",", "")) != statements:
        problem("runbook decision log does not record snapshot 2 with the same statement count")
    fact("freeze_graph_statements", statements, "Freeze_2026-10-14/README.md section 6 (explicit statements, "
         "snapshot1_graph.trig); equal at snapshot 2 (runbook decision log, 24 Oct)")
    fact("freeze_graph_named_graphs", graphs, "Freeze_2026-10-14/README.md section 6")


# ── 5. access control, documents, stores and actuation at the tag ────────────────────────────────────────────────


def access_and_data():
    rbac = show("orchestrator/middleware/rbac.py")
    perms = module_constant(rbac, "ALL_PERMISSIONS")
    roles = [k.value for node in ast.parse(rbac).body
             if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "ROLE_PERMISSIONS"
             for k in node.value.keys]
    fact("rbac_roles", len(roles), "orchestrator/middleware/rbac.py ROLE_PERMISSIONS keys: " + " ".join(roles))
    fact("rbac_permissions", len(perms), "orchestrator/middleware/rbac.py ALL_PERMISSIONS")

    access = yaml.safe_load(show("bldg1/role_datasource_access.yaml"))["roles"]
    if not access or any(v != "*" for v in access.values()):
        problem(f"role_datasource_access.yaml at the tag is not open to every role: {access}")
    fact("datasource_roles_open", len(access), "bldg1/role_datasource_access.yaml: every listed role maps to '*' "
         "(the QA setting of 2 Oct)")

    docs = [p for p in ls("bldg1/documents") if p.endswith(".md")]
    registers = 0
    for p in docs:
        m = re.match(r"---\r?\n(.*?)\r?\n---", show(p), re.S)
        front = yaml.safe_load(m.group(1)) if m else None
        registers += bool(isinstance(front, dict) and front.get("record_type"))
    fact("tag_documents", len(docs), f"git ls-tree {TAG} bldg1/documents (*.md)")
    fact("tag_register_documents", registers, "bldg1/documents/*.md whose front matter names a record_type")
    fact("tag_prose_documents", len(docs) - registers, "tag_documents - tag_register_documents")

    reg = yaml.safe_load(show("bldg1/database_registry.yaml"))["databases"]
    nature = {}
    for entry in reg.values():
        if isinstance(entry, dict) and entry.get("nature"):
            nature[entry["nature"]] = nature.get(entry["nature"], 0) + 1
    if set(nature) != {"real", "synthetic"}:
        problem(f"registry natures at the tag: {nature}")
    fact("tag_stores_real", nature.get("real", 0), "bldg1/database_registry.yaml entries with nature: real")
    fact("tag_stores_synthetic", nature.get("synthetic", 0), "bldg1/database_registry.yaml entries with nature: synthetic")
    stores_named_by_points(reg)

    brick_files = [p for p in ls("bldg1") if re.fullmatch(r"bldg1/Brick_v[\d.]+\.ttl", p)]
    if len(brick_files) != 1:
        problem(f"expected one vendored Brick file at the tag, found {brick_files}")
    else:
        m = re.search(r'owl:versionInfo "(\d+)\.(\d+)(?:\.\d+)?"', show(brick_files[0]))
        if not m or brick_files[0] != f"bldg1/Brick_v{m.group(1)}.{m.group(2)}.ttl":
            problem(f"Brick version in {brick_files[0]} does not match its file name")
        else:
            fact("brick_version", f"{m.group(1)}.{m.group(2)}",
                 f"{brick_files[0]} owl:versionInfo (major.minor; equals the file name)")

    driver = (yaml.safe_load(show("bldg1/building.yaml")).get("actuation") or {}).get("driver")
    if driver != "sim":
        problem(f"actuation driver at the tag is {driver!r}")
    fact("actuation_driver", "sim", "bldg1/building.yaml actuation.driver (services/actuation/sim_driver.py: log only)")


def building_ttls():
    """The tagged building TTL files the uploader loads: every top-level bldg1/*.ttl except the shared schema files
    (Brick*.ttl, *_schema.ttl), which ttl_uploader handles once. Files in subfolders are not loaded."""
    return [p for p in ls("bldg1") if re.fullmatch(r"bldg1/[^/]+\.ttl", p)
            and not p.split("/")[-1].startswith("Brick") and not p.endswith("_schema.ttl")]


# The storedAt object as a literal, a full IRI or a prefixed name; only objects that are registry keys are counted, so
# a triple about the property itself (ref:storedAt rdfs:label ...) cannot add a key.
STORED_AT = re.compile(r'storedAt>?\s+(?:"([^"]+)"|<([^>]+)>|([A-Za-z][\w-]*:[\w.-]+))')
# Kinds of interval record in the events store, as the table caption words them (review item 51).
EVENT_KINDS = {"access", "booking", "workorder", "asset_outage"}


def stores_named_by_points(reg):
    """How many of the registry's real and synthetic stores a point names through ref:storedAt at the tag, and what
    the others are. tab:building-characteristics counts storedAt keys (frozen graph); the registry has one entry more."""
    natured = {k: v for k, v in reg.items() if isinstance(v, dict) and v.get("nature")}
    named = set()
    for path in building_ttls():
        for m in STORED_AT.finditer(show(path)):
            token = m.group(1) or m.group(2) or m.group(3)
            local = re.split(r"[#/:]", token.rstrip("/"))[-1]
            if local in natured:
                named.add(local)
    unnamed = sorted(set(natured) - named)
    if any(natured[k].get("type") != "mysql_events" for k in unnamed):
        problem(f"registry stores no point names at the tag are not all interval-record stores: {unnamed}")
    kinds = set(json_kinds(show("bldg1/bldg1_events_publish_map.json")))
    if unnamed and kinds != EVENT_KINDS:
        problem(f"event kinds at the tag are {sorted(kinds)}; the building table's caption names {sorted(EVENT_KINDS)}")
    fact("tag_stores_named_by_points", len(named),
         "registry entries with a nature named as a ref:storedAt object in the tagged building TTLs: " + " ".join(sorted(named)))
    fact("tag_stores_not_named", len(unnamed),
         "registry entries with a nature that no point names (type mysql_events, interval records): " + " ".join(unnamed))


def json_kinds(text):
    import json

    return (json.loads(text).get("kinds") or {}).keys()


def floors_at_tag():
    """The individuals the live query `?f a brick:Floor` counts, read from the tagged files: those typed brick:Floor,
    and those typed with a subclass of it in the vendored Brick (inference adds brick:Floor to them in GraphDB)."""
    import rdflib
    from rdflib.namespace import RDF, RDFS

    brick_ns = rdflib.Namespace("https://brickschema.org/schema/Brick#")
    brick = rdflib.Graph()
    brick.parse(data=show(f"bldg1/Brick_v{fact_value('brick_version')}.ttl"), format="turtle")
    floor_classes = set(brick.transitive_subjects(RDFS.subClassOf, brick_ns.Floor))
    storeys, others = set(), {}
    for path in building_ttls():
        text = show(path)
        if not any(str(c).split("#")[-1] in text for c in floor_classes):
            continue  # no floor class is named in the file, so it types no floor
        g = rdflib.Graph()
        try:
            g.parse(data=text, format="turtle")
        except Exception as exc:  # a file that cannot be read must not be skipped quietly
            problem(f"could not parse {path} at the tag to count floor nodes: {exc}")
            continue
        for cls in floor_classes:
            for s in g.subjects(RDF.type, cls):
                if cls == brick_ns.Floor:
                    storeys.add(s)
                else:
                    others.setdefault(s, set()).add(str(cls).split("#")[-1])
    for s in storeys:
        others.pop(s, None)
    other_classes = {c for cs in others.values() for c in cs}
    if other_classes != {"Rooftop", "Parking_Level"}:
        problem(f"floor nodes typed by a subclass at the tag are {sorted(other_classes)}; the building table's caption "
                "names the rooftop and a parking level")
    local = lambda s: str(s).split("#")[-1]  # noqa: E731
    fact("tag_floor_storeys", len(storeys), "tagged building TTLs (rdflib): individuals typed brick:Floor: "
         + " ".join(sorted(local(s) for s in storeys)))
    fact("tag_floor_other", len(others), "tagged building TTLs (rdflib): individuals typed with a subclass of "
         "brick:Floor in the vendored Brick: " + " ".join(f"{local(s)} ({'/'.join(sorted(c))})" for s, c in
                                                          sorted(others.items())))


# ── 6. the building as frozen for the study (14 October 2026), re-counted 29 October 2026 ────────────────────────────────────────────────

# CSV characteristic -> (key, label in the building table, group). Labels are authored; numbers come from the CSV.
BUILDING_ROWS = [
    ("floors", "bldg_floors", r"Floor nodes (\texttt{brick:Floor} and its subclasses)", "model"),
    ("locations_modelled", "bldg_locations", r"Locations (\texttt{brick:Location} and its subclasses)", "model"),
    ("equipment", "bldg_equipment", r"Equipment (\texttt{brick:Equipment} and its subclasses)", "model"),
    ("points_total", "bldg_points_total", "Points in all", "total"),
    ("distinct_point_classes", "bldg_point_classes", "Distinct point classes", "total"),
    ("timeseries_bindings", "bldg_ts_references", r"Timeseries references (\texttt{ref:hasTimeseriesId})", "refs"),
    ("distinct_timeseries_ids", "bldg_ts_ids", r"\quad distinct series identifiers", "refs"),
    ("stored_at_keys", "bldg_stores", r"Stores named by points (distinct \texttt{ref:storedAt} keys)", "refs"),
    ("hbco_concepts", "bldg_hbco_concepts", "Lay-term concepts (HBCO)", "ext"),
    ("hbco_lay_terms", "bldg_hbco_lay_terms", r"\quad lay terms", "ext"),
    ("ocbv_amenities", "bldg_amenities", "Amenities (OCBV)", "ext"),
    ("ocbv_knowledge_topics", "bldg_topics", "Knowledge topics (OCBV)", "ext"),
    ("ocbv_classes", "bldg_ocbv_classes", "Classes declared in the OCBV namespace", "ext"),
    ("ocbv_properties", "bldg_ocbv_properties", "Properties declared in the OCBV namespace", "ext"),
]
POINT_KINDS = [
    ("points: Indoor climate (CO2, RH, air temp.)", "bldg_points_climate",
     r"Indoor climate (CO\textsubscript{2}, humidity, air temperature)"),
    ("points: Air quality (PM, TVOC, NO2, CO, CH2O, gas)", "bldg_points_air_quality",
     r"Air quality (particulates, TVOC, NO\textsubscript{2}, CO, formaldehyde, gas)"),
    ("points: Lighting (colour temp., illuminance)", "bldg_points_lighting",
     "Lighting (colour temperature, illuminance)"),
    ("points: Occupancy (count, status)", "bldg_points_occupancy", "Occupancy (count, status)"),
    ("points: Door and access contact", "bldg_points_contact",
     "Door and window contacts, intrusion detectors, cameras"),
    ("points: Acoustics (sound, noise)", "bldg_points_acoustics", "Sound and noise level"),
    ("points: HVAC plant (air flow, damper, filter, fan)", "bldg_points_hvac",
     "HVAC plant (air flow, damper, filter, fan)"),
    ("points: Waste", "bldg_points_waste", "Waste (fill, weight)"),
    ("points: Electrical power", "bldg_points_power", "Electrical power and energy"),
    ("points: Water (flow, level, temp., metering)", "bldg_points_water",
     "Water (flow, level, temperature, metering)"),
    ("points: Outdoor and weather", "bldg_points_outdoor", "Outdoor and weather"),
    ("points: uncategorised", "bldg_points_unassigned", "Not assigned to a kind above"),
]


def building_frozen():
    with open(BUILDING_CSV, encoding="utf-8") as fh:
        rows = [r for r in csv.reader(fh) if r and not r[0].startswith("#")]
    values = {r[0]: r[1] for r in rows[1:]}
    known = {c for c, *_ in BUILDING_ROWS} | {c for c, *_ in POINT_KINDS}
    for c in values:
        if c not in known:
            problem(f"building-characteristics.csv row {c!r} has no place in the table")
    src = ("paper/generated/frozen_2026-10-14/building-characteristics.csv (the frozen study graph, re-counted 29 October 2026; draft1Nov_work/recount_frozen_graph.py)")
    for csv_name, key, *_ in BUILDING_ROWS + POINT_KINDS:
        if csv_name not in values:
            problem(f"building-characteristics.csv has no row {csv_name!r}")
            continue
        fact(key, int(values[csv_name]), f"{src}, row '{csv_name}'")
    kinds = sum(int(values.get(c, 0)) for c, *_ in POINT_KINDS)
    if kinds != int(values.get("points_total", -1)):
        problem(f"point kinds sum to {kinds}, total is {values.get('points_total')}")


def cross_check_building():
    """The building table's caption explains two of its counts from the tagged files; they must agree."""
    floors = fact_value("tag_floor_storeys") + fact_value("tag_floor_other")
    if floors != fact_value("bldg_floors"):
        problem(f"floor nodes at the tag ({floors}) differ from the frozen-graph count ({fact_value('bldg_floors')}); "
                "the caption's account of them would not hold")
    if fact_value("tag_stores_named_by_points") != fact_value("bldg_stores"):
        problem(f"stores named by points at the tag ({fact_value('tag_stores_named_by_points')}) differ from the "
                f"frozen-graph count ({fact_value('bldg_stores')}); the caption's account of them would not hold")


# ── 7. tables ────────────────────────────────────────────────────────────────────────────────────────────────────

GEN_NOTE = "% {name} -- generated by paper/scripts/freeze_facts.py; do not edit by hand (re-run the script).\n"
FV_RE = re.compile(r"\\fv\{([^}]*)\}")
SV_RE = re.compile(r"\\sv\{([^}]*)\}")
STUDY_NUMBERS = os.path.join(PAPER, "generated", "study_v9", "numbers.tex")
_SV = {}


def study_value(key):
    """A study value (\\sv) as numbers.tex defines it; an unknown key is a problem, as it is a build error."""
    if not _SV:
        with open(STUDY_NUMBERS, encoding="utf-8") as fh:
            for m in re.finditer(r"\\csname sv@([^\\]+)\\endcsname\{(.*)\}%", fh.read()):
                _SV[m.group(1)] = m.group(2)
    if key not in _SV:
        problem(f"unknown \\sv key {key!r}")
        return "??"
    return _SV[key].replace("\\%", "%")


def resolve_fv(text, latex):
    def sub(m):
        key = m.group(1)
        try:
            value = fact_value(key)
        except KeyError:
            problem(f"unknown \\fv key {key!r} in an input file")
            return m.group(0)
        return m.group(0) if latex else str(value)
    text = FV_RE.sub(sub, text)
    return SV_RE.sub(lambda m: m.group(0) if latex else study_value(m.group(1)), text)


def check_sv(text):
    for key in SV_RE.findall(text):
        study_value(key)


def plain(text):
    """A CSV twin cell: LaTeX markup removed, so a reader sees the text and the values."""
    text = resolve_fv(text, latex=False)
    text = re.sub(r"\\textsubscript\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\texttt\{([^}]*)\}", r"\1", text)
    text = text.replace(r"\S\ref{sec:rq2-checks}", "section RQ2 (sec:rq2-checks)").replace(r"\quad ", "  ")
    text = re.sub(r"\\S\\ref\{([^}]*)\}", r"section (\1)", text)
    text = text.replace(r"\_", "_").replace("{,}", ",").replace("$^\\dagger$", " (rule only)")
    return text


def table_building():
    def row(label, key):
        return f"{label} & {latex_value(fact_value(key))} \\\\"

    body = [r"\multicolumn{2}{@{}l}{\textbf{Spaces and equipment}} \\"]
    body += [row(lab, key) for _, key, lab, grp in BUILDING_ROWS if grp == "model"]
    body += [r"\midrule", r"\multicolumn{2}{@{}l}{\textbf{Points, by kind} (each counted once)} \\"]
    body += [row(r"\quad " + lab, key) for _, key, lab in POINT_KINDS]
    body += [row(lab, key) for _, key, lab, grp in BUILDING_ROWS if grp == "total"]
    body += [r"\midrule", r"\multicolumn{2}{@{}l}{\textbf{Links from points to stored readings}} \\"]
    body += [row(lab, key) for _, key, lab, grp in BUILDING_ROWS if grp == "refs"]
    body += [r"\midrule", r"\multicolumn{2}{@{}l}{\textbf{Extensions to Brick}} \\"]
    body += [row(lab, key) for _, key, lab, grp in BUILDING_ROWS if grp == "ext"]
    tex = (GEN_NOTE.format(name="tab_building.tex")
           + "\\begin{table}[t]\n\\centering\n\\footnotesize\n"
           "\\caption{\\bldg{} as modelled in the graph frozen for the study, counted by SPARQL queries against it. "
           "Each point is counted once, under the first kind whose "
           "classes it carries, so the kinds sum to the total. Brick classes a rooftop and a parking level as kinds of "
           "floor, so the floor nodes are the building's \\fv{tag_floor_storeys} storeys and these "
           "\\fv{tag_floor_other} spaces. Besides the stores that points name, the store registry lists a store of interval records "
           "(bookings, work orders, door access and equipment outages), which no point names.}\n"
           "\\label{tab:building-characteristics}\n"
           "\\begin{tabular}{@{}lr@{}}\n\\toprule\n\\textbf{Characteristic} & \\textbf{Count} \\\\\n\\midrule\n"
           + "\n".join(body) + "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")
    twin = [["group", "characteristic", "count"]]
    for _, key, lab, grp in BUILDING_ROWS:
        twin.append([grp, plain(lab), fact_value(key)])
    for _, key, lab in POINT_KINDS:
        twin.append(["points by kind", plain(lab), fact_value(key)])
    return tex, twin


def verify_evidence(row):
    for slot in ("ev1", "ev2", "ev3", "ev4"):
        where, expect = (row.get(slot) or "").strip(), (row.get(f"{slot}_text") or "").strip()
        if not where:
            continue
        path, _, line = where.rpartition(":")
        try:
            lines = show(path).split("\n")
        except RuntimeError as exc:
            problem(f"checks.csv {row['check']} {slot}: {exc}")
            continue
        n = int(line)
        if not (1 <= n <= len(lines)) or expect not in lines[n - 1]:
            now = [i + 1 for i, text in enumerate(lines) if expect in text]
            problem(f"checks.csv {row['check']} {slot}: {path}:{n} does not hold {expect!r} at the tag "
                    f"(found on lines {now})")


def table_checks():
    with open(os.path.join(OUT, "checks.csv"), encoding="utf-8", newline="") as fh:
        rows = sorted(csv.DictReader(fh), key=lambda r: int(r["order"]))
    body, twin = [], [["check", "what it tests", "study setting", "if it cannot run", "measured in the study",
                       "evidence at the tag"]]
    for r in rows:
        verify_evidence(r)
        cells = [resolve_fv(r[c], latex=True) for c in ("check", "tests", "setting", "if_cannot_run", "measured")]
        body.append(" & ".join(cells) + " \\\\")
        evidence = "; ".join(r[s] for s in ("ev1", "ev2", "ev3", "ev4") if r.get(s))
        twin.append([plain(r[c]) for c in ("check", "tests", "setting", "if_cannot_run", "measured")] + [evidence])
    col = r">{\raggedright\arraybackslash}"
    caption = (
        "The main checks in code in the study build. \\emph{Setting}: a switchable check could be turned off by "
        "configuration; \\emph{on} means it was always applied, and any other setting that could change it is "
        "named. \\emph{If it cannot run}: what happens when the check errors or times out. \\emph{Measured}: where "
        "the study reports how often the check acted (--, not analysed). Each answer's evidence record shows that "
        "freshness acted on \\sv{checks_live_evidence_record_gate_freshness}, and the two document-passage tests on "
        "\\sv{checks_live_evidence_record_gate_grounding_guard} and "
        "\\sv{checks_live_evidence_record_gate_passage_relevance}, of the \\sv{checks_live_answers} live answers. "
        "Every row was checked against the tagged code. Smaller passes that reword a reply or reconcile a single "
        "statement with a recorded value are not listed."
    )
    check_sv(caption)
    tex = (GEN_NOTE.format(name="tab_checks_frozen.tex")
           + "\\begin{table}[tp]\n\\centering\n\\footnotesize\n\\setlength{\\tabcolsep}{4pt}\n"
           f"\\caption{{{caption}}}\n"
           "\\label{tab:checks-frozen}\n"
           f"\\begin{{tabularx}}{{\\textwidth}}{{@{{}}{col}p{{2.2cm}}{col}X{col}p{{2.0cm}}{col}p{{2.5cm}}"
           f"{col}p{{1.25cm}}@{{}}}}\n"
           "\\toprule\n\\textbf{Check} & \\textbf{What it does} & \\textbf{Setting} & \\textbf{If it cannot run} & "
           "\\textbf{Measured} \\\\\n\\midrule\n"
           + "\n".join(body) + "\n\\bottomrule\n\\end{tabularx}\n\\end{table}\n")
    return tex, twin


def table_lanes(shipped, overlay):
    with open(os.path.join(OUT, "lanes.csv"), encoding="utf-8", newline="") as fh:
        rows = sorted(csv.DictReader(fh), key=lambda r: int(r["order"]))
    by_name = {i["name"]: i for i in shipped + overlay}
    expected = {i["name"] for i in shipped
                if i.get("pipeline_group") == "standalone" or (i.get("pipeline_group") == "meta" and i.get("node_method"))}
    # The building's overlay (review item 51): an overlay intent with a node of its own must sit in a lane; one without
    # has no lane at the tag (the router's safety net sends it to the response step), and the caption says so.
    expected |= {i["name"] for i in overlay if i.get("node_method")}
    laneless = sorted(i["name"] for i in overlay if not i.get("node_method") and i.get("pipeline_group") != "data")
    if laneless and "falling back to response" not in show("orchestrator/workflow/_orchestrator.py"):
        problem("the router's fallback for an intent with no node is not where the caption assumes it is")
    seen = []
    orchestrator_src = show("orchestrator/workflow/_orchestrator.py")
    body, twin = [], [["lane", "what it answers", "intents", "node methods"]]
    for r in rows:
        names = r["intents"].split()
        shown, methods = [], []
        for n in names:
            if n not in by_name:
                problem(f"lanes.csv: intent {n!r} does not exist at the tag")
                continue
            seen.append(n)
            method = by_name[n].get("node_method")
            if method:
                methods.append(method)
                if f"async def {method}(" not in orchestrator_src:
                    problem(f"lanes.csv: {n}'s node method {method} is not defined in _orchestrator.py at the tag")
            internal = str(by_name[n].get("description", "")).lstrip().startswith("INTERNAL")
            shown.append(r"\texttt{" + latex_value(n) + "}" + ("$^\\dagger$" if internal else ""))
        body.append(f"{r['lane']} & {r['answers']} & " + ", ".join(shown) + " \\\\")
        twin.append([r["lane"], r["answers"], plain(", ".join(shown)), " ".join(sorted(set(methods)))])
    if sorted(seen) != sorted(expected):
        problem(f"lanes.csv: missing {sorted(expected - set(seen))}, extra or repeated "
                f"{sorted(n for n in seen if seen.count(n) > 1 or n not in expected)}")
    col = r">{\raggedright\arraybackslash}"
    tex = (GEN_NOTE.format(name="tab_subsystems.tex")
           + "\\begin{table}[t]\n\\centering\n\\footnotesize\n"
           "\\caption{The lanes outside the shared data pipeline in the study build, and the intents routed to each. "
           "Intents marked $\\dagger$ are reached only through a routing rule; the classifier's prompt tells the "
           "model not to choose them."
           + ("" if not laneless else
              (" The building's overlay intent " if len(laneless) == 1 else " The building's overlay intents ")
              + " and ".join(r"\texttt{" + latex_value(n) + "}" for n in laneless)
              + (" has" if len(laneless) == 1 else " have") + r" no lane (\S\ref{sec:sys-pipeline}).")
           + "}\n"
           "\\label{tab:subsystems}\n"
           f"\\begin{{tabularx}}{{\\textwidth}}{{@{{}}{col}p{{3.1cm}}{col}X{col}p{{3.9cm}}@{{}}}}\n"
           "\\toprule\n\\textbf{Lane} & \\textbf{What it answers} & \\textbf{Intents} \\\\\n\\midrule\n"
           + "\n".join(body) + "\n\\bottomrule\n\\end{tabularx}\n\\end{table}\n")
    return tex, twin


# ── 8. write ─────────────────────────────────────────────────────────────────────────────────────────────────────


def csv_text(rows):
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    check_tag()
    shipped, overlay = intents()
    routing_rules()
    settings()
    access_and_data()
    floors_at_tag()
    building_frozen()
    cross_check_building()
    outputs = {}
    for name, (tex, twin) in (("tab_building", table_building()),
                              ("tab_checks_frozen", table_checks()),
                              ("tab_subsystems", table_lanes(shipped, overlay))):
        outputs[name + ".tex"] = tex
        outputs[name + ".csv"] = csv_text(twin)

    lines = ["%% System facts of the frozen OntoSage+ build (tag " + TAG + ") and, for now, the building counts of",
             "%% frozen study graph of 14 October 2026 (keys starting bldg_). Written by paper/scripts/freeze_facts.py; do not edit by hand.",
             "%% The source of every value is in freeze_facts.csv."]
    tex = "\n".join(lines) + "\n" + FV_DEFINITION + "\n"
    for key, value, source in FACTS:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
            problem(f"key {key!r} has characters a \\fv key should not carry")
        tex += f"\\expandafter\\def\\csname fv@{key}\\endcsname{{{latex_value(value)}}}\n"
    outputs["freeze_facts.tex"] = tex
    outputs["freeze_facts.csv"] = csv_text([["key", "value", "source"]] + [[k, v, s] for k, v, s in FACTS])

    if PROBLEMS:
        print("NOTHING WRITTEN. Problems:")
        for p in PROBLEMS:
            print("  -", p)
        return 1
    os.makedirs(OUT, exist_ok=True)
    for name, text in outputs.items():
        with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    width = max(len(k) for k, _, _ in FACTS)
    for key, value, _ in FACTS:
        print(f"  {key:<{width}}  {value}")
    print(f"\n{len(FACTS)} values and {len(outputs) - 2} table files written to {os.path.relpath(OUT, PAPER)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
