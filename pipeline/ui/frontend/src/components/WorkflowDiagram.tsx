import { useMemo, useState, useEffect } from 'react';
import {
  FileText,
  Users,
  BookOpen,
  ShieldCheck,
  Merge,
  Sparkles,
  BarChart3,
  Layers,
  GitCompareArrows,
  Calculator,
  PieChart,
  CheckCircle,
  Loader2,
  Circle,
  XCircle,
  SkipForward,
  ChevronRight,
  Clock,
  Search,
  Settings,
  Database,
  ShieldAlert,
  HardDrive,
  Zap,
} from 'lucide-react';
import type { PipelineStep } from '../hooks/usePipeline';

/* ------------------------------------------------------------------ */
/*  Step metadata                                                      */
/* ------------------------------------------------------------------ */

interface StepMeta {
  id: string;
  label: string;
  description: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  phase: 1 | 2 | 3;
}

const STEPS: StepMeta[] = [
  {
    id: '1', phase: 1, icon: FileText,
    label: 'Document Segmentation & Organization',
    description: 'Splits raw compliance documents into semantically coherent chunks and organises them by topic using table-of-contents analysis and AI reasoning. Output feeds every downstream step.',
  },
  {
    id: '2', phase: 1, icon: Users,
    label: 'Domain Entity & Relationship Discovery',
    description: 'Identifies the key domain entities (e.g. Borrower, Collateral, Loan) and maps their attributes and relationships. Runs iterative meta-agent refinement to maximise coverage and quality.',
  },
  {
    id: '3', phase: 1, icon: BookOpen,
    label: 'Business Rules Extraction',
    description: 'Extracts detailed business rules from each document chunk using a large reasoning model. Rules are batched in parallel to hit the configured target count.',
  },
  {
    id: '3.5', phase: 1, icon: ShieldCheck,
    label: 'Rule Quality Validation',
    description: 'Validates every extracted rule for completeness, consistency and domain relevance. Rules that fall below the confidence threshold are flagged or discarded before the merge step.',
  },
  {
    id: '4', phase: 1, icon: Merge,
    label: 'Rules & Entity Integration',
    description: 'Joins validated business rules with the entity model, linking each rule to the entities and attributes it governs. Produces the first complete, structured knowledge graph.',
  },
  {
    id: '5', phase: 1, icon: Sparkles,
    label: 'Knowledge Graph Deduplication & Optimization',
    description: 'Removes duplicate and near-duplicate rules, resolves conflicts, and adds dependency links between rules that reference each other. Substantially reduces graph size while preserving coverage.',
  },
  {
    id: '6', phase: 1, icon: BarChart3,
    label: 'Graph Visualization & Export',
    description: 'Generates an interactive HTML visualization of the final knowledge graph and exports JSON and CSV artefacts for downstream use.',
  },
  {
    id: '7', phase: 2, icon: Layers,
    label: 'Cross-Graph Rule Clustering',
    description: 'Groups rules from both input graphs into semantic clusters so that semantically related rules across graphs are compared together in the next step.',
  },
  {
    id: '8', phase: 2, icon: GitCompareArrows,
    label: 'Semantic Rule Alignment',
    description: 'Uses an LLM to compare rule pairs across graphs and classify each pair as equivalent, contradictory, or unique to one graph. This is the most computationally intensive step of the joining pipeline.',
  },
  {
    id: '9', phase: 2, icon: Calculator,
    label: 'Graph Set Analysis',
    description: 'Applies set operations (intersection, difference, union, contradiction detection) to the aligned rule pairs, producing five distinct result sets ready for review.',
  },
  {
    id: '10', phase: 2, icon: PieChart,
    label: 'Comparison Visualization & Export',
    description: 'Renders interactive visualizations for each set operation result and exports the full comparison as JSON, giving analysts a clear view of how the two graphs agree, differ, and conflict.',
  },
];

const PUBLISH_STEPS: StepMeta[] = [
  {
    id: 'P1', phase: 3, icon: Search,
    label: 'Locate KG Data',
    description: 'Locates the knowledge graph JSON from pipeline output, validates it exists, and derives the graph key and configuration parameters.',
  },
  {
    id: 'P2', phase: 3, icon: Settings,
    label: 'Save & Configure',
    description: 'Saves the KG JSON to the graph store, updates graphs.yaml configuration, and regenerates JanusGraph property files.',
  },
  {
    id: 'P3', phase: 3, icon: Database,
    label: 'Open Graph Runtime',
    description: 'Opens the graph in JanusGraph at runtime without requiring a container restart. Creates the Cassandra keyspace and OpenSearch index.',
  },
  {
    id: 'P4', phase: 3, icon: ShieldAlert,
    label: 'Create Schema',
    description: 'Creates the graph schema in JanusGraph — vertex labels, edge labels, property keys, and composite/mixed indexes for efficient traversal.',
  },
  {
    id: 'P5', phase: 3, icon: HardDrive,
    label: 'Load Data',
    description: 'Loads all business rules, entities, attributes, and relationships into the graph database as vertices and edges.',
  },
  {
    id: 'P6', phase: 3, icon: Zap,
    label: 'Index Embeddings',
    description: 'Builds semantic search embeddings for all rules and entities, enabling natural language queries against the published graph.',
  },
];

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function statusOf(stepId: string, steps: PipelineStep[]): string {
  return steps.find(s => s.step === stepId)?.status ?? 'pending';
}

function detailOf(stepId: string, steps: PipelineStep[]): string | undefined {
  return steps.find(s => s.step === stepId)?.detail;
}

function durationOf(stepId: string, steps: PipelineStep[]): string | undefined {
  const s = steps.find(s => s.step === stepId);
  if (!s?.started_at) return undefined;
  const start = new Date(s.started_at).getTime();
  const end = s.finished_at ? new Date(s.finished_at).getTime() : Date.now();
  const sec = Math.round((end - start) / 1000);
  if (sec < 1) return '<1s';
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`;
}

/* ------------------------------------------------------------------ */
/*  Tooltip                                                            */
/* ------------------------------------------------------------------ */

function StepTooltip({ description, label }: { description: string; label: string }) {
  return (
    <div className="
      absolute z-50 top-[calc(100%+10px)] left-1/2 -translate-x-1/2
      w-64 p-3 rounded-xl
      bg-gray-900 border border-gray-700
      shadow-xl shadow-black/40
      pointer-events-none
      opacity-0 group-hover:opacity-100
      -translate-y-1 group-hover:translate-y-0
      transition-all duration-200
    ">
      {/* Arrow pointing up */}
      <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-px
        border-8 border-transparent border-b-gray-700" />
      <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-[1px]
        border-8 border-transparent border-b-gray-900" />
      <p className="text-[11px] font-semibold text-gray-200 mb-1.5">{label}</p>
      <p className="text-[11px] text-gray-400 leading-relaxed">{description}</p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Status visuals                                                     */
/* ------------------------------------------------------------------ */

const STATUS_STYLE: Record<string, {
  border: string;
  bg: string;
  glow: string;
  text: string;
  iconColor: string;
  connectorColor: string;
}> = {
  completed: {
    border: 'border-emerald-500/60',
    bg: 'bg-emerald-500/8',
    glow: 'shadow-emerald-500/20',
    text: 'text-emerald-400',
    iconColor: 'text-emerald-400',
    connectorColor: 'stroke-emerald-500',
  },
  running: {
    border: 'border-blue-500/70',
    bg: 'bg-blue-500/10',
    glow: 'shadow-blue-500/30',
    text: 'text-blue-400',
    iconColor: 'text-blue-400',
    connectorColor: 'stroke-blue-500',
  },
  failed: {
    border: 'border-red-500/60',
    bg: 'bg-red-500/10',
    glow: 'shadow-red-500/20',
    text: 'text-red-400',
    iconColor: 'text-red-400',
    connectorColor: 'stroke-red-500',
  },
  skipped: {
    border: 'border-gray-600/40',
    bg: 'bg-gray-800/30',
    glow: '',
    text: 'text-gray-500',
    iconColor: 'text-gray-500',
    connectorColor: 'stroke-gray-600',
  },
  pending: {
    border: 'border-gray-700/50',
    bg: 'bg-gray-800/20',
    glow: '',
    text: 'text-gray-500',
    iconColor: 'text-gray-600',
    connectorColor: 'stroke-gray-700',
  },
};

function StatusBadge({ status }: { status: string }) {
  switch (status) {
    case 'completed':
      return <CheckCircle size={15} className="text-emerald-400" />;
    case 'running':
      return <Loader2 size={15} className="text-blue-400 animate-spin" />;
    case 'failed':
      return <XCircle size={15} className="text-red-400" />;
    case 'skipped':
      return <SkipForward size={15} className="text-gray-500" />;
    default:
      return <Circle size={15} className="text-gray-600" />;
  }
}

/* ------------------------------------------------------------------ */
/*  Arrow connector                                                    */
/* ------------------------------------------------------------------ */

function Arrow({ status }: { status: string }) {
  const style = STATUS_STYLE[status] || STATUS_STYLE.pending;
  const isActive = status === 'running';
  const isDone = status === 'completed';

  return (
    <div className="flex items-center justify-center self-center mx-[-2px]">
      <svg width="32" height="16" viewBox="0 0 32 16" className="overflow-visible">
        <defs>
          {isActive && (
            <linearGradient id={`flow-${status}`} x1="0" x2="1" y1="0" y2="0">
              <stop offset="0%" stopColor="currentColor" stopOpacity="0.2">
                <animate attributeName="offset" values="-0.5;1" dur="1.5s" repeatCount="indefinite" />
              </stop>
              <stop offset="40%" stopColor="currentColor" stopOpacity="1">
                <animate attributeName="offset" values="0;1.5" dur="1.5s" repeatCount="indefinite" />
              </stop>
              <stop offset="100%" stopColor="currentColor" stopOpacity="0.2">
                <animate attributeName="offset" values="0.5;2" dur="1.5s" repeatCount="indefinite" />
              </stop>
            </linearGradient>
          )}
        </defs>
        <line
          x1="0" y1="8" x2="24" y2="8"
          className={`${isDone ? 'stroke-emerald-500' : isActive ? 'stroke-blue-500' : 'stroke-gray-700'}`}
          strokeWidth="2"
          strokeDasharray={isActive ? '4 3' : 'none'}
          strokeOpacity={isDone ? 0.7 : isActive ? 1 : 0.4}
        >
          {isActive && (
            <animate attributeName="stroke-dashoffset" values="7;0" dur="0.6s" repeatCount="indefinite" />
          )}
        </line>
        <polygon
          points="24,3 32,8 24,13"
          className={`${isDone ? 'fill-emerald-500' : isActive ? 'fill-blue-500' : 'fill-gray-700'}`}
          fillOpacity={isDone ? 0.7 : isActive ? 1 : 0.4}
        />
      </svg>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Phase connector (vertical)                                         */
/* ------------------------------------------------------------------ */

function PhaseConnector({ status }: { status: string }) {
  const isDone = status === 'completed';
  const isActive = status === 'running';

  return (
    <div className="flex justify-center py-1">
      <svg width="16" height="28" viewBox="0 0 16 28">
        <line
          x1="8" y1="0" x2="8" y2="20"
          className={`${isDone ? 'stroke-emerald-500' : isActive ? 'stroke-blue-500' : 'stroke-gray-700'}`}
          strokeWidth="2"
          strokeDasharray={isActive ? '4 3' : 'none'}
          strokeOpacity={isDone ? 0.7 : isActive ? 1 : 0.4}
        >
          {isActive && (
            <animate attributeName="stroke-dashoffset" values="7;0" dur="0.6s" repeatCount="indefinite" />
          )}
        </line>
        <polygon
          points="3,20 8,28 13,20"
          className={`${isDone ? 'fill-emerald-500' : isActive ? 'fill-blue-500' : 'fill-gray-700'}`}
          fillOpacity={isDone ? 0.7 : isActive ? 1 : 0.4}
        />
      </svg>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Step card                                                          */
/* ------------------------------------------------------------------ */

function StepCard({
  meta,
  steps,
}: {
  meta: StepMeta;
  steps: PipelineStep[];
}) {
  const status = statusOf(meta.id, steps);
  const detail = detailOf(meta.id, steps);
  const duration = durationOf(meta.id, steps);
  const style = STATUS_STYLE[status] || STATUS_STYLE.pending;
  const Icon = meta.icon;

  return (
    <div
      className={`
        group relative flex flex-col items-center
        w-[140px] h-[148px] p-3 rounded-xl border transition-all duration-500
        ${style.border} ${style.bg}
        ${status === 'running' ? `shadow-lg ${style.glow} wf-pulse` : ''}
        ${status === 'completed' ? `shadow-md ${style.glow}` : ''}
      `}
    >
      <StepTooltip label={meta.label} description={meta.description} />
      {/* Step number badge */}
      <span className={`absolute -top-2 -left-2 w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold
        ${status === 'completed' ? 'bg-emerald-500/20 text-emerald-400 ring-1 ring-emerald-500/40'
        : status === 'running' ? 'bg-blue-500/20 text-blue-400 ring-1 ring-blue-500/40'
        : status === 'failed' ? 'bg-red-500/20 text-red-400 ring-1 ring-red-500/40'
        : 'bg-gray-800 text-gray-500 ring-1 ring-gray-700/50'}`}
      >
        {meta.id}
      </span>

      {/* Status badge */}
      <div className="absolute -top-2 -right-2">
        <StatusBadge status={status} />
      </div>

      {/* Icon */}
      <div className={`w-9 h-9 shrink-0 rounded-lg flex items-center justify-center
        ${status === 'completed' ? 'bg-emerald-500/15'
        : status === 'running' ? 'bg-blue-500/15'
        : status === 'failed' ? 'bg-red-500/15'
        : 'bg-gray-800/50'}`}
      >
        <Icon size={18} className={style.iconColor} />
      </div>

      {/* Label — fills remaining space so all cards are the same height */}
      <span className={`flex-1 flex items-center justify-center text-[11px] font-medium text-center leading-tight mt-1 ${style.text}`}>
        {meta.label}
      </span>

      {/* Duration — always reserves its row; empty when not yet available */}
      <span className="h-4 shrink-0 flex items-center justify-center gap-1 text-[10px] text-gray-500">
        {duration && <><Clock size={10} />{duration}</>}
      </span>

      {/* Running indicator bar */}
      {status === 'running' && (
        <div className="absolute bottom-0 left-2 right-2 h-0.5 overflow-hidden rounded-full">
          <div className="wf-progress-bar h-full rounded-full bg-blue-500" />
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Phase header                                                       */
/* ------------------------------------------------------------------ */

function PhaseHeader({
  title,
  phaseNum,
  steps,
  stepIds,
}: {
  title: string;
  phaseNum: number;
  steps: PipelineStep[];
  stepIds: string[];
}) {
  const statuses = stepIds.map(id => statusOf(id, steps));
  const completed = statuses.filter(s => s === 'completed').length;
  const total = statuses.length;
  const hasRunning = statuses.includes('running');
  const hasFailed = statuses.includes('failed');
  const allDone = completed === total && total > 0;

  return (
    <div className="flex items-center gap-3 mb-3">
      <div className={`flex items-center justify-center w-7 h-7 rounded-lg text-xs font-bold
        ${allDone ? 'bg-emerald-500/20 text-emerald-400 ring-1 ring-emerald-500/30'
        : hasRunning ? 'bg-blue-500/20 text-blue-400 ring-1 ring-blue-500/30'
        : hasFailed ? 'bg-red-500/20 text-red-400 ring-1 ring-red-500/30'
        : 'bg-gray-800 text-gray-500 ring-1 ring-gray-700/40'}`}
      >
        {phaseNum}
      </div>
      <div>
        <span className={`text-sm font-semibold ${allDone ? 'text-emerald-400' : hasRunning ? 'text-blue-400' : 'text-gray-300'}`}>
          {title}
        </span>
        <div className="flex items-center gap-2 mt-0.5">
          <div className="w-24 h-1 bg-gray-800 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-700 ease-out ${
                hasFailed ? 'bg-red-500' : allDone ? 'bg-emerald-500' : 'bg-blue-500'
              }`}
              style={{ width: `${total > 0 ? (completed / total) * 100 : 0}%` }}
            />
          </div>
          <span className="text-[10px] text-gray-500">{completed}/{total}</span>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Overall progress summary                                           */
/* ------------------------------------------------------------------ */

function OverallProgress({ steps, visibleSteps }: { steps: PipelineStep[]; visibleSteps: StepMeta[] }) {
  const totalSteps = visibleSteps.length;
  const completed = visibleSteps.filter(s => statusOf(s.id, steps) === 'completed').length;
  const running = visibleSteps.find(s => statusOf(s.id, steps) === 'running');
  const failed = visibleSteps.filter(s => statusOf(s.id, steps) === 'failed').length;
  const pct = totalSteps > 0 ? Math.round((completed / totalSteps) * 100) : 0;
  const allDone = completed === totalSteps && totalSteps > 0;

  return (
    <div className="flex items-center gap-4 mb-5">
      {/* Circular progress */}
      <div className="relative w-14 h-14 flex-shrink-0">
        <svg viewBox="0 0 56 56" className="w-full h-full -rotate-90">
          <circle cx="28" cy="28" r="24" fill="none" stroke="currentColor" strokeWidth="3"
            className="text-gray-800" />
          <circle cx="28" cy="28" r="24" fill="none" strokeWidth="3"
            className={`${allDone ? 'text-emerald-500' : failed > 0 ? 'text-red-500' : 'text-blue-500'} transition-all duration-700`}
            strokeDasharray={`${2 * Math.PI * 24}`}
            strokeDashoffset={`${2 * Math.PI * 24 * (1 - pct / 100)}`}
            strokeLinecap="round"
          />
        </svg>
        <span className={`absolute inset-0 flex items-center justify-center text-xs font-bold
          ${allDone ? 'text-emerald-400' : failed > 0 ? 'text-red-400' : 'text-blue-400'}`}>
          {pct}%
        </span>
      </div>

      {/* Stats */}
      <div className="flex flex-col gap-1">
        <span className="text-sm font-medium text-gray-300">
          {allDone
            ? 'Pipeline Complete'
            : running
            ? `Running: ${running.label}`
            : failed > 0
            ? `Failed — ${failed} step(s)`
            : 'Waiting to start'}
        </span>
        <span className="text-xs text-gray-500">
          {completed} of {totalSteps} steps completed
        </span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export default function WorkflowDiagram({
  steps,
  pipelineType = 'all',
}: {
  steps: PipelineStep[];
  pipelineType?: 'extraction' | 'comparison' | 'publish' | 'all';
}) {
  const phase1 = useMemo(() => STEPS.filter(s => s.phase === 1), []);
  const phase2 = useMemo(() => STEPS.filter(s => s.phase === 2), []);
  const phase3 = useMemo(() => PUBLISH_STEPS, []);

  // Tick every second so running-step elapsed timers stay current
  const [, setTick] = useState(0);
  useEffect(() => {
    const hasRunning = steps.some(s => s.status === 'running');
    if (!hasRunning) return;
    const id = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(id);
  }, [steps]);

  const visibleSteps = useMemo(() => {
    if (pipelineType === 'extraction') return phase1;
    if (pipelineType === 'comparison') return phase2;
    if (pipelineType === 'publish') return phase3;
    return STEPS;
  }, [pipelineType, phase1, phase2, phase3]);

  // Determine connector status between steps
  const connectorStatus = (prevId: string): string => {
    const prev = statusOf(prevId, steps);
    if (prev === 'completed') return 'completed';
    if (prev === 'running') return 'running';
    return 'pending';
  };

  // Phase connector status (between phase 1 last → phase 2 first)
  const phaseLink = (): string => {
    const last1 = statusOf('6', steps);
    if (last1 === 'completed') return 'completed';
    if (last1 === 'running') return 'running';
    return 'pending';
  };

  const showPhase1 = pipelineType === 'extraction' || pipelineType === 'all';
  const showPhase2 = pipelineType === 'comparison' || pipelineType === 'all';
  const showPublish = pipelineType === 'publish';

  return (
    <div className="wf-diagram">
      <OverallProgress steps={steps} visibleSteps={visibleSteps} />

      {/* Publish to Graph DB */}
      {showPublish && (
        <div>
          <PhaseHeader
            title="Publish to Graph DB"
            phaseNum={1}
            steps={steps}
            stepIds={phase3.map(s => s.id)}
          />
          <div className="wf-phase-body bg-gray-900/30 border border-gray-800/60 rounded-xl p-4">
            {/* Row 1: P1 → P2 → P3 */}
            <div className="flex flex-wrap items-center gap-1 justify-center">
              {phase3.slice(0, 3).map((meta, i) => (
                <div key={meta.id} className="flex items-center gap-1">
                  {i > 0 && <Arrow status={connectorStatus(phase3[i - 1].id)} />}
                  <StepCard meta={meta} steps={steps} />
                </div>
              ))}
            </div>

            {/* Vertical connector from row 1 → row 2 */}
            <PhaseConnector status={connectorStatus('P3')} />

            {/* Row 2: P4 → P5 → P6 */}
            <div className="flex flex-wrap items-center gap-1 justify-center">
              {phase3.slice(3).map((meta, i) => (
                <div key={meta.id} className="flex items-center gap-1">
                  {i > 0 && <Arrow status={connectorStatus(phase3[3 + i - 1].id)} />}
                  <StepCard meta={meta} steps={steps} />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Phase 1: Knowledge Extraction */}
      {showPhase1 && (
        <div className={showPhase2 ? 'mb-4' : ''}>
          <PhaseHeader
            title="Knowledge Extraction"
            phaseNum={1}
            steps={steps}
            stepIds={phase1.map(s => s.id)}
          />
          <div className="wf-phase-body bg-gray-900/30 border border-gray-800/60 rounded-xl p-4">
            {/* Row 1: Steps 1 → 2 → 3 → 3.5 */}
            <div className="flex flex-wrap items-center gap-1 justify-center">
              {phase1.slice(0, 4).map((meta, i) => (
                <div key={meta.id} className="flex items-center gap-1">
                  {i > 0 && <Arrow status={connectorStatus(phase1[i - 1].id)} />}
                  <StepCard meta={meta} steps={steps} />
                </div>
              ))}
            </div>

            {/* Vertical connector from row 1 → row 2 */}
            <PhaseConnector status={connectorStatus('3.5')} />

            {/* Row 2: Steps 4 → 5 → 6 */}
            <div className="flex flex-wrap items-center gap-1 justify-center">
              {phase1.slice(4).map((meta, i) => (
                <div key={meta.id} className="flex items-center gap-1">
                  {i > 0 && <Arrow status={connectorStatus(phase1[4 + i - 1].id)} />}
                  <StepCard meta={meta} steps={steps} />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Vertical connector between phases */}
      {showPhase1 && showPhase2 && (
        <PhaseConnector status={phaseLink()} />
      )}

      {/* Phase 2: Comparison & Analysis */}
      {showPhase2 && (
        <div>
          <PhaseHeader
            title="Comparison & Analysis"
            phaseNum={2}
            steps={steps}
            stepIds={phase2.map(s => s.id)}
          />
          <div className="wf-phase-body bg-gray-900/30 border border-gray-800/60 rounded-xl p-4">
            <div className="flex flex-wrap items-center gap-1 justify-center">
              {phase2.map((meta, i) => (
                <div key={meta.id} className="flex items-center gap-1">
                  {i > 0 && <Arrow status={connectorStatus(phase2[i - 1].id)} />}
                  <StepCard meta={meta} steps={steps} />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
