"""Plotly chart helpers in the CineBook dark style."""
from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

RED = "#E50914"
SEQ = ["#E50914", "#F5C542", "#2DD4BF", "#A78BFA", "#3B82F6", "#F97316", "#22C55E", "#EC4899"]
CAT_COLORS = {"regular": "#2DD4BF", "premium": "#F5C542", "recliner": "#A78BFA"}
STATUS_COLORS = {"confirmed": "#22C55E", "cancelled": "#E50914", "pending": "#F59E0B", "failed": "#6B7280"}


def style(fig: go.Figure, height: int = 320) -> go.Figure:
    fig.update_layout(
        template="plotly_dark", height=height, margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(family="Inter, sans-serif", size=12),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), title_font=dict(size=15),
    )
    fig.update_xaxes(gridcolor="#24242F", zeroline=False)
    fig.update_yaxes(gridcolor="#24242F", zeroline=False)
    return fig


def show(fig: go.Figure, height: int = 320, legend_bottom: bool = False) -> None:
    fig = style(fig, height)
    if legend_bottom:
        fig.update_layout(legend=dict(orientation="h", y=-0.08, x=0.5, xanchor="center", yanchor="top"))
    st.plotly_chart(fig, config={"displayModeBar": False}, width="stretch")


def bar(data: list[dict], x: str, y: str, title: str, color: str | None = None, horizontal: bool = False,
        color_map: dict | None = None, height: int = 320) -> None:
    if not data:
        st.caption(f"{title}: no data yet")
        return
    kwargs = dict(title=title, color=color, color_discrete_map=color_map,
                  color_discrete_sequence=[RED] if not color else SEQ)
    fig = px.bar(data, x=y if horizontal else x, y=x if horizontal else y, orientation="h" if horizontal else "v",
                 **kwargs)
    if horizontal:
        fig.update_yaxes(autorange="reversed", title=None)
    fig.update_traces(marker_line_width=0, width=0.45 if len(data) < 4 else None)
    fig.update_xaxes(type="category") if not horizontal else fig.update_yaxes(type="category")
    show(fig, height)


def donut(labels: list[str], values: list[float], title: str, color_map: dict | None = None) -> None:
    pairs = [(lbl, v) for lbl, v in zip(labels, values) if v]
    if not pairs:
        st.caption(f"{title}: no data yet")
        return
    labels, values = [p[0] for p in pairs], [p[1] for p in pairs]
    colors = [(color_map or {}).get(lbl, SEQ[i % len(SEQ)]) for i, lbl in enumerate(labels)]
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.6, marker=dict(colors=colors), sort=False))
    fig.update_layout(title=title)
    show(fig, 340, legend_bottom=True)


def trend(data: list[dict], x: str, title: str) -> None:
    if not data:
        st.caption(f"{title}: no data yet")
        return
    fig = go.Figure()
    fig.add_bar(x=[d[x] for d in data], y=[d["tickets"] for d in data], name="Tickets", marker_color="#3A3A4A",
                width=0.5 if len(data) < 4 else None)
    fig.add_scatter(x=[d[x] for d in data], y=[d["revenue"] for d in data], name="Booking value", yaxis="y2",
                    mode="lines+markers", line=dict(color=RED, width=3))
    fig.update_xaxes(type="category")
    fig.update_layout(title=title, yaxis=dict(title="Tickets", rangemode="tozero"),
                      yaxis2=dict(title="Value", overlaying="y", side="right", showgrid=False, rangemode="tozero"))
    show(fig)
