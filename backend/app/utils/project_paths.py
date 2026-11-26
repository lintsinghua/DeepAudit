from pathlib import Path


def resolve_project_path(project_root: str, path: str) -> str:
    """Resolve a host path and require its real destination to be inside the project."""
    root = Path(project_root).resolve()
    try:
        target = (root / path).resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError("无法解析项目文件路径") from exc
    if not target.is_relative_to(root):
        raise ValueError("安全错误：不允许访问项目目录外的路径")
    return str(target)
