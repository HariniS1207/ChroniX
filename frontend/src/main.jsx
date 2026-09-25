import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Activity, ArrowUpRight, Check, ChevronDown, FileText, Radio, Search, ShieldCheck, UploadCloud, X } from 'lucide-react'
import './styles.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8001'
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
  const statusLabels = { local: 'LOCAL', used: 'USED', unavailable: 'UNAVAILABLE', failed: 'FAILED', invalid_response: 'INVALID RESPONSE' }
  const statusMessage = analysis.llm_status === 'unavailable' ? 'Local model unavailable. Deterministic analysis is active.' : analysis.llm_status === 'failed' ? 'Local model request failed. Deterministic analysis is active.' : analysis.llm_status === 'invalid_response' ? 'Local model response was rejected. Deterministic analysis is active.' : 'Deterministic analysis is active. No LLM enrichment was used for this result.'
  return <section className="ai-panel"><div className="section-heading"><div><p className="eyebrow">Reasoning layer</p><h2>AI analysis</h2></div><span className={`ai-status ai-status-${analysis.llm_status}`}>LLM: {statusLabels[analysis.llm_status] || analysis.llm_status}</span></div>{(analysis.llm_status === 'local' || analysis.llm_status === 'used') && enrichment ? <><p className="ai-summary">{enrichment.incident_summary}</p><div className="ai-grid"><ClaimList title="Probable causes" claims={enrichment.probable_causes} /><ClaimList title="Contributing factors" claims={enrichment.contributing_factors} /><ClaimList title="Uncertainty" claims={enrichment.uncertainty} /><ClaimList title="Recommendations" claims={enrichment.investigation_recommendations.map(description => ({ description, evidence_ids: [], confidence: null }))} /></div></> : <p className="muted">{statusMessage}</p>}</section>
}

function Timeline({ events }) {
  const [open, setOpen] = useState(null)
  return <section className="timeline-section"><div className="section-heading"><div><p className="eyebrow">Reconstructed sequence</p><h2>Incident timeline</h2></div><span className="count">{events.length} events</span></div><div className="timeline">{events.map((item, index) => <article className="event" key={`${item.source}-${index}`}><div className="event-rail"><span className="event-dot" /></div><div className="event-time">{item.timestamp ? new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }) : '-'}</div><div className="event-body"><div className="event-top"><h3>{item.event}</h3><Badge value={item.classification} /></div><div className="event-meta"><span><FileText size={14} />{item.source}</span>{item.related_event_ids?.length > 0 && <span>{item.related_event_ids.length} related</span>}</div><button className="evidence-toggle" onClick={() => setOpen(open === index ? null : index)}>{open === index ? 'Hide source evidence' : 'View source evidence'}<ChevronDown size={15} className={open === index ? 'rotate' : ''} /></button>{open === index && <div className="evidence"><strong>Evidence</strong><p>{item.evidence}</p></div>}</div></article>)}</div></section>
}

function InsightColumn({ title, items, kind }) {
  return <div className="insight"><div className="insight-title"><span className={`insight-line line-${kind}`} /><h3>{title}</h3><span>{items.length}</span></div>{items.length ? <ul>{items.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p className="muted">None identified in the available evidence.</p>}</div>
}

function App() {
  const [files, setFiles] = useState([])
  const [analysis, setAnalysis] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [stage, setStage] = useState(-1)
  const [activeCount, setActiveCount] = useState(0)

  useEffect(() => {
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
      } catch {
        // The existing analysis action reports backend availability errors.
      }
    }
    refresh()
    const timer = setInterval(refresh, 2000)
    return () => clearInterval(timer)
  }, [])

  const addFiles = (incoming) => {
    setFiles(current => [...current, ...Array.from(incoming).filter(file => !current.some(existing => existing.name === file.name))])
    setError('')
  }

  const runAnalysis = async (request) => {
    setLoading(true)
    setAnalysis(null)
    setError('')
    setStage(0)
    const timer = setInterval(() => setStage(current => Math.min(current + 1, stages.length - 1)), 500)
    try {
      const response = await request()
      if (!response.ok) throw new Error('The analysis service returned an error.')
      setAnalysis(await response.json())
    } catch (err) {
      setError(`${err.message} Check that the backend is running.`)
    } finally {
      clearInterval(timer)
      setStage(-1)
      setLoading(false)
    }
  }

  const analyze = () => {
    if (!files.length) return
    runAnalysis(() => {
      const body = new FormData()
      files.forEach(file => body.append('files', file))
      return fetch(`${API_URL}/api/v1/incidents/analyze`, { method: 'POST', body })
    })
  }

  const analyzeActive = () => runAnalysis(() => fetch(`${API_URL}/api/v1/incidents/analyze-active`, { method: 'POST' }))

  return <div className="app"><header><div className="brand"><div className="brand-mark"><Activity size={18} /></div><div><div className="brand-name">CHRONIX</div><div className="brand-sub">Evidence-driven incident intelligence</div></div></div><div className="header-status"><span className="live-dot" /> deterministic analysis ready</div></header><main><section className="hero"><div><p className="eyebrow">Operational truth, reconstructed</p><h1>Turn scattered signals into a story you can verify.</h1><p className="hero-copy">ChroniX connects logs, conversations, reports, and metrics into one chronological incident view. Every conclusion stays linked to evidence.</p></div><div className="hero-note"><ShieldCheck size={20} /><span>Evidence traceability<br /><strong>built into every event</strong></span></div></section><section className="workspace"><aside className="upload-panel"><div className="section-heading"><div><p className="eyebrow">01 / Collect</p><h2>Incident evidence</h2></div></div><div className="live-source"><div className="live-source-heading"><Radio size={16} /><span>LIVE SOURCES</span><span className="connected-dot" /></div><strong>ChroniX Demo Payment Service</strong><span className="connected-label">Connected</span><div className="live-count">Events received: <b>{activeCount}</b></div><button className="active-analyze" disabled={!activeCount || loading} onClick={analyzeActive}>Analyze Active Incident<ArrowUpRight size={15} /></button></div><label className="dropzone" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); addFiles(event.dataTransfer.files) }}><UploadCloud size={26} /><strong>Drop files here</strong><span>or choose CSV, TXT, LOG, PDF</span><input type="file" multiple accept=".csv,.txt,.log,.pdf" onChange={event => addFiles(event.target.files)} /></label>{files.length > 0 && <div className="file-list">{files.map(file => <div className="file-row" key={file.name}><FileText size={16} /><span>{file.name}</span><button aria-label={`Remove ${file.name}`} onClick={() => setFiles(files.filter(item => item.name !== file.name))}><X size={15} /></button></div>)}</div>}<button className="analyze-button" disabled={!files.length || loading} onClick={analyze}>{loading ? 'Reconstructing...' : 'Analyze incident'}<ArrowUpRight size={17} /></button>{error && <p className="error">{error}</p>}<div className="stages">{stages.map((item, index) => <div className={`stage ${stage >= index ? 'active' : ''}`} key={item}><span>{stage > index ? <Check size={13} /> : index + 1}</span>{item}</div>)}</div></aside><section className="results">{!analysis && !loading && <EmptyState />}{loading && <div className="loading-state"><div className="pulse" /><h2>Reconstructing incident</h2><p>Reading sources, correlating signals, and checking claims against evidence.</p></div>}{analysis && <><section className="overview"><div><p className="eyebrow">Incident overview</p><h2>{analysis.incident_title}</h2><p>{analysis.summary}</p></div><div className="root-status"><span>Root cause</span><strong>{analysis.root_cause_status}</strong></div></section><AIEnrichment analysis={analysis} />{analysis.file_errors?.length > 0 && <div className="warning"><strong>Some evidence was skipped</strong>{analysis.file_errors.map((item, index) => <div key={index}>{item}</div>)}</div>}<Timeline events={analysis.timeline} /><section className="intelligence"><div className="section-heading"><div><p className="eyebrow">Interpretation layer</p><h2>Incident intelligence</h2></div></div><div className="insight-grid"><InsightColumn title="Facts" items={analysis.facts} kind="fact" /><InsightColumn title="Inferences" items={analysis.inferences} kind="inference" /><InsightColumn title="Conflicts" items={analysis.conflicts} kind="conflict" /><InsightColumn title="Unknowns" items={analysis.unknowns} kind="unknown" /></div></section><section className="gaps"><div><p className="eyebrow">Next investigation move</p><h2>Missing evidence</h2></div><ul>{analysis.missing_evidence.map((item, index) => <li key={index}>{item}<ArrowUpRight size={15} /></li>)}</ul></section></>}</section></section></main><footer><span>CHRONIX / MVP</span><span>Evidence -&gt; Events -&gt; Correlation -&gt; Timeline -&gt; Intelligence</span></footer></div>
}

createRoot(document.getElementById('root')).render(<App />)
