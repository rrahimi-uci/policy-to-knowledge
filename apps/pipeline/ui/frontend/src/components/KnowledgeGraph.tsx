import { useRef, useMemo, useCallback, useState, useEffect } from 'react';
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d';
import { ZoomIn, ZoomOut, Maximize2, X, Info } from 'lucide-react';
import { useTheme } from '@/hooks/useTheme';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface KGNode {
  id: string;
  label: string;
  group: string;          // 'rule_type' | 'rule_<type>' | 'entity'
  shape: 'box' | 'dot' | 'diamond';
  color: string;          // fill / primary color
  borderColor: string;
  size: number;           // value used for radius scaling
  tooltip?: string;
  ruleCount?: number;
  ruleId?: string;        // original rule_id for rule nodes
  entityName?: string;    // for entity nodes
  x?: number;
  y?: number;
}

interface KGLink {
  source: string;
  target: string;
  label?: string;
  color: string;
  width: number;
  dashed?: boolean;
  arrow?: boolean;        // draw arrowhead at target
  type: string;           // 'category' | 'dependency' | 'entity_rule'
}

interface GraphJSON {
  entity_types?: Record<string, any>;
  relationships?: Record<string, any>;
  business_rules?: any[];
}

interface Props {
  data: GraphJSON;
  typeColors: Record<string, string>;
  onEntityClick?: (entity: string) => void;
}

/* ------------------------------------------------------------------ */
/*  Palette                                                            */
/* ------------------------------------------------------------------ */

const ENTITY_BG = '#0d9488';         // teal-600
const ENTITY_BORDER = '#0f766e';     // teal-700
const THEME_COLORS = {
  dark:  { bg: '#030712', text: '#e2e8f0', dim: '#475569', label: '#ffffff', sublabel: '#94a3b8', pill: 'rgba(3,7,18,0.8)' },
  light: { bg: '#f8fafc', text: '#334155', dim: '#94a3b8', label: '#1e293b', sublabel: '#64748b', pill: 'rgba(241,245,249,0.9)' },
};

const DEP_COLORS: Record<string, string> = {
  prerequisite: '#b91c1c',
  sequential: '#7c2d12',
  conditional: '#ca8a04',
  complementary: '#059669',
  contradictory: '#5b21b6',
  override: '#be185d',
  validation: '#0e7490',
};
const DEP_DEFAULT = '#64748b';

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Lighten a hex color by mixing 60% original + 40% white */
export function lighten(hex: string): string {
  // Guard against malformed colors from API/config: parseInt on a bad slice
  // yields NaN and produces "#nan…" fills (or throws on undefined).
  if (typeof hex !== 'string' || !/^#[0-9a-fA-F]{6}$/.test(hex)) {
    hex = DEP_DEFAULT;
  }
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const lr = Math.round(r * 0.6 + 255 * 0.4);
  const lg = Math.round(g * 0.6 + 255 * 0.4);
  const lb = Math.round(b * 0.6 + 255 * 0.4);
  return `#${lr.toString(16).padStart(2, '0')}${lg.toString(16).padStart(2, '0')}${lb.toString(16).padStart(2, '0')}`;
}

/* ------------------------------------------------------------------ */
/*  Build graph — matches agent_6 HTML vis.js output                   */
/* ------------------------------------------------------------------ */

function buildGraph(
  data: GraphJSON,
  typeColors: Record<string, string>,
): { nodes: KGNode[]; links: KGLink[] } {
  const nodes: KGNode[] = [];
  const links: KGLink[] = [];
  const nodeIdSet = new Set<string>();
  const rules = data.business_rules || [];

  // -- 1) Group rules by rule_type ---------------------------------
  const rulesByType: Record<string, any[]> = {};
  for (const r of rules) {
    const t = (r.rule_type || 'unknown').toLowerCase();
    (rulesByType[t] ??= []).push(r);
  }

  // -- 2) Rule-Type aggregate nodes (box) --------------------------
  for (const [type, typeRules] of Object.entries(rulesByType)) {
    const id = `type_${type}`;
    const color = typeColors[type] || DEP_DEFAULT;
    nodes.push({
      id,
      label: type.charAt(0).toUpperCase() + type.slice(1),
      group: 'rule_type',
      shape: 'box',
      color,
      borderColor: color,
      size: 60 + typeRules.length * 2,
      ruleCount: typeRules.length,
      tooltip: `${type.charAt(0).toUpperCase() + type.slice(1)}: ${typeRules.length} rules`,
    });
    nodeIdSet.add(id);
  }

  // -- 3) Individual Rule nodes (dot) + category edges -------------
  const usedIds = new Set<string>();
  for (const rule of rules) {
    const ruleType = (rule.rule_type || 'unknown').toLowerCase();
    const baseColor = typeColors[ruleType] || DEP_DEFAULT;
    const lightColor = lighten(baseColor);

    let ruleId: string = rule.rule_id || `rule_${Math.random().toString(36).slice(2, 8)}`;
    if (usedIds.has(ruleId)) {
      let dup = 1;
      while (usedIds.has(`${ruleId}_dup${dup}`)) dup++;
      ruleId = `${ruleId}_dup${dup}`;
    }
    usedIds.add(ruleId);

    const mandatory = rule.mandatory ? 'Yes' : 'No';
    const ref = rule.source_reference || '';
    const refDisplay = ref
      ? `${String(ref).slice(0, 50)}${rule.reference_verified ? ' ✓' : ' ✗'}`
      : 'N/A';

    nodes.push({
      id: ruleId,
      label: rule.rule_id || ruleId,
      group: `rule_${ruleType}`,
      shape: 'dot',
      color: lightColor,
      borderColor: baseColor,
      size: 15,
      ruleId: rule.rule_id,
      tooltip: [
        `${rule.rule_id}: ${rule.rule_name || ''}`,
        `Type: ${ruleType}`,
        `Mandatory: ${mandatory}`,
        `Ref: ${refDisplay}`,
        rule.risk_level ? `Risk: ${rule.risk_level}` : null,
        rule.jurisdiction ? `Jurisdiction: ${rule.jurisdiction}` : null,
      ].filter(Boolean).join('\n'),
    });
    nodeIdSet.add(ruleId);

    // Category edge: type → rule
    const typeId = `type_${ruleType}`;
    links.push({
      source: typeId,
      target: ruleId,
      color: baseColor + '40',
      width: 1,
      type: 'category',
    });
  }

  // -- 4) Dependency edges (rule → rule) ---------------------------
  for (const rule of rules) {
    const ruleId = rule.rule_id;
    if (!ruleId || !nodeIdSet.has(ruleId)) continue;
    for (const dep of rule.dependencies || []) {
      const depTarget = dep.depends_on_rule || dep.depends_on;
      if (!depTarget || !nodeIdSet.has(depTarget)) continue;
      const depType = (dep.dependency_type || 'default').toLowerCase();
      links.push({
        source: depTarget,
        target: ruleId,
        label: depType,
        color: DEP_COLORS[depType] || DEP_DEFAULT,
        width: 3,
        arrow: true,
        type: 'dependency',
      });
    }
  }

  // -- 5) Entity nodes (diamond) + entity→rule edges ---------------
  const rulesByEntity: Record<string, string[]> = {};
  for (const rule of rules) {
    const entity = rule.entity_or_relationship;
    if (!entity) continue;
    (rulesByEntity[entity] ??= []).push(rule.rule_id);
  }

  const entityDefs = data.entity_types || {};
  for (const [entityName, ruleIds] of Object.entries(rulesByEntity)) {
    const id = `entity_${entityName}`;
    const def = entityDefs[entityName];
    const entityKind = def?.entity_type || def?.kind || '';
    const desc = def?.definition || def?.description || '';
    nodes.push({
      id,
      label: entityName.replace(/_/g, ' ').split(' ').map(w => w.charAt(0) + w.slice(1).toLowerCase()).join(' ').slice(0, 30),
      group: 'entity',
      shape: 'diamond',
      color: ENTITY_BG,
      borderColor: ENTITY_BORDER,
      size: 30 + ruleIds.length * 3,
      ruleCount: ruleIds.length,
      entityName,
      tooltip: [
        entityName,
        entityKind ? `Kind: ${entityKind}` : null,
        `Connected rules: ${ruleIds.length}`,
        desc ? desc.slice(0, 120) : null,
      ].filter(Boolean).join('\n'),
    });
    nodeIdSet.add(id);

    for (const rid of ruleIds) {
      if (!nodeIdSet.has(rid)) continue;
      links.push({
        source: id,
        target: rid,
        color: ENTITY_BG + '30',
        width: 1,
        dashed: true,
        arrow: true,
        type: 'entity_rule',
      });
    }
  }

  return { nodes, links };
}

/* ------------------------------------------------------------------ */
/*  Tooltip                                                            */
/* ------------------------------------------------------------------ */

function Tooltip({ node, x, y }: { node: KGNode; x: number; y: number }) {
  const lines = (node.tooltip || node.label).split('\n');
  return (
    <div
      className="fixed z-50 pointer-events-none"
      style={{ left: x + 14, top: y - 10 }}
    >
      <div className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 shadow-xl max-w-xs">
        {lines.map((line, i) => (
          <p key={i} className={`text-xs ${i === 0 ? 'font-medium text-gray-100' : 'text-gray-400'}`}>
            {line}
          </p>
        ))}
        <div className="flex items-center gap-2 mt-1">
          <span
            className="w-2 h-2 rounded-full"
            style={{ backgroundColor: node.color }}
          />
          <span className="text-[10px] text-gray-500 capitalize">
            {node.shape === 'box' ? 'Rule Type' : node.shape === 'diamond' ? 'Entity' : 'Rule'}
          </span>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Legend                                                              */
/* ------------------------------------------------------------------ */

function Legend({ typeColors }: { typeColors: Record<string, string> }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="absolute top-3 left-3 z-10">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 px-2.5 py-1.5 bg-gray-800/90 backdrop-blur border border-gray-700 rounded-lg text-xs text-gray-300 hover:bg-gray-700/90 transition-colors"
      >
        <Info size={13} />
        Legend
      </button>
      {open && (
        <div className="mt-1.5 bg-gray-800/95 backdrop-blur border border-gray-700 rounded-lg p-3 shadow-xl min-w-[180px] max-h-[420px] overflow-y-auto">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] text-gray-500 uppercase tracking-wider">Node Types</span>
            <button onClick={() => setOpen(false)} className="text-gray-500 hover:text-gray-300">
              <X size={12} />
            </button>
          </div>
          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <span className="w-3 h-3 rotate-45" style={{ backgroundColor: ENTITY_BG }} />
              <span className="text-xs text-gray-300">Entity (diamond)</span>
            </div>
            {Object.entries(typeColors).map(([type, color]) => (
              <div key={type} className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-sm" style={{ backgroundColor: color }} />
                <span className="text-xs text-gray-300 capitalize">{type} (box)</span>
              </div>
            ))}
            {Object.entries(typeColors).map(([type, color]) => (
              <div key={`rule_${type}`} className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: lighten(color) }} />
                <span className="text-xs text-gray-400 capitalize">{type} rule (dot)</span>
              </div>
            ))}
          </div>
          <div className="mt-2.5 pt-2 border-t border-gray-700 space-y-1.5">
            <span className="text-[10px] text-gray-500 uppercase tracking-wider">Edges</span>
            <div className="flex items-center gap-2">
              <div className="w-4 h-0 border-t border-gray-500" />
              <span className="text-xs text-gray-400">Type → Rule</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-0 border-t-2 border-red-700" />
              <span className="text-xs text-gray-400">Dependency (arrow)</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-0 border-t border-dashed border-teal-500" />
              <span className="text-xs text-gray-400">Entity → Rule</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */

export default function KnowledgeGraph({ data, typeColors, onEntityClick }: Props) {
  const { theme } = useTheme();
  const tc = THEME_COLORS[theme];
  const fgRef = useRef<ForceGraphMethods | undefined>(undefined);
  const containerRef = useRef<HTMLDivElement>(null);
  const [hoverNode, setHoverNode] = useState<{ node: KGNode; x: number; y: number } | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [zoomLevel, setZoomLevel] = useState(1);
  const zoomLevelRef = useRef(1);
  const mousePos = useRef({ x: 0, y: 0 });

  // Resize observer
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect;
      setDimensions({ width: Math.round(width), height: Math.round(height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const { nodes, links } = useMemo(
    () => buildGraph(data, typeColors),
    [data, typeColors],
  );

  const graphData = useMemo(() => ({ nodes, links }), [nodes, links]);

  // Adjacency set for selection highlight
  const highlightSet = useMemo(() => {
    if (!selectedNode) return null;
    const s = new Set<string>();
    s.add(selectedNode);
    links.forEach(l => {
      const src = typeof l.source === 'object' ? (l.source as any).id : l.source;
      const tgt = typeof l.target === 'object' ? (l.target as any).id : l.target;
      if (src === selectedNode || tgt === selectedNode) {
        s.add(src);
        s.add(tgt);
      }
    });
    return s;
  }, [selectedNode, links]);

  // Track mouse position for tooltip
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const handler = (e: MouseEvent) => { mousePos.current = { x: e.clientX, y: e.clientY }; };
    el.addEventListener('mousemove', handler);
    return () => el.removeEventListener('mousemove', handler);
  }, []);

  const handleNodeHover = useCallback((node: any) => {
    if (node) {
      setHoverNode({ node: node as KGNode, x: mousePos.current.x, y: mousePos.current.y });
    } else {
      setHoverNode(null);
    }
    const el = containerRef.current;
    if (el) el.style.cursor = node ? 'pointer' : 'grab';
  }, []);

  const handleNodeClick = useCallback((node: any) => {
    const n = node as KGNode;
    setSelectedNode(prev => prev === n.id ? null : n.id);
    if (n.group === 'entity' && onEntityClick && n.entityName) {
      onEntityClick(n.entityName);
    }
    if (node.x != null && node.y != null) fgRef.current?.centerAt(node.x, node.y, 400);
  }, [onEntityClick]);

  const handleZoomIn = () => fgRef.current?.zoom(zoomLevelRef.current * 1.4, 300);
  const handleZoomOut = () => fgRef.current?.zoom(zoomLevelRef.current / 1.4, 300);
  const handleFit = () => fgRef.current?.zoomToFit(400, 60);

  /* ---- Canvas: Nodes -------------------------------------------- */
  const nodeCanvasObject = useCallback(
    (node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const n = node as KGNode;
      const isSelected = selectedNode === n.id;
      const isVisible = !highlightSet || highlightSet.has(n.id);
      const alpha = isVisible ? 1 : 0.08;
      ctx.globalAlpha = alpha;

      const s = n.size;

      if (n.shape === 'box') {
        // Rule type aggregate — box
        const halfW = Math.max(s * 0.5, 30);
        const halfH = Math.max(s * 0.25, 14);
        const r = 4;
        const x = node.x - halfW;
        const y = node.y - halfH;
        const w = halfW * 2;
        const h = halfH * 2;
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.lineTo(x + w - r, y);
        ctx.quadraticCurveTo(x + w, y, x + w, y + r);
        ctx.lineTo(x + w, y + h - r);
        ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
        ctx.lineTo(x + r, y + h);
        ctx.quadraticCurveTo(x, y + h, x, y + h - r);
        ctx.lineTo(x, y + r);
        ctx.quadraticCurveTo(x, y, x + r, y);
        ctx.closePath();
        ctx.fillStyle = n.color;
        ctx.fill();
        ctx.strokeStyle = isSelected ? '#ffffff' : n.borderColor;
        ctx.lineWidth = isSelected ? 2.5 : 1;
        ctx.stroke();

        // Label
        const fontSize = Math.min(16, Math.max(10, halfH * 0.8));
        ctx.font = `bold ${fontSize}px Inter, system-ui, sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = '#ffffff';
        ctx.fillText(n.label, node.x, node.y);
      } else if (n.shape === 'diamond') {
        // Entity — diamond
        const half = Math.max(s * 0.3, 12);
        ctx.beginPath();
        ctx.moveTo(node.x, node.y - half);
        ctx.lineTo(node.x + half, node.y);
        ctx.lineTo(node.x, node.y + half);
        ctx.lineTo(node.x - half, node.y);
        ctx.closePath();
        ctx.fillStyle = n.color;
        ctx.fill();
        ctx.strokeStyle = isSelected ? '#99f6e4' : n.borderColor;
        ctx.lineWidth = isSelected ? 2.5 : 1;
        ctx.stroke();

        // Label below
        if (globalScale > 0.3) {
          const fontSize = Math.max(8, Math.min(12, 10 / globalScale));
          ctx.font = `bold ${fontSize}px Inter, system-ui, sans-serif`;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'top';
          ctx.fillStyle = isVisible ? tc.label : tc.dim;
          ctx.fillText(n.label, node.x, node.y + half + 3);
        }
      } else {
        // Individual rule — dot
        const radius = Math.max(s * 0.25, 3);
        // Glow for selected
        if (isSelected) {
          ctx.beginPath();
          ctx.arc(node.x, node.y, radius + 5, 0, 2 * Math.PI);
          ctx.fillStyle = n.borderColor + '40';
          ctx.fill();
        }
        ctx.beginPath();
        ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
        ctx.fillStyle = n.color;
        ctx.fill();
        ctx.strokeStyle = isSelected ? '#ffffff' : n.borderColor;
        ctx.lineWidth = isSelected ? 1.5 : 0.5;
        ctx.stroke();

        // Label only when zoomed in or selected
        if (globalScale > 2 || isSelected) {
          const fontSize = Math.max(7, 8 / globalScale);
          ctx.font = `${fontSize}px Inter, system-ui, sans-serif`;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'top';
          ctx.fillStyle = isVisible ? tc.sublabel : tc.dim;
          ctx.fillText(n.label, node.x, node.y + radius + 2);
        }
      }

      ctx.globalAlpha = 1;
    },
    [selectedNode, highlightSet, tc],
  );

  /* ---- Canvas: Links -------------------------------------------- */
  const linkCanvasObject = useCallback(
    (link: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const l = link as KGLink;
      const src = l.source as any;
      const tgt = l.target as any;
      if (src?.x == null || tgt?.x == null) return;

      const srcId = typeof src === 'object' ? src.id : src;
      const tgtId = typeof tgt === 'object' ? tgt.id : tgt;
      const isVisible = !highlightSet || highlightSet.has(srcId) || highlightSet.has(tgtId);

      if (l.type === 'category') {
        ctx.globalAlpha = isVisible ? 0.25 : 0.02;
      } else if (l.type === 'entity_rule') {
        ctx.globalAlpha = isVisible ? 0.2 : 0.02;
      } else {
        ctx.globalAlpha = isVisible ? 0.7 : 0.04;
      }

      ctx.beginPath();
      if (l.dashed) {
        ctx.setLineDash([4 / globalScale, 4 / globalScale]);
      } else {
        ctx.setLineDash([]);
      }
      ctx.moveTo(src.x, src.y);
      ctx.lineTo(tgt.x, tgt.y);
      ctx.strokeStyle = l.color;
      ctx.lineWidth = l.width / globalScale;
      ctx.stroke();
      ctx.setLineDash([]);

      // Arrow head for dependency / entity_rule
      if (l.arrow) {
        const angle = Math.atan2(tgt.y - src.y, tgt.x - src.x);
        const arrowLen = Math.max(6, 8 / globalScale);
        ctx.beginPath();
        ctx.moveTo(tgt.x, tgt.y);
        ctx.lineTo(
          tgt.x - arrowLen * Math.cos(angle - Math.PI / 7),
          tgt.y - arrowLen * Math.sin(angle - Math.PI / 7),
        );
        ctx.lineTo(
          tgt.x - arrowLen * Math.cos(angle + Math.PI / 7),
          tgt.y - arrowLen * Math.sin(angle + Math.PI / 7),
        );
        ctx.closePath();
        ctx.fillStyle = l.color;
        ctx.fill();
      }

      // Dependency label
      if (l.label && l.type === 'dependency' && globalScale > 0.6 && isVisible) {
        const mx = (src.x + tgt.x) / 2;
        const my = (src.y + tgt.y) / 2;
        const fontSize = Math.max(7, 9 / globalScale);
        ctx.font = `${fontSize}px Inter, system-ui, sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        // Background pill
        const tw = ctx.measureText(l.label).width + 6;
        ctx.fillStyle = tc.pill;
        ctx.fillRect(mx - tw / 2, my - fontSize / 2 - 1, tw, fontSize + 2);
        ctx.fillStyle = tc.sublabel;
        ctx.fillText(l.label, mx, my);
      }

      ctx.globalAlpha = 1;
    },
    [highlightSet, tc],
  );

  /* ---- Pointer area --------------------------------------------- */
  const nodePointerAreaPaint = useCallback(
    (node: any, color: string, ctx: CanvasRenderingContext2D) => {
      const n = node as KGNode;
      const r = n.shape === 'box'
        ? Math.max(n.size * 0.5, 30)
        : n.shape === 'diamond'
          ? Math.max(n.size * 0.3, 12) + 4
          : Math.max(n.size * 0.25, 3) + 4;
      ctx.beginPath();
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();
    },
    [],
  );

  // Count summary
  const nodeStats = useMemo(() => {
    let ruleTypes = 0, rules = 0, entities = 0;
    nodes.forEach(n => {
      if (n.shape === 'box') ruleTypes++;
      else if (n.shape === 'diamond') entities++;
      else rules++;
    });
    return { ruleTypes, rules, entities };
  }, [nodes]);

  // Total entity types from data (matches JanusGraph entity_category vertex count)
  const entityTypesCount = useMemo(
    () => Object.keys(data.entity_types || {}).length,
    [data],
  );

  const depCount = useMemo(
    () => links.filter(l => l.type === 'dependency').length,
    [links],
  );

  // Edges that exist in JanusGraph: depends_on + belongs_to_category (excludes
  // visual-only category edges that group rules under rule-type aggregate nodes)
  const edgeCount = useMemo(
    () => links.filter(l => l.type !== 'category').length,
    [links],
  );

  return (
    <div
      ref={containerRef}
      className="relative bg-gray-950 border border-gray-800 rounded-xl overflow-hidden"
      style={{ height: 650 }}
    >
      {/* Controls */}
      <div className="absolute top-3 right-3 z-10 flex flex-col gap-1">
        <button
          onClick={handleZoomIn}
          className="p-2 bg-gray-800/90 backdrop-blur border border-gray-700 rounded-lg text-gray-300 hover:bg-gray-700/90 transition-colors"
          title="Zoom in"
        >
          <ZoomIn size={15} />
        </button>
        <button
          onClick={handleZoomOut}
          className="p-2 bg-gray-800/90 backdrop-blur border border-gray-700 rounded-lg text-gray-300 hover:bg-gray-700/90 transition-colors"
          title="Zoom out"
        >
          <ZoomOut size={15} />
        </button>
        <button
          onClick={handleFit}
          className="p-2 bg-gray-800/90 backdrop-blur border border-gray-700 rounded-lg text-gray-300 hover:bg-gray-700/90 transition-colors"
          title="Fit to screen"
        >
          <Maximize2 size={15} />
        </button>
        {selectedNode && (
          <button
            onClick={() => setSelectedNode(null)}
            className="p-2 bg-gray-800/90 backdrop-blur border border-gray-700 rounded-lg text-gray-300 hover:bg-gray-700/90 transition-colors"
            title="Clear selection"
          >
            <X size={15} />
          </button>
        )}
      </div>

      {/* Legend */}
      <Legend typeColors={typeColors} />

      {/* Stats bar */}
      <div className="absolute bottom-3 left-3 z-10 flex items-center gap-3 px-3 py-1.5 bg-gray-800/80 backdrop-blur border border-gray-700 rounded-lg">
        <span className="text-[10px] text-gray-300 font-medium">
          {nodeStats.rules + entityTypesCount} nodes
        </span>
        <span className="text-[10px] text-gray-600">·</span>
        <span className="text-[10px] text-gray-300 font-medium">
          {edgeCount} edges
        </span>
        <span className="text-[10px] text-gray-600">|</span>
        <span className="text-[10px] text-gray-500">
          {nodeStats.rules} rules
        </span>
        <span className="text-[10px] text-gray-600">·</span>
        <span className="text-[10px] text-gray-500">
          {entityTypesCount} entities
        </span>
        <span className="text-[10px] text-gray-600">·</span>
        <span className="text-[10px] text-gray-500">
          {depCount} deps
        </span>
        {selectedNode && (
          <>
            <span className="text-[10px] text-gray-600">|</span>
            <span className="text-[10px] text-blue-400 truncate max-w-[140px]">
              {nodes.find(n => n.id === selectedNode)?.label}
            </span>
          </>
        )}
      </div>

      {/* Graph canvas */}
      <ForceGraph2D
        ref={fgRef}
        graphData={graphData}
        width={dimensions.width}
        height={dimensions.height}
        backgroundColor={tc.bg}
        nodeCanvasObject={nodeCanvasObject}
        nodePointerAreaPaint={nodePointerAreaPaint}
        linkCanvasObject={linkCanvasObject}
        onNodeHover={handleNodeHover}
        onNodeClick={handleNodeClick}
        onBackgroundClick={() => setSelectedNode(null)}
        onZoom={({ k }) => { zoomLevelRef.current = k; setZoomLevel(k); }}
        cooldownTicks={200}
        d3AlphaDecay={0.015}
        d3VelocityDecay={0.25}
        warmupTicks={80}
        enableNodeDrag={true}
        enableZoomInteraction={true}
        enablePanInteraction={true}
      />

      {/* Hover tooltip */}
      {hoverNode && <Tooltip {...hoverNode} />}
    </div>
  );
}
