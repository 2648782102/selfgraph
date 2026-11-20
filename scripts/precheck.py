#!/usr/bin/env python3
import argparse
import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from io import BytesIO

REPO = os.environ.get("PRECHECK_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PY_TEST_GLOB = "tests/"
TS_TEST_SUFFIX = ".test.ts"
PY_CONF = "typescript/test/conformance/py_side.py"
TS_CONF = "typescript/test/conformance/ts_side.ts"
LIB_PY = "src/selfgraph/"
LIB_TS = "typescript/src/"

PY_PRAGMAS = ("type:", "noqa", "pragma", "ruff:", "mypy:", "nosec", "pylint:")
TS_DIRECTIVES = (
    "biome-ignore",
    "@ts-",
    "eslint",
    "<reference",
    "v8 ignore",
    "c8 ignore",
    "prettier-ignore",
    "vite-ignore",
    "@vitest",
    "@__PURE__",
)
EM_DASH = "\u2014"
BOM = "\ufeff"

MAX_LINES = 1000
LOCKFILE = re.compile(r"(package-lock\.json|\.lock)$")
CONFORMANCE_SIGNALS = re.compile(
    r"\b(raise|throw|ValidationError|SelfGraphError|sorted|localeCompare|ORDER BY|order by"
    r"|min_count|max_count|json_iso|jsonIso|to_jsonable|toJsonable|parse_time|parseTime"
    r"|parse_json|parseJson|_tokens|expand_tokens|expandTokens|schema_forms|schemaForms"
    r"|from_tables|fromTables|NFKC|normalize|encode|decode|dumps|loads)\b"
    r"|code=|\{\s*code|error\[|\.sort\("
)


@dataclass
class Report:
    sections: list = field(default_factory=list)

    def add(self, name, status, lines):
        """Record one check's outcome.

        @param name (str): the check name.
        @param status (str): "pass", "warn", or "fail".
        @param lines (list[str]): detail lines to print under the check.
        @return (None): nothing.
        """
        self.sections.append((name, status, lines))

    def failed(self):
        """Whether any recorded check failed.

        @return (bool): True when at least one section is a failure.
        """
        return any(status == "fail" for _, status, _ in self.sections)


def run_git(args, cwd=REPO, check=True):
    """Run a git command and return its stdout.

    @param args (list[str]): git arguments after the executable.
    @param cwd (str): the working directory.
    @param check (bool): raise on a non-zero exit when True.
    @return (subprocess.CompletedProcess): the finished process.
    """
    return subprocess.run(
        ["git", *args], cwd=cwd, check=check, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def resolve_base(base):
    """Resolve the base ref and the merge base with HEAD.

    @param base (str): the requested base ref.
    @return (tuple[str, str]): the base commit and the merge base commit.
    """
    for candidate in (base, base.split("/", 1)[-1], "main", "master"):
        probe = run_git(["rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}"], check=False)
        if probe.returncode == 0:
            base_commit = probe.stdout.strip()
            mb = run_git(["merge-base", base_commit, "HEAD"], check=False)
            merge_base = mb.stdout.strip() if mb.returncode == 0 else base_commit
            return base_commit, merge_base
    sys.exit(f"precheck: cannot resolve base ref '{base}'. Pass --base <ref> for a ref that exists locally.")


def changed_files(merge_base):
    """List files that differ between the merge base and the working tree.

    @param merge_base (str): the merge base commit.
    @return (list[tuple[str, str]]): (status, path) pairs, renames reduced to the new path.
    """
    out = run_git(["diff", "--name-status", "-M", merge_base]).stdout
    files = []
    for line in out.splitlines():
        parts = line.split("\t")
        status = parts[0][0]
        path = parts[-1]
        files.append((status, path))
    return files


def added_lines(merge_base, path):
    """Map added line numbers to their text for one file.

    @param merge_base (str): the merge base commit.
    @param path (str): the repo-relative path.
    @return (dict[int, str]): new line number to added line text.
    """
    out = run_git(["diff", "--unified=0", "--no-color", merge_base, "--", path], check=False).stdout
    result = {}
    new_line = 0
    for line in out.splitlines():
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            new_line = int(m.group(1)) if m else 0
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            result[new_line] = line[1:]
            new_line += 1
        elif not line.startswith("-"):
            new_line += 1
    return result


def read_worktree(path):
    """Read a file from the working tree as text.

    @param path (str): the repo-relative path.
    @return (str | None): the contents, or None when the file is absent.
    """
    full = os.path.join(REPO, path)
    try:
        with open(full, encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return None


def check_text_rules(files, merge_base):
    """Flag em dashes, BOMs, and non-pragma comments on added lines.

    @param files (list[tuple[str, str]]): changed files.
    @param merge_base (str): the merge base commit.
    @return (list[str]): one message per violation.
    """
    problems = []
    for status, path in files:
        if status == "D":
            continue
        is_py = path.endswith(".py")
        is_ts = path.endswith((".ts", ".tsx"))
        text_kind = path.endswith((".py", ".ts", ".tsx", ".md", ".json", ".yml", ".yaml", ".toml", ".cfg", ".txt"))
        if not text_kind:
            continue
        adds = added_lines(merge_base, path)
        for lineno, text in adds.items():
            if EM_DASH in text:
                problems.append(f"{path}:{lineno}: em dash; replace it with a hyphen, comma, or two sentences")
            if BOM in text:
                problems.append(f"{path}:{lineno}: byte order mark (U+FEFF); save the file as plain UTF-8")
        if is_py:
            problems.extend(_py_comments(path, adds))
        elif is_ts:
            problems.extend(_ts_comments(path, adds))
    return problems


def _py_comments(path, adds):
    """Find disallowed Python comments on added lines.

    @param path (str): the file path.
    @param adds (dict[int, str]): added line numbers to text.
    @return (list[str]): one message per disallowed comment.
    """
    source = read_worktree(path)
    if source is None:
        return []
    out = []
    try:
        tokens = tokenize.tokenize(BytesIO(source.encode("utf-8")).readline)
        for tok in tokens:
            if tok.type != tokenize.COMMENT:
                continue
            lineno = tok.start[0]
            if lineno not in adds:
                continue
            body = tok.string.lstrip("#").strip()
            if lineno == 1 and tok.string.startswith("#!"):
                continue
            if body.startswith("-*-") or body.lower().startswith("coding"):
                continue
            if any(body.startswith(p) for p in PY_PRAGMAS):
                continue
            out.append(f"{path}:{lineno}: comment not allowed; delete it, only '# noqa', '# type:', '# pragma' stay")
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return out
    return out


def _ts_comment_start(line):
    """Return the column of a real comment start on one line, or -1.

    @param line (str): a single source line.
    @return (int): the index of '//' or '/*' outside of a string, else -1.
    """
    quote = None
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"`":
            quote = ch
            i += 1
            continue
        if ch == "/" and i + 1 < n and line[i + 1] in "/*":
            return i
        i += 1
    return -1


def _ts_comments(path, adds):
    """Find disallowed TypeScript comments on added lines.

    @param path (str): the file path.
    @param adds (dict[int, str]): added line numbers to text.
    @return (list[str]): one message per disallowed comment.
    """
    out = []
    for lineno, text in sorted(adds.items()):
        col = _ts_comment_start(text)
        if col < 0:
            continue
        rest = text[col:]
        if rest.startswith("/**"):
            continue
        marker = rest.lstrip("/*").strip()
        if any(marker.startswith(d) or d in rest for d in TS_DIRECTIVES):
            continue
        out.append(f"{path}:{lineno}: comment not allowed; delete it, only doxygen /** */ and tool directives stay")
    return out


def _py_functions(source):
    """Yield top-level and method functions with their line spans and docstring state.

    @param source (str): the file contents.
    @return (list[tuple]): (name, lineno, end, has_doc, skip) per function.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    skip_decorators = {
        "property",
        "cached_property",
        "field_validator",
        "model_validator",
        "validator",
        "overload",
        "setter",
        "getter",
        "deleter",
        "staticmethod",
        "root_validator",
    }
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        parent = parents.get(node)
        nested = isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef))
        dunder = node.name.startswith("__") and node.name.endswith("__")
        decos = set()
        for dec in node.decorator_list:
            name = dec
            if isinstance(dec, ast.Call):
                name = dec.func
            if isinstance(name, ast.Attribute):
                decos.add(name.attr)
            elif isinstance(name, ast.Name):
                decos.add(name.id)
        body = [s for s in node.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
        skip = nested or dunder or bool(decos & skip_decorators) or len(body) < 2
        has_doc = ast.get_docstring(node) is not None
        header_start = min([node.lineno, *[d.lineno for d in node.decorator_list]])
        header_end = node.body[0].lineno - 1 if node.body else node.lineno
        out.append((node.name, node.lineno, header_start, header_end, has_doc, skip))
    return out


def check_py_docstrings(path, adds):
    """Flag new or re-signed Python library functions that lack a docstring.

    @param path (str): the file path.
    @param adds (dict[int, str]): added line numbers to text.
    @return (list[str]): one message per function missing a docblock.
    """
    source = read_worktree(path)
    if source is None:
        return []
    out = []
    for name, lineno, header_start, header_end, has_doc, skip in _py_functions(source):
        if skip or has_doc:
            continue
        if any(header_start <= ln <= header_end for ln in adds):
            out.append(f"{path}:{lineno}: function '{name}' needs a one-line doxygen docstring with @param and @return")
    return out


def check_ts_docstrings(path, adds):
    """Flag added or changed exported TypeScript functions that lack a JSDoc block.

    @param path (str): the file path.
    @param adds (dict[int, str]): added line numbers to text.
    @return (list[str]): one message per exported function missing a docblock.
    """
    source = read_worktree(path)
    if source is None:
        return []
    lines = source.splitlines()
    out = []
    for i, line in enumerate(lines):
        if not re.match(r"^export (async )?function [A-Za-z_]", line):
            continue
        decl = line
        j = i
        while "{" not in decl and ";" not in decl and j + 1 < len(lines):
            j += 1
            decl += " " + lines[j]
        if "{" not in decl:
            continue
        body_end = _ts_block_end(lines, j)
        if body_end - j < 2:
            continue
        if not any((i + 1) <= ln <= (j + 1) for ln in adds):
            continue
        prev = lines[i - 1].strip() if i > 0 else ""
        if prev.endswith("*/"):
            continue
        out.append(f"{path}:{i + 1}: exported function needs a one-line doxygen /** */ block with @param and @return")
    return out


def _ts_block_end(lines, start):
    """Find the line index where the brace opened on or after start closes.

    @param lines (list[str]): the file lines.
    @param start (int): the line index holding the opening brace.
    @return (int): the line index of the matching closing brace.
    """
    depth = 0
    seen = False
    for idx in range(start, len(lines)):
        for ch in lines[idx]:
            if ch == "{":
                depth += 1
                seen = True
            elif ch == "}":
                depth -= 1
        if seen and depth <= 0:
            return idx
    return len(lines) - 1


def check_docstrings(files, merge_base):
    """Flag added or changed library functions that lack a docblock.

    @param files (list[tuple[str, str]]): changed files.
    @param merge_base (str): the merge base commit.
    @return (list[str]): one message per function.
    """
    problems = []
    for status, path in files:
        if status == "D":
            continue
        adds = added_lines(merge_base, path)
        if path.startswith(LIB_PY) and path.endswith(".py"):
            problems.extend(check_py_docstrings(path, adds))
        elif path.startswith(LIB_TS) and path.endswith(".ts") and not path.endswith(".test.ts"):
            problems.extend(check_ts_docstrings(path, adds))
    return problems


def check_conformance(files, merge_base):
    """Require both conformance sides to change together when behaviour changes.

    @param files (list[tuple[str, str]]): changed files.
    @param merge_base (str): the merge base commit.
    @return (tuple[str, list[str]]): the status and detail lines.
    """
    paths = {path for _, path in files}
    py_changed = PY_CONF in paths
    ts_changed = TS_CONF in paths
    if py_changed != ts_changed:
        missing = TS_CONF if py_changed else PY_CONF
        return "fail", [f"only one conformance side changed; mirror the case in {missing}"]
    if py_changed and ts_changed:
        return "pass", ["both conformance sides changed"]
    signal_files = []
    for status, path in files:
        if status == "D":
            continue
        if path.endswith(".test.ts") or path.startswith("tests/"):
            continue
        if not (path.startswith(LIB_PY) and path.endswith(".py")) and not (
            path.startswith(LIB_TS) and path.endswith(".ts")
        ):
            continue
        for text in added_lines(merge_base, path).values():
            stripped = text.strip()
            if stripped.startswith(("#", "//", "*", "/*")):
                continue
            if CONFORMANCE_SIGNALS.search(text):
                signal_files.append(path)
                break
    if signal_files:
        shown = ", ".join(sorted(set(signal_files)))
        return "warn", [
            "deterministic behaviour (errors, parsing, validation, or ordering) changed in:",
            f"  {shown}",
            f"add a case to both {PY_CONF} and {TS_CONF}, or state in the PR why it is not deterministic",
        ]
    return "pass", ["no deterministic behaviour change detected"]


def check_size(merge_base):
    """Hold back a pull request from outside the org that changes more than MAX_LINES lines (lockfiles excluded).

    @param merge_base (str): the merge base commit.
    @return (tuple[str, list[str]]): the status and detail lines.
    """
    total = 0
    for line in run_git(["diff", "--numstat", merge_base]).stdout.splitlines():
        added, removed, path = line.split("\t", 2)
        if not LOCKFILE.search(path) and added != "-":
            total += int(added) + int(removed)
    if total <= MAX_LINES:
        return "pass", [f"{total} changed lines"]
    if os.environ.get("PR_AUTHOR_ASSOCIATION") in ("OWNER", "MEMBER") or "size-ok" in os.environ.get("PR_LABELS", ""):
        return "warn", [f"{total} changed lines, over {MAX_LINES}; allowed for this PR"]
    return "fail", [
        f"{total} changed lines, over {MAX_LINES}; split it into stacked PRs: open the first against main, base each",
        'next one on the previous branch, and give the order in each description ("1/3", "2/3")',
    ]


def check_merge(base_commit):
    """Check that HEAD still merges into the base without conflicts.

    @param base_commit (str): the base commit.
    @return (tuple[str, list[str]]): the status and detail lines.
    """
    result = run_git(["merge-tree", "--write-tree", base_commit, "HEAD"], check=False)
    if result.returncode == 0:
        return "pass", ["HEAD merges cleanly into the base"]
    conflicts = [ln for ln in result.stdout.splitlines() if ln and not re.match(r"^[0-9a-f]{40}$", ln)]
    detail = ["rebase on main; HEAD does not merge cleanly:"]
    detail.extend(f"  {ln}" for ln in conflicts[:20])
    return "fail", detail


def _changed_py_tests(files, merge_base):
    """Collect pytest node ids for added or changed test functions.

    @param files (list[tuple[str, str]]): changed files.
    @param merge_base (str): the merge base commit.
    @return (list[tuple[str, str, str]]): (file, node_id, function) per test.
    """
    nodes = []
    for status, path in files:
        if status == "D" or not path.startswith(PY_TEST_GLOB) or not path.endswith(".py"):
            continue
        if os.path.basename(path) in ("helpers.py", "conftest.py"):
            continue
        source = read_worktree(path)
        if source is None:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        adds = set(added_lines(merge_base, path))
        for node in tree.body:
            classes = [(None, node)] if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else []
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                classes = [(node.name, m) for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for cls, fn in classes:
                if not fn.name.startswith("test"):
                    continue
                end = getattr(fn, "end_lineno", fn.lineno)
                if not any(fn.lineno <= ln <= end for ln in adds):
                    continue
                node_id = f"{path}::{cls}::{fn.name}" if cls else f"{path}::{fn.name}"
                nodes.append((path, node_id, fn.name))
    return nodes


TS_MARKER = re.compile(r"""\b(it|test|describe)(?:\.\w+)?(?:\([^)]*\))?\s*\(\s*(['"`])(.+?)\2""")


def _ts_markers(lines):
    """Find vitest it, test, and describe calls with their titles and line numbers.

    @param lines (list[str]): the file lines.
    @return (list[tuple[int, str, str]]): (line number, kind, title) per marker.
    """
    markers = []
    for i, line in enumerate(lines, start=1):
        m = TS_MARKER.search(line)
        if m:
            markers.append((i, m.group(1), m.group(3)))
    return markers


def _changed_ts_tests(files, merge_base):
    """Collect vitest titles whose body or header a change touches.

    @param files (list[tuple[str, str]]): changed files.
    @param merge_base (str): the merge base commit.
    @return (dict[str, list[str]]): test file path to the changed titles in it.
    """
    out = {}
    for status, path in files:
        if status == "D" or not path.endswith(TS_TEST_SUFFIX):
            continue
        if path.endswith("conformance.test.ts"):
            continue
        source = read_worktree(path)
        if source is None:
            continue
        adds = set(added_lines(merge_base, path))
        lines = source.splitlines()
        markers = _ts_markers(lines)
        titles = []
        for idx, (lineno, kind, title) in enumerate(markers):
            if kind == "describe" or "${" in title:
                continue
            end = markers[idx + 1][0] - 1 if idx + 1 < len(markers) else len(lines)
            if any(lineno <= ln <= end for ln in adds):
                titles.append(title)
        if titles:
            out[path] = sorted(set(titles))
    return out


def _materialize_base(base_commit):
    """Extract the base tree into a temporary directory.

    @param base_commit (str): the base commit.
    @return (str): the path to the extracted tree.
    """
    dest = tempfile.mkdtemp(prefix="precheck-base-")
    git = subprocess.Popen(["git", "archive", "--format=tar", base_commit], cwd=REPO, stdout=subprocess.PIPE)
    tar = subprocess.Popen(["tar", "-x", "-C", dest], stdin=git.stdout)
    git.stdout.close()
    tar.communicate()
    git.wait()
    return dest


def _junit_passed(xml_path):
    """Read a junit xml file and return the names of tests that passed.

    @param xml_path (str): the junit report path.
    @return (set[str]): names of passing testcases.
    """
    passed = set()
    try:
        tree = ET.parse(xml_path)
    except (ET.ParseError, FileNotFoundError):
        return passed
    for case in tree.iter("testcase"):
        bad = any(case.find(tag) is not None for tag in ("failure", "error", "skipped"))
        if not bad:
            passed.add(case.get("name", ""))
    return passed


def _run_py_on_base(base_tree, nodes, python, env):
    """Run changed pytest node ids against the base source and report which pass.

    @param base_tree (str): the extracted base tree.
    @param nodes (list[tuple[str, str, str]]): (file, node_id, function) per test.
    @param python (str): the interpreter.
    @param env (dict): the subprocess environment.
    @return (list[str]): messages for tests that pass on main.
    """
    for path, _, _ in nodes:
        src = os.path.join(REPO, path)
        dst = os.path.join(base_tree, path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
    xml = os.path.join(base_tree, "precheck-py.xml")
    node_ids = [n for _, n, _ in nodes]
    subprocess.run(
        [
            python,
            "-m",
            "pytest",
            *node_ids,
            "-p",
            "no:cacheprovider",
            "-q",
            "--no-header",
            "-o",
            "addopts=",
            "--junitxml",
            xml,
        ],
        cwd=base_tree,
        env=env,
        capture_output=True,
        text=True,
    )
    passed = _junit_passed(xml)
    out = []
    for path, _node_id, fn in nodes:
        hits = [name for name in passed if name == fn or name.startswith(fn + "[")]
        if hits:
            out.append(_not_guarding(path, fn))
    return out


def _run_ts_on_base(base_tree, ts_tests, env):
    """Run changed vitest titles against the base source and report which pass.

    @param base_tree (str): the extracted base tree.
    @param ts_tests (dict[str, list[str]]): test file to its changed titles.
    @param env (dict): the subprocess environment.
    @return (list[str]): messages for tests that pass on main.
    """
    link = os.path.join(base_tree, "typescript", "node_modules")
    src_nm = os.path.join(REPO, "typescript", "node_modules")
    if not os.path.exists(link) and os.path.isdir(src_nm):
        os.symlink(src_nm, link)
    out = []
    for path, titles in ts_tests.items():
        shutil.copyfile(os.path.join(REPO, path), os.path.join(base_tree, path))
        xml = os.path.join(base_tree, "precheck-ts.xml")
        name_filter = "(" + "|".join(re.escape(t) for t in titles) + ")"
        subprocess.run(
            [
                "npx",
                "vitest",
                "run",
                os.path.relpath(path, "typescript"),
                "-t",
                name_filter,
                "--reporter=junit",
                "--outputFile",
                xml,
                "--no-color",
            ],
            cwd=os.path.join(base_tree, "typescript"),
            env=env,
            capture_output=True,
            text=True,
        )
        passed = _junit_passed(xml)
        for title in titles:
            if any(title in name for name in passed):
                out.append(_not_guarding(path, title))
    return out


def _line_of(path, needle):
    """Return the first line number in a file that mentions a name.

    @param path (str): the repo-relative path.
    @param needle (str): the function or title to find.
    @return (int): the 1-based line number, or 1 when not found.
    """
    source = read_worktree(path) or ""
    for i, line in enumerate(source.splitlines(), start=1):
        if needle in line:
            return i
    return 1


def _not_guarding(path, name):
    """Build the message for a changed test that passes on main.

    @param path (str): the test file path.
    @param name (str): the test function or title.
    @return (str): the file:line message.
    """
    return (
        f"{path}:{_line_of(path, name)}: test '{name}' passes on main, so it does not guard the fix; "
        "assert the new behaviour or stored state"
    )


def check_tests_on_main(files, base_commit, merge_base, python):
    """Run changed tests against the base source and flag those that pass, unless the PR has the tests-ok label.

    @param files (list[tuple[str, str]]): changed files.
    @param base_commit (str): the base commit.
    @param merge_base (str): the merge base commit.
    @param python (str): the interpreter for pytest.
    @return (tuple[str, list[str]]): the status and detail lines.
    """
    nodes = _changed_py_tests(files, merge_base)
    ts_tests = _changed_ts_tests(files, merge_base)
    if not nodes and not ts_tests:
        return "pass", ["no added or changed test cases to run"]
    base_tree = _materialize_base(base_commit)
    env = dict(os.environ)
    env["SELFGRAPH_TEST_STORE"] = "kuzu"
    env["SELFGRAPH_TEST_STORES"] = "kuzu"
    env["KUZU_PATH"] = os.path.join(base_tree, "precheck.kuzu")
    env.pop("SELFGRAPH_PY", None)
    messages = []
    notes = []
    try:
        if nodes:
            messages.extend(_run_py_on_base(base_tree, nodes, python, env))
        if ts_tests:
            if shutil.which("npx") and os.path.isdir(os.path.join(REPO, "typescript", "node_modules")):
                messages.extend(_run_ts_on_base(base_tree, ts_tests, env))
            else:
                notes.append("skipped TypeScript tests on main: npx or node_modules not available")
    finally:
        shutil.rmtree(base_tree, ignore_errors=True)
    if messages:
        if "tests-ok" in os.environ.get("PR_LABELS", "").split(","):
            return "warn", ["allowed for this PR (tests-ok)"] + messages + notes
        return "fail", messages + notes
    tested = [fn for _, _, fn in nodes] + [t for ts in ts_tests.values() for t in ts]
    return "pass", [f"all {len(tested)} changed tests fail or error on main, so they guard the fix"] + notes


def main(argv=None):
    """Run every precheck and print a report.

    @param argv (list[str] | None): command line arguments.
    @return (int): 0 when all checks pass, 1 otherwise.
    """
    parser = argparse.ArgumentParser(description="Review precheck for hydra-db/selfgraph.")
    parser.add_argument("--base", default="origin/main", help="base ref to compare against (default origin/main)")
    parser.add_argument("--python", default=sys.executable, help="interpreter used to run tests on main")
    parser.add_argument(
        "--skip", default="", help="comma separated checks to skip, e.g. tests,text,docstrings,conformance,size,merge"
    )  # noqa: E501
    args = parser.parse_args(argv)
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}

    base_commit, merge_base = resolve_base(args.base)
    files = [f for f in changed_files(merge_base) if f[1] not in (".gitignore",)]

    report = Report()

    if "text" not in skip:
        problems = check_text_rules(files, merge_base)
        report.add(
            "comments, em dashes, and BOMs",
            "fail" if problems else "pass",
            problems or ["no banned comments, em dashes, or BOMs on added lines"],
        )

    if "docstrings" not in skip:
        problems = check_docstrings(files, merge_base)
        report.add(
            "docstrings on new library functions",
            "fail" if problems else "pass",
            problems or ["every added or changed library function has a docblock"],
        )

    if "conformance" not in skip:
        status, lines = check_conformance(files, merge_base)
        report.add("conformance pair", status, lines)

    if "size" not in skip:
        status, lines = check_size(merge_base)
        report.add("size", status, lines)

    if "merge" not in skip:
        status, lines = check_merge(base_commit)
        report.add("merges into main", status, lines)

    if "tests" not in skip:
        status, lines = check_tests_on_main(files, base_commit, merge_base, args.python)
        report.add("tests fail on main", status, lines)

    report.add("scope (warning only)", "warn", [f"{status} {path}" for status, path in files])

    print(f"precheck: base {base_commit[:12]}, merge-base {merge_base[:12]}, {len(files)} changed files\n")
    mark = {"pass": "ok  ", "warn": "warn", "fail": "FAIL"}
    for name, status, lines in report.sections:
        print(f"[{mark[status]}] {name}")
        for line in lines:
            print(f"       {line}")
        print()
    if report.failed():
        print("precheck: FAIL. Fix the items above, then run it again.")
        return 1
    print("precheck: all checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
