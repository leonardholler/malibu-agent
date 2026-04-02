import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pydeck as pdk
from data_loader import load_data, NEIGHBORHOODS
from analysis import (
    market_overview, find_comps, find_sold_comps, find_overpriced,
    find_stale, find_deals, find_teardown_candidates, construction_analysis,
    fmt_price, neighborhood_color, neighborhood_color_rgb,
)

st.set_page_config(
    page_title="Malibu Agent",
    page_icon="🏖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .block-container {padding-top: 1rem; padding-bottom: 1rem;}
    h1 {font-size: 2rem !important;}
    h2 {font-size: 1.4rem !important; margin-top: 1.5rem !important;}
    h3 {font-size: 1.1rem !important;}
    [data-testid="stMetric"] {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 8px;
        padding: 12px 16px;
    }
    [data-testid="stMetricLabel"] {font-size: 0.8rem;}
    .legend-dot {
        display: inline-block; width: 10px; height: 10px;
        border-radius: 50%; margin-right: 6px;
    }
    div[data-testid="stTabs"] button {font-size: 0.85rem;}
</style>
""", unsafe_allow_html=True)


@st.cache_data
def get_data():
    active, sold = load_data()
    return active, sold


def apply_filters(df, neighborhoods, price_range, beds_range):
    """Apply sidebar filters to a DataFrame."""
    filtered = df.copy()
    if neighborhoods:
        filtered = filtered[filtered["neighborhood"].isin(neighborhoods)]
    filtered = filtered[
        (filtered["price"] >= price_range[0]) &
        (filtered["price"] <= price_range[1])
    ]
    if beds_range[0] > 0:
        filtered = filtered[filtered["beds"] >= beds_range[0]]
    if beds_range[1] < 20:
        filtered = filtered[filtered["beds"] <= beds_range[1]]
    return filtered


# ── Load data ────────────────────────────────────────────────────────────────
active_raw, sold_raw = get_data()

if active_raw.empty and sold_raw.empty:
    st.error("No data found. Place Redfin CSV files in the data/ directory.")
    st.stop()

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("Malibu Agent")
    st.caption("Luxury market intelligence for Malibu real estate")
    st.divider()

    all_hoods = sorted(
        set(active_raw["neighborhood"].unique()) | set(sold_raw["neighborhood"].unique()),
        key=lambda x: list(NEIGHBORHOODS.keys()).index(x) if x in NEIGHBORHOODS else 99
    )

    selected_hoods = st.multiselect(
        "Neighborhoods",
        options=all_hoods,
        default=all_hoods,
    )

    all_prices = pd.concat([active_raw["price"], sold_raw["price"]]).dropna()
    price_min = int(all_prices.min())
    price_max = int(all_prices.max())

    price_range = st.slider(
        "Price Range",
        min_value=price_min,
        max_value=price_max,
        value=(price_min, price_max),
        step=1_000_000,
        format="$%dM",
    )

    all_beds = pd.concat([active_raw["beds"], sold_raw["beds"]]).dropna()
    beds_range = st.slider(
        "Bedrooms",
        min_value=0,
        max_value=int(all_beds.max()),
        value=(0, int(all_beds.max())),
    )

    data_view = st.radio("Show", ["Active Listings", "Sold Properties", "Both"], index=0)

    st.divider()
    st.caption(f"Data: Redfin MLS | {len(active_raw)} active, {len(sold_raw)} sold")

# ── Apply filters ────────────────────────────────────────────────────────────
active = apply_filters(active_raw, selected_hoods, price_range, beds_range)
sold = apply_filters(sold_raw, selected_hoods, price_range, beds_range)

if data_view == "Active Listings":
    display_df = active
elif data_view == "Sold Properties":
    display_df = sold
else:
    display_df = pd.concat([active, sold])

if display_df.empty:
    st.warning("No properties match your filters. Try widening the criteria.")
    st.stop()


# ── KPI Row ──────────────────────────────────────────────────────────────────
st.markdown("## Market Snapshot")
k1, k2, k3, k4, k5 = st.columns(5)

with k1:
    st.metric("Active Listings", f"{len(active)}")
with k2:
    med = active["price"].median()
    st.metric("Median Price", fmt_price(med) if pd.notna(med) else "N/A")
with k3:
    ppsf = active["price_per_sqft"].median()
    st.metric("Median $/sqft", f"${ppsf:,.0f}" if pd.notna(ppsf) else "N/A")
with k4:
    dom = active["dom"].median()
    st.metric("Median DOM", f"{dom:.0f} days" if pd.notna(dom) else "N/A")
with k5:
    new_pct = (active["year_built"] >= 2010).sum() / len(active) * 100 if len(active) > 0 else 0
    st.metric("New Builds (2010+)", f"{new_pct:.0f}%")


# ── Interactive Map ──────────────────────────────────────────────────────────
st.markdown("## Malibu Properties Map")

map_df = display_df[display_df["lat"].notna() & display_df["lng"].notna()].copy()
map_df["color"] = map_df["neighborhood"].apply(neighborhood_color_rgb)
map_df["radius"] = (map_df["price"] / 800_000).clip(30, 200)
map_df["price_fmt"] = map_df["price"].apply(fmt_price)
map_df["sqft_fmt"] = map_df["sqft"].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "N/A")
map_df["year_fmt"] = map_df["year_built"].apply(lambda x: str(int(x)) if pd.notna(x) else "Unknown")
map_df["beds_fmt"] = map_df["beds"].apply(lambda x: str(int(x)) if pd.notna(x) else "?")
map_df["baths_fmt"] = map_df["baths"].apply(lambda x: f"{x:g}" if pd.notna(x) else "?")
map_df["land_ratio_fmt"] = map_df["land_value_ratio"].apply(
    lambda x: f"{x:.0%}" if pd.notna(x) else "N/A"
)

layer = pdk.Layer(
    "ScatterplotLayer",
    data=map_df,
    get_position=["lng", "lat"],
    get_fill_color="color",
    get_radius="radius",
    pickable=True,
    opacity=0.8,
    stroked=True,
    get_line_color=[255, 255, 255],
    line_width_min_pixels=1,
)

view = pdk.ViewState(
    latitude=34.028,
    longitude=-118.78,
    zoom=11.5,
    pitch=0,
)

tooltip = {
    "html": """
    <div style="font-family: system-ui; padding: 4px;">
        <b style="font-size: 14px;">{address}</b><br/>
        <span style="font-size: 18px; font-weight: 700;">{price_fmt}</span><br/>
        <span>{beds_fmt} bd / {baths_fmt} ba &nbsp;·&nbsp; {sqft_fmt} sqft</span><br/>
        <span style="color: #aaa;">Built {year_fmt} &nbsp;·&nbsp; Est. {land_ratio_fmt} land value</span><br/>
        <span style="color: #ccc; font-size: 12px;">{neighborhood}</span>
    </div>
    """,
    "style": {
        "backgroundColor": "#1a1a2e",
        "color": "white",
        "border": "1px solid rgba(255,255,255,0.1)",
        "border-radius": "8px",
    },
}

st.pydeck_chart(pdk.Deck(
    layers=[layer],
    initial_view_state=view,
    tooltip=tooltip,
    map_style="mapbox://styles/mapbox/dark-v11",
))

# Map legend
legend_cols = st.columns(len(selected_hoods) if len(selected_hoods) <= 5 else 5)
for i, hood in enumerate(selected_hoods[:10]):
    col = legend_cols[i % len(legend_cols)]
    color = neighborhood_color(hood)
    col.markdown(
        f'<span class="legend-dot" style="background:{color};"></span> {hood}',
        unsafe_allow_html=True,
    )


# ── Neighborhood Breakdown ───────────────────────────────────────────────────
st.markdown("## Neighborhood Breakdown")

overview = market_overview(active, sold)
hood_names = [h for h in NEIGHBORHOODS if h in overview]

if hood_names:
    cols = st.columns(min(len(hood_names), 3))
    for i, hood in enumerate(hood_names):
        stats = overview[hood]
        with cols[i % len(cols)]:
            color = neighborhood_color(hood)
            st.markdown(f"**<span style='color:{color}'>{hood}</span>**", unsafe_allow_html=True)
            st.caption(stats["description"])

            mc1, mc2 = st.columns(2)
            mc1.metric("Active", stats["active_count"])
            mc2.metric("Sold", stats["sold_count"])

            if stats["active_med_price"]:
                st.metric("Median Price", fmt_price(stats["active_med_price"]))
            if stats["active_med_ppsf"]:
                st.metric("Median $/sqft", f"${stats['active_med_ppsf']:,.0f}")
            if stats["active_med_dom"]:
                st.metric("Median DOM", f"{stats['active_med_dom']:.0f} days")
            if stats["med_land_value_ratio"]:
                st.metric("Land Value Ratio", f"{stats['med_land_value_ratio']:.0%}")


# ── Price Analysis Charts ────────────────────────────────────────────────────
st.markdown("## Price Analysis")

chart1, chart2 = st.columns(2)

with chart1:
    fig = px.histogram(
        display_df[display_df["price"].notna()],
        x="price",
        color="neighborhood",
        color_discrete_map={h: neighborhood_color(h) for h in NEIGHBORHOODS},
        nbins=25,
        labels={"price": "Price ($)", "neighborhood": "Neighborhood"},
        title="Price Distribution",
    )
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis_tickformat="$,.0s",
        showlegend=False,
        height=400,
        margin=dict(t=40, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)

with chart2:
    ppsf_df = display_df[display_df["price_per_sqft"].notna()]
    if not ppsf_df.empty:
        fig = px.box(
            ppsf_df,
            x="neighborhood",
            y="price_per_sqft",
            color="neighborhood",
            color_discrete_map={h: neighborhood_color(h) for h in NEIGHBORHOODS},
            labels={"price_per_sqft": "$/sqft", "neighborhood": ""},
            title="Price per Square Foot by Neighborhood",
        )
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            yaxis_tickformat="$,.0f",
            showlegend=False,
            height=400,
            margin=dict(t=40, b=40),
            xaxis_tickangle=-30,
        )
        st.plotly_chart(fig, use_container_width=True)


# ── Construction & Land Value Analysis ───────────────────────────────────────
st.markdown("## Construction Era & Land Value Analysis")
st.caption(
    "Older homes in Malibu are often valued near land price — the house itself adds little. "
    "New builds command a premium for improvements."
)

era1, era2 = st.columns(2)

with era1:
    era_df = display_df[display_df["construction_era"] != "Unknown"]
    if not era_df.empty:
        era_order = [e[2] for e in CONSTRUCTION_ERAS]
        fig = px.box(
            era_df,
            x="construction_era",
            y="price_per_sqft",
            color="construction_era",
            category_orders={"construction_era": era_order},
            labels={"price_per_sqft": "$/sqft", "construction_era": "Construction Era"},
            title="$/sqft by Construction Era",
            color_discrete_sequence=["#6B7280", "#3B82F6", "#10B981", "#F59E0B"],
        )
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            yaxis_tickformat="$,.0f",
            showlegend=False,
            height=400,
            margin=dict(t=40, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)

with era2:
    lvr_df = display_df[display_df["land_value_ratio"].notna() & display_df["year_built"].notna()]
    if not lvr_df.empty:
        fig = px.scatter(
            lvr_df,
            x="year_built",
            y="land_value_ratio",
            color="neighborhood",
            size="price",
            size_max=25,
            color_discrete_map={h: neighborhood_color(h) for h in NEIGHBORHOODS},
            hover_data=["address", "price", "sqft"],
            labels={
                "year_built": "Year Built",
                "land_value_ratio": "Est. Land Value Ratio",
                "neighborhood": "Neighborhood",
            },
            title="Land Value Ratio vs. Construction Year",
        )
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            yaxis_tickformat=".0%",
            height=400,
            margin=dict(t=40, b=40),
        )
        fig.add_hline(y=0.75, line_dash="dash", line_color="rgba(255,255,255,0.3)",
                      annotation_text="Teardown threshold", annotation_position="top left")
        st.plotly_chart(fig, use_container_width=True)


# ── Price vs DOM ─────────────────────────────────────────────────────────────
st.markdown("## Price vs. Days on Market")

dom_df = active[active["dom"].notna() & active["price"].notna()]
if not dom_df.empty:
    fig = px.scatter(
        dom_df,
        x="dom",
        y="price",
        color="neighborhood",
        size="sqft",
        size_max=30,
        color_discrete_map={h: neighborhood_color(h) for h in NEIGHBORHOODS},
        hover_data=["address", "beds", "baths", "price_per_sqft", "year_built"],
        labels={"dom": "Days on Market", "price": "Price ($)", "neighborhood": "Neighborhood"},
    )
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        yaxis_tickformat="$,.0s",
        height=450,
        margin=dict(t=20, b=40),
    )
    fig.add_vline(x=120, line_dash="dash", line_color="rgba(255,255,255,0.2)",
                  annotation_text="120 days", annotation_position="top")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Properties in the upper-right are expensive AND lingering — potential price reductions coming.")


# ── Market Intelligence Tabs ─────────────────────────────────────────────────
st.markdown("## Market Intelligence")

tab_deals, tab_overpriced, tab_stale, tab_teardowns, tab_all = st.tabs(
    ["Deals", "Overpriced", "Stale Listings", "Teardown Candidates", "All Listings"]
)

display_cols = [
    "address", "price", "beds", "baths", "sqft", "lot_size", "year_built",
    "dom", "price_per_sqft", "neighborhood", "construction_era", "land_value_ratio", "url",
]


def get_display_cols(df):
    return [c for c in display_cols if c in df.columns]


def format_table_config():
    return {
        "price": st.column_config.NumberColumn("Price", format="$%d"),
        "price_per_sqft": st.column_config.NumberColumn("$/sqft", format="$%d"),
        "sqft": st.column_config.NumberColumn("Sqft", format="%d"),
        "lot_size": st.column_config.NumberColumn("Lot Size", format="%d"),
        "land_value_ratio": st.column_config.NumberColumn("Land Value %", format="%.0f%%"),
        "dom": st.column_config.NumberColumn("DOM", format="%d"),
        "url": st.column_config.LinkColumn("Redfin", display_text="View"),
    }


with tab_deals:
    deals = find_deals(active, sold)
    if not deals.empty:
        st.caption(f"Active listings priced below neighborhood sold median $/sqft — {len(deals)} potential deals")
        dcols = get_display_cols(deals) + ["discount_pct", "sold_median_ppsf"]
        dcols = [c for c in dcols if c in deals.columns]
        st.dataframe(
            deals[dcols],
            column_config={
                **format_table_config(),
                "discount_pct": st.column_config.NumberColumn("vs Sold Median", format="%d%%"),
                "sold_median_ppsf": st.column_config.NumberColumn("Sold Median $/sqft", format="$%d"),
            },
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No deals found with current filters.")

with tab_overpriced:
    overpriced = find_overpriced(active, sold)
    if not overpriced.empty:
        st.caption(f"Active listings 40%+ above neighborhood sold median $/sqft — {len(overpriced)} flagged")
        ocols = get_display_cols(overpriced) + ["premium_pct", "baseline_ppsf"]
        ocols = [c for c in ocols if c in overpriced.columns]
        st.dataframe(
            overpriced[ocols],
            column_config={
                **format_table_config(),
                "premium_pct": st.column_config.NumberColumn("Premium %", format="+%d%%"),
                "baseline_ppsf": st.column_config.NumberColumn("Sold Median $/sqft", format="$%d"),
            },
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No overpriced listings detected.")

with tab_stale:
    stale = find_stale(active)
    if not stale.empty:
        st.caption(f"Listings exceeding expected days on market for their price segment — {len(stale)} flagged")
        scols = get_display_cols(stale) + ["price_segment"]
        scols = [c for c in scols if c in stale.columns]
        st.dataframe(
            stale[scols],
            column_config=format_table_config(),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No stale listings with current filters.")

with tab_teardowns:
    teardowns = find_teardown_candidates(active)
    if not teardowns.empty:
        st.caption(
            f"Pre-1990 construction with 75%+ estimated land value ratio — {len(teardowns)} candidates. "
            "These properties are priced near land value; the existing structure adds minimal value."
        )
        tcols = get_display_cols(teardowns) + ["est_land_value", "est_improvement_value"]
        tcols = [c for c in tcols if c in teardowns.columns]
        st.dataframe(
            teardowns[tcols],
            column_config={
                **format_table_config(),
                "est_land_value": st.column_config.NumberColumn("Est. Land Value", format="$%d"),
                "est_improvement_value": st.column_config.NumberColumn("Est. Improvement", format="$%d"),
            },
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No teardown candidates found.")

with tab_all:
    st.caption(f"{len(display_df)} properties")
    st.dataframe(
        display_df[get_display_cols(display_df)],
        column_config=format_table_config(),
        hide_index=True,
        use_container_width=True,
        height=500,
    )


# ── Property Comps Search ────────────────────────────────────────────────────
st.markdown("## Property Lookup")

search = st.text_input("Search by address", placeholder="e.g. Malibu Colony, Broad Beach, Sea Lane...")

if search:
    match = active[active["address"].str.contains(search, case=False, na=False)]
    if match.empty:
        match = sold[sold["address"].str.contains(search, case=False, na=False)]
    if match.empty:
        st.warning(f"No property found matching '{search}'")
    else:
        target = match.iloc[0]

        pc1, pc2, pc3 = st.columns(3)
        pc1.metric("Price", fmt_price(target["price"]))
        beds_str = f"{int(target['beds'])}" if pd.notna(target.get("beds")) else "?"
        baths_str = f"{target['baths']:g}" if pd.notna(target.get("baths")) else "?"
        pc2.metric("Beds / Baths", f"{beds_str} / {baths_str}")
        pc3.metric("Neighborhood", target["neighborhood"])

        pd1, pd2, pd3, pd4 = st.columns(4)
        pd1.metric("Sqft", f"{int(target['sqft']):,}" if pd.notna(target.get("sqft")) else "N/A")
        pd2.metric("$/sqft", f"${int(target['price_per_sqft']):,}" if pd.notna(target.get("price_per_sqft")) else "N/A")
        pd3.metric("Year Built", str(int(target["year_built"])) if pd.notna(target.get("year_built")) else "Unknown")
        lvr = target.get("land_value_ratio")
        pd4.metric("Land Value Ratio", f"{lvr:.0%}" if pd.notna(lvr) else "N/A")

        comp_tab1, comp_tab2 = st.tabs(["Active Comps", "Sold Comps"])

        with comp_tab1:
            comps = find_comps(target, active, n=5)
            if not comps.empty:
                st.dataframe(
                    comps[get_display_cols(comps)],
                    column_config=format_table_config(),
                    hide_index=True,
                    use_container_width=True,
                )
            else:
                st.info("No active comps found.")

        with comp_tab2:
            sold_comps, sold_med_ppsf, premium_pct = find_sold_comps(target, sold, n=5)
            if sold_med_ppsf is not None:
                sc1, sc2 = st.columns(2)
                sc1.metric("Sold Median $/sqft", f"${sold_med_ppsf:,.0f}")
                if premium_pct is not None:
                    if premium_pct > 10:
                        sc2.metric("vs. Sold Median", f"{premium_pct:+.0f}%", delta_color="inverse")
                    elif premium_pct < -10:
                        sc2.metric("vs. Sold Median", f"{premium_pct:+.0f}%", delta_color="normal")
                    else:
                        sc2.metric("vs. Sold Median", f"{premium_pct:+.0f}%", delta_color="off")
            if not sold_comps.empty:
                st.dataframe(
                    sold_comps[get_display_cols(sold_comps)],
                    column_config=format_table_config(),
                    hide_index=True,
                    use_container_width=True,
                )
            else:
                st.info("No sold comps in this neighborhood.")
