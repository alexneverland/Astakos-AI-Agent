# ================================================================
# Project: Astakos AI Agent 🦞
# Skill:   repo_mapper — Repo Architecture Scanner
# Scans project folder, returns tree + AST analysis
# ================================================================
import os
import ast
import json
from langchain_core.tools import tool
from core.i18n import t

# ── Ignored folders/files ────────────────────────────────────
_SKIP_DIRS = {
    "venv", ".venv", "__pycache__", ".git", ".pytest_tmp", ".pytest_cache",
    "node_modules", "dist", "build", ".tox", ".mypy_cache", "migrations",
    "chroma_db", "telegram_photos", "telegram_uploads", "outputs", "avatars",
    "watch_folder", ".ruff_cache", "eggs", ".eggs",
}
_SKIP_EXTS = {".pyc", ".pyo", ".pyd", ".so", ".dll", ".db", ".sqlite3",
              ".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".xlsx",
              ".xls", ".docx", ".mp3", ".mp4", ".wav", ".bin", ".lock"}

# ── Decorator patterns that we recognize ─────────────────────
_KNOWN_DECORATORS = {
    "tool":             "🔧 LangChain Tool",
    "app.get":          "🌐 GET Route",
    "app.post":         "🌐 POST Route",
    "server.get":       "🌐 GET Route",
    "server.post":      "🌐 POST Route",
    "server.delete":    "🌐 DELETE Route",
    "server.patch":     "🌐 PATCH Route",
    "router.get":       "🌐 GET Route",
    "router.post":      "🌐 POST Route",
    "property":         "📎 Property",
    "staticmethod":     "📎 Static",
    "classmethod":      "📎 Class Method",
}

# ── Base classes that we classify ──────────────────────────────
_CLASS_BASES = {
    "Model":       "🗄️  Django Model",
    "BaseModel":   "📐 Pydantic Model",
    "Enum":        "🔢 Enum",
    "Exception":   "⚠️  Exception",
    "TypedDict":   "📝 TypedDict",
}


def _get_decorator_label(dec_node) -> str:
    """Returns a label for a decorator node."""
    if isinstance(dec_node, ast.Name):
        name = dec_node.id
    elif isinstance(dec_node, ast.Attribute):
        name = f"{_unparse_attr(dec_node)}"
    elif isinstance(dec_node, ast.Call):
        return _get_decorator_label(dec_node.func)
    else:
        return ""
    return _KNOWN_DECORATORS.get(name, f"@{name}")


def _unparse_attr(node) -> str:
    if isinstance(node, ast.Attribute):
        return f"{_unparse_attr(node.value)}.{node.attr}"
    elif isinstance(node, ast.Name):
        return node.id
    return "?"


def _class_label(bases) -> str:
    for base in bases:
        name = _unparse_attr(base) if isinstance(base, (ast.Attribute, ast.Name)) else ""
        for key, label in _CLASS_BASES.items():
            if key in name:
                return label
    return "📦 Class"


def _analyze_file(filepath: str) -> dict:
    """AST shallow analysis of a .py file."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            src = f.read()
        tree = ast.parse(src, filename=filepath)
    except SyntaxError as e:
        return {"error": f"SyntaxError L{e.lineno}: {e.msg}"}
    except Exception as e:
        return {"error": str(e)}

    classes = []
    functions = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            label = _class_label(node.bases)
            methods = [
                n.name for n in ast.iter_child_nodes(node)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            classes.append({
                "name":    node.name,
                "label":   label,
                "line":    node.lineno,
                "methods": methods,
            })

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            dec_labels = [_get_decorator_label(d) for d in node.decorator_list]
            dec_labels = [d for d in dec_labels if d]
            functions.append({
                "name":       node.name,
                "line":       node.lineno,
                "async":      isinstance(node, ast.AsyncFunctionDef),
                "decorators": dec_labels,
            })

    return {"classes": classes, "functions": functions}


def _scan_dir(root: str, max_depth: int, current_depth: int = 0) -> dict:
    """Recursive directory scan — returns a nested dict."""
    result = {"files": [], "dirs": {}}
    if current_depth >= max_depth:
        return result
    try:
        entries = sorted(os.scandir(root), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        return result

    for entry in entries:
        if entry.name.startswith(".") and entry.name not in (".env",):
            continue
        if entry.is_dir(follow_symlinks=False):
            if entry.name in _SKIP_DIRS:
                continue
            result["dirs"][entry.name] = _scan_dir(entry.path, max_depth, current_depth + 1)
        elif entry.is_file():
            ext = os.path.splitext(entry.name)[1].lower()
            if ext in _SKIP_EXTS:
                continue
            file_info = {"name": entry.name, "ext": ext}
            if ext == ".py":
                file_info["ast"] = _analyze_file(entry.path)
            result["files"].append(file_info)

    return result


def _render_tree(node: dict, prefix: str = "", name: str = "") -> list[str]:
    """Converts the dict tree into lines of text."""
    lines = []
    if name:
        lines.append(f"{prefix}📁 {name}/")
        child_prefix = prefix + "  "
    else:
        child_prefix = prefix

    # Files
    files = node.get("files", [])
    dirs  = node.get("dirs", {})
    all_items = len(files) + len(dirs)
    for i, f in enumerate(files):
        is_last = (i == len(files) - 1) and not dirs
        connector = "└─" if is_last else "├─"
        icon = "🐍" if f["ext"] == ".py" else "📄"
        lines.append(f"{child_prefix}{connector} {icon} {f['name']}")
        ast_data = f.get("ast", {})
        if ast_data.get("error"):
            lines.append(f"{child_prefix}   ⚠️  {ast_data['error']}")
            continue
        for cls in ast_data.get("classes", []):
            meth_str = f"  [{', '.join(cls['methods'][:6])}{'...' if len(cls['methods'])>6 else ''}]" if cls['methods'] else ""
            lines.append(f"{child_prefix}   {cls['label']} {cls['name']} (L{cls['line']}){meth_str}")
        for fn in ast_data.get("functions", []):
            prefix_sym = "⚡" if fn["async"] else "⚙️ "
            dec_str = " ".join(fn["decorators"])
            lines.append(f"{child_prefix}   {prefix_sym} {fn['name']}() L{fn['line']} {dec_str}".rstrip())

    # Subdirectories
    dir_items = list(dirs.items())
    for i, (dname, dnode) in enumerate(dir_items):
        lines.extend(_render_tree(dnode, child_prefix, dname))

    return lines


@tool
def repo_mapper(folder_path: str, max_depth: int = 4) -> str:
    """
    Scans a project folder and returns:
    - Text tree representing the file structure
    - AST shallow analysis: classes, top-level functions, decorators
    Useful for quick debugging without reading file by file.

    folder_path: The project folder (e.g., C:\\astakos_v2 or C:\\astakos_v2\\core)
    max_depth: Search depth (default 4, max 6)
    """
    folder_path = folder_path.strip().strip("'\"")
    max_depth   = max(1, min(int(max_depth), 6))

    if not os.path.isdir(folder_path):
        return t("skills.repo_mapper.msg_folder_missing", path=folder_path)

    abs_path = os.path.realpath(folder_path)
    folder_name = os.path.basename(abs_path) or abs_path

    tree = _scan_dir(abs_path, max_depth)

    # ── Text output ─────────────────────────────────────────
    lines = [f"🗂️  Repo Map: {folder_name}/ (depth={max_depth})", ""]
    lines.extend(_render_tree(tree, "", folder_name))

    # ── Stats ────────────────────────────────────────────────
    def count_files(node):
        total = len(node.get("files", []))
        for d in node.get("dirs", {}).values():
            total += count_files(d)
        return total

    def count_py(node):
        total = sum(1 for f in node.get("files", []) if f["ext"] == ".py")
        for d in node.get("dirs", {}).values():
            total += count_py(d)
        return total

    total_f = count_files(tree)
    total_py = count_py(tree)
    lines.append("")
    lines.append(t("skills.repo_mapper.msg_stats", f=total_f, py=total_py, d=max_depth))

    # ── JSON summary (compact) ───────────────────────────────
    def _compact_json(node):
        result = {}
        for f in node.get("files", []):
            if f["ext"] != ".py":
                continue
            ast_d = f.get("ast", {})
            if ast_d.get("error"):
                continue
            classes   = [c["name"] for c in ast_d.get("classes", [])]
            functions = [fn["name"] for fn in ast_d.get("functions", [])]
            if classes or functions:
                result[f["name"]] = {
                    "classes": classes,
                    "functions": functions,
                }
        for dname, dnode in node.get("dirs", {}).items():
            sub = _compact_json(dnode)
            if sub:
                result[dname + "/"] = sub
        return result

    json_summary = _compact_json(tree)
    json_str = json.dumps(json_summary, ensure_ascii=False, indent=2)

    output = "\n".join(lines)
    output += f"\n\n```json\n{json_str}\n```"

    # Limit to avoid overwhelming the context
    if len(output) > 18000:
        output = output[:18000] + t("skills.repo_mapper.msg_truncated_2")

    return output


if __name__ == "__main__":
    import sys
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    depth  = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    print(repo_mapper.func(folder, depth))
