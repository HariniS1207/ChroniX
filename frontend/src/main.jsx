import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Activity, ArrowLeft, ArrowUpRight, Check, ChevronDown, Clock3, FileText, Radio, Search, ShieldCheck, UploadCloud, X } from 'lucide-react'
import './styles.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8001'
const DEMO_URL = import.meta.env.VITE_DEMO_URL || 'http://localhost:9000'
const stages = ['Collect', 'Extract', 'Correlate', 'Reconstruct', 'Verify']

function Badge({ value }) {
  return <span className={`badge badge-${value.toLowerCase()}`}><span className="badge-mark">{value === 'FACT' ? 'F' : value === 'INFERENCE' ? 'I' : value === 'CONFLICT' ? 'C' : '?'}</span>{value}</span>
}

function EmptyState() {
  return <div className="empty"><Search size={30} /><h2>Start with the evidence</h2><p>Upload the files that describe one incident. ChroniX will keep each conclusion attached to its source.</p></div>
}

function ClaimList({ title, claims }) {
  if (!claims?.length) return null
  return <div className="ai-claims"><strong>{title}</strong><ul>{claims.map((claim, index) => <li key={index}>{claim.description}{claim.confidence !== null && claim.confidence !== undefined ? ` (${Math.round(claim.confidence * 100)}% confidence)` : ''}<small>Evidence: {claim.evidence_ids.join(', ') || 'none referenced'}</small></li>)}</ul></div>
}

function AIEnrichment({ analysis }) {
  const enrichment = analysis.llm_enrichment
  const labels = { local_pending: 'LOCAL PENDING', local_processing: 'LOCAL PROCESSING', local: 'LOCAL', local_unavailable: 'LOCAL UNAVAILABLE', local_failed: 'LOCAL FAILED', unavailable: 'UNAVAILABLE', failed: 'FAILED', invalid_response: 'INVALID RESPONSE', used: 'USED' }
  const messages = { local_pending: 'Evidence is ready. Local enrichment will run after the current event burst.', local_processing: 'Local enrichment is processing the complete incident evidence.', local_unavailable: 'Local model unavailable. Deterministic analysis is active.', local_failed: 'Local model request failed. Deterministic analysis is active.', unavailable: 'LLM enrichment unavailable. Deterministic analysis is active.', failed: 'LLM request failed. Deterministic analysis is active.', invalid_response: 'Local model response was rejected. Deterministic analysis is active.' }
  return <section className="ai-panel"><div className="section-heading"><div><p className="eyebrow">Reasoning layer</p><h2>AI analysis</h2></div><span className={`ai-status ai-status-${analysis.llm_status}`}>LLM: {labels[analysis.llm_status] || analysis.llm_status}</span></div>{(analysis.llm_status === 'local' || analysis.llm_status === 'used') && enrichment ? <><p className="ai-summary">{enrichment.incident_summary}</p><div className="ai-grid"><ClaimList title="Probable causes" claims={enrichment.probable_causes} /><ClaimList title="Contributing factors" claims={enrichment.contributing_factors} /><ClaimList title="Uncertainty" claims={enrichment.uncertainty} /><ClaimList title="Recommendations" claims={enrichment.investigation_recommendations.map(description => ({ description, evidence_ids: [], confidence: null }))} /></div></> : <p className="muted">{messages[analysis.llm_status] || 'Deterministic analysis is active.'}</p>}</section>
}

function Timeline({ events }) {
  const [open, setOpen] = useState(null)
  return <section className="timeline-section"><div className="section-heading"><div><p className="eyebrow">Reconstructed sequence</p><h2>Incident timeline</h2></div><span className="count">{events.length} events</span></div><div className="timeline">{events.map((item, index) => <article className="event" key={`${item.source_id || item.source}-${index}`}><div className="event-rail"><span className="event-dot" /></div><div className="event-time">{item.timestamp ? new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }) : '-'}</div><div className="event-body"><div className="event-top"><h3>{item.event}</h3><Badge value={item.classification || 'UNKNOWN'} /></div><div className="event-meta"><span><FileText size={14} />{item.source || item.source_name}</span>{item.related_event_ids?.length > 0 && <span>{item.related_event_ids.length} related</span>}</div><button className="evidence-toggle" onClick={() => setOpen(open === index ? null : index)}>{open === index ? 'Hide source evidence' : 'View source evidence'}<ChevronDown size={15} className={open === index ? 'rotate' : ''} /></button>{open === index && <div className="evidence"><strong>Evidence</strong><p>{item.evidence || item.raw_evidence}</p></div>}</div></article>)}</div></section>
}

function InsightColumn({ title, items, kind }) {
  return <div className="insight"><div className="insight-title"><span className={`insight-line line-${kind}`} /><h3>{title}</h3><span>{items.length}</span></div>{items.length ? <ul>{items.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p className="muted">None identified in the available evidence.</p>}</div>
}

function EvidenceRelationships({ analysis }) {
  const events = analysis.timeline || []
  const byId = Object.fromEntries(events.map(event => [event.source_id, event]))
  const relationships = analysis.relationships || []
  return <section className="relationships-section"><div className="section-heading"><div><p className="eyebrow">Traceable evidence graph</p><h2>Evidence relationships</h2></div><span className="count">{relationships.length} links</span></div>{relationships.length ? <div className="relationship-list">{relationships.map((rel, index) => { const source = byId[rel.source_evidence_id]; const target = byId[rel.target_evidence_id]; return <article className="relationship-row" key={rel.relationship_id || `${rel.source_evidence_id}-${rel.target_evidence_id}-${index}`}><div className="relationship-node"><Badge value={source?.classification || 'UNKNOWN'} /><span>{source?.event || rel.source_evidence_id}</span><small>{source?.source || rel.source_evidence_id}</small></div><div className="relationship-edge"><strong>{rel.relationship_type.replaceAll('_', ' ')}</strong><span>{Math.round((rel.confidence || 0) * 100)}% confidence</span></div><div className="relationship-node"><Badge value={target?.classification || 'UNKNOWN'} /><span>{target?.event || rel.target_evidence_id}</span><small>{target?.source || rel.target_evidence_id}</small></div><p>{rel.basis}</p></article> })}</div> : <p className="muted">No relationships are supported by the available evidence yet.</p>}</section>
}

function IntelligenceWorkspace({ analysis }) {
  return <><section className="overview"><div><p className="eyebrow">Incident overview</p><h2>{analysis.incident_title}</h2><p>{analysis.summary}</p></div><div className="root-status"><span>Root cause</span><strong>{analysis.root_cause_status}</strong></div></section><Timeline events={analysis.timeline} /><EvidenceRelationships analysis={analysis} /><AIEnrichment analysis={analysis} /><section className="intelligence"><div className="section-heading"><div><p className="eyebrow">Deterministic interpretation</p><h2>Incident intelligence</h2></div></div><div className="insight-grid"><InsightColumn title="Facts" items={analysis.facts} kind="fact" /><InsightColumn title="Inferences" items={analysis.inferences} kind="inference" /><InsightColumn title="Conflicts" items={analysis.conflicts} kind="conflict" /><InsightColumn title="Unknowns" items={analysis.unknowns} kind="unknown" /></div></section><section className="gaps"><div><p className="eyebrow">Next investigation move</p><h2>Missing evidence</h2></div><ul>{analysis.missing_evidence.map((item, index) => <li key={index}>{item}<ArrowUpRight size={15} /></li>)}</ul></section></>
}

function HistoryList({ incidents, onSelect }) {
  if (!incidents.length) return <div className="history-empty"><Clock3 size={30} /><h2>No incidents recorded yet.</h2><p>Completed incidents will appear here once ChroniX has persistent evidence.</p></div>
  return <div className="history-list">{incidents.map(incident => <button className="history-row" key={incident.incident_id} onClick={() => onSelect(incident.incident_id)}><div><strong>{incident.incident_title}</strong><small>{incident.incident_id}</small></div><span>{new Date(incident.updated_at).toLocaleString()}</span><span>{incident.evidence_count} evidence</span><span>{incident.root_cause_status}</span><span className={`history-status status-${incident.llm_status}`}>{(incident.llm_status || 'unavailable').replaceAll('_', ' ').toUpperCase()}</span></button>)}</div>
}

function EvidenceUpload({ incidentId, onUploaded }) {
  const [file, setFile] = useState(null)
  const [targets, setTargets] = useState([])
  const [target, setTarget] = useState(incidentId || '')
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)
  useEffect(() => {
    if (incidentId) return undefined
    fetch(`${API_URL}/api/v1/incidents`).then(response => response.json()).then(setTargets).catch(() => setTargets([]))
    return undefined
  }, [incidentId])
  const submit = async () => {
    if (!file) return
    setUploading(true); setStatus('Uploading evidence...'); setError('')
    const body = new FormData(); body.append('file', file); if (target) body.append('incident_id', target)
    try {
      const response = await fetch(`${API_URL}/api/v1/evidence/upload`, { method: 'POST', body })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || 'Evidence upload failed.')
      setStatus(`${result.created_count} created / ${result.duplicate_count} duplicate / ${result.rejected_count} rejected`); setFile(null); onUploaded?.()
    } catch (uploadError) { setError(uploadError.message); setStatus('') } finally { setUploading(false) }
  }
  return <section className="evidence-upload"><div className="section-heading"><div><p className="eyebrow">Evidence ingestion</p><h2>Upload source file</h2></div></div><div className="upload-controls"><input type="file" accept=".txt,.log,.csv,.json,.pdf" onChange={event => setFile(event.target.files?.[0] || null)} />{incidentId ? <span className="upload-target">This incident</span> : <select value={target} onChange={event => setTarget(event.target.value)}><option value="">Active incident</option>{targets.map(item => <option key={item.incident_id} value={item.incident_id}>{item.incident_title} / {item.incident_id.slice(0, 8)}</option>)}</select>}<button className="analyze-button" disabled={!file || uploading} onClick={submit}>{uploading ? 'Uploading...' : 'Upload evidence'}<ArrowUpRight size={16} /></button></div><small className="upload-hint">TXT / LOG / CSV / JSON / PDF, up to 10 MB. PDF text extraction only; OCR is not enabled.</small>{status && <p className="upload-success">{status}</p>}{error && <p className="error">{error}</p>}</section>
}

function HistoryDetail({ detail, onBack, onUploaded }) {
  return <section className="history-detail"><button className="back-button" onClick={onBack}><ArrowLeft size={16} />Incident History</button><div className="history-detail-heading"><div><p className="eyebrow">Persisted investigation</p><h1>{detail.incident_title}</h1><p>{detail.incident_id} / revision {detail.revision}</p></div><div className="root-status"><span>Root cause</span><strong>{detail.root_cause_status}</strong></div></div><EvidenceUpload incidentId={detail.incident_id} onUploaded={onUploaded} />{detail.analysis ? <IntelligenceWorkspace analysis={detail.analysis} /> : <div className="history-empty"><h2>Analysis not available.</h2><p>The evidence is persisted, but no analysis has been stored for this incident.</p></div>}<section className="evidence-section"><div className="section-heading"><div><p className="eyebrow">Source record</p><h2>Evidence</h2></div><span className="count">{detail.evidence.length} events</span></div><div className="evidence-records">{detail.evidence.map(item => <article key={item.evidence_id}><div><strong>{item.event}</strong><small>{item.evidence_id} / {item.source_name}</small></div><span>{item.classification}</span><p>{item.raw_evidence}</p></article>)}</div></section><section className="relationships-section"><div className="section-heading"><div><p className="eyebrow">Correlated signals</p><h2>Relationships</h2></div></div>{detail.relationships.length ? <ul>{detail.relationships.map(item => <li key={item.relationship_id}>{item.source_evidence_id} - {item.relationship_type} - {item.target_evidence_id}</li>)}</ul> : <p className="muted">No persisted relationships for this incident.</p>}</section></section>
}

function App() {
  const [files, setFiles] = useState([])
  const [analysis, setAnalysis] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [stage, setStage] = useState(-1)
  const [activeCount, setActiveCount] = useState(0)
  const [demoBusy, setDemoBusy] = useState(false)
  const [demoMessage, setDemoMessage] = useState('')
  const [view, setView] = useState(window.location.pathname.startsWith('/history') ? 'history' : 'live')
  const [history, setHistory] = useState([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState(false)
  const [selectedIncidentId, setSelectedIncidentId] = useState(window.location.pathname.split('/')[2] || null)
  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState(false)

  useEffect(() => {
    const onPopState = () => { setView(window.location.pathname.startsWith('/history') ? 'history' : 'live'); setSelectedIncidentId(window.location.pathname.split('/')[2] || null) }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  useEffect(() => {
    if (view !== 'live') return undefined
    const refresh = async () => {
      try {
        const activeResponse = await fetch(`${API_URL}/api/v1/incidents/active`)
        const active = activeResponse.ok ? await activeResponse.json() : { count: 0 }
        setActiveCount(active.count)
        const intelligenceResponse = await fetch(`${API_URL}/api/v1/incidents/active/intelligence`)
        if (intelligenceResponse.ok) {
          const intelligence = await intelligenceResponse.json()
          if (intelligence.status === 'ready') setAnalysis(intelligence.analysis)
          else if (active.count === 0) setAnalysis(null)
        }
      } catch { /* Live controls expose action errors when invoked. */ }
    }
    refresh()
    const timer = setInterval(refresh, 2000)
    return () => clearInterval(timer)
  }, [view])

  useEffect(() => {
    if (view !== 'history') return undefined
    setHistoryLoading(true)
    setHistoryError(false)
    fetch(`${API_URL}/api/v1/incidents`).then(response => { if (!response.ok) throw new Error('history'); return response.json() }).then(setHistory).catch(() => setHistoryError(true)).finally(() => setHistoryLoading(false))
    return undefined
  }, [view])

  useEffect(() => {
    if (view !== 'history' || !selectedIncidentId) { setDetail(null); return undefined }
    setDetailLoading(true)
    setDetailError(false)
    fetch(`${API_URL}/api/v1/incidents/${selectedIncidentId}`).then(response => { if (!response.ok) throw new Error('detail'); return response.json() }).then(setDetail).catch(() => setDetailError(true)).finally(() => setDetailLoading(false))
    return undefined
  }, [view, selectedIncidentId])

  const navigate = (path, nextView, incidentId = null) => { window.history.pushState({}, '', path); setView(nextView); setSelectedIncidentId(incidentId) }
  const addFiles = incoming => { setFiles(current => [...current, ...Array.from(incoming).filter(file => !current.some(existing => existing.name === file.name))]); setError('') }
  const runAnalysis = async request => { setLoading(true); setAnalysis(null); setError(''); setStage(0); const timer = setInterval(() => setStage(current => Math.min(current + 1, stages.length - 1)), 500); try { const response = await request(); if (!response.ok) throw new Error('The analysis service returned an error.'); setAnalysis(await response.json()) } catch (err) { setError(`${err.message} Check that the backend is running.`) } finally { clearInterval(timer); setStage(-1); setLoading(false) } }
  const analyze = () => { if (!files.length) return; runAnalysis(() => { const body = new FormData(); files.forEach(file => body.append('files', file)); return fetch(`${API_URL}/api/v1/incidents/analyze`, { method: 'POST', body }) }) }
  const analyzeActive = () => runAnalysis(() => fetch(`${API_URL}/api/v1/incidents/analyze-active`, { method: 'POST' }))
  const simulateDemo = async () => { setDemoBusy(true); setDemoMessage('Sending demo events...'); try { const response = await fetch(`${DEMO_URL}/simulate-incident`, { method: 'POST' }); const result = await response.json(); if (!response.ok) throw new Error(result.detail || 'Demo simulation failed.'); setDemoMessage(`${result.events_sent} demo events sent.`) } catch (err) { setDemoMessage(`${err.message} Check that the demo service is running.`) } finally { setDemoBusy(false) } }
  const refreshDetail = () => { if (!selectedIncidentId) return; fetch(`${API_URL}/api/v1/incidents/${selectedIncidentId}`).then(response => response.json()).then(setDetail).catch(() => setDetailError(true)) }
  const liveView = <><section className="hero"><div><p className="eyebrow">Operational truth, reconstructed</p><h1>Turn scattered signals into a story you can verify.</h1><p className="hero-copy">ChroniX connects logs, conversations, reports, and metrics into one chronological incident view. Every conclusion stays linked to evidence.</p></div><div className="hero-note"><ShieldCheck size={20} /><span>Evidence traceability<br /><strong>built into every event</strong></span></div></section><section className="workspace"><aside className="upload-panel"><div className="section-heading"><div><p className="eyebrow">01 / Collect</p><h2>Incident evidence</h2></div></div><div className="live-source"><div className="live-source-heading"><Radio size={16} /><span>LIVE SOURCES</span><span className="connected-dot" /></div><strong>ChroniX Demo Payment Service</strong><span className="connected-label">Demo service · port 9000</span><div className="live-count">Events received: <b>{activeCount}</b></div><button className="active-analyze" disabled={demoBusy} onClick={simulateDemo}>{demoBusy ? 'Sending demo...' : 'Simulate 7 event incident'}<Radio size={15} /></button><button className="active-analyze" disabled={!activeCount || loading} onClick={analyzeActive}>Analyze Active Incident<ArrowUpRight size={15} /></button>{demoMessage && <p className="upload-hint">{demoMessage}</p>}</div><EvidenceUpload /><label className="dropzone" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); addFiles(event.dataTransfer.files) }}><UploadCloud size={26} /><strong>Drop files here</strong><span>or choose CSV, TXT, LOG, PDF</span><input type="file" multiple accept=".csv,.txt,.log,.json,.pdf" onChange={event => addFiles(event.target.files)} /></label>{files.length > 0 && <div className="file-list">{files.map(file => <div className="file-row" key={file.name}><FileText size={16} /><span>{file.name}</span><button aria-label={`Remove ${file.name}`} onClick={() => setFiles(files.filter(item => item.name !== file.name))}><X size={15} /></button></div>)}</div>}<button className="analyze-button" disabled={!files.length || loading} onClick={analyze}>{loading ? 'Reconstructing...' : 'Analyze incident'}<ArrowUpRight size={17} /></button>{error && <p className="error">{error}</p>}<div className="stages">{stages.map((item, index) => <div className={`stage ${stage >= index ? 'active' : ''}`} key={item}><span>{stage > index ? <Check size={13} /> : index + 1}</span>{item}</div>)}</div></aside><section className="results">{!analysis && !loading && <EmptyState />}{loading && <div className="loading-state"><div className="pulse" /><h2>Reconstructing incident</h2><p>Reading sources, correlating signals, and checking claims against evidence.</p></div>}{analysis && <IntelligenceWorkspace analysis={analysis} />}</section></section></>
  const historyView = selectedIncidentId ? detailLoading ? <div className="history-state">Loading incident...</div> : detailError || !detail ? <div className="history-state error">Unable to load incident.</div> : <HistoryDetail detail={detail} onBack={() => navigate('/history', 'history')} onUploaded={refreshDetail} /> : <section className="history-page"><div className="history-heading"><div><p className="eyebrow">Persistent record</p><h1>Incident History</h1><p>Browse reconstructed investigations stored by ChroniX.</p></div></div>{historyLoading ? <div className="history-state">Loading incident history...</div> : historyError ? <div className="history-state error">Unable to load incident history.</div> : <HistoryList incidents={history} onSelect={id => navigate(`/history/${id}`, 'history', id)} />}</section>
  return <div className="app"><header><div className="brand"><div className="brand-mark"><Activity size={18} /></div><div><div className="brand-name">CHRONIX</div><div className="brand-sub">Evidence-driven incident intelligence</div></div></div><nav className="primary-nav"><button className={view === 'live' ? 'active' : ''} onClick={() => navigate('/', 'live')}>Live Incident</button><button className={view === 'history' ? 'active' : ''} onClick={() => navigate('/history', 'history')}>Incident History</button></nav><div className="header-status"><span className="live-dot" /> deterministic analysis ready</div></header><main>{view === 'live' ? liveView : historyView}</main><footer><span>CHRONIX / MVP</span><span>Evidence → Events → Correlation → Timeline → Intelligence</span></footer></div>
}

createRoot(document.getElementById('root')).render(<App />)
