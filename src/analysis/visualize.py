"""Matplotlib figures for the analysis outputs."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402


def bar(counts: dict[str, int], title: str, path: Path, color: str = "#3b6ea5") -> None:
    fig, ax = plt.subplots(figsize=(9, 4.8))
    keys = list(counts)
    vals = [counts[k] for k in keys]
    ax.barh(keys[::-1], vals[::-1], color=color)
    for i, v in enumerate(vals[::-1]):
        ax.text(v, i, f" {v:,}", va="center", fontsize=9)
    ax.set_title(title)
    ax.set_xlabel("count")
    ax.margins(x=0.15)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def degree_hist(dist: list[tuple[int, int]], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 4.5))
    xs = [d for d, c in dist if d > 0]
    ys = [c for d, c in dist if d > 0]
    ax.loglog(xs, ys, "o", ms=4, color="#a5473b")
    ax.set_xlabel("degree (distinct co-authors)")
    ax.set_ylabel("number of authors")
    ax.set_title("Degree distribution, author co-authorship projection (log-log, degree>0)")
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def subgraph_plot(g: nx.Graph, center: str, path: Path, radius: int = 2, max_nodes: int = 60,
                  communities: dict[str, int] | None = None) -> None:
    ego = nx.ego_graph(g, center, radius=radius)
    if ego.number_of_nodes() > max_nodes:
        keep = sorted(ego.nodes(), key=lambda n: (-g.degree(n), n))[:max_nodes]
        if center not in keep:
            keep[-1] = center
        ego = ego.subgraph(keep).copy()
    pos = nx.spring_layout(ego, seed=20261107, k=0.6)
    fig, ax = plt.subplots(figsize=(10, 8))
    colors = [communities.get(n, -1) if communities else 0 for n in ego.nodes()]
    widths = [0.6 + 0.8 * d.get("weight", 1) for _, _, d in ego.edges(data=True)]
    nx.draw_networkx_edges(ego, pos, ax=ax, width=widths, alpha=0.4)
    nx.draw_networkx_nodes(ego, pos, ax=ax, node_color=colors, cmap="tab20",
                           node_size=[60 + 25 * g.degree(n) for n in ego.nodes()])
    top = sorted(ego.nodes(), key=lambda n: (-g.degree(n), n))[:15]
    nx.draw_networkx_labels(ego, pos, ax=ax, labels={n: ego.nodes[n].get("name", n) for n in top}, font_size=7)
    ax.set_title(f"Ego network (radius {radius}) of {g.nodes[center].get('name')} - colours = Louvain community")
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def small_world_plot(sw: dict[str, Any], path: Path) -> None:
    if sw.get("status") != "computed":
        return
    fig, axes = plt.subplots(1, 2, figsize=(9, 4))
    axes[0].bar(["observed", "random (mean)"], [sw["C_obs"], sw["C_rand"]], color=["#3b6ea5", "#999"])
    axes[0].set_title("Average clustering C")
    axes[1].bar(["observed", "random (mean)"], [sw["L_obs"], sw["L_rand"]], color=["#3b6ea5", "#999"])
    axes[1].set_title("Average shortest path L")
    fig.suptitle(f"Author LCC (n={sw['lcc_nodes']}) vs {sw['n_random']} degree-preserving random graphs; sigma={sw['sigma']}")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
