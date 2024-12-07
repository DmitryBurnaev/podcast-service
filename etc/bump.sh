# /bin/sh

set -e


# set new lib name version
package_name=$1; shift;
new_version=$1;

echo "package_name=${package_name}"
echo "new_version=${new_version}"

tmp_branch_name="bump-${package_name}"
current_branch_name="$(git --no-pager branch --show-current)"

#git stash -m "stashed for bump ${package_name}"
git checkout master
git pull
git checkout -b "${tmp_branch_name}"

old_version=$(pip freeze | sed -n '/yt-dlp==/s///p')
echo "Detected old version ${old_version} "

# Create a backup of the Pipfile
cp Pipfile Pipfile.bak

# Use sed to replace the string in the Pipfile
sed -i "s/$package_name = \"==$old_version\"/$package_name = \"==$new_version\"/g" Pipfile

# Check if the replacement was successful
if grep -q "$package_name = \"==$new_version\"" Pipfile; then
    echo "Replacement successful!"
  rm Pipfile.bak
else
    echo "Replacement failed. Restoring from backup..."
    mv Pipfile.bak Pipfile
  git checkout "${current_branch_name}"
  exit 1
fi

pipenv update
git add Pipfile
git add Pipfile.lock
echo "Changed finished"
git commit -m "Bumped ${package_name}: $old_version -> $new_version"
#git push
echo "Changed pushed to GIT"
echo "rolling back brach..."
#git checkout "${current_branch_name}"
echo "git checked-out..."
