import { useEffect, useState, useRef, useCallback } from 'react';
import { fetchDocuments, fetchSubdirFiles, fetchPreview, uploadDocuments, deleteDocument, deleteFolder, createFolder } from '../api';
import { FolderOpen, FileText, Eye, ArrowLeft, Loader2, Search, Upload, FolderUp, Trash2, FolderPlus, Check, X, Maximize2, Minimize2, Download, Play } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useEmbeddedNavigate } from '../hooks/useEmbeddedNavigate';

const DOMAINS = [
  { value: 'mortgage', label: 'Mortgage' },
  { value: 'aml', label: 'AML' },
  { value: 'healthcare', label: 'Healthcare' },
  { value: 'commercial_lending', label: 'Commercial Lending' },
];

/** Map a folder name to its domain value using naming conventions.
 *  - p2k-* / fannie* / freddie* / fnma* / fhlmc* → mortgage
 *  - aml*             → aml
 *  - *lending* / *commercial* / *comercial* → commercial_lending
 *  - healthcare*      → healthcare
 *  - anything else    → '' (unclassified, visible only in "All" tab)
 */
function getFolderDomain(name: string): string {
  const lower = name.toLowerCase();
  if (
    lower.startsWith('p2k') ||
    lower.startsWith('fannie') ||
    lower.startsWith('freddie') ||
    lower.startsWith('freddies') ||
    lower.startsWith('fnma') ||
    lower.startsWith('fhlmc')
  ) return 'mortgage';
  if (lower.startsWith('aml')) return 'aml';
  if (lower.includes('lending') || lower.includes('commercial') || lower.includes('comercial')) return 'commercial_lending';
  if (lower.startsWith('healthcare')) return 'healthcare';
  return '';
}

function getFileRelativePath(file: File): string {
  const candidate = (file as File & { webkitRelativePath?: string }).webkitRelativePath;
  return candidate && candidate.trim() ? candidate : file.name;
}

function getDocumentPath(doc: { name: string; relative_path?: string }): string {
  return doc.relative_path || doc.name;
}

function encodeDocumentPath(value: string): string {
  return value
    .split('/')
    .filter(Boolean)
    .map(segment => encodeURIComponent(segment))
    .join('/');
}

const API_BASE = ((import.meta.env.VITE_API_BASE_PREFIX as string) ?? '').replace(/\/$/, '');

function rawDocumentUrl(subdir: string, filename: string): string {
  return `${API_BASE}/api/documents/raw/${encodeURIComponent(subdir)}/${encodeDocumentPath(filename)}`;
}

type UploadFeedback = {
  tone: 'success' | 'error';
  title: string;
  detail: string;
  primaryFolder?: string | null;
  domain?: string | null;
  fileName?: string | null;
};

type PreviewPayload = {
  filename: string;
  content: string;
  type?: string;
  truncated?: boolean;
};

type SpreadsheetSheet = {
  name: string;
  rows: string[][];
};

type SlidePreview = {
  title: string;
  bullets: string[];
};

function parsePreviewJson<T>(content: string, fallback: T): T {
  try {
    return JSON.parse(content) as T;
  } catch {
    return fallback;
  }
}

function resolveFolderDomain(folder: { name: string; domain?: string | null } | string, fallback = ''): string {
  if (typeof folder === 'string') return getFolderDomain(folder) || fallback;
  return folder.domain || getFolderDomain(folder.name) || fallback;
}

export default function Documents() {
  const navigate = useEmbeddedNavigate();
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<string>('all');
  const [uploadDomain, setUploadDomain] = useState<string>('');
  const [domainCounts, setDomainCounts] = useState<Record<string, number>>({});
  const [subdirs, setSubdirs] = useState<any[]>([]);
  const [docs, setDocs] = useState<any[]>([]);
  const [currentDir, setCurrentDir] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [preview, setPreview] = useState<PreviewPayload | null>(null);
  const [pdfViewer, setPdfViewer] = useState<{ filename: string; url: string; detectedAsPdfContent?: boolean } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadFeedback, setUploadFeedback] = useState<UploadFeedback | null>(null);
  const [fileSearch, setFileSearch] = useState('');
  const [dragging, setDragging] = useState(false);

  // New-folder inline input state
  const [creatingFolder, setCreatingFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const [folderError, setFolderError] = useState('');
  const newFolderInputRef = useRef<HTMLInputElement>(null);


  const folderInputRef = useRef<HTMLInputElement | null>(null);
  const folderRef = useCallback((node: HTMLInputElement | null) => {
    folderInputRef.current = node;
    if (node) {
      node.setAttribute('webkitdirectory', '');
      node.setAttribute('directory', '');
    }
  }, []);
  const dragCounter = useRef(0);
  const isAllView = activeTab === 'all';

  const load = async (subdir?: string) => {
    setLoading(true);
    try {
      if (subdir) {
        const res = await fetchSubdirFiles(subdir);
        setDocs(res.documents || []);
        setSubdirs([]);
        setCurrentDir(subdir);
      } else {
        const res = await fetchDocuments();
        setSubdirs(res.subdirectories || []);
        setDocs(res.documents || []);
        setCurrentDir(null);
      }
    } catch { /* ignore */ }
    setLoading(false);
  };

  // Aggregate file counts per domain whenever the root folder list refreshes
  useEffect(() => {
    if (subdirs.length > 0) {
      setDomainCounts(() => {
        const next: Record<string, number> = {};
        subdirs.forEach(s => {
          const domain = resolveFolderDomain(s);
          if (domain) next[domain] = (next[domain] || 0) + (s.file_count || 0);
        });
        return next;
      });
    }
  }, [subdirs]);

  const switchTab = (tab: string) => {
    setActiveTab(tab);
    setPreview(null);
    setPdfViewer(null);
    setSelected(new Set());
    setFileSearch('');
    // If we're inside a folder, go back to root; the filter will handle the rest
    if (currentDir !== null) load();
  };

  useEffect(() => { load(); }, []);

  // Close any open preview on Escape key
  useEffect(() => {
    if (!pdfViewer && !preview) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setPdfViewer(null);
        setPreview(null);
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [pdfViewer, preview]);

  // Focus the new-folder input when it appears
  useEffect(() => {
    if (creatingFolder) {
      setTimeout(() => newFolderInputRef.current?.focus(), 50);
    }
  }, [creatingFolder]);

  const toggleSelect = (name: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === filteredDocs.length) setSelected(new Set());
    else setSelected(new Set(filteredDocs.map(d => getDocumentPath(d))));
  };

  const handlePreview = async (filename: string) => {
    const dir = currentDir || 'sample-guidelines';
    // Open PDFs directly in full-screen viewer
    if (filename.toLowerCase().endsWith('.pdf')) {
      const url = rawDocumentUrl(dir, filename);
      setPreview(null);
      setPdfViewer({ filename, url, detectedAsPdfContent: false });
      return;
    }
    try {
      const res = await fetchPreview(dir, filename);
      if (res.type === 'pdf_embed' || res.type === 'pdf_text') {
        const url = rawDocumentUrl(dir, filename);
        setPreview(null);
        setPdfViewer({
          filename,
          url,
          detectedAsPdfContent: !filename.toLowerCase().endsWith('.pdf'),
        });
        return;
      }
      setPdfViewer(null);
      setPreview(res);
    } catch { /* ignore */ }
  };

  const handleUpload = async (files: FileList) => {
    if (isAllView) {
      setUploadFeedback({
        tone: 'error',
        title: 'Select a domain first',
        detail: 'The All tab is read-only. Switch to a domain tab to upload files or folders with the correct extraction prompts.',
      });
      return;
    }
    setUploading(true);
    setUploadFeedback(null);
    // When not inside a specific folder, route to a domain-appropriate folder so
    // the uploaded files are visible in the active tab after upload.
    const domainDefaultDir: Record<string, string> = {
      mortgage: 'p2k-uploads',
    };
    const fileList = Array.from(files);
    const relativePaths = fileList.map(getFileRelativePath);
    const isFolderUpload = relativePaths.some(path => path.includes('/'));
    const selectedDomain = activeTab !== 'all' ? activeTab : (uploadDomain || undefined);
    if (!currentDir && isFolderUpload && !selectedDomain) {
      setUploadFeedback({
        tone: 'error',
        title: 'Select a target domain',
        detail: 'Choose the domain for this folder before uploading so the correct extraction prompts are used.',
      });
      setUploading(false);
      return;
    }
    const dir = currentDir ?? (!isFolderUpload && activeTab !== 'all' ? (domainDefaultDir[activeTab] ?? 'uploads') : (!isFolderUpload ? 'uploads' : undefined));

    try {
      const res = await uploadDocuments(dir, fileList, {
        relativePaths: isFolderUpload ? relativePaths : undefined,
        domain: !currentDir && isFolderUpload ? selectedDomain : undefined,
      });
      // Reset inputs so the same file can be re-uploaded without a page refresh

      if (folderInputRef.current) folderInputRef.current.value = '';

      const uploadedCount = res.count || 0;
      const primaryFolder = res.primary_folder ?? currentDir ?? dir ?? null;
      const primaryDomain = res.domain ?? (primaryFolder ? resolveFolderDomain(primaryFolder) : selectedDomain ?? null);

      if (isFolderUpload && !currentDir) {
        if (primaryDomain) setActiveTab(primaryDomain);
        await load();
      } else if (primaryFolder) {
        await load(primaryFolder);
      } else {
        await load();
      }

      if (uploadedCount === 0) {
        setUploadFeedback({
          tone: 'error',
          title: 'No supported files were uploaded',
          detail: 'Upload PDF, TXT, MD, CSV, XLSX, DOCX, or PPTX files to continue.',
        });
        return;
      }

      const title = isFolderUpload ? 'Folder upload complete — ready for extraction' : 'Upload complete — ready for extraction';
      const detail = isFolderUpload
        ? primaryFolder
          ? `Stored ${uploadedCount} file${uploadedCount === 1 ? '' : 's'} in ${primaryFolder}. Click "Run Pipeline" to generate the knowledge graph.`
          : `Stored ${uploadedCount} file${uploadedCount === 1 ? '' : 's'} with preserved folder paths. Click "Run Pipeline" to continue.`
        : `Stored ${uploadedCount} file${uploadedCount === 1 ? '' : 's'} in ${primaryFolder ?? 'documents'}. Click "Run Pipeline" to generate the knowledge graph.`;

      setUploadFeedback({
        tone: 'success',
        title,
        detail,
        primaryFolder,
        domain: primaryDomain,
        fileName: !isFolderUpload && uploadedCount === 1 ? fileList[0]?.name ?? null : null,
      });
    } catch (err: any) {
      setUploadFeedback({
        tone: 'error',
        title: isFolderUpload ? 'Folder upload failed' : 'Upload failed',
        detail: err?.message || 'The upload could not be completed.',
      });
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteFile = async (filename: string) => {
    if (isAllView) return;
    const dir = currentDir || '';
    if (!dir) return;
    if (!window.confirm(`Delete "${filename}"? This cannot be undone.`)) return;
    try {
      await deleteDocument(dir, filename);
      if (preview?.filename === filename) setPreview(null);
      setSelected(prev => { const s = new Set(prev); s.delete(filename); return s; });
      load(dir);
    } catch { /* ignore */ }
  };

  const handleDeleteFolder = async (folderName: string) => {
    if (isAllView) return;
    if (!window.confirm(`Delete folder "${folderName}" and all its files? This cannot be undone.`)) return;
    try {
      await deleteFolder(folderName);
      load();
    } catch { /* ignore */ }
  };

  const handleDeleteSelected = async () => {
    if (isAllView) return;
    const dir = currentDir || '';
    if (!dir || selected.size === 0) return;
    if (!window.confirm(`Delete ${selected.size} selected file${selected.size > 1 ? 's' : ''}? This cannot be undone.`)) return;
    await Promise.allSettled([...selected].map(f => deleteDocument(dir, f)));
    setSelected(new Set());
    if (preview && selected.has(preview.filename)) setPreview(null);
    load(dir);
  };

  const handleCreateFolder = async () => {
    if (isAllView) return;
    const name = newFolderName.trim();
    if (!name) { setFolderError('Folder name cannot be empty'); return; }
    if (/[/\\.]/.test(name)) { setFolderError('Invalid characters in folder name'); return; }
    try {
      await createFolder(name, activeTab !== 'all' ? activeTab : undefined);
      setCreatingFolder(false);
      setNewFolderName('');
      setFolderError('');
      load();
    } catch (err: any) {
      setFolderError(err.message?.includes('409') ? 'Folder already exists' : 'Failed to create folder');
    }
  };

  const cancelCreateFolder = () => {
    setCreatingFolder(false);
    setNewFolderName('');
    setFolderError('');
  };

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    if (isAllView) return;
    e.preventDefault();
    dragCounter.current++;
    if (e.dataTransfer.types.includes('Files')) setDragging(true);
  }, [isAllView]);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    if (isAllView) return;
    e.preventDefault();
    dragCounter.current--;
    if (dragCounter.current === 0) setDragging(false);
  }, [isAllView]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    if (isAllView) return;
    e.preventDefault();
  }, [isAllView]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    if (isAllView) return;
    e.preventDefault();
    dragCounter.current = 0;
    setDragging(false);
    const files = e.dataTransfer.files;
    if (files.length > 0) handleUpload(files);
  }, [handleUpload, isAllView]);

  const openExtraction = useCallback((folderName: string, domainOverride?: string | null, fileName?: string | null) => {
    navigate('/pipeline', {
      state: {
        pipelineTab: 'creation',
        preselectedFolder: folderName,
        preselectedDomain: domainOverride || getFolderDomain(folderName) || (activeTab !== 'all' ? activeTab : undefined),
        preselectedFile: fileName || undefined,
      },
    });
  }, [activeTab, navigate]);

  const filteredSubdirs = activeTab === 'all'
    ? subdirs
    : subdirs.filter(s => resolveFolderDomain(s) === activeTab);

  const filteredDocs = docs.filter(d =>
    !fileSearch || getDocumentPath(d).toLowerCase().includes(fileSearch.toLowerCase())
  );

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1048576).toFixed(1)} MB`;
  };

  const extIcon = (ext: string) => {
    const colors: Record<string, string> = {
      '.md': 'text-blue-400', '.pdf': 'text-red-400', '.csv': 'text-green-400',
      '.xlsx': 'text-green-400', '.docx': 'text-indigo-400', '.txt': 'text-gray-400',
      '.pptx': 'text-orange-400',
    };
    return colors[ext] || 'text-gray-400';
  };

  return (
    <div
      className="flex gap-6 h-full relative"
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {/* Drag overlay */}
      {dragging && !isAllView && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-gray-950/80 border-2 border-dashed border-blue-500 rounded-2xl">
          <div className="text-center">
            <Upload size={40} className="mx-auto text-blue-400 mb-3" />
            <p className="text-lg font-medium text-blue-300">Drop files or folders to upload</p>
            <p className="text-sm text-gray-500 mt-1">Items will be added to {currentDir || 'documents'}</p>
          </div>
        </div>
      )}

      {/* File List */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            {currentDir && (
              <button type="button" onClick={() => load()} title="Back to folders" aria-label="Back to folders" className="p-1.5 rounded hover:bg-gray-800">
                <ArrowLeft size={18} className="text-gray-400" />
              </button>
            )}
            <h2 className="text-2xl font-bold">Domain Documents</h2>
            {currentDir && (
              <span className="text-sm text-gray-500">
                {activeTab !== 'all' && `${DOMAINS.find(d => d.value === activeTab)?.label} / `}{currentDir}
              </span>
            )}
          </div>
          <div className="flex gap-2">
            <input
              ref={folderRef}
              type="file"
              title="Upload folder"
              aria-label="Upload folder"
              className="hidden"
              onChange={(e) => e.target.files && handleUpload(e.target.files)}
            />
            {!isAllView ? (
              <>
                <button
                  type="button"
                  onClick={() => folderInputRef.current?.click()}
                  disabled={uploading}
                  className="flex items-center gap-2 px-4 py-2 bg-gray-700 hover:bg-gray-600 disabled:bg-gray-800 text-white text-sm rounded-lg transition-colors"
                >
                  <FolderUp size={16} /> Add Folder
                </button>

              </>
            ) : (
              <span className="rounded-lg border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-gray-400">
                All domains is view-only. Switch to a domain tab to upload or create folders.
              </span>
            )}
          </div>
        </div>

        {/* Domain tab bar */}
        <div className="flex gap-1 p-1 bg-gray-900 border border-gray-800 rounded-xl mb-4 w-fit">
          <button
            type="button"
            onClick={() => switchTab('all')}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              activeTab === 'all'
                ? 'bg-gray-700 text-gray-200 shadow-sm'
                : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50'
            }`}
          >
            All
          </button>
          {DOMAINS.map(d => (
            <button
              key={d.value}
              type="button"
              onClick={() => switchTab(d.value)}
              className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                activeTab === d.value
                  ? 'bg-blue-500/15 text-blue-400 border border-blue-500/30 shadow-sm'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50 border border-transparent'
              }`}
            >
              {d.label}
              {domainCounts[d.value] != null && (
                <span className="text-[10px] bg-gray-800 text-gray-500 px-1.5 py-0.5 rounded-full">
                  {domainCounts[d.value]}
                </span>
              )}
            </button>
          ))}
        </div>

        {uploadFeedback && (
          <div className={`mb-4 rounded-xl border overflow-hidden ${
            uploadFeedback.tone === 'success'
              ? 'border-green-500/30 bg-green-500/10'
              : 'border-red-500/30 bg-red-500/10'
          }`}>
            <div className="flex items-start justify-between gap-4 px-4 py-3">
              <div>
                <p className={`text-sm font-medium ${uploadFeedback.tone === 'success' ? 'text-green-300' : 'text-red-300'}`}>
                  {uploadFeedback.title}
                </p>
                <p className="mt-1 text-sm text-gray-300">{uploadFeedback.detail}</p>
              </div>
              <button
                type="button"
                onClick={() => setUploadFeedback(null)}
                className="rounded-lg p-2 text-gray-400 transition-colors hover:bg-gray-800 hover:text-gray-200 shrink-0"
                title="Dismiss upload feedback"
                aria-label="Dismiss upload feedback"
              >
                <X size={14} />
              </button>
            </div>
            {uploadFeedback.tone === 'success' && uploadFeedback.primaryFolder && (
              <div className="flex items-center justify-between gap-4 px-4 py-3 bg-blue-500/10 border-t border-blue-500/20">
                <div className="flex items-center gap-2 text-xs text-blue-300">
                  {uploadFeedback.fileName && (
                    <><FileText size={13} className="text-blue-400" /><span className="font-medium">{uploadFeedback.fileName}</span><span className="text-gray-500">in</span></>
                  )}
                  <FolderOpen size={13} className="text-blue-400" />
                  <span className="font-medium">{uploadFeedback.primaryFolder}</span>
                  <span className="text-gray-500 ml-1">→</span>
                  <span className="text-blue-200 font-medium">Next: generate knowledge graph</span>
                </div>
                <button
                  type="button"
                  onClick={() => openExtraction(uploadFeedback.primaryFolder!, uploadFeedback.domain, uploadFeedback.fileName)}
                  className="flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-blue-500 shadow-lg shadow-blue-600/20 animate-pulse"
                >
                  <Play size={14} /> Run Pipeline
                </button>
              </div>
            )}
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center h-40">
            <Loader2 className="animate-spin text-blue-400" size={24} />
          </div>
        ) : (
          <>
            {/* Subdirectory cards */}
            {filteredSubdirs.length > 0 && (
              <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mb-4">
                {filteredSubdirs.map(s => (
                  <div
                    key={s.name}
                    className="flex items-center gap-3 p-4 bg-gray-900 border border-gray-800 rounded-xl hover:border-gray-700 cursor-pointer transition-colors group"
                  >
                    <button
                      type="button"
                      className="flex items-center gap-3 flex-1 text-left"
                      onClick={() => load(s.name)}
                    >
                      <FolderOpen size={20} className="text-amber-400" />
                      <div>
                        <p className="text-sm font-medium text-gray-200">{s.name}</p>
                        <p className="text-xs text-gray-500">{s.file_count} files{resolveFolderDomain(s) ? ` · ${DOMAINS.find(d => d.value === resolveFolderDomain(s))?.label ?? resolveFolderDomain(s)}` : ''}</p>
                      </div>
                    </button>
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); openExtraction(s.name, resolveFolderDomain(s)); }}
                        className="p-1.5 rounded hover:bg-blue-500/20"
                        title="Extract knowledge"
                      >
                        <Play size={15} className="text-blue-400" />
                      </button>
                      {!isAllView && (
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); handleDeleteFolder(s.name); }}
                          className="p-1.5 rounded hover:bg-red-500/20"
                          title="Delete folder"
                        >
                          <Trash2 size={15} className="text-red-400" />
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* File list */}
            {docs.length > 0 && (
              <div className="bg-gray-900 border border-gray-800 rounded-xl">
                {/* File search + header */}
                <div className="flex items-center gap-3 px-4 py-2.5 border-b border-gray-800">
                  {!isAllView && (
                    <input
                      type="checkbox"
                      aria-label="Select all files"
                      checked={selected.size === filteredDocs.length && filteredDocs.length > 0}
                      onChange={toggleAll}
                      className="accent-blue-500"
                    />
                  )}
                  <div className="relative flex-1 max-w-xs">
                    <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500" />
                    <input
                      value={fileSearch}
                      aria-label="Filter files"
                      onChange={e => setFileSearch(e.target.value)}
                      placeholder="Filter files..."
                      className="w-full pl-8 pr-3 py-1 bg-gray-800 border border-gray-700 rounded text-xs text-gray-200 focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  <span className="text-xs text-gray-500">
                    {selected.size > 0 ? `${selected.size} selected` : `${filteredDocs.length} files`}
                  </span>
                  {!isAllView && selected.size > 0 && (
                    <button
                      type="button"
                      onClick={handleDeleteSelected}
                      className="ml-auto flex items-center gap-1.5 px-3 py-1 bg-red-600/20 text-red-400 text-xs rounded hover:bg-red-600/30 border border-red-500/30"
                    >
                      <Trash2 size={12} />
                      Delete ({selected.size})
                    </button>
                  )}
                </div>
                {filteredDocs.map(d => (
                  <div
                    key={getDocumentPath(d)}
                    className="flex items-center gap-3 px-4 py-2.5 border-b border-gray-800/50 last:border-0 hover:bg-gray-800/30 transition-colors group"
                  >
                    {!isAllView && (
                      <input
                        type="checkbox"
                        aria-label={`Select ${getDocumentPath(d)}`}
                        checked={selected.has(getDocumentPath(d))}
                        onChange={() => toggleSelect(getDocumentPath(d))}
                        className="accent-blue-500"
                      />
                    )}
                    <FileText size={16} className={extIcon(d.extension)} />
                    <div className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-gray-200">{d.name}</span>
                      {getDocumentPath(d) !== d.name && (
                        <span className="block truncate text-xs text-gray-500">{getDocumentPath(d)}</span>
                      )}
                    </div>
                    <span className="text-xs text-gray-500">{formatSize(d.size)}</span>
                    <button
                      type="button"
                      onClick={() => handlePreview(getDocumentPath(d))}
                      className="p-1.5 rounded hover:bg-gray-700 opacity-0 group-hover:opacity-100 transition-opacity"
                      title={`Preview ${getDocumentPath(d)}`}
                      aria-label={`Preview ${getDocumentPath(d)}`}
                    >
                      <Eye size={14} className="text-gray-400" />
                    </button>
                    {!isAllView && (
                      <button
                        type="button"
                        onClick={() => handleDeleteFile(getDocumentPath(d))}
                        className="p-1.5 rounded hover:bg-red-500/20 opacity-0 group-hover:opacity-100 transition-opacity"
                        title={`Delete ${getDocumentPath(d)}`}
                        aria-label={`Delete ${getDocumentPath(d)}`}
                      >
                        <Trash2 size={14} className="text-red-400" />
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}

            {docs.length === 0 && filteredSubdirs.length === 0 && !creatingFolder && (
              <div className="bg-gray-900 border border-gray-800 border-dashed rounded-xl p-10 flex flex-col items-center gap-4 text-center">
                <Upload size={32} className="text-gray-600" />
                <div>
                  <p className="text-gray-300 font-medium mb-1">
                    {activeTab === 'all' ? 'No documents yet' : `No ${DOMAINS.find(d => d.value === activeTab)?.label ?? activeTab} documents yet`}
                  </p>
                  <p className="text-sm text-gray-500">
                    {activeTab === 'all' ? 'Switch to a domain tab to upload files or create folders.' : 'Upload files to add them to this domain.'}
                  </p>
                </div>

              </div>
            )}
          </>
        )}
      </div>

      {/* Full-screen viewer for non-PDF files */}
      {preview && (
        <div className="fixed inset-0 z-50 flex flex-col bg-gray-950/95 backdrop-blur-sm">
          <div className="flex items-center justify-between px-6 py-3 bg-gray-900 border-b border-gray-800 shrink-0">
            <div className="flex items-center gap-3 min-w-0">
              <FileText size={18} className="text-blue-400 shrink-0" />
              <h2 className="text-sm font-medium text-gray-200 truncate">{preview.filename}</h2>
            </div>
            <div className="flex items-center gap-2">
              {currentDir && (
                <a
                  href={rawDocumentUrl(currentDir, preview.filename)}
                  download={preview.filename}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-300 bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors"
                  title="Download document"
                >
                  <Download size={14} /> Download
                </a>
              )}
              {currentDir && (
                <button
                  type="button"
                  onClick={() => window.open(rawDocumentUrl(currentDir, preview.filename), '_blank')}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-300 bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors"
                  title="Open in new tab"
                >
                  <Maximize2 size={14} /> New Tab
                </button>
              )}
              <button
                type="button"
                onClick={() => setPreview(null)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-300 bg-gray-800 hover:bg-red-500/20 hover:text-red-300 rounded-lg transition-colors"
                title="Close viewer"
              >
                <X size={14} /> Close
              </button>
            </div>
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto px-6 py-5">
            {preview.type === 'docx_html' ? (
              <div className="mx-auto max-w-3xl rounded-2xl border border-gray-800 bg-white text-gray-900 shadow-2xl">
                <div
                  className="docx-preview prose max-w-none px-10 py-12 prose-headings:font-semibold prose-headings:text-gray-900 prose-h1:text-3xl prose-h2:text-2xl prose-h3:text-xl prose-p:leading-relaxed prose-p:text-gray-800 prose-a:text-blue-700 prose-strong:text-gray-900 prose-li:text-gray-800 prose-table:text-sm prose-th:bg-gray-100 prose-th:text-gray-900 prose-td:border prose-td:border-gray-200 prose-th:border prose-th:border-gray-200 prose-blockquote:border-l-4 prose-blockquote:border-blue-500 prose-blockquote:bg-blue-50 prose-blockquote:px-4 prose-blockquote:py-2 prose-blockquote:not-italic prose-img:rounded-lg prose-img:shadow"
                  dangerouslySetInnerHTML={{ __html: preview.content }}
                />
              </div>
            ) : preview.type === 'markdown' || preview.type === 'docx_text' || preview.filename.endsWith('.md') ? (
              <div className="mx-auto max-w-4xl rounded-2xl border border-gray-800 bg-gray-900/60 px-8 py-10 shadow-xl">
                <div className="prose prose-invert max-w-none prose-headings:text-gray-100 prose-headings:font-semibold prose-h1:border-b prose-h1:border-gray-800 prose-h1:pb-2 prose-h2:border-b prose-h2:border-gray-800/70 prose-h2:pb-1 prose-p:text-gray-300 prose-p:leading-relaxed prose-a:text-blue-400 prose-strong:text-gray-100 prose-em:text-gray-200 prose-code:text-blue-300 prose-code:bg-gray-800 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:before:content-none prose-code:after:content-none prose-pre:bg-gray-950 prose-pre:border prose-pre:border-gray-800 prose-pre:rounded-lg prose-li:text-gray-300 prose-blockquote:border-l-4 prose-blockquote:border-blue-500/70 prose-blockquote:text-gray-300 prose-blockquote:bg-gray-800/40 prose-blockquote:py-1 prose-blockquote:px-4 prose-blockquote:not-italic prose-table:text-sm prose-th:bg-gray-800 prose-th:text-gray-100 prose-th:border prose-th:border-gray-700 prose-td:border prose-td:border-gray-800 prose-td:text-gray-300 prose-hr:border-gray-800 prose-img:rounded-lg">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{preview.content}</ReactMarkdown>
                </div>
              </div>
            ) : preview.type === 'csv' || preview.filename.endsWith('.csv') ? (
              <div className="overflow-x-auto rounded-xl border border-gray-800 bg-gray-900">
                <table className="w-full text-sm text-gray-300 border-collapse">
                  {preview.content.split('\n').filter(Boolean).slice(0, 50).map((row, ri) => {
                    const cells = row.split(',');
                    const Tag = ri === 0 ? 'th' : 'td';
                    return (
                      <tr key={ri} className={ri === 0 ? 'bg-gray-800' : ri % 2 ? 'bg-gray-900/50' : ''}>
                        {cells.map((c, ci) => (
                          <Tag key={ci} className="px-3 py-2 border border-gray-800 text-left whitespace-nowrap align-top">
                            {c.trim().replace(/^"|"$/g, '')}
                          </Tag>
                        ))}
                      </tr>
                    );
                  })}
                </table>
              </div>
            ) : preview.type === 'xlsx_sheets' ? (
              <div className="space-y-6">
                {parsePreviewJson<SpreadsheetSheet[]>(preview.content, []).map((sheet) => (
                  <section key={sheet.name} className="rounded-xl border border-gray-800 bg-gray-900 overflow-hidden">
                    <div className="px-4 py-3 border-b border-gray-800 bg-gray-900/80">
                      <h3 className="text-sm font-medium text-gray-200">{sheet.name}</h3>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm text-gray-300 border-collapse">
                        {sheet.rows.map((row, rowIndex) => {
                          const Tag = rowIndex === 0 ? 'th' : 'td';
                          return (
                            <tr key={`${sheet.name}-${rowIndex}`} className={rowIndex === 0 ? 'bg-gray-800' : rowIndex % 2 ? 'bg-gray-900/50' : ''}>
                              {row.map((cell, cellIndex) => (
                                <Tag key={cellIndex} className="px-3 py-2 border border-gray-800 text-left whitespace-nowrap align-top">
                                  {cell || ' '}
                                </Tag>
                              ))}
                            </tr>
                          );
                        })}
                      </table>
                    </div>
                  </section>
                ))}
              </div>
            ) : preview.type === 'pptx_slides' ? (
              <div className="space-y-4">
                {parsePreviewJson<SlidePreview[]>(preview.content, []).map((slide, index) => (
                  <section key={`${slide.title}-${index}`} className="rounded-xl border border-gray-800 bg-gray-900 p-5">
                    <p className="text-xs uppercase tracking-[0.2em] text-gray-500 mb-2">Slide {index + 1}</p>
                    <h3 className="text-lg font-semibold text-gray-100 mb-3">{slide.title}</h3>
                    {slide.bullets.length > 0 ? (
                      <ul className="space-y-2 list-disc list-inside text-gray-300">
                        {slide.bullets.map((bullet, bulletIndex) => (
                          <li key={bulletIndex}>{bullet}</li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-sm text-gray-400">No additional bullet content extracted from this slide.</p>
                    )}
                  </section>
                ))}
              </div>
            ) : (
              <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
                <pre className="text-sm text-gray-300 whitespace-pre-wrap leading-relaxed font-mono">
                  {preview.content}
                </pre>
              </div>
            )}
            {preview.truncated && (
              <p className="mt-4 text-xs text-gray-500 italic">Preview truncated to keep the viewer responsive.</p>
            )}
          </div>
        </div>
      )}

      {/* Full-screen PDF Viewer Modal */}
      {pdfViewer && (
        <div className="fixed inset-0 z-50 flex flex-col bg-gray-950/95 backdrop-blur-sm">
          {/* Header bar */}
          <div className="flex items-center justify-between px-6 py-3 bg-gray-900 border-b border-gray-800 shrink-0">
            <div className="flex items-center gap-3 min-w-0">
              <FileText size={18} className="text-red-400 shrink-0" />
              <h2 className="text-sm font-medium text-gray-200 truncate">{pdfViewer.filename}</h2>
                {pdfViewer.detectedAsPdfContent && (
                  <span className="shrink-0 rounded-full border border-amber-400/40 bg-amber-500/15 px-2 py-0.5 text-[11px] font-medium text-amber-200">
                    Detected as PDF content
                  </span>
                )}
            </div>
            <div className="flex items-center gap-2">
              <a
                href={pdfViewer.url}
                download={pdfViewer.filename}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-300 bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors"
                title="Download PDF"
              >
                <Download size={14} /> Download
              </a>
              <button
                type="button"
                onClick={() => window.open(pdfViewer.url, '_blank')}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-300 bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors"
                title="Open in new tab"
              >
                <Maximize2 size={14} /> New Tab
              </button>
              <button
                type="button"
                onClick={() => setPdfViewer(null)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-300 bg-gray-800 hover:bg-red-500/20 hover:text-red-300 rounded-lg transition-colors"
                title="Close viewer"
              >
                <X size={14} /> Close
              </button>
            </div>
          </div>
          {/* PDF iframe */}
          <div className="flex-1 min-h-0">
            <iframe
              src={pdfViewer.url}
              className="w-full h-full border-0"
              title={`PDF viewer: ${pdfViewer.filename}`}
            />
          </div>
        </div>
      )}
    </div>
  );
}
