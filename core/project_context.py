"""Bounded project discovery: file names and manifest signals, never executable project hooks."""
import os
from pathlib import Path
from core.project_files import ENGINE_ROOT_CACHES

SKIP_DIRS = {".git", ".director_worktrees", ".venv", "venv", "env", "node_modules", "__pycache__",
             ".next", ".nuxt", ".cache", ".pytest_cache", "dist", "build", "coverage", "target",
             "secrets", "credentials", ".godot"}
MANIFESTS = {"pyproject.toml": "Python", "requirements.txt": "Python", "package.json": "JavaScript/TypeScript",
             "tsconfig.json": "TypeScript", "Cargo.toml": "Rust", "go.mod": "Go", "pom.xml": "Java",
             "project.godot": "Godot", "ProjectSettings/ProjectVersion.txt": "Unity",
             "build.gradle": "Java/Kotlin", "composer.json": "PHP", "Gemfile": "Ruby"}
PRIORITY = {"src": 0, "app": 1, "lib": 2, "tests": 3, "test": 4, "docs": 5}
VISIBLE_DOT_DIRS = {".github", ".vscode", ".devcontainer"}
VISIBLE_DOT_FILES = {".gitignore", ".gitattributes", ".editorconfig", ".prettierrc", ".eslintrc"}


def collect_project_context(project_path, max_files=100, max_directories=120, max_entries=3000):
    root = Path(project_path).resolve()
    files, scanned, directories, skipped = [], 0, 0, 0
    truncated = False
    pending = [root]
    while pending:
        if directories >= max_directories:
            truncated = True
            break
        directory = pending.pop()
        directories += 1
        keep, names = [], []
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    scanned += 1
                    if scanned > max_entries:
                        truncated = True
                        break
                    if entry.is_symlink():
                        skipped += 1
                    elif entry.is_dir(follow_symlinks=False):
                        if entry.name in SKIP_DIRS or (directory == root and entry.name.lower() in ENGINE_ROOT_CACHES) or (entry.name.startswith('.') and entry.name not in VISIBLE_DOT_DIRS):
                            skipped += 1
                        else:
                            keep.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        names.append(entry.name)
        except OSError:
            skipped += 1
            continue
        names.sort(key=lambda n: (0 if n in MANIFESTS or n in {"README.md", "AGENTS.md"} else 1, n))
        for name in names:
            path = Path(directory) / name
            if (name.startswith('.') and name not in VISIBLE_DOT_FILES) or path.suffix.lower() in {'.pyc', '.db', '.sqlite3', '.log', '.key', '.pem', '.pfx'}:
                continue
            files.append(path.relative_to(root).as_posix())
            if len(files) >= max_files:
                truncated = True
                break
        if truncated:
            break
        pending.extend(sorted(keep, key=lambda p: (PRIORITY.get(p.name, 9), p.name), reverse=True))
    stack = sorted({language for name, language in MANIFESTS.items() if (root / name).is_file() and not (root / name).is_symlink()})
    return {"project_path": str(root), "existing_files": files,
            "project_discovery": {"stack": stack, "listed_files": len(files), "directories_scanned": min(directories, max_directories),
                                  "skipped_directories": skipped, "truncated": truncated}}
