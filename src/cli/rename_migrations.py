import datetime
import os

from alembic.config import Config
from alembic.script import Script, ScriptDirectory
from slugify import slugify

from core import settings

MIGRATIONS_DIR = settings.PROJECT_ROOT_DIR / "migrations/versions/"


def get_history_migrations_scripts() -> list[Script]:
    # from unit_test.migrations.utils import get_revision_scripts
    # TODO: implement getting revisions get_revision_scripts:
    # MigrationScript.upgrade_ops_list
    # revision_scripts = []
    config = Config(settings.PROJECT_ROOT_DIR / "alembic.ini")
    script = ScriptDirectory.from_config(config)
    scripts = []
    for sc in script.walk_revisions(base="base", head="heads"):
        scripts.insert(0, sc)

    return scripts
    # return [script for script in revision_scripts]


def parse(file_content: str, token: str) -> str:
    index = file_content.index(token) + len(token)
    res = ""
    for ch in file_content[index:]:
        if ord(ch) == 10:
            break
        res += ch
    return res


def rename2(need_file_rename=True):
    migration_scripts = get_history_migrations_scripts()
    res = {}
    for file_number, migration_script in enumerate(migration_scripts, start=1):
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

            rev_id = migration_script.revision
            revision_in_docstring = parse(migration_script.longdoc, "Revision ID: ")
            assert (
                rev_id == revision_in_docstring
            ), f"Asser for rev_id failed: {rev_id} != {revision_in_docstring}"
            old_rev_id = f"_{rev_id}" if rev_id != f"{file_number:04d}" else ""
            new_filename = f"{file_number:04d}_{mess}{old_rev_id}.py"

        old_filepath = settings.PROJECT_ROOT_DIR / migration_script.module.__file__
        old_filename = os.path.basename(old_filepath)
        if need_file_rename:
            new_filepath = os.path.join(MIGRATIONS_DIR, new_filename)
            if str(old_filepath) == str(new_filepath):
                print(f"\t*** SKIP {new_filepath} *** ")
            else:
                print(f"Rename migration: {old_filename} -> {new_filename}")
                os.system(f"git mv {old_filepath} {new_filepath}")

        res[old_filename] = new_filename

    return res


if __name__ == "__main__":
    # for s in get_history_migrations_scripts():
    #     print(s)
    rename2()
