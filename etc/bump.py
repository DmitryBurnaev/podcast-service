import toml
import subprocess
from git import Repo, GitCommandError

pipfile = "Pipfile"
repo_dir = "."
default_branch = "master"


def update_packages(packages: dict[str, str], repo: Repo, branch_name: str) -> None:
    # Read Pipfile
    with open("Pipfile", "r") as file:
        pipfile_content = toml.load(file)

    updated_packages = []

    for package_name, package_version in packages.items():
        # Check if the package exists in Pipfile
        if "packages" in pipfile_content and package_name in pipfile_content["packages"]:
            # Install the specific version of the package
            subprocess.run(["pipenv", "install", f"{package_name}{package_version}"], check=True)
            updated_packages.append(f"{package_name} -> {package_version}")
            print(f"Package {package_name} successfully updated to version {package_version}.")
        else:
            print(f"Package {package_name} not found in Pipfile.")

    if not updated_packages:
        print("No packages to update.")
        return

    # Add changes to the index
    repo.git.add("Pipfile")
    repo.git.add("Pipfile.lock")  # Pipfile.lock is also updated when packages are updated

    # Create a commit
    bump_packages_msg = "\n- ".join(updated_packages)
    commit_message = f"Bumped libraries: \n{bump_packages_msg}"
    repo.index.commit(commit_message)

    # Push changes to the remote repository
    origin = repo.remote(name="origin")
    origin.push(branch_name, set_upstream=True)
    print(f"Changes pushed to branch {branch_name}.")


def delete_branch(repo, branch_name):
    """Delete a branch locally and remotely if it exists."""
    # Delete local branch
    if branch_name in repo.heads:
        print(f"Deleting local branch {branch_name}...")
        repo.git.branch("-D", branch_name)  # Force delete the local branch

    # Delete remote branch
    origin = repo.remote(name="origin")
    try:
        print(f"Deleting remote branch {branch_name}...")
        origin.push(refspec=f":{branch_name}")  # Push an empty refspec to delete the remote branch
    except GitCommandError as e:
        print(f"Remote branch {branch_name} does not exist or could not be deleted: {e}")


def create_git_branch(packages: dict[str, str], repo: Repo) -> str:
    updated_packages = "-".join(packages.keys())
    branch_name = f"update-{'-'.join(updated_packages)}"
    delete_branch(repo, branch_name)
    new_branch = repo.create_head(branch_name)
    new_branch.checkout()
    return new_branch.name


def main():
    # User input for packages
    packages = {}
    while True:
        input_question = (
            "Enter the package name and version (e.g. yt-dlp==2025.1.15) or press Enter to finish: "
        )
        package_name_version = input(input_question).strip()
        if not package_name_version:
            break

        package_name, package_version = package_name_version.split("==")
        packages[package_name] = package_version

    if not packages:
        print("No packages specified for update.")
        return

    repo = Repo(".")
    git_branch = create_git_branch(packages, repo)
    update_packages(packages, repo, git_branch)


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
