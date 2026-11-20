import cytoscape, { type Core } from "cytoscape";
import { BarChart3, CircleDot, Database, Network, Search, ShieldCheck, Users } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { getAtlasSnapshot } from "../lib/api";
import type { AtlasNode, AtlasSnapshot } from "../lib/types";

const COMMUNITY_COLORS = [
  "#2764ae", "#a16207", "#18724b", "#8b4ea1", "#bd4b3e", "#397f8c", "#6d7335", "#6d5ca8",
];

interface AtlasDashboardProps {
  onAsk: (question: string) => void;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("vi-VN").format(value);
}

function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function AtlasDashboard({ onAsk }: AtlasDashboardProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Core | null>(null);
  const [snapshot, setSnapshot] = useState<AtlasSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [community, setCommunity] = useState<string>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    getAtlasSnapshot().then(setSnapshot).catch((caught: unknown) => {
      setError(caught instanceof Error ? caught.message : "Không đọc được snapshot phân tích thật.");
    });
  }, []);

  const visible = useMemo(() => {
    if (!snapshot) return { nodes: [], edges: [] };
    const needle = query.trim().toLocaleLowerCase("vi");
    const nodes = snapshot.graph.nodes.filter((node) => {
      const inCommunity = community === "all" || String(node.community) === community;
      const matches = !needle || node.name.toLocaleLowerCase("vi").includes(needle) || node.id.includes(needle);
      return inCommunity && matches;
    });
    const ids = new Set(nodes.map((node) => node.id));
    const edges = snapshot.graph.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));
    return { nodes, edges };
  }, [snapshot, query, community]);

  useEffect(() => {
    if (!containerRef.current || !snapshot) return;
    graphRef.current?.destroy();
    const graph = cytoscape({
      container: containerRef.current,
      elements: [
        ...visible.nodes.map((node) => ({
          data: { ...node, label: node.name, size: 18 + Math.min(34, node.degree * 0.7) },
        })),
        ...visible.edges.map((edge) => ({ data: edge })),
      ],
      style: [
        {
          selector: "node",
          style: {
            "background-color": (element) => COMMUNITY_COLORS[Number(element.data("community") ?? 0) % COMMUNITY_COLORS.length],
            "border-color": "#ffffff",
            "border-width": 1.5,
            label: "data(label)",
            color: "#17324d",
            "font-size": 9,
            "text-background-color": "#ffffff",
            "text-background-opacity": 0.86,
            "text-background-padding": "2px",
            "text-valign": "bottom",
            "text-margin-y": 6,
            width: "data(size)",
            height: "data(size)",
          },
        },
        {
          selector: "edge",
          style: {
            width: "mapData(shared_count, 1, 10, 1, 6)",
            "line-color": "#9aabba",
            opacity: 0.58,
            "curve-style": "haystack",
          },
        },
        { selector: "node:selected", style: { "border-color": "#a16207", "border-width": 4 } },
      ],
      layout: { name: "cose", animate: false, randomize: true, nodeRepulsion: () => 5200, idealEdgeLength: () => 72 },
      minZoom: 0.2,
      maxZoom: 3,
    });
    graph.on("tap", "node", (event) => setSelectedId(String(event.target.id())));
    graphRef.current = graph;
    return () => graph.destroy();
  }, [snapshot, visible]);

  const selected: AtlasNode | null = snapshot?.graph.nodes.find((node) => node.id === selectedId) ?? null;
  const evidenceIds = selected && snapshot
    ? [...new Set(snapshot.graph.edges.filter((edge) => edge.source === selected.id || edge.target === selected.id)
      .flatMap((edge) => edge.evidence_paper_ids))].slice(0, 8)
    : [];

  if (error) return <section className="atlas-error" role="alert"><strong>Atlas không khả dụng.</strong><span>{error}</span></section>;
  if (!snapshot) return <section className="atlas-loading" aria-live="polite">Đang đọc snapshot phân tích thật…</section>;

  return (
    <section className="atlas-page" aria-label="Bảng phân tích mạng xã hội">
      <header className="atlas-hero">
        <div>
          <span className="eyebrow"><ShieldCheck aria-hidden="true" /> REAL OFFLINE SNAPSHOT</span>
          <h1>Author network, measured.</h1>
          <p>PageRank, Louvain, k-core và kiểm định small-world trên đúng snapshot <code>{snapshot.scope_id}</code>.</p>
        </div>
        <div className="provenance-card"><Database aria-hidden="true" /><div><strong>{snapshot.provenance.analysis_source}</strong><span>{snapshot.provenance.directory}</span></div></div>
      </header>

      <div className="metric-grid">
        <article><Database /><span>Toàn knowledge graph</span><strong>{formatNumber(snapshot.counts.total_nodes)}</strong><small>{formatNumber(snapshot.counts.total_relationships)} quan hệ</small></article>
        <article><Users /><span>Mạng đồng tác giả</span><strong>{formatNumber(snapshot.network_stats.authors_total)}</strong><small>{formatNumber(snapshot.network_stats.edges)} cạnh</small></article>
        <article><Network /><span>Louvain communities</span><strong>{snapshot.communities.n_communities}</strong><small>modularity {snapshot.communities.modularity}</small></article>
        <article><CircleDot /><span>Hạt nhân k-core</span><strong>k = {snapshot.core.max_core}</strong><small>{snapshot.core.kernel_size} tác giả</small></article>
      </div>

      <div className="atlas-layout">
        <article className="graph-card">
          <div className="section-heading">
            <div><span className="eyebrow">INTERACTIVE PROJECTION</span><h2>Co-authorship explorer</h2></div>
            <span>{visible.nodes.length} node · {visible.edges.length} edge</span>
          </div>
          <div className="atlas-filters">
            <label><Search aria-hidden="true" /><span className="sr-only">Tìm tác giả</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Tìm tác giả…" /></label>
            <label><span className="sr-only">Lọc cộng đồng</span><select value={community} onChange={(event) => setCommunity(event.target.value)}><option value="all">Mọi cộng đồng</option>{snapshot.community_summary.map((item) => <option key={item.community} value={item.community}>Community {item.community} ({item.size})</option>)}</select></label>
            <button onClick={() => graphRef.current?.fit(undefined, 36)}>Fit graph</button>
          </div>
          <div ref={containerRef} className="cytoscape-canvas" aria-label="Đồ thị đồng tác giả tương tác" />
          <p className="graph-note">Kích thước node = degree; màu = Louvain community; độ dày cạnh = số bài viết chung. Preview bị chặn ở {snapshot.graph.max_nodes} node, không phải toàn graph.</p>
        </article>

        <aside className="atlas-inspector">
          {selected ? (
            <>
              <span className="eyebrow">SELECTED AUTHOR</span><h2>{selected.name}</h2><code>{selected.id}</code>
              <dl><div><dt>PageRank</dt><dd>{selected.pagerank.toFixed(6)}</dd></div><div><dt>Degree</dt><dd>{selected.degree}</dd></div><div><dt>Community</dt><dd>{selected.community ?? "—"}</dd></div><div><dt>Core</dt><dd>{selected.core_number}</dd></div></dl>
              <h3>Evidence papers</h3><ul>{evidenceIds.map((id) => <li key={id}><code>{id}</code></li>)}</ul>
              <button className="ask-button" onClick={() => onAsk(`Phân tích tác giả ${selected.name} và các quan hệ đồng tác giả có bằng chứng`)}>Hỏi GraphRAG về node này</button>
            </>
          ) : <div className="inspector-empty"><CircleDot /><h2>Chọn một node</h2><p>Xem PageRank, community, k-core và paper IDs làm bằng chứng.</p></div>}
        </aside>
      </div>

      <div className="analysis-grid">
        <article className="analysis-card"><span className="eyebrow"><BarChart3 /> SMALL-WORLD</span><h2>{snapshot.small_world.verdict}</h2><div className="ratio-row"><div><span>C observed / random</span><strong>{snapshot.small_world.C_obs} / {snapshot.small_world.C_rand}</strong></div><div><span>L observed / random</span><strong>{snapshot.small_world.L_obs} / {snapshot.small_world.L_rand}</strong></div><div><span>Sigma</span><strong>{snapshot.small_world.sigma}</strong></div></div><p>LCC chỉ chiếm {percent(snapshot.network_stats.lcc_ratio_of_all_authors)} tác giả. Sigma cao không đủ khi đường đi quan sát dài hơn random quá nhiều.</p></article>
        <article className="analysis-card"><span className="eyebrow"><Users /> TOP PAGERANK</span><ol className="ranking-list">{snapshot.top_pagerank.slice(0, 6).map((author, index) => <li key={author.author_id}><span>{index + 1}</span><button onClick={() => setSelectedId(author.author_id)}>{author.name}</button><strong>{author.score.toFixed(5)}</strong></li>)}</ol></article>
      </div>
    </section>
  );
}
