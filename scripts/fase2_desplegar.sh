#!/usr/bin/env bash
# FASE 2 — Ingesta por eventos.
# Sube el código de las Lambdas al lago (SSE-S3, para que Lambda pueda leerlo
# aunque el bucket cifre por defecto con la CMK) y despliega el stack cn-eq01-ingesta.
# Requiere el stack cn-eq01-base ya creado.
# Uso en CloudShell:  bash scripts/fase2_desplegar.sh
set -euo pipefail
cd "$(dirname "$0")/.."
REGION="${AWS_REGION:-us-east-2}"
BASE="cn-eq01-base"
STACK="cn-eq01-ingesta"

if [[ "$REGION" != "us-east-2" ]]; then
  echo "Esta solución solo se despliega en us-east-2 (región del proyecto). Región actual: $REGION"
  exit 1
fi

echo "1/3 Comprobando el stack base $BASE ..."
BUCKET=$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$BASE" \
  --query "Stacks[0].Outputs[?OutputKey=='BucketLago'].OutputValue" --output text)
if [[ -z "$BUCKET" || "$BUCKET" == "None" ]]; then
  echo "No está el lago. Corre antes: bash scripts/fase1_desplegar.sh"
  exit 1
fi
echo "   Bucket: $BUCKET"

hash_zip() {
  python3 -c 'import hashlib,pathlib,sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()[:12])' "$1"
}

echo "2/3 Empaquetando Lambdas y subiéndolas con SSE-S3 ..."
rm -f /tmp/cn-eq01-api.zip /tmp/cn-eq01-expediente.zip /tmp/cn-eq01-leer-cfdi.zip
(cd src/api && zip -q -X /tmp/cn-eq01-api.zip app.py)
(cd src/expediente && zip -q -X /tmp/cn-eq01-expediente.zip app.py)
(cd src/leer_cfdi && zip -q -X /tmp/cn-eq01-leer-cfdi.zip app.py)
H_API=$(hash_zip /tmp/cn-eq01-api.zip)
H_EXP=$(hash_zip /tmp/cn-eq01-expediente.zip)
H_CFDI=$(hash_zip /tmp/cn-eq01-leer-cfdi.zip)
aws s3 cp /tmp/cn-eq01-api.zip "s3://$BUCKET/despliegue/fase2/api-${H_API}.zip" \
  --region "$REGION" --sse AES256 --only-show-errors
aws s3 cp /tmp/cn-eq01-expediente.zip "s3://$BUCKET/despliegue/fase2/expediente-${H_EXP}.zip" \
  --region "$REGION" --sse AES256 --only-show-errors
aws s3 cp /tmp/cn-eq01-leer-cfdi.zip "s3://$BUCKET/despliegue/fase2/leer-cfdi-${H_CFDI}.zip" \
  --region "$REGION" --sse AES256 --only-show-errors
echo "   Hashes: api=$H_API expediente=$H_EXP leer_cfdi=$H_CFDI"

echo "3/3 Desplegando $STACK (tarda 3-6 min) ..."
aws cloudformation deploy --region "$REGION" --stack-name "$STACK" \
  --template-file infra/fase2-ingesta.yaml --capabilities CAPABILITY_IAM \
  --no-fail-on-empty-changeset \
  --parameter-overrides Proyecto=cn-eq01 "HashApi=$H_API" "HashExpediente=$H_EXP" "HashLeerCfdi=$H_CFDI" \
  --tags proyecto=cn-eq01 entrega=E2_EQ01

echo
echo "Stack $STACK listo. Siguiente paso: bash scripts/fase2_probar.sh"
aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query "Stacks[0].Outputs[].[OutputKey,OutputValue]" --output table
