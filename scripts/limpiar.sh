#!/usr/bin/env bash
# LIMPIEZA — Borra todo lo que crearon las fases 1 a 5, después de la calificación.
# Orden: cn-eq01-roles -> cn-eq01-curado -> cn-eq01-ingesta -> vaciar el bucket del lago -> cn-eq01-base.
# El bucket tiene versionado, así que se borran también las versiones anteriores.
# La llave KMS queda 7 días en borrado programado (se puede cancelar en ese plazo).
# Uso:  bash scripts/limpiar.sh
set -euo pipefail
REGION="${AWS_REGION:-us-east-2}"
BASE="cn-eq01-base"
INGESTA="cn-eq01-ingesta"
CURADO="cn-eq01-curado"
ROLES="cn-eq01-roles"

if [[ "$REGION" != "us-east-2" ]]; then
  echo "Esta solución solo se despliega en us-east-2. Región actual: $REGION"
  exit 1
fi

BUCKET=$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$BASE" \
  --query "Stacks[0].Outputs[?OutputKey=='BucketLago'].OutputValue" --output text 2>/dev/null || true)

echo "Se borrarán los stacks $ROLES, $CURADO, $INGESTA y $BASE en $REGION"
echo "y todo el contenido del bucket ${BUCKET:-(no encontrado)}, incluidas sus versiones."
read -r -p "Escribe BORRAR para continuar: " RESP
[[ "$RESP" == "BORRAR" ]] || { echo "Cancelado."; exit 0; }

borrar_stack() {
  if aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" >/dev/null 2>&1; then
    echo "Borrando $1 ..."
    aws cloudformation delete-stack --region "$REGION" --stack-name "$1"
    aws cloudformation wait stack-delete-complete --region "$REGION" --stack-name "$1"
    echo "  $1 borrado."
  else
    echo "  $1 no existe; se omite."
  fi
}

borrar_stack "$ROLES"
borrar_stack "$CURADO"
borrar_stack "$INGESTA"

if [[ -n "${BUCKET:-}" && "$BUCKET" != "None" ]]; then
  echo "Vaciando s3://$BUCKET (objetos y versiones) ..."
  python3 - "$BUCKET" "$REGION" <<'PY'
import sys, boto3
bucket, region = sys.argv[1], sys.argv[2]
b = boto3.resource("s3", region_name=region).Bucket(bucket)
b.object_versions.delete()
print("  Bucket vacío.")
PY
fi

borrar_stack "$BASE"
echo "Listo. Revisa en Step Functions, Glue y S3 que no quede nada con el prefijo cn-eq01."
