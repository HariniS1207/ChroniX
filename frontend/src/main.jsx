import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Activity, ArrowLeft, ArrowUpRight, ChevronDown, Clock3, FileText, Radio, UploadCloud, X } from 'lucide-react'
import './styles.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8001'
const DEMO_URL = import.meta.env.VITE_DEMO_URL || 'http://localhost:9001'
const DEMO_PORT = new URL(DEMO_URL).port || (new URL(DEMO_URL).protocol === 'https:' ? '443' : '80')

function Badge({ value }) {
  return <span className={`badge badge-${value.toLowerCase()}`}><span className="badge-mark">{value === 'FACT' ? 'F' : value === 'INFERENCE' ? 'I' : value === 'CONFLICT' ? 'C' : '?'}</span>{value}</span>
}

function ClaimList({ title, claims }) {
  if (!claims?.length) return null
  const describe = description => title === 'Probable causes'
    ? `Possible, unconfirmed explanation (inference): ${description}. Direct causal evidence is missing.`
    : title === 'Contributing factors'
      ? `Potential contributing factor (not confirmed): ${description}`
      : description
  return <div className="ai-claims"><strong>{title}</strong><ul>{claims.map((claim, index) => <li key={index}>{describe(claim.description)}<small>Evidence: {claim.evidence_ids?.join(', ') || 'not explicitly referenced'}</small></li>)}</ul></div>
}

function AIEnrichment({ analysis }) {
  const enrichment = analysis.llm_enrichment
  const labels = { local_pending: 'PROCESSING', local_processing: 'PROCESSING', local: 'LOCAL', local_unavailable: 'UNAVAILABLE', local_failed: 'FAILED', unavailable: 'UNAVAILABLE', failed: 'FAILED', invalid_response: 'INVALID RESPONSE', used: 'USED' }
  const fallback = 'Local intelligence status is unknown. Deterministic analysis remains active.'
  const messages = { local_pending: 'Evidence is saved. Local intelligence will start after the current upload burst.', local_processing: 'Local intelligence is analyzing the incident evidence.', local_unavailable: 'Ollama or the configured model could not be reached. Deterministic analysis remains active.', local_failed: 'Local intelligence processing failed. Deterministic analysis remains active.', unavailable: 'Local intelligence is not configured. Deterministic analysis remains active.', failed: 'Local intelligence processing failed. Deterministic analysis remains active.', invalid_response: 'The local model response did not pass validation. Deterministic analysis remains active.' }
  return <section className="ai-panel"><div className="section-heading"><div><p className="eyebrow">Enrichment layer</p><h2>Local intelligence</h2><p className="ai-disclaimer">AI enrichment is hypothesis only. Deterministic analysis remains authoritative.</p></div><span className={`ai-status ai-status-${analysis.llm_status}`}>LLM: {labels[analysis.llm_status] || analysis.llm_status}</span></div>{(analysis.llm_status === 'local' || analysis.llm_status === 'used') && enrichment ? <><p className="ai-summary"><strong>{analysis.root_cause_status === 'NOT CONFIRMED' ? 'Root cause remains NOT CONFIRMED. AI output is a hypothesis only.' : 'AI output is a hypothesis only; deterministic root-cause status is authoritative.'}</strong> {enrichment.incident_summary}</p><div className="ai-grid"><ClaimList title="Probable causes" claims={enrichment.probable_causes} /><ClaimList title="Contributing factors" claims={enrichment.contributing_factors} /><ClaimList title="Uncertainty" claims={enrichment.uncertainty} /><ClaimList title="Recommendations" claims={(enrichment.investigation_recommendations || []).map(description => ({ description, evidence_ids: [], confidence: null }))} /></div></> : <p className="muted">{messages[analysis.llm_status] || fallback}</p>}</section>
}

function Timeline({ events }) {
  const [open, setOpen] = useState(null)
  return <section className="timeline-section"><div className="section-heading"><div><p className="eyebrow">Reconstructed sequence</p><h2>Incident timeline</h2></div><span className="count">{events.length} reconstructed events</span></div><div className="timeline">{events.map((item, index) => <article className="event" key={`${item.source_id || item.source}-${index}`}><div className="event-rail"><span className="event-dot" /></div><div className="event-time"><small>TIME</small>{item.timestamp ? new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }) : '-'}</div><div className="event-body"><div className="event-top"><h3>{item.event}</h3><Badge value={item.classification || 'UNKNOWN'} /></div><div className="event-meta"><span><FileText size={14} /><small>SOURCE</small>{item.source || item.source_name || 'Unknown source'}</span>{item.related_event_ids?.length > 0 && <span><small>RELATED</small>{item.related_event_ids.length}</span>}</div><button className="evidence-toggle" onClick={() => setOpen(open === index ? null : index)}>{open === index ? 'Hide source evidence' : 'View source evidence'}<ChevronDown size={15} className={open === index ? 'rotate' : ''} /></button>{open === index && <div className="evidence"><strong>Evidence</strong><p>{item.evidence || item.raw_evidence}</p></div>}</div></article>)}</div></section>
}

function InsightColumn({ title, items, kind, count = items.length }) {
  return <div className="insight"><div className="insight-title"><span className={`insight-line line-${kind}`} /><h3>{title}</h3><span>{count}</span></div>{items.length ? <ul>{items.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p className="muted">None identified in the available evidence.</p>}</div>
}

function EvidenceRelationships({ analysis }) {
  const events = analysis.timeline || []
  const byId = Object.fromEntries(events.map(event => [event.source_id, event]))
  const relationships = analysis.relationships || []
  return <section className="relationships-section"><div className="section-heading"><div><p className="eyebrow">Traceable evidence graph</p><h2>Evidence relationships</h2></div><span className="count">{relationships.length} links</span></div>{relationships.length ? <div className="relationship-list">{relationships.map((rel, index) => { const source = byId[rel.source_evidence_id]; const target = byId[rel.target_evidence_id]; return <article className="relationship-row" key={rel.relationship_id || `${rel.source_evidence_id}-${rel.target_evidence_id}-${index}`}><div className="relationship-node"><Badge value={source?.classification || 'UNKNOWN'} /><span>{source?.event || rel.source_evidence_id}</span><small>{source ? `${source.source || source.source_name || 'Unknown source'} / ${rel.source_evidence_id}` : rel.source_evidence_id}</small></div><div className="relationship-edge"><strong>{rel.relationship_type.replaceAll('_', ' ')}</strong><span>{Math.round((rel.confidence || 0) * 100)}% confidence</span></div><div className="relationship-node"><Badge value={target?.classification || 'UNKNOWN'} /><span>{target?.event || rel.target_evidence_id}</span><small>{target ? `${target.source || target.source_name || 'Unknown source'} / ${rel.target_evidence_id}` : rel.target_evidence_id}</small></div><p>{rel.basis}</p></article> })}</div> : <p className="muted">No relationships are supported by the available evidence yet.</p>}</section>
}

function RootCauseStatus({ analysis }) {
  const status = analysis?.root_cause_status || 'NOT CONFIRMED'
  const evidenceIds = analysis?.root_cause_evidence_ids || []
  const confidence = analysis?.root_cause_confidence
  const basis = status === 'NOT CONFIRMED'
    ? 'Available evidence is insufficient or contradictory to establish a causal chain.'
    : analysis?.root_cause_basis || 'Available evidence is insufficient to establish causality.'
  return <div className={`root-status root-status-${status.toLowerCase().replaceAll(' ', '-')}`}>
    <span>Root cause</span>
    <strong>{status}</strong>
    <p>{basis}</p>
    {confidence !== null && confidence !== undefined && <small>Evidence confidence: {Math.round(confidence * 100)}% checklist coverage</small>}
    {evidenceIds.length > 0 && <small>Supporting evidence IDs: {evidenceIds.join(', ')}</small>}
  </div>
}

function IntelligenceWorkspace({ analysis, incidentId, evidenceCount, stateLabel = 'INCIDENT' }) {
  const [reportLoading, setReportLoading] = useState(false)
  const [reportError, setReportError] = useState('')
  const timeline = analysis.timeline || []
  const facts = analysis.facts || []
  const inferences = analysis.inferences || []
  const conflicts = analysis.conflicts || []
  const unknowns = analysis.unknowns || []
  const reconstructedTimelineLabel = `${timeline.length} reconstructed timeline ${timeline.length === 1 ? 'event' : 'events'}`
  const downloadReport = async () => {
    if (!incidentId) { setReportError('Incident ID is unavailable. Refresh the incident and try again.'); return }
    setReportLoading(true)
    setReportError('')
    try {
      const response = await fetch(`${API_URL}/api/v1/incidents/${incidentId}/report`)
      if (!response.ok) {
        let detail = 'The report could not be generated.'
        try { const payload = await response.json(); detail = payload.detail || detail } catch { /* Use the readable fallback. */ }
        throw new Error(detail)
      }
      if (!response.headers.get('content-type')?.includes('application/pdf')) throw new Error('The server response was not a PDF report.')
      const blob = await response.blob()
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `chronix-incident-report-${incidentId}.pdf`
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.setTimeout(() => window.URL.revokeObjectURL(url), 1000)
    } catch (error) {
      setReportError(error.message || 'The report could not be downloaded. Check the backend connection and try again.')
    } finally { setReportLoading(false) }
  }
  return <><section className="overview"><div><p className="eyebrow">Incident overview <span className="overview-state">{stateLabel}</span></p><h2>{analysis.incident_title}</h2><p>{analysis.summary}</p><div className="overview-counts"><span>{reconstructedTimelineLabel}</span><span>{facts.length} facts</span><span>{inferences.length} inferences</span><span>{conflicts.length} conflict findings</span><span>{unknowns.length} open unknowns</span></div>{Number.isFinite(evidenceCount) && <p className="count-explanation"><strong>{evidenceCount} evidence signals</strong> were received and correlated into <strong>{reconstructedTimelineLabel}</strong>. Facts and inferences classify timeline events; conflicts and unknowns are separate analysis findings.</p>}</div><RootCauseStatus analysis={analysis} /></section><Timeline events={timeline} /><EvidenceRelationships analysis={analysis} /><section className="intelligence"><div className="section-heading"><div><p className="eyebrow">Deterministic interpretation</p><h2>Incident intelligence</h2><p className="section-caption">Facts and inferences classify reconstructed events. Conflicts and unknowns are cross-event findings, not extra timeline events.</p></div></div><div className="insight-grid"><InsightColumn title="Facts" items={facts} kind="fact" /><InsightColumn title="Inferences" items={inferences} kind="inference" /><InsightColumn title="Conflict findings" items={conflicts} kind="conflict" /><InsightColumn title="Open unknowns" items={unknowns} kind="unknown" /></div><p className="classification-legend"><b>FACT</b> directly observed <b>INFERENCE</b> interpretation <b>CONFLICT</b> evidence disagreement <b>UNKNOWN</b> insufficient evidence</p></section><section className="gaps"><div><p className="eyebrow">Next investigation move</p><h2>Missing evidence</h2></div><ul>{analysis.missing_evidence.map((item, index) => <li key={index}>{item}<ArrowUpRight size={15} /></li>)}</ul></section>
<AIEnrichment analysis={analysis} />

<section className="incident-report">
  <div>
    <p className="eyebrow">Incident report</p>
    <h2>Download incident report</h2>
    <p className="section-caption">
      Export the reconstructed incident with its evidence, timeline,
      classifications, relationships, uncertainty, and investigation gaps.
    </p>
  </div>

  <div className="report-actions">
    <button className="report-download" disabled={!incidentId || reportLoading} onClick={downloadReport}>
      {reportLoading ? 'Preparing report...' : 'Download incident report'} <ArrowUpRight size={15} />
    </button>
    {!incidentId && <p className="report-id-hint">Incident ID unavailable. Refresh the incident before downloading its report.</p>}
    {reportError && <p className="error report-error" role="alert">{reportError}</p>}
  </div>
</section>
</>
}

function HistoryList({ incidents, onSelect }) {
  if (!incidents.length) return <div className="history-empty"><Clock3 size={30} /><h2>No incidents recorded yet.</h2><p>Completed incidents will appear here once ChroniX has persistent evidence.</p></div>
  return <div className="history-list">{incidents.map(incident => <button className="history-row" key={incident.incident_id} onClick={() => onSelect(incident.incident_id)}><div><strong>{incident.incident_title}</strong><small>{incident.incident_id}</small></div><span>{new Date(incident.updated_at).toLocaleString()}</span><span>{incident.evidence_count} evidence</span><span>{incident.root_cause_status}</span><span className={`history-status status-${incident.llm_status}`}>{(incident.llm_status || 'unavailable').replaceAll('_', ' ').toUpperCase()}</span></button>)}</div>
}

function EvidenceUpload({ incidentId, onUploaded }) {
  const [files, setFiles] = useState([])
  const [targets, setTargets] = useState([])
  const [target, setTarget] = useState(incidentId || '')
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [dragging, setDragging] = useState(false)

  useEffect(() => {
    if (incidentId) return undefined
    fetch(`${API_URL}/api/v1/incidents`).then(response => response.json()).then(setTargets).catch(() => setTargets([]))
    return undefined
  }, [incidentId])

  const addFiles = incoming => {
    const chosen = Array.from(incoming || [])
    const accepted = chosen.filter(file => file.size <= 10 * 1024 * 1024)
    if (accepted.length !== chosen.length) setError('Files must be 10 MB or smaller. Oversized files were not added.')
    if (!accepted.length) return
    setFiles(current => {
      const seen = new Set(current.map(file => `${file.name}:${file.size}:${file.lastModified}`))
      return [...current, ...accepted.filter(file => {
        const key = `${file.name}:${file.size}:${file.lastModified}`
        if (seen.has(key)) return false
        seen.add(key)
        return true
      })]
    })
    setStatus('')
    setError('')
  }

  const submit = async () => {
    if (!files.length || uploading) return
    setUploading(true)
    setStatus('Uploading evidence and updating incident analysis...')
    setError('')
    let createdCount = 0
    let duplicateCount = 0
    let incidentResult = null
    const uploadedNames = []
    const failedFiles = []
    const failureMessages = []
    const selectedTarget = incidentId || target

    for (const file of files) {
      const body = new FormData()
      body.append('file', file)
      if (selectedTarget) body.append('incident_id', selectedTarget)
      try {
        const response = await fetch(`${API_URL}/api/v1/evidence/upload`, { method: 'POST', body })
        const result = await response.json()
        if (!response.ok) throw new Error('Upload failed. Check the file format and incident destination, then try again.')
        createdCount += result.created_count || 0
        duplicateCount += result.duplicate_count || 0
        incidentResult = result
        uploadedNames.push(file.name)
      } catch (uploadError) {
        failedFiles.push(file)
        const message = uploadError.name === 'TypeError'
          ? 'Could not reach the ChroniX backend.'
          : uploadError.name === 'SyntaxError'
            ? 'The backend returned an unreadable response.'
            : uploadError.message
        failureMessages.push(`${file.name}: ${message}`)
      }
    }

    if (uploadedNames.length) {
      const fileLabel = uploadedNames.length === 1 ? uploadedNames[0] : `${uploadedNames.length} files`
      setStatus(createdCount
        ? `${fileLabel} - Evidence added successfully - ${createdCount} evidence signals added${duplicateCount ? `; ${duplicateCount} duplicate signals skipped` : ''}.`
        : `${fileLabel} uploaded; no new evidence signals were added${duplicateCount ? ` (${duplicateCount} duplicates)` : ''}.`)
      onUploaded?.({ incident_id: incidentResult?.incident_id || selectedTarget || null, target: selectedTarget || '' })
    } else {
      setStatus('')
    }
    setFiles(failedFiles)
    if (failureMessages.length) setError(failureMessages.join(' '))
    setUploading(false)
  }

  return <section className="evidence-upload">
    <div className="section-heading"><div><p className="eyebrow">Evidence ingestion</p><h2>Add source evidence</h2></div></div>
    <div className="upload-controls">
      <label className={`upload-droparea dropzone ${dragging ? 'dragging' : ''}`} onDragEnter={event => { event.preventDefault(); setDragging(true) }} onDragOver={event => event.preventDefault()} onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget)) setDragging(false) }} onDrop={event => { event.preventDefault(); setDragging(false); addFiles(event.dataTransfer.files) }}>
        <UploadCloud size={22} /><strong>{dragging ? 'Drop evidence to add it' : 'Drop files here or choose files'}</strong><span>TXT | LOG | CSV | JSON | PDF</span>
        <input id="evidence-upload-input" type="file" multiple accept=".txt,.log,.csv,.json,.pdf" onChange={event => { addFiles(event.target.files); event.currentTarget.value = '' }} />
      </label>
      {files.length > 0 && <div className="upload-selected-files">{files.map((file, index) => <div className="file-row" key={`${file.name}:${file.lastModified}:${index}`}><FileText size={16} /><span>{file.name}<small>{file.name.split('.').pop()?.toUpperCase()} | {file.size < 1024 * 1024 ? `${Math.max(1, Math.round(file.size / 1024))} KB` : `${(file.size / (1024 * 1024)).toFixed(1)} MB`}</small></span><button type="button" aria-label={`Remove ${file.name}`} disabled={uploading} onClick={() => setFiles(current => current.filter((_, itemIndex) => itemIndex !== index))}><X size={15} /></button></div>)}</div>}
      {incidentId ? <span className="upload-target">Target: this incident</span> : <select aria-label="Evidence destination" value={target} onChange={event => setTarget(event.target.value)}><option value="">Active incident</option>{targets.filter(item => item.status !== 'active').map(item => <option key={item.incident_id} value={item.incident_id}>{item.incident_title} / {item.incident_id.slice(0, 8)}</option>)}</select>}
      <button className="analyze-button upload-submit" disabled={!files.length || uploading} onClick={submit}>{uploading ? 'Uploading & analyzing...' : 'Upload & Analyze'}<ArrowUpRight size={16} /></button>
    </div>
    <small className="upload-hint">Up to 10 MB per file. Evidence is persisted and the deterministic analysis refreshes after upload. PDF text extraction only; scanned PDFs need OCR.</small>
    {status && <p className="upload-success" role="status">{status}</p>}
    {error && <p className="error" role="alert">{error}</p>}
  </section>
}
function HistoryDetail({ detail, onBack, onUploaded }) {
  return <section className="history-detail"><button className="back-button" onClick={onBack}><ArrowLeft size={16} />Incident History</button><div className="history-detail-heading"><div><p className="eyebrow">Persisted investigation</p><h1>{detail.incident_title}</h1><p>{detail.incident_id} / revision {detail.revision}</p></div><RootCauseStatus analysis={detail.analysis || { root_cause_status: detail.root_cause_status }} /></div><EvidenceUpload incidentId={detail.incident_id} onUploaded={onUploaded} />{detail.analysis ? <IntelligenceWorkspace analysis={detail.analysis} incidentId={detail.incident_id} evidenceCount={detail.evidence.length} stateLabel={detail.status?.toUpperCase() || 'HISTORICAL'} /> : <div className="history-empty"><h2>Analysis not available.</h2><p>The evidence is persisted, but no analysis has been stored for this incident.</p></div>}<section className="evidence-section"><div className="section-heading"><div><p className="eyebrow">Source record</p><h2>Evidence received</h2></div><span className="count">{detail.evidence.length} signals</span></div><div className="evidence-records">{detail.evidence.map(item => <article key={item.evidence_id}><div><strong>{item.event}</strong><small>{item.evidence_id} / {item.source_name}</small></div><span>{item.classification}</span><p>{item.raw_evidence}</p></article>)}</div></section><section className="relationships-section"><div className="section-heading"><div><p className="eyebrow">Correlated signals</p><h2>Relationships</h2></div></div>{detail.relationships.length ? <ul>{detail.relationships.map(item => <li key={item.relationship_id}>{item.source_evidence_id} - {item.relationship_type} - {item.target_evidence_id}</li>)}</ul> : <p className="muted">No persisted relationships for this incident.</p>}</section></section>
}

function App() {
  const [analysis, setAnalysis] = useState(null)
  const [activeIncidentId, setActiveIncidentId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [activeCount, setActiveCount] = useState(0)
  const [activeEvents, setActiveEvents] = useState([])
  const [demoBusy, setDemoBusy] = useState(false)
  const [demoMessage, setDemoMessage] = useState('')
  const [demoStatus, setDemoStatus] = useState('checking')
  const [backendStatus, setBackendStatus] = useState('checking')
  const [view, setView] = useState(window.location.pathname.startsWith('/history') ? 'history' : window.location.pathname === '/' ? 'landing' : 'live')
  const [history, setHistory] = useState([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState(false)
  const [selectedIncidentId, setSelectedIncidentId] = useState(window.location.pathname.split('/')[2] || null)
  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState(false)

  useEffect(() => {
    const onPopState = () => { const nextView = window.location.pathname.startsWith('/history') ? 'history' : window.location.pathname === '/' ? 'landing' : 'live'; setView(nextView); if (nextView === 'live') { setAnalysis(null); setError('') }; setSelectedIncidentId(window.location.pathname.split('/')[2] || null) }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  useEffect(() => {
    let mounted = true
    const checkDemo = async () => {
      try {
        const response = await fetch(`${DEMO_URL}/`)
        if (mounted) setDemoStatus(response.ok ? 'online' : 'offline')
      } catch {
        if (mounted) setDemoStatus('offline')
      }
    }
    checkDemo()
    const timer = setInterval(checkDemo, 10000)
    return () => { mounted = false; clearInterval(timer) }
  }, [])

  useEffect(() => {
    let mounted = true
    let consecutiveFailures = 0
    const checkBackend = async () => {
      try {
        const response = await fetch(`${API_URL}/health`)
        consecutiveFailures = 0
        if (mounted) setBackendStatus(response.ok ? 'online' : 'offline')
      } catch {
        consecutiveFailures += 1
        if (mounted) setBackendStatus(consecutiveFailures === 1 ? 'checking' : 'offline')
      }
    }
    checkBackend()
    const timer = setInterval(checkBackend, 3000)
    return () => { mounted = false; clearInterval(timer) }
  }, [])

  const refreshActive = async () => {
    try {
      const activeResponse = await fetch(`${API_URL}/api/v1/incidents/active`)
      if (!activeResponse.ok) return
      const active = await activeResponse.json()
      setActiveCount(active.count)
      setActiveEvents(active.events || [])
      const intelligenceResponse = await fetch(`${API_URL}/api/v1/incidents/active/intelligence`)
      if (!intelligenceResponse.ok) return
      const intelligence = await intelligenceResponse.json()
      const nextIncidentId = intelligence.incident_id || null
      if (activeIncidentId && activeIncidentId !== nextIncidentId) setAnalysis(null)
      setActiveIncidentId(nextIncidentId)
    } catch {
      // Keep the last successful state visible during a brief backend restart.
    }
  }

  useEffect(() => {
    if (view !== 'live') return undefined
    refreshActive()
    const timer = setInterval(refreshActive, 2000)
    return () => clearInterval(timer)
  }, [view, activeIncidentId])

  useEffect(() => {
    if (view !== 'live' || !analysis || !['local_pending', 'local_processing'].includes(analysis.llm_status)) return undefined
    let mounted = true
    const refreshEnrichment = async () => {
      try {
        const response = await fetch(`${API_URL}/api/v1/incidents/active/intelligence`)
        if (response.ok) {
          const latest = await response.json()
          if (latest.status === 'ready' && latest.incident_id === activeIncidentId && !['local_pending', 'local_processing'].includes(latest.analysis?.llm_status)) {
            if (mounted) setAnalysis(current => current && ['local_pending', 'local_processing'].includes(current.llm_status) ? latest.analysis : current)
            return
          }
        }
      } catch { /* Keep deterministic analysis visible if enrichment polling briefly fails. */ }
    }
    refreshEnrichment()
    const timer = setInterval(refreshEnrichment, 1500)
    return () => { mounted = false; clearInterval(timer) }
  }, [view, analysis, activeIncidentId])

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

  useEffect(() => {
    if (view !== 'history' || !selectedIncidentId || !['local_pending', 'local_processing'].includes(detail?.analysis?.llm_status)) return undefined
    let mounted = true
    const refreshHistoricalEnrichment = async () => {
      try {
        const response = await fetch(`${API_URL}/api/v1/incidents/${selectedIncidentId}`)
        if (!response.ok) return
        const latest = await response.json()
        if (mounted) setDetail(current => current?.incident_id === selectedIncidentId ? latest : current)
      } catch { /* Keep the persisted deterministic analysis visible during brief network interruptions. */ }
    }
    const timer = setInterval(refreshHistoricalEnrichment, 1500)
    return () => { mounted = false; clearInterval(timer) }
  }, [view, selectedIncidentId, detail?.analysis?.llm_status])

  const navigate = (path, nextView, incidentId = null) => { window.history.pushState({}, '', path); setView(nextView); if (nextView === 'live') { setAnalysis(null); setError('') }; setSelectedIncidentId(incidentId) }
  const showUploadedActiveAnalysis = async incidentId => {
    if (!incidentId) return
    try {
      const response = await fetch(`${API_URL}/api/v1/incidents/active/intelligence`)
      if (!response.ok) return
      const latest = await response.json()
      if (latest.status === 'ready' && latest.incident_id === incidentId) setAnalysis(latest.analysis)
    } catch { /* Keep the upload confirmation visible if the analysis refresh is temporarily unavailable. */ }
  }
  const runAnalysis = async request => { setAnalysis(null); setLoading(true); setError(''); try { const response = await request(); if (!response.ok) throw new Error(); setAnalysis(await response.json()) } catch { setError('Analysis could not be completed. Check the backend connection and try again.') } finally { setLoading(false) } }
  const analyzeActive = () => runAnalysis(() => fetch(`${API_URL}/api/v1/incidents/analyze-active`, { method: 'POST' }))
  const simulateDemo = async () => {
    setDemoBusy(true); setAnalysis(null); setError(''); setDemoMessage('Starting a clean demo incident...')
    try {
      const resetResponse = await fetch(`${API_URL}/api/v1/incidents/active/reset`, { method: 'POST' })
      if (!resetResponse.ok) throw new Error('Could not prepare a clean active incident.')
      setActiveIncidentId(null); setActiveCount(0); setActiveEvents([])
      const response = await fetch(`${DEMO_URL}/simulate-incident`, { method: 'POST' })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || 'Demo events could not be sent.')
      await refreshActive()
      setDemoMessage(`${result.events_sent} evidence events received. Ready to analyze.`)
    } catch (simulationError) {
      setDemoMessage(simulationError.message || 'Could not connect to the demo service. Check its configured URL and that the service is running.')
    } finally { setDemoBusy(false) }
  }
  const refreshDetail = () => { if (!selectedIncidentId) return; fetch(`${API_URL}/api/v1/incidents/${selectedIncidentId}`).then(response => response.json()).then(setDetail).catch(() => setDetailError(true)) }
  const liveView = (
    <>
      <section className="workspace">
        <aside className="upload-panel">
          <div className="section-heading"><div><h2>Incident evidence</h2></div></div>
          <div className="live-source">
            <div className="live-source-heading"><Radio size={16} /><span>LIVE SOURCES</span><span className={`connected-dot connected-${demoStatus}`} /></div>
            <strong>ChroniX Demo Payment Service</strong>
            <span className="connected-label">Demo service / port {DEMO_PORT}</span>
            <span className={`demo-health demo-${demoStatus}`}>{demoStatus === 'checking' ? 'Checking demo service...' : demoStatus === 'online' ? 'Demo service ready' : 'Demo service unavailable - simulation disabled'}</span>
            <div className="live-count"><span>EVIDENCE RECEIVED</span><b>{activeCount} signals</b></div>
            {activeCount > 0 && <div className="detected-events"><strong>Received signals</strong><ul>{activeEvents.map((event, index) => <li key={event.source_id || index}>{event.event || event.raw_evidence || 'Evidence received'}</li>)}</ul></div>}
            {activeCount > 0 && !analysis && !loading && <p className="ready-message">{activeCount} evidence events received. Ready to analyze.</p>}
            <div className="live-actions">
              <button className="active-analyze" disabled={demoBusy || demoStatus !== 'online'} onClick={simulateDemo}>{demoBusy ? 'Sending demo...' : 'Simulate 7 event incident'}<Radio size={15} /></button>
              <button className="active-analyze" disabled={!activeCount || loading} onClick={analyzeActive}>{loading ? 'Analyzing incident...' : 'Analyze Active Incident'}<ArrowUpRight size={15} /></button>
            </div>
            {demoMessage && <p className="upload-hint">{demoMessage}</p>}
          </div>
          <EvidenceUpload onUploaded={result => {
            if (!result?.target) showUploadedActiveAnalysis(result?.incident_id)
            refreshActive()
            if (result?.target && result.incident_id) navigate(`/history/${result.incident_id}`, 'history', result.incident_id)
          }} />
        </aside>
        <section className="results">
          {error && <p className="error" role="alert">{error}</p>}
          {!analysis && !loading && <div className="live-empty"><p className="eyebrow">Investigation state</p><h2>{error ? 'Analysis failed' : activeCount ? 'Ready to analyze' : 'Waiting for evidence'}</h2><p>{error || (activeCount ? 'Evidence has arrived. Select Analyze Active Incident when you are ready to reconstruct the timeline.' : 'Send a demo incident or upload source evidence to begin.')}</p></div>}
          {loading && <div className="loading-state"><div className="pulse" /><h2>Reconstructing incident</h2><p>Reading sources, correlating signals, and checking claims against evidence.</p></div>}
          {analysis && <IntelligenceWorkspace analysis={analysis} incidentId={activeIncidentId || analysis.incident_id} evidenceCount={activeCount} stateLabel="ACTIVE" />}
        </section>
      </section>
    </>
  )
  const historyView = selectedIncidentId ? detailLoading ? <div className="history-state">Loading incident...</div> : detailError || !detail ? <div className="history-state error">Unable to load incident.</div> : <HistoryDetail detail={detail} onBack={() => navigate('/history', 'history')} onUploaded={refreshDetail} /> : <section className="history-page"><div className="history-heading"><div><p className="eyebrow">Persistent record</p><h1>Incident History</h1><p>Browse reconstructed investigations stored by ChroniX.</p></div></div>{historyLoading ? <div className="history-state">Loading incident history...</div> : historyError ? <div className="history-state error">Unable to load incident history.</div> : <HistoryList incidents={history} onSelect={id => navigate(`/history/${id}`, 'history', id)} />}</section>
  const landingView = <section className="landing"><p className="eyebrow">From fragmented evidence to one traceable incident story.</p><h1>Turn scattered signals into a story you can verify.</h1><p>ChroniX connects incident evidence into a clear, traceable account. See what the evidence shows, what it suggests, and what remains unknown.</p><div className="landing-actions"><button onClick={() => navigate('/live', 'live')}>Open Live Incident <ArrowUpRight size={17} /></button><button onClick={() => navigate('/history', 'history')}>Incident History <ArrowUpRight size={17} /></button></div></section>
  return <div className="app"><header><div className="brand"><div className="brand-mark"><Activity size={18} /></div><div><div className="brand-name">CHRONIX</div><div className="brand-sub">Evidence-driven incident intelligence</div></div></div><nav className="primary-nav"><button className={view === 'live' ? 'active' : ''} onClick={() => navigate('/live', 'live')}>Live Incident</button><button className={view === 'history' ? 'active' : ''} onClick={() => navigate('/history', 'history')}>Incident History</button></nav><div className={`header-status backend-${backendStatus}`}><span className="live-dot" /> {backendStatus === 'online' ? 'deterministic ready' : backendStatus === 'checking' ? 'checking system' : 'backend unavailable'}</div></header><main>{view === 'landing' ? landingView : view === 'live' ? liveView : historyView}</main><footer><span>CHRONIX / Evidence-Driven Incident Intelligence</span></footer></div>
}

createRoot(document.getElementById('root')).render(<App />)
