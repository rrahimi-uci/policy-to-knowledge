import { CheckCircle, Loader2, Circle, XCircle, SkipForward } from 'lucide-react';
import type { PipelineStep } from '../hooks/usePipeline';

const STEP_LABELS: Record<string, string> = {
  '1':   'Document Segmentation & Organization',
  '2':   'Domain Entity & Relationship Discovery',
  '3':   'Business Rules Extraction',
  '3.5': 'Rule Quality Validation',
  '4':   'Rules & Entity Integration',
  '5':   'Knowledge Graph Deduplication & Optimization',
  '6':   'Graph Visualization & Export',
  '7':   'Cross-Graph Rule Clustering',
  '8':   'Semantic Rule Alignment',
  '9':   'Graph Set Analysis',
  '10':  'Comparison Visualization & Export',
};

export default function ProgressTracker({ steps }: { steps: PipelineStep[] }) {
  return (
    <div className="space-y-2">
      {steps.map((s) => {
        const label = STEP_LABELS[s.step] || `Step ${s.step}`;
        return (
          <div
            key={s.step}
            className={`flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm ${
              s.status === 'running'
                ? 'bg-blue-500/10 border border-blue-500/30'
                : s.status === 'completed'
                ? 'bg-green-500/5 border border-transparent'
                : s.status === 'failed'
                ? 'bg-red-500/10 border border-red-500/30'
                : 'bg-gray-800/30 border border-transparent'
            }`}
          >
            {s.status === 'completed' && <CheckCircle size={18} className="text-green-400" />}
            {s.status === 'running' && <Loader2 size={18} className="text-blue-400 animate-spin" />}
            {s.status === 'failed' && <XCircle size={18} className="text-red-400" />}
            {s.status === 'skipped' && <SkipForward size={18} className="text-gray-500" />}
            {s.status === 'pending' && <Circle size={18} className="text-gray-600" />}

            <span className={s.status === 'pending' ? 'text-gray-500' : 'text-gray-200'}>
              Step {s.step}: {label}
            </span>

            {s.status === 'running' && (
              <span className="ml-auto text-xs text-blue-400 animate-pulse">In progress...</span>
            )}

            {s.detail && (
              <span className="ml-auto text-xs text-gray-500 truncate max-w-xs">{s.detail}</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
