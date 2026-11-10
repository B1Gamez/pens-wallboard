#!/bin/sh
# Pull the latest "main" from GitHub and restart the wallboard if anything changed.
# Run by pens-wallboard-update.timer every few minutes. If the new version won't
# start, it rolls back to the last working one.
set -e
cd "$(dirname "$0")/.."

git fetch --quiet origin main
OLD=$(git rev-parse HEAD)
NEW=$(git rev-parse origin/main)
[ "$OLD" = "$NEW" ] && exit 0

OLD_REQ=$(git show HEAD:requirements.txt 2>/dev/null | sha1sum)
git reset --hard --quiet origin/main
NEW_REQ=$(sha1sum < requirements.txt)
if [ "$OLD_REQ" != "$NEW_REQ" ]; then
    echo "requirements.txt changed, installing packages"
    venv/bin/pip install --quiet -r requirements.txt
fi

echo "Updating $(echo "$OLD" | cut -c1-7) -> $(echo "$NEW" | cut -c1-7): $(git log -1 --format=%s)"
sudo -n /usr/bin/systemctl restart pens-wallboard
sleep 8
if ! systemctl is-active --quiet pens-wallboard; then
    echo "New version failed to start, rolling back to $(echo "$OLD" | cut -c1-7)"
    git reset --hard --quiet "$OLD"
    sudo -n /usr/bin/systemctl restart pens-wallboard
    exit 1
fi
echo "Update finished"
