import { useMemo } from 'react';
import { useLocation } from 'react-router-dom';
import MicroFrame from '@/components/MicroFrame';

// VITE_CA_URL is the public origin (or origin+prefix) of the assistant
// service, baked at build time. In dev defaults to localhost; in prod must be
// set via the --build-arg VITE_CA_URL at image build time, otherwise the
// iframe would resolve to the suite-shell origin and recurse.
// `??` only catches null/undefined — guard against the empty string too.
const RAW_CA_URL = import.meta.env.VITE_CA_URL as string | undefined;
const CA_URL =
  RAW_CA_URL && RAW_CA_URL.length > 0 ? RAW_CA_URL : 'http://localhost:5000/app/';

export default function Assistant() {
  const location = useLocation();

  const frameSrc = useMemo(() => {
    const sub = location.pathname.replace(/^\/assistant/, '') || '/';
    const params = new URLSearchParams({ embedded: 'true', graph_name: 'sample_guidelines_g' });
    if (sub !== '/') params.set('view', sub.replace(/^\//, ''));
    const sep = CA_URL.endsWith('/') ? '' : '/';
    return `${CA_URL}${sep}?${params.toString()}`;
  }, [location.pathname]);

  return (
    <div className="h-[calc(100vh-0px)]">
      <MicroFrame src={frameSrc} title="Assistant" />
    </div>
  );
}
