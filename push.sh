#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# Um commit por vez (rede/proxy bloqueia pacote grande)
for sha in $(git log --reverse --format=%H origin/main..HEAD); do
  msg=$(git log --oneline -1 "$sha")
  echo "--- enviando: $msg ---"
  git -c http.postBuffer=524288000 -c http.version=HTTP/1.1 push origin "$sha:main"
  sleep 1
done

echo "Pronto."
