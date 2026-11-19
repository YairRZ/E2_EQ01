"""Job de Glue cn-eq01-curar (Fase 4).

raw/extracciones/cfdi/*.json  ->  curated/expedientes/anio=/mes=/   (Parquet, 1 renglon por expediente)
                              ->  curated/conceptos/anio=/mes=/     (Parquet, 1 renglon por concepto)
raw/catalogo_se/*.jsonl       ->  curated/catalogo_se/              (Parquet, sin particion)

- Particion por anio/mes de la fecha del CFDI: Athena lee solo los meses que pide la consulta.
- Montos homologados a MXN con el tipo de cambio del propio CFDI (moneda USD).
- Solo datos fiscales y de negocio; ningun correo ni telefono llega a curated/.
- Sobrescritura dinamica: cada corrida reemplaza solo las particiones que vuelve a calcular.
"""
import sys

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql import functions as F
from pyspark.sql import types as T

args = getResolvedOptions(sys.argv, ["JOB_NAME", "LAGO_BUCKET"])
sc = SparkContext()
glue = GlueContext(sc)
spark = glue.spark_session
job = Job(glue)
job.init(args["JOB_NAME"], args)
spark.conf.set("spark.sql.sources.partitionOverwriteMode", "dynamic")

LAGO = f"s3://{args['LAGO_BUCKET']}"
DEC = T.DecimalType(18, 2)

ESQUEMA_CFDI = T.StructType([
    T.StructField("expediente_id", T.StringType()),
    T.StructField("valido", T.BooleanType()),
    T.StructField("errores", T.ArrayType(T.StringType())),
    T.StructField("uuid", T.StringType()),
    T.StructField("fecha", T.StringType()),
    T.StructField("moneda", T.StringType()),
    T.StructField("tipo_cambio", T.StringType()),
    T.StructField("subtotal", T.StringType()),
    T.StructField("iva", T.StringType()),
    T.StructField("total", T.StringType()),
    T.StructField("emisor_rfc", T.StringType()),
    T.StructField("emisor_nombre", T.StringType()),
    T.StructField("receptor_rfc", T.StringType()),
    T.StructField("conceptos", T.ArrayType(T.StructType([
        T.StructField("descripcion", T.StringType()),
        T.StructField("importe", T.StringType()),
        T.StructField("clave_prod_serv", T.StringType()),
    ]))),
])

# ---------- CFDI ----------
cfdi = (
    spark.read.schema(ESQUEMA_CFDI).json(f"{LAGO}/raw/extracciones/cfdi/")
    .where(F.col("expediente_id").isNotNull())
    .dropDuplicates(["expediente_id"])
    .withColumn("fecha_cfdi", F.to_date("fecha"))
    .where(F.col("fecha_cfdi").isNotNull())
    .withColumn("tc", F.when(F.col("moneda") == "USD", F.col("tipo_cambio").cast(T.DecimalType(12, 6)))
                .otherwise(F.lit(1).cast(T.DecimalType(12, 6))))
    .withColumn("anio", F.year("fecha_cfdi"))
    .withColumn("mes", F.month("fecha_cfdi"))
)

expedientes = cfdi.select(
    "expediente_id",
    F.col("uuid").alias("cfdi_uuid"),
    F.col("emisor_rfc").alias("proveedor_rfc"),
    F.col("emisor_nombre").alias("proveedor_nombre"),
    "receptor_rfc",
    "fecha_cfdi",
    "moneda",
    F.col("tc").alias("tipo_cambio"),
    F.col("subtotal").cast(DEC).alias("subtotal"),
    F.col("iva").cast(DEC).alias("iva"),
    F.col("total").cast(DEC).alias("total"),
    (F.col("subtotal").cast(DEC) * F.col("tc")).cast(DEC).alias("subtotal_mxn"),
    F.size("conceptos").cast(T.IntegerType()).alias("num_conceptos"),
    F.col("valido").alias("cfdi_valido"),
    F.concat_ws(" | ", "errores").alias("errores_cfdi"),
    F.current_timestamp().alias("curado_en"),
    "anio",
    "mes",
)

conceptos = (
    cfdi.select("expediente_id", "moneda", "tc", "anio", "mes", F.posexplode("conceptos").alias("pos", "c"))
    .select(
        "expediente_id",
        (F.col("pos") + 1).cast(T.IntegerType()).alias("linea"),
        F.col("c.clave_prod_serv").alias("clave_prod_serv"),
        F.col("c.descripcion").alias("descripcion"),
        "moneda",
        F.col("c.importe").cast(DEC).alias("importe"),
        (F.col("c.importe").cast(DEC) * F.col("tc")).cast(DEC).alias("importe_mxn"),
        "anio",
        "mes",
    )
)


def escribir(df, ruta, particionado=True):
    w = df.repartition(*(["anio", "mes"] if particionado else [])) if particionado else df.coalesce(1)
    w = w.write.mode("overwrite").option("compression", "snappy")
    if particionado:
        w = w.partitionBy("anio", "mes")
    w.parquet(ruta)


escribir(expedientes, f"{LAGO}/curated/expedientes/")
escribir(conceptos, f"{LAGO}/curated/conceptos/")

# ---------- Catalogo SE ----------
catalogo = (
    spark.read.json(f"{LAGO}/raw/catalogo_se/")
    .select(
        F.trim("codigo_se").alias("codigo_se"),
        F.substring(F.trim("codigo_se"), 1, 1).alias("grupo_clave"),
        F.trim("actividad").alias("actividad"),
        F.trim("grupo").alias("grupo"),
    )
    .where(F.col("codigo_se") != "")
    .dropDuplicates(["codigo_se"])
)
escribir(catalogo, f"{LAGO}/curated/catalogo_se/", particionado=False)

print(f"RESUMEN expedientes={expedientes.count()} conceptos={conceptos.count()} catalogo_se={catalogo.count()}")
job.commit()
