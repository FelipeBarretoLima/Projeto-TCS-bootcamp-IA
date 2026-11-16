#!/bin/sh
# Container start: puts the Secret Files where the API expects them and starts uvicorn.
# Render mounts them in /etc/secrets (read-only); SECRETS_DIR exists only to test this script.
set -eu
SECRETS="${SECRETS_DIR:-/etc/secrets}"
cd "$(dirname "$0")/../.."
mkdir -p data/private ml/modelos ml/dados

# the model goes as base64 text (the Render dashboard takes text); decoded again on every start
if [ -f "$SECRETS/svm_tfidf.pkl.b64" ]; then
  base64 -d "$SECRETS/svm_tfidf.pkl.b64" > ml/modelos/svm_tfidf.pkl
else
  echo "aviso: svm_tfidf.pkl.b64 ausente: as saídas ficam sem categoria" >&2
fi

# the merchant maps (people marked by the user, used to anonymize); the API only reads these two
for f in estabelecimentos_revisar.csv estabelecimentos_novos.csv; do
  if [ -f "$SECRETS/$f" ]; then
    cp "$SECRETS/$f" data/private/
  else
    echo "aviso: $f ausente: as pessoas marcadas nesse mapa não são anonimizadas" >&2
  fi
done

# base CSV of the retraining (optional: without it the retraining records an error and nothing else changes)
if [ -f "$SECRETS/transacoes_rotuladas.csv" ]; then
  cp "$SECRETS/transacoes_rotuladas.csv" ml/dados/
fi

# a single process: the per-user rate limit and the retraining lock live in the API memory
exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-10000}" --proxy-headers --forwarded-allow-ips="*"
