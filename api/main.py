from fastapi import FastAPI, Query
from typing import Optional
import pandas as pd
import os

app = FastAPI(
    title="NutriData API",
    description="API pour filtrer les aliments naturels par régime, nutriments et accessibilité",
    version="1.0.0"
)

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data")

def load_recommendations():
    return pd.read_csv(os.path.join(DATA_PATH, "mart_diet_recommendations.csv"), on_bad_lines='skip')

def load_diets():
    return pd.read_csv(os.path.join(DATA_PATH, "mart_diets_compat.csv"), on_bad_lines='skip')

def load_accessibility():
    return pd.read_csv(os.path.join(DATA_PATH, "mart_accessibility.csv"), on_bad_lines='skip')

def clean_df(df):
    return df.where(pd.notnull(df), None)


# ─── ROUTES GÉNÉRALES ────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"message": "NutriData API is running", "version": "1.0.0"}

@app.get("/stats")
def stats():
    df = load_diets()
    return {
        "total_produits": len(df),
        "vegan": int(df["is_vegan"].sum()),
        "vegetarian": int(df["is_vegetarian"].sum()),
        "halal": int(df["is_halal"].sum()),
        "kosher": int(df["is_kosher"].sum()),
        "gluten_free": int(df["is_gluten_free"].sum()),
        "organic": int(df["is_organic"].sum()),
        "no_added_sugar": int(df["is_no_added_sugar"].sum())
    }


# ─── ROUTES RÉGIMES ──────────────────────────────────────────────────────────

@app.get("/diets/filter")
def filter_by_diet(
    vegan: Optional[bool] = Query(None),
    vegetarian: Optional[bool] = Query(None),
    halal: Optional[bool] = Query(None),
    kosher: Optional[bool] = Query(None),
    gluten_free: Optional[bool] = Query(None),
    organic: Optional[bool] = Query(None),
    no_added_sugar: Optional[bool] = Query(None),
    limit: int = Query(20, le=200)
):
    df = load_diets()
    if vegan is not None: df = df[df["is_vegan"] == vegan]
    if vegetarian is not None: df = df[df["is_vegetarian"] == vegetarian]
    if halal is not None: df = df[df["is_halal"] == halal]
    if kosher is not None: df = df[df["is_kosher"] == kosher]
    if gluten_free is not None: df = df[df["is_gluten_free"] == gluten_free]
    if organic is not None: df = df[df["is_organic"] == organic]
    if no_added_sugar is not None: df = df[df["is_no_added_sugar"] == no_added_sugar]
    return clean_df(df.head(limit)).to_dict(orient="records")

@app.get("/diets/nutriscore")
def nutriscore_by_diet():
    df = load_recommendations()
    result = {}
    for regime in ["is_vegan", "is_vegetarian", "is_halal", "is_kosher", "is_gluten_free"]:
        subset = df[df[regime] == True]["nutriscore_grade"].value_counts().to_dict()
        result[regime.replace("is_", "")] = subset
    return result


# ─── ROUTES NUTRIMENTS ───────────────────────────────────────────────────────

@app.get("/nutrients/filter")
def filter_by_nutrients(
    min_proteins: Optional[float] = Query(None, description="Protéines min (g/100g)"),
    max_proteins: Optional[float] = Query(None),
    min_fiber: Optional[float] = Query(None, description="Fibres min (g/100g)"),
    max_fat: Optional[float] = Query(None, description="Graisses max (g/100g)"),
    max_sugars: Optional[float] = Query(None, description="Sucres max (g/100g)"),
    max_salt: Optional[float] = Query(None, description="Sel max (g/100g)"),
    max_energy_kcal: Optional[float] = Query(None, description="Calories max (kcal/100g)"),
    limit: int = Query(20, le=200)
):
    df = load_diets()
    if min_proteins is not None: df = df[df["proteins"] >= min_proteins]
    if max_proteins is not None: df = df[df["proteins"] <= max_proteins]
    if min_fiber is not None: df = df[df["fiber"] >= min_fiber]
    if max_fat is not None: df = df[df["fat"] <= max_fat]
    if max_sugars is not None: df = df[df["sugars"] <= max_sugars]
    if max_salt is not None: df = df[df["salt"] <= max_salt]
    if max_energy_kcal is not None: df = df[df["energy_kcal"] <= max_energy_kcal]
    return clean_df(df.head(limit)).to_dict(orient="records")

@app.get("/nutrients/top_proteins")
def top_proteins(
    regime: Optional[str] = Query(None, description="vegan, halal, kosher, gluten_free, vegetarian"),
    limit: int = Query(20, le=100)
):
    df = load_diets()
    if regime:
        col = f"is_{regime}"
        if col in df.columns:
            df = df[df[col] == True]
    df = df[df["proteins"].notna()]
    df = df.sort_values("proteins", ascending=False)
    return clean_df(df.head(limit))[["code", "product_name", "brands", "proteins", "energy_kcal"]].to_dict(orient="records")


# ─── ROUTES ACCESSIBILITÉ ────────────────────────────────────────────────────

@app.get("/accessibility/countries")
def by_country():
    df = load_accessibility()
    df = df[df["countries_tags"].notna()]
    countries = df["countries_tags"].str.replace('["', '').str.replace('"]', '').str.split('","', expand=True).stack()
    return countries.value_counts().head(30).to_dict()

@app.get("/accessibility/nutriscore")
def by_nutriscore(
    grade: Optional[str] = Query(None, description="a, b, c, d, e"),
    limit: int = Query(20, le=200)
):
    df = load_accessibility()
    if grade:
        df = df[df["nutriscore_grade"] == grade.lower()]
    return clean_df(df.head(limit)).to_dict(orient="records")


# ─── ROUTE RECOMMANDATIONS ───────────────────────────────────────────────────

@app.get("/recommendations")
def recommendations(
    regime: Optional[str] = Query(None, description="vegan, vegetarian, halal, kosher, gluten_free"),
    nutriscore: Optional[str] = Query(None, description="a, b, c, d, e"),
    diet_profile: Optional[str] = Query(None, description="high-protein, low-sugar, high-fiber, standard"),
    min_proteins: Optional[float] = Query(None),
    max_sugars: Optional[float] = Query(None),
    country: Optional[str] = Query(None, description="ex: en:france"),
    limit: int = Query(20, le=200)
):
    df = load_recommendations()
    if regime:
        col = f"is_{regime}"
        if col in df.columns:
            df = df[df[col] == True]
    if nutriscore:
        df = df[df["nutriscore_grade"] == nutriscore.lower()]
    if diet_profile:
        df = df[df["diet_profile"] == diet_profile]
    if min_proteins is not None:
        df = df[df["proteins"] >= min_proteins]
    if max_sugars is not None:
        df = df[df["sugars"] <= max_sugars]
    if country:
        df = df[df["countries_tags"].str.contains(country, na=False)]
    return clean_df(df.head(limit)).to_dict(orient="records")


# ─── ROUTE RECHERCHE ─────────────────────────────────────────────────────────

@app.get("/search")
def search(
    q: str = Query(..., description="Nom du produit ou marque"),
    limit: int = Query(20, le=100)
):
    df = load_recommendations()
    mask = (
        df["product_name"].str.contains(q, case=False, na=False) |
        df["brands"].str.contains(q, case=False, na=False)
    )
    return clean_df(df[mask].head(limit)).to_dict(orient="records")