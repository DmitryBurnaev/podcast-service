# /bin/sh

set -e


replace_ver(){
  local lib=$1; shift
  local old_v=$1; shift
  local new_v=$1
  local python_script="
old_string = '$lib = \"==${old_v}\"';
new_string = '$lib = \"==${new_v}\"';
print(f' py replacing: {old_string} -> {new_string}');
with open('Pipfile', 'rt') as f:
    pipfile_content = f.read();
pipfile_content = pipfile_content.replace(old_string, new_string);
with open('Pipfile', 'wt') as f:
    f.write(pipfile_content);
print(' py replaced $lib for file Pipfile')
"
  python -c "$python_script"
}

bump_version(){
# set new lib name version
  local package_name=$1; shift;
  local new_version=$1;

  echo "package_name=${package_name}"
  echo "new_version=${new_version}"

  local new_branch="bump-${package_name}"
  local current_branch="$(git --no-pager branch --show-current)"

  git stash -m "stashed for bump ${package_name}"
  git checkout master
  echo "pulling master..."
  git pull
  git checkout -b "${new_branch}"

  local old_version=$(pip freeze | sed -n '/yt-dlp==/s///p')
  echo "detected old version ${old_version}"

  # Create a backup of the Pipfile
  cp Pipfile Pipfile.bak

  # Use sed to replace the string in the Pipfile
  echo "replacing '$package_name': '$old_version' -> '$new_version'"
  replace_ver "$package_name" "$old_version" "$new_version"

  # Check if the replacement was successful
  if grep -q "$package_name = \"==$new_version\"" Pipfile; then
      echo "Replacement successful!"
    rm Pipfile.bak
  else
      echo "Replacement failed. Restoring from backup..."
      mv Pipfile.bak Pipfile
    git checkout "${current_branch}"
    exit 1
  fi

  pipenv update
  git add Pipfile
  git add Pipfile.lock
  echo "Changed finished"
  git commit -m "Bumped ${package_name}: $old_version -> $new_version"
  git push
  echo "Changed pushed to GIT"
  echo "rolling back branch..."
  git checkout "${current_branch}"
  echo "git checked-out..."
}


bump_version $@
