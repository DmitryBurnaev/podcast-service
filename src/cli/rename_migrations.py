import datetime
import os

from alembic.config import Config
from alembic.script import Script, ScriptDirectory
from slugify import slugify  # pip install python-slugify==6.1.2

from core import settings

MIGRATIONS_DIR = settings.PROJECT_ROOT_DIR / "alembic/versions/"


def get_history_migrations_scripts() -> list[Script]:
    config = Config(settings.PROJECT_ROOT_DIR / "alembic.ini")
    script = ScriptDirectory.from_config(config)
    scripts = []
    for sc in script.walk_revisions(base="base", head="heads"):
        scripts.insert(0, sc)

    return scripts


def parse(file_content: str, token: str) -> str:
    index = file_content.index(token) + len(token)
    res = ""
    for ch in file_content[index:]:
        if ord(ch) == 10:
            break
        res += ch
    return res


def rename():
    migration_scripts = get_history_migrations_scripts()
    res = {}
    prev_alembic_rev_id, prev_new_rev_id = None, None
    for file_number, migration_script in enumerate(migration_scripts, start=1):
        print(f"\n = Revision #{migration_script.revision}: {migration_script.module.__file__} = ")
        alembic_rev_id = migration_script.revision
        new_rev_id = f"{file_number:04d}"

        if file_number == 1:
            new_filename = "0001_init.py"
        else:
            mess = slugify(migration_script.doc, separator="_")
            if mess == "empty_message":
                migration_time = datetime.datetime.strptime(
                    parse(migration_script.longdoc, "Create Date: ").replace(
                        "+00:00", ""
                    ),
                    "%Y-%m-%d %H:%M:%S.%f",
                )
                mess = migration_time.strftime("%Y%m%d_%H%M")

            revision_in_docstring = parse(migration_script.longdoc, "Revision ID: ")
            assert (
                alembic_rev_id == revision_in_docstring
            ), f"Asser for rev_id failed: {alembic_rev_id} != {revision_in_docstring}"
            new_filename = f"{new_rev_id}_{mess}.py"

        old_filepath = settings.PROJECT_ROOT_DIR / migration_script.module.__file__
        old_filename = os.path.basename(old_filepath)
        new_filepath = os.path.join(MIGRATIONS_DIR, new_filename)

        # ===
        # change revision IDs inside migration's files (ex.: 24c9e468369c -> 0002)
        # ===
        print(f"   Change migration: {old_filename} -> {new_filename}")

        sed_1 = f"sed -i '' 's/{alembic_rev_id}/{new_rev_id}/g' {old_filepath}"
        print(f"   - {sed_1}")
        os.system(sed_1)
        if prev_alembic_rev_id:
            sed_2 = f"sed -i '' 's/{prev_alembic_rev_id}/{prev_new_rev_id}/g' {old_filepath}"
            print(f"   - {sed_2}")
            os.system(sed_2)

        # ===
        # file-rename logic (using git mv allows to save git history)
        # ===
        if str(old_filepath) == str(new_filepath):
            print(f"\t*** SKIP {new_filepath} *** ")
        else:
            # print(f"Rename migration: {old_filename} -> {new_filename}")
            print(f"   Rename: {old_filepath} -> {new_filepath}")
            os.system(f"git mv {old_filepath} {new_filepath}")

        # ===

        res[old_filename] = new_filename
        prev_alembic_rev_id = alembic_rev_id
        prev_new_rev_id = new_rev_id

    return res


if __name__ == "__main__":
    print("=== BEFORE ===")
    for s in get_history_migrations_scripts():
        print(s)

    rename()

    print("=== AFTER ===")
    for s in get_history_migrations_scripts():
        print(s)
