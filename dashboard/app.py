import streamlit as st
import pandas as pd
import plotly.express as px
import os
import re

st.set_page_config(
    page_title="NutriData",
    page_icon="🥦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Constantes ───────────────────────────────────────────────────────────────

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data")

DIET_COLS = {
    "is_vegan":         "Végan",
    "is_vegetarian":    "Végétarien",
    "is_halal":         "Halal",
    "is_kosher":        "Kasher",
    "is_gluten_free":   "Sans Gluten",
    "is_organic":       "Bio",
    "is_no_added_sugar":"Sans Sucre Ajouté",
}

NUTRISCORE_COLORS = {
    "a": "#038141",
    "b": "#85bb2f",
    "c": "#fecb02",
    "d": "#ee8100",
    "e": "#e63e11",
}

NUTRIENT_CAPS = {
    "proteins":    95,   # max réaliste pour un isolat de protéines
    "fat":         100,
    "sugars":      100,
    "fiber":       80,
    "salt":        10,
    "energy_kcal": 900,
}

NUTRIENT_LABELS = {
    "proteins":    "Protéines (g/100g)",
    "fat":         "Lipides (g/100g)",
    "sugars":      "Sucres (g/100g)",
    "fiber":       "Fibres (g/100g)",
    "salt":        "Sel (g/100g)",
    "energy_kcal": "Énergie (kcal/100g)",
}

PROFILE_LABELS = {
    "high-protein": "Hyperprotéiné",
    "low-sugar":    "Low-Sugar",
    "high-fiber":   "Riche en Fibres",
    "standard":     "Standard",
}

CHART_TEMPLATE = "plotly_white"

# ─── Chargement données ───────────────────────────────────────────────────────

def _cast(df: pd.DataFrame) -> pd.DataFrame:
    for col in DIET_COLS:
        if col in df.columns:
            df[col] = (
                df[col].astype(str).str.strip().str.lower()
                .map({"true": True, "false": False})
                .fillna(False)
            )
    # Cap valeurs aberrantes sur tous les nutriments
    for col, cap in NUTRIENT_CAPS.items():
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            df.loc[df[col] >= cap, col] = float("nan")
    return df


@st.cache_data
def load_recommendations() -> pd.DataFrame:
    return _cast(pd.read_csv(
        os.path.join(DATA_PATH, "mart_diet_recommendations.csv"), on_bad_lines="skip"
    ))


@st.cache_data
def load_diets() -> pd.DataFrame:
    return _cast(pd.read_csv(
        os.path.join(DATA_PATH, "mart_diets_compat.csv"), on_bad_lines="skip"
    ))


@st.cache_data
def load_countries() -> pd.DataFrame:
    df = pd.read_csv(
        os.path.join(DATA_PATH, "mart_accessibility.csv"),
        usecols=["countries_tags"],
        on_bad_lines="skip",
    )
    counts: dict[str, int] = {}
    for val in df["countries_tags"].dropna():
        for tag in re.findall(r"[a-z]{2}:[a-z][a-z0-9-]+", str(val)):
            label = tag.split(":", 1)[-1].replace("-", " ").title()
            counts[label] = counts.get(label, 0) + 1
    return (
        pd.DataFrame.from_dict(counts, orient="index", columns=["Produits"])
        .sort_values("Produits", ascending=False)
        .reset_index()
        .rename(columns={"index": "Pays"})
    )


# ─── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🥦 NutriData")
    st.caption("Open Food Facts · Couche Gold")
    st.divider()
    page = st.radio(
        "Navigation",
        options=["accueil", "regimes", "recommandations"],
        format_func=lambda x: {
            "accueil":          "📊 Vue d'ensemble",
            "regimes":          "🥗 Régimes & Nutrition",
            "recommandations":  "⭐ Recommandations",
        }[x],
        label_visibility="collapsed",
    )

# ─── PAGE 1 : Vue d'ensemble ──────────────────────────────────────────────────

if page == "accueil":
    st.title("NutriData — Vue d'ensemble")
    st.caption("Open Food Facts · Architecture Médaillon Bronze / Silver / Gold")
    st.divider()

    df = load_recommendations()

    # KPIs
    total = len(df)
    ab_pct = round(
        df["nutriscore_grade"].isin(["a", "b"]).sum() / total * 100, 1
    )
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Produits analysés",  f"{total:,}")
    k2.metric("Nutri-Score A ou B", f"{ab_pct} %")
    k3.metric("Compatibles Végan",  f"{int(df['is_vegan'].sum()):,}")
    k4.metric("Sans Gluten",        f"{int(df['is_gluten_free'].sum()):,}")

    st.divider()
    col_l, col_r = st.columns(2)

    # Nutriscore distribution — seulement les grades présents
    with col_l:
        nutri = (
            df["nutriscore_grade"]
            .dropna()
            .str.lower()
            .value_counts()
            .reset_index()
        )
        nutri.columns = ["grade", "count"]
        nutri = nutri[nutri["grade"].isin(NUTRISCORE_COLORS)].sort_values("grade")
        nutri["label"] = nutri["grade"].str.upper()

        fig = px.bar(
            nutri,
            x="label", y="count",
            color="grade",
            color_discrete_map=NUTRISCORE_COLORS,
            text="count",
            labels={"label": "Nutri-Score", "count": "Produits"},
            title="Distribution des Nutri-Scores",
            template=CHART_TEMPLATE,
        )
        fig.update_traces(textposition="outside", showlegend=False)
        fig.update_layout(showlegend=False, xaxis_title="Nutri-Score")
        st.plotly_chart(fig, use_container_width=True)

    # Produits par régime
    with col_r:
        regime_counts = {
            DIET_COLS[col]: int(df[col].sum())
            for col in DIET_COLS if col in df.columns
        }
        rdf = (
            pd.DataFrame({"Régime": list(regime_counts.keys()),
                          "Produits": list(regime_counts.values())})
            .sort_values("Produits", ascending=True)
        )
        fig2 = px.bar(
            rdf,
            x="Produits", y="Régime",
            orientation="h",
            text="Produits",
            color="Produits",
            color_continuous_scale=["#b7dfc7", "#2E7D52"],
            title="Produits compatibles par régime",
            template=CHART_TEMPLATE,
        )
        fig2.update_traces(textposition="outside")
        fig2.update_layout(coloraxis_showscale=False)
        st.plotly_chart(fig2, use_container_width=True)

    # Accessibilité pays
    st.divider()
    st.subheader("Top 15 pays — Volume de produits")
    countries_df = load_countries()
    fig3 = px.bar(
        countries_df.head(15),
        x="Pays", y="Produits",
        color="Produits",
        color_continuous_scale=["#b7dfc7", "#2E7D52"],
        text="Produits",
        template=CHART_TEMPLATE,
    )
    fig3.update_traces(textposition="outside")
    fig3.update_layout(coloraxis_showscale=False, xaxis_tickangle=-30)
    st.plotly_chart(fig3, use_container_width=True)

# ─── PAGE 2 : Régimes & Nutrition ─────────────────────────────────────────────

elif page == "regimes":
    st.title("Régimes & Nutrition")
    st.divider()

    # Source unique : mart_diet_recommendations (83 589 produits, cohérent avec la vue d'ensemble)
    df = load_recommendations()

    with st.sidebar:
        st.divider()
        regime_sel = st.selectbox(
            "Régime alimentaire",
            options=list(DIET_COLS.keys()),
            format_func=lambda x: DIET_COLS[x],
        )
        nutri_filter = st.multiselect(
            "Nutri-Score",
            options=["a", "b", "c", "d", "e"],
            default=[],
            format_func=str.upper,
        )

    subset = df[df[regime_sel] == True].copy()
    if nutri_filter:
        subset = subset[subset["nutriscore_grade"].isin(nutri_filter)]

    # KPIs — tous issus de la même source
    k1, k2, k3 = st.columns(3)
    k1.metric("Produits compatibles", f"{len(subset):,}")
    if "proteins" in subset.columns:
        k2.metric("Protéines moy.", f"{subset['proteins'].mean():.1f} g/100g")
    if "energy_kcal" in subset.columns:
        k3.metric("Énergie moy.", f"{subset['energy_kcal'].mean():.0f} kcal/100g")

    st.divider()
    col_l, col_r = st.columns(2)

    # Nutriscore du régime sélectionné
    with col_l:
        nutri_sub = (
            subset["nutriscore_grade"]
            .dropna().str.lower()
            .value_counts().reset_index()
        )
        nutri_sub.columns = ["grade", "count"]
        nutri_sub = nutri_sub[nutri_sub["grade"].isin(NUTRISCORE_COLORS)].sort_values("grade")
        nutri_sub["label"] = nutri_sub["grade"].str.upper()

        fig = px.bar(
            nutri_sub,
            x="label", y="count",
            color="grade",
            color_discrete_map=NUTRISCORE_COLORS,
            text="count",
            labels={"label": "Nutri-Score", "count": "Produits"},
            title=f"Nutri-Score — {DIET_COLS[regime_sel]}",
            template=CHART_TEMPLATE,
        )
        fig.update_traces(textposition="outside", showlegend=False)
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    # Top 10 protéines — même subset que le tableau
    with col_r:
        top_prot = (
            subset[subset["proteins"].notna()]
            .nlargest(10, "proteins")
            [["product_name", "proteins"]]
            .sort_values("proteins")
        )
        top_prot["product_name"] = top_prot["product_name"].str[:35]
        fig2 = px.bar(
            top_prot,
            x="proteins", y="product_name",
            orientation="h",
            text="proteins",
            color="proteins",
            color_continuous_scale=["#b7dfc7", "#2E7D52"],
            labels={"proteins": "g/100g", "product_name": "Produit"},
            title=f"Top 10 Protéines — {DIET_COLS[regime_sel]}",
            template=CHART_TEMPLATE,
        )
        fig2.update_traces(texttemplate="%{text:.1f}g", textposition="outside")
        fig2.update_layout(coloraxis_showscale=False, yaxis_title="")
        st.plotly_chart(fig2, use_container_width=True)

    # Tableau — exactement les mêmes produits que les graphiques
    st.divider()
    st.subheader(f"Produits — {DIET_COLS[regime_sel]}")
    show_cols = [c for c in ["product_name", "brands", "nutriscore_grade",
                              "proteins", "fat", "sugars", "fiber", "energy_kcal"]
                 if c in subset.columns]
    st.dataframe(
        subset[show_cols]
        .rename(columns={
            "product_name":    "Produit",
            "brands":          "Marque",
            "nutriscore_grade":"Nutri-Score",
            **NUTRIENT_LABELS,
        })
        .reset_index(drop=True)
        .head(300),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(f"{len(subset):,} produits · affichage limité à 300")

# ─── PAGE 3 : Recommandations ─────────────────────────────────────────────────

elif page == "recommandations":
    st.title("Recommandations")
    st.caption("Trouvez les aliments naturels adaptés à votre régime")
    st.divider()

    df = load_recommendations()

    with st.sidebar:
        st.divider()
        st.subheader("Filtres")

        regime_sel = st.selectbox(
            "Régime",
            options=["tous"] + list(DIET_COLS.keys()),
            format_func=lambda x: "Tous" if x == "tous" else DIET_COLS[x],
        )
        nutriscore_sel = st.multiselect(
            "Nutri-Score",
            options=["a", "b", "c", "d", "e"],
            default=["a", "b"],
            format_func=str.upper,
        )
        if "diet_profile" in df.columns:
            profiles = df["diet_profile"].dropna().unique().tolist()
            profile_sel = st.selectbox(
                "Profil",
                options=["tous"] + profiles,
                format_func=lambda x: "Tous" if x == "tous" else PROFILE_LABELS.get(x, x),
            )
        else:
            profile_sel = "tous"

        st.markdown("**Seuils nutritionnels**")
        min_prot   = st.slider("Protéines min (g)", 0.0, 50.0, 0.0, 0.5)
        max_sugar  = st.slider("Sucres max (g)",    0.0, 100.0, 100.0, 1.0)
        max_kcal   = st.slider("Calories max",      0, 900, 900, 10)
        limit      = st.number_input("Résultats max", 10, 300, 50, step=10)

    # Application des filtres
    res = df.copy()
    if regime_sel != "tous":
        res = res[res[regime_sel] == True]
    if nutriscore_sel:
        res = res[res["nutriscore_grade"].isin(nutriscore_sel)]
    if profile_sel != "tous" and "diet_profile" in res.columns:
        res = res[res["diet_profile"] == profile_sel]
    if min_prot > 0 and "proteins" in res.columns:
        res = res[res["proteins"] >= min_prot]
    if max_sugar < 100 and "sugars" in res.columns:
        res = res[res["sugars"] <= max_sugar]
    if max_kcal < 900 and "energy_kcal" in res.columns:
        res = res[res["energy_kcal"] <= max_kcal]
    res = res.head(int(limit))

    # KPIs résultat
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Résultats", f"{len(res):,}")
    if len(res) > 0:
        top_grade = res["nutriscore_grade"].dropna().value_counts()
        if not top_grade.empty:
            k2.metric("Grade dominant", top_grade.idxmax().upper())
        if "proteins" in res.columns:
            k3.metric("Protéines moy.", f"{res['proteins'].mean():.1f} g")
        if "energy_kcal" in res.columns:
            k4.metric("Calories moy.", f"{res['energy_kcal'].mean():.0f} kcal")

    if len(res) == 0:
        st.warning("Aucun produit ne correspond à ces critères. Élargissez les filtres.")
        st.stop()

    st.divider()

    # Nutriscore des résultats
    col_l, col_r = st.columns(2)
    with col_l:
        nutri_res = (
            res["nutriscore_grade"]
            .dropna().str.lower()
            .value_counts().reset_index()
        )
        nutri_res.columns = ["grade", "count"]
        nutri_res = nutri_res[nutri_res["grade"].isin(NUTRISCORE_COLORS)].sort_values("grade")
        nutri_res["label"] = nutri_res["grade"].str.upper()

        fig = px.bar(
            nutri_res,
            x="label", y="count",
            color="grade",
            color_discrete_map=NUTRISCORE_COLORS,
            text="count",
            labels={"label": "Nutri-Score", "count": "Produits"},
            title="Nutri-Score des résultats",
            template=CHART_TEMPLATE,
        )
        fig.update_traces(textposition="outside", showlegend=False)
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    # Profil nutritionnel si disponible
    with col_r:
        if "diet_profile" in res.columns:
            prof = (
                res["diet_profile"].map(PROFILE_LABELS)
                .value_counts().reset_index()
            )
            prof.columns = ["Profil", "count"]
            fig2 = px.pie(
                prof,
                values="count", names="Profil",
                title="Profils nutritionnels",
                color_discrete_sequence=["#2E7D52", "#85bb2f", "#fecb02", "#b7dfc7"],
                hole=0.45,
                template=CHART_TEMPLATE,
            )
            fig2.update_traces(textinfo="label+percent")
            st.plotly_chart(fig2, use_container_width=True)

    # Tableau final
    st.subheader("Produits recommandés")
    disp_cols = [c for c in [
        "product_name", "brands", "nutriscore_grade", "diet_profile",
        "proteins", "fat", "sugars", "fiber", "energy_kcal",
    ] if c in res.columns]

    st.dataframe(
        res[disp_cols].rename(columns={
            "product_name":    "Produit",
            "brands":          "Marque",
            "nutriscore_grade":"Nutri-Score",
            "diet_profile":    "Profil",
            **NUTRIENT_LABELS,
        }).reset_index(drop=True),
        use_container_width=True,
        hide_index=True,
    )

    st.download_button(
        "⬇ Télécharger les résultats (CSV)",
        res.to_csv(index=False).encode("utf-8"),
        "nutridata_resultats.csv",
        "text/csv",
    )
