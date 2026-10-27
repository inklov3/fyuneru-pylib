from pathlib import Path


def load_lua_scripts() -> dict[str, str]:
    script_dir = Path(__file__).resolve().with_name("lua")
    scripts: dict[str, str] = {}
    for script_path in sorted(script_dir.glob("*.lua")):
        scripts[script_path.stem] = script_path.read_text(encoding="utf-8")
    return scripts
