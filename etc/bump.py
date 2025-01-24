import argparse
from pathlib import Path

import git

pipfile = "Pipfile"
repo_dir = "."
default_branch = "master"


def find_version_in_file(lib_name: str) -> str | None:
    """Detects library in current Pipfile and returns version"""
    file_path = Path(pipfile)
    contents = file_path.read_text()
    for line in contents.splitlines():
        if line.startswith(lib_name):
            return line.split("=")[1].strip()

    return None


def replace_version_in_file(lib_name: str, old_version: str, new_version: str) -> None:
    file_path = Path(pipfile)
    contents = file_path.read_text()
    result_contents: list[str] = []

    for line in contents.splitlines():
        if line.startswith(lib_name):
            line = line.replace(old_version, new_version)
        result_contents.append(line)

    file_path.write_text("\n".join(result_contents))
    return None


def create_tmp_git_branch(branch_name: str) -> None:
    repo = git.Repo.init(repo_dir)
    past_branch = repo.create_head(branch_name, default_branch)
    print(past_branch)
    # git_dir.mkdir(exist_ok=True)
    # git_dir


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lib_name", required=True, type=str)
    parser.add_argument("--old_version", required=True, type=str)
    parser.add_argument("--new_version", required=True, type=str)
    args = parser.parse_args()
    lib_name = args.lib_name
    old_version = args.old_version
    new_version = args.new_version
    replace_version_in_file(lib_name, old_version, new_version)
    create_tmp_git_branch(args.lib_name)
    return None


if __name__ == "__main__":
    main()
