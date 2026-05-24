# Projet Big Data Framework : NutriData

Utilisation de Hadoop et Apache Spark pour gérer le dataset OpenFoodFacts qui répertorie l'ensemble des aliments existants, vendus en grande surface ou en dehors.

Objectif : Créer un dashboard et une API pour répondre à la problématique :
**Quels aliments permettent au mieux de manger sainement tout en s'adaptant à certains régimes alimentaires (halal, kosher, vegan, végétarien, riche en protéines, riche en fibres) ?**

---

## Environnement technique

Le cluster Hadoop/Spark tourne dans un environnement Docker basé sur le projet [Marcel-Jan/docker-hadoop-spark](https://github.com/Marcel-Jan/docker-hadoop-spark). L'ensemble des commandes PySpark sont exécutées directement dans le container `spark-master`.

Lancement du container :

```bash
docker exec -it spark-master bash
```

---

## Import du dataset dans HDFS

Le fichier `food.parquet` (~6 Go) est d'abord copié dans le container `namenode` puis déposé dans HDFS :

```bash
docker cp food.parquet namenode:/tmp/food.parquet
docker exec -it namenode bash
hdfs dfs -mkdir -p /data/openfoodfacts
hdfs dfs -put /tmp/food.parquet /data/openfoodfacts/food.parquet
```

Vérification de la présence du fichier dans HDFS :

```bash
hdfs dfs -ls /data/openfoodfacts/
```

---

## Lancement de PySpark

PySpark est lancé depuis le container `spark-master` avec des paramètres mémoire adaptés à la machine (32 Go de RAM disponible) :

```bash
/spark/bin/pyspark \
  --master spark://spark-master:7077 \
  --driver-memory 4g \
  --executor-memory 8g \
  --executor-cores 2 \
  --conf spark.sql.shuffle.partitions=100
```

---

## Architecture Médaillon

L'architecture choisie est une architecture médaillon en trois couches : Bronze, Silver et Gold. Chaque couche affine les données de la précédente jusqu'à obtenir des tables directement exploitables pour répondre à la problématique.

```
food.parquet (HDFS)
    |
    Bronze : données brutes intégrales
    |
    Silver : données nettoyées, filtrées NOVA 1, nutriments extraits
    |
    Gold : tables métier prêtes à consommer
        |-- mart_diets_compat
        |-- mart_accessibility
        |-- mart_diet_recommendations
```

---

## Imports des dépendances PySpark

```python
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, ArrayType, MapType
from pyspark.sql.functions import get_json_object, from_json, explode, col
from pyspark.sql.types import ArrayType, StructType, StructField, StringType, DoubleType
```

---

## Création de la database

```python
spark.sql("CREATE DATABASE IF NOT EXISTS nutridata2")
spark.sql("USE nutridata2")
```

---

## Couche Bronze : table bronze_data

La couche Bronze est une copie exacte du parquet brut. Les colonnes de types complexes (StructType, ArrayType, MapType) sont converties en JSON string pour assurer la compatibilité avec le metastore Hive.

Lecture du parquet et aplatissement des colonnes complexes :

```python
df = spark.read.parquet("hdfs://namenode:9000/data/openfoodfacts/food.parquet")

for field in df.schema.fields:
    if isinstance(field.dataType, (StructType, ArrayType, MapType)):
        df = df.withColumn(field.name, F.to_json(F.col(field.name)))
```

Création de la table Bronze :

```python
df.write \
  .mode("overwrite") \
  .option("path", "hdfs://namenode:9000/data/nutridata2/bronze_data/") \
  .saveAsTable("nutridata2.bronze_data")
```

Tests de vérification :

```python
spark.sql("SELECT COUNT(*) FROM nutridata2.bronze_data").show()
spark.sql("SELECT code, product_name, brands FROM nutridata2.bronze_data LIMIT 3").show(truncate=False)
```

---

## Couche Silver : table silver_food

La couche Silver filtre uniquement les aliments non transformés (NOVA 1), extrait les valeurs nutritionnelles depuis leur colonne JSON et supprime les doublons.

Définition du schéma de la colonne nutriments :

```python
nutriments_schema = ArrayType(StructType([
    StructField("name", StringType()),
    StructField("100g", DoubleType()),
    StructField("value", DoubleType()),
    StructField("unit", StringType())
]))
```

Extraction des nutriments depuis le JSON via explode et pivot :

```python
df_bronze = spark.table("nutridata2.bronze_data")

df_nutriments = df_bronze.select(
    "code",
    explode(from_json("nutriments", nutriments_schema)).alias("n")
).select(
    "code",
    col("n.name").alias("nutriment_name"),
    col("n.100g").alias("per_100g")
).groupBy("code").pivot("nutriment_name", [
    "energy-kcal", "proteins", "fat", "saturated-fat",
    "carbohydrates", "sugars", "fiber", "salt"
]).agg(F.first("per_100g"))
```

Sélection des colonnes utiles et filtrage NOVA 1 :

```python
df_base = df_bronze.select(
    "code",
    get_json_object("product_name", "$[0].text").alias("product_name"),
    "brands",
    "categories",
    "countries_tags",
    "nova_group",
    "nutriscore_grade",
    "nutriscore_score",
    "ingredients_text",
    "allergens_tags",
    "labels_tags"
).filter(F.col("nova_group") == 1) \
 .filter(F.col("code").isNotNull()) \
 .dropDuplicates(["code"])
```

Fusion avec les nutriments et création de la table Silver :

```python
df_silver = df_base.join(df_nutriments, on="code", how="left")

df_silver.write \
  .mode("overwrite") \
  .option("path", "hdfs://namenode:9000/data/nutridata2/silver_food/") \
  .saveAsTable("nutridata2.silver_food")
```

Tests de vérification :

```python
spark.sql("SELECT COUNT(*) FROM nutridata2.silver_food").show()
spark.sql("SELECT code, product_name, nova_group, nutriscore_grade, proteins FROM nutridata2.silver_food LIMIT 5").show(truncate=False)
```

---

## Couche Gold

La couche Gold regroupe trois tables métier construites à partir de la Silver, chacune répondant à un angle précis de la problématique.

### Table mart_diets_compat

Cette table indique la compatibilité de chaque aliment avec les différents régimes alimentaires. Les colonnes `labels_tags` et `ingredients_text` de la Silver sont transformées en colonnes booléennes.

Pour les régimes halal et kosher, la détection repose à la fois sur les labels officiels et sur l'absence d'ingrédients incompatibles dans le texte :

```python
df_silver = spark.table("nutridata2.silver_food")

def is_halal(df):
    return F.when(
        F.col("labels_tags").contains("en:halal") |
        (~F.col("ingredients_text").rlike("(?i)pork|lard|bacon|ham|alcohol|wine|beer")),
        True
    ).otherwise(False)

def is_kosher(df):
    return F.when(
        F.col("labels_tags").contains("en:kosher") |
        (~F.col("ingredients_text").rlike("(?i)pork|lard|shellfish|lobster|shrimp|crab")),
        True
    ).otherwise(False)

df_diets = df_silver.select(
    "code", "product_name", "brands", "categories",
    F.when(F.col("labels_tags").contains("en:vegan"), True).otherwise(False).alias("is_vegan"),
    F.when(F.col("labels_tags").contains("en:vegetarian"), True).otherwise(False).alias("is_vegetarian"),
    is_halal(df_silver).alias("is_halal"),
    is_kosher(df_silver).alias("is_kosher"),
    F.when(F.col("labels_tags").contains("en:no-gluten"), True).otherwise(False).alias("is_gluten_free"),
    F.when(F.col("labels_tags").contains("en:organic"), True).otherwise(False).alias("is_organic"),
    F.when(F.col("labels_tags").contains("en:no-added-sugar"), True).otherwise(False).alias("is_no_added_sugar"),
    F.col("proteins").cast("double"),
    F.col("fat").cast("double"),
    F.col("sugars").cast("double"),
    F.col("fiber").cast("double"),
    F.col("salt").cast("double"),
    F.col("energy-kcal").cast("double").alias("energy_kcal")
)

df_diets.write \
  .mode("overwrite") \
  .option("path", "hdfs://namenode:9000/data/nutridata2/mart_diets_compat/") \
  .saveAsTable("nutridata2.mart_diets_compat")
```

Tests de vérification :

```python
spark.sql("SELECT COUNT(*) FROM nutridata2.mart_diets_compat").show()
spark.sql("SELECT product_name, is_vegan, is_halal, is_kosher, is_gluten_free FROM nutridata2.mart_diets_compat LIMIT 5").show(truncate=False)
```

### Table mart_accessibility

Cette table répertorie le nutriscore et les pays de disponibilité de chaque produit. Elle répond à la dimension accessibilité de la problématique.

```python
df_silver = spark.table("nutridata2.silver_food")

df_accessibility = df_silver.select(
    "code", "product_name", "brands", "categories",
    "nutriscore_grade", "nutriscore_score", "countries_tags"
).filter(F.col("nutriscore_grade").isNotNull())

df_accessibility.write \
  .mode("overwrite") \
  .option("path", "hdfs://namenode:9000/data/nutridata2/mart_accessibility/") \
  .saveAsTable("nutridata2.mart_accessibility")
```

Tests de vérification :

```python
spark.sql("SELECT COUNT(*) FROM nutridata2.mart_accessibility").show()
spark.sql("SELECT product_name, nutriscore_grade, countries_tags FROM nutridata2.mart_accessibility LIMIT 5").show(truncate=False)
```

### Table mart_diet_recommendations

Table finale qui croise `mart_diets_compat` et `mart_accessibility`. Elle ajoute une colonne `diet_profile` calculée à partir des valeurs nutritionnelles et filtre uniquement les produits ayant un nutriscore A, B ou C.

```python
df_diets = spark.table("nutridata2.mart_diets_compat")
df_access = spark.table("nutridata2.mart_accessibility")

df_recommendations = df_diets.join(
    df_access.select("code", "nutriscore_grade", "nutriscore_score", "countries_tags"),
    on="code", how="left"
).select(
    "code", "product_name", "brands", "categories", "countries_tags",
    "nutriscore_grade", "nutriscore_score",
    "is_vegan", "is_vegetarian", "is_halal", "is_kosher",
    "is_gluten_free", "is_organic", "is_no_added_sugar",
    "energy_kcal", "proteins", "fat", "sugars", "fiber", "salt",
    F.when(F.col("proteins") >= 20, "high-protein") \
     .when(F.col("sugars") <= 5, "low-sugar") \
     .when(F.col("fiber") >= 5, "high-fiber") \
     .otherwise("standard").alias("diet_profile")
).filter(F.col("nutriscore_grade").isin("a", "b", "c"))

df_recommendations.write \
  .mode("overwrite") \
  .option("path", "hdfs://namenode:9000/data/nutridata2/mart_diet_recommendations/") \
  .saveAsTable("nutridata2.mart_diet_recommendations")
```

Tests de vérification :

```python
spark.sql("SELECT COUNT(*) FROM nutridata2.mart_diet_recommendations").show()
spark.sql("SELECT product_name, nutriscore_grade, is_halal, diet_profile, proteins FROM nutridata2.mart_diet_recommendations LIMIT 5").show(truncate=False)
```

---

## Export des tables Gold en CSV

Les trois tables Gold sont exportées en CSV depuis PySpark vers HDFS, en un seul fichier par table grâce à `coalesce(1)` :

```python
for table in ["mart_diet_recommendations", "mart_diets_compat", "mart_accessibility"]:
    spark.table("nutridata2." + table) \
      .coalesce(1) \
      .write.mode("overwrite") \
      .option("header", "true") \
      .csv("hdfs://namenode:9000/data/nutridata2/exports/" + table + "_csv")
```

Récupération des CSV depuis HDFS vers le container `namenode` :

```bash
hdfs dfs -get /data/nutridata2/exports/mart_diet_recommendations_csv/part-00000*.csv /tmp/mart_diet_recommendations.csv
hdfs dfs -get /data/nutridata2/exports/mart_diets_compat_csv/part-00000*.csv /tmp/mart_diets_compat.csv
hdfs dfs -get /data/nutridata2/exports/mart_accessibility_csv/part-00000*.csv /tmp/mart_accessibility.csv
```

Copie des CSV depuis le container vers la machine locale :

```bash
docker cp namenode:/tmp/mart_diet_recommendations.csv ./data/
docker cp namenode:/tmp/mart_diets_compat.csv ./data/
docker cp namenode:/tmp/mart_accessibility.csv ./data/
```

---

## Structure finale du projet

```
Projet_nutridata/
    data/
        mart_diet_recommendations.csv
        mart_diets_compat.csv
        mart_accessibility.csv
    api/
        main.py
    app/
        streamlit_app.py
    requirements.txt
```

---

## Tables Gold créées dans nutridata2

| Table | Lignes approximatives | Description |
|---|---|---|
| bronze_data | ~4 400 000 | Parquet brut intégral |
| silver_food | ~132 000 | Aliments NOVA 1 nettoyés avec nutriments |
| mart_diets_compat | ~132 000 | Compatibilité régimes par produit |
| mart_accessibility | ~50 000 | Nutriscore et disponibilité par pays |
| mart_diet_recommendations | ~30 000 | Recommandations finales nutriscore A/B/C |