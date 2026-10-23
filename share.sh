#!/bin/bash
# Shares your wardrobe through your ngrok link. Keep this window open; Ctrl-C stops sharing.
cd "$(dirname "$0")" || exit 1
source .venv/bin/activate

[ -f .share-password ] || openssl rand -base64 9 | tr -d '/+=' | cut -c1-8 > .share-password
export WARDROBE_INVITE_CODE="$(cat .share-password)"   # people need this code to create an account
[ -f .secret-key ] || python3 -c "import secrets; print(secrets.token_urlsafe(50))" > .secret-key
export WARDROBE_SECRET_KEY="$(cat .secret-key)"
export WARDROBE_DEBUG=0

python manage.py migrate --noinput >/dev/null
python manage.py runserver --insecure --noreload 127.0.0.1:8000 >server.log 2>&1 &
SERVER=$!
caffeinate -dis &   # stops the Mac sleeping while sharing
SLEEP=$!
ngrok http 8000 --log=stdout >ngrok.log 2>&1 &
NGROK=$!
trap 'kill $SERVER $SLEEP $NGROK 2>/dev/null' EXIT

for _ in $(seq 1 20); do   # ask ngrok which public address it gave us
  URL=$(curl -s localhost:4040/api/tunnels | python3 -c "import sys,json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])" 2>/dev/null)
  [ -n "$URL" ] && break
  sleep 1
done
echo
echo "Link for your friend:  ${URL:-not ready, see ngrok.log}"
echo "Invite code:           $WARDROBE_INVITE_CODE   (needed once, when creating an account)"
echo
echo "Sharing. Press Ctrl-C to stop."
wait $NGROK
