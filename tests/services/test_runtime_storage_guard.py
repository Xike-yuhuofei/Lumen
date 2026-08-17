from __future__ import annotations

from pathlib import Path

from deeptutor.services.config.loader import load_config_with_main


def test_runtime_config_paths_are_confined_to_data_user() -> None:
    config = load_config_with_main("main.yaml")
    paths = config.get("paths", {})
    user_root = Path(config["paths"]["user_data_dir"]).resolve()

    assert user_root.name == "user"
    assert Path(paths["question_output_dir"]).resolve().is_relative_to(user_root)
    assert Path(paths["user_log_dir"]).resolve() == user_root / "logs"
    assert Path(config["tools"]["run_code"]["workspace"]).resolve().is_relative_to(user_root)
