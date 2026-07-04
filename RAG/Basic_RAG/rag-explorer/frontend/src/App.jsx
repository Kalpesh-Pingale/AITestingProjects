import React, { useState, useRef, useCallback } from 'react'

const API_BASE = '/api'

export default function App() {
  const [file, setFile] = useState(null)
  const [ingesting, setIngesting] = useState(false)
  const [querying, setQuerying] = useState(false)
  const [ingestionResult, setIngestionResult] = useState(null)
  const [queryResult, setQueryResult] = useState(null)
  const [query, setQuery] = useState('')
  const [stats, setStats] = useState(null)
  const [error, setError] = useState('')
  const fileInputRef = useRef()

  // --- Ingestion ---
  const handleFileChange = (e) => {
    const f = e.target.files?.[0]
    if (f && f.name.endsWith('.pdf')) {
      setFile(f)
      setError('')
    } else {
      setError('Please select a PDF file.')
    }
  }

  const handleIngest = useCallback(async () => {
    if (!file) return
    setIngesting(true)
    setError('')
    setIngestionResult(null)
    setQueryResult(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch(`${API_BASE}/ingest`, { method: 'POST', body: form })
      if (!res.ok) {
        const msg = await res.text()
        throw new Error(msg || 'Ingestion failed')
      }
      const data = await res.json()
      setIngestionResult(data)
      // Refresh stats
      const s = await fetch(`${API_BASE}/stats`).then((r) => r.json())
      setStats(s)
    } catch (err) {
      setError(err.message)
    } finally {
      setIngesting(false)
    }
  }, [file])

  // --- Query ---
  const handleQuery = useCallback(async () => {
    if (!query.trim()) return
    setQuerying(true)
    setError('')
    setQueryResult(null)
    try {
      const res = await fetch(`${API_BASE}/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: query.trim() }),
      })
      if (!res.ok) {
        const msg = await res.text()
        throw new Error('Query failed')
      }
      const data = await res.json()
      setQueryResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setQuerying(false)
    }
  }, [query])

  // --- Reset ---
  const handleReset = useCallback(async () => {
    await fetch(`${API_BASE}/reset`, { method: 'POST' })
    setIngestionResult(null)
    setQueryResult(null)
    setStats(null)
    setFile(null)
    setQuery('')
    setError('')
    if (fileInputRef.current) fileInputRef.current.value = ''
  }, [])

  return (
    <div className="app">
      <header className="header">
        <h1>RAG Explorer</h1>
        <p className="subtitle">
          End-to-end RAG pipeline &mdash; Ingest PDF &rarr; Chunk &rarr; Embed &rarr; Store &rarr; Retrieve &rarr; Answer
        </p>
      </header>

      {/* Flow steps visualization */}
      <div className="flow-bar">
        <Step label="Ingest" active={!!ingestionResult} />
        <Step label="Chunk" active={!!ingestionResult} count={ingestionResult?.num_chunks} />
        <Step label="Embed" active={!!ingestionResult} model={ingestionResult?.model} />
        <Step label="Store" active={!!stats} sub={stats ? `${stats.chunk_count} chunks` : ''} />
        <Step label="Retrieve" active={!!queryResult?.chunks?.length} count={queryResult?.chunks?.length} />
        <Step label="Answer" active={!!queryResult?.answer} model={queryResult?.llm_model} />
      </div>

      <div className="main-grid">
        {/* LEFT: Ingestion */}
        <section className="card">
          <h2>
            <span className="icon">&#128196;</span> PDF Ingestion
          </h2>
          <div className="card-body">
            <div className="upload-area">
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf"
                onChange={handleFileChange}
                disabled={ingesting}
              />
              <button
                className="btn btn-primary"
                onClick={handleIngest}
                disabled={!file || ingesting}
              >
                {ingesting ? 'Ingesting...' : 'Ingest PDF'}
              </button>
            </div>
            {ingestionResult && (
              <div className="result-box">
                <p><strong>Document:</strong> {ingestionResult.doc_name}</p>
                <p><strong>Total characters:</strong> {ingestionResult.total_chars.toLocaleString()}</p>
                <p><strong>Chunks created:</strong> {ingestionResult.num_chunks}</p>
                <p><strong>Embedding model:</strong> <code>{ingestionResult.model}</code></p>
                <p><strong>Vector DB:</strong> ChromaDB (local)</p>
              </div>
            )}
          </div>
        </section>

        {/* RIGHT: Query */}
        <section className="card">
          <h2>
            <span className="icon">&#128269;</span> Query
          </h2>
          <div className="card-body">
            <div className="query-area">
              <input
                type="text"
                placeholder="Ask a question about the PDF..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleQuery()}
                disabled={!ingestionResult || querying}
              />
              <button
                className="btn btn-primary"
                onClick={handleQuery}
                disabled={!query.trim() || querying || !ingestionResult}
              >
                {querying ? 'Thinking...' : 'Ask'}
              </button>
            </div>
            {queryResult && (
              <>
                <div className="result-box answer-box">
                  <p className="answer-label">Answer</p>
                  <p className="answer-text">{queryResult.answer}</p>
                  <p className="model-tag">
                    <strong>LLM:</strong> <code>{queryResult.llm_model}</code>
                  </p>
                </div>
                <details className="chunks-details" open>
                  <summary>
                    Retrieved Chunks ({queryResult.chunks.length})
                  </summary>
                  {queryResult.chunks.map((chunk, i) => (
                    <div key={i} className="chunk-card">
                      <div className="chunk-header">
                        <span>Chunk #{i + 1}</span>
                        <span className="score">Score: {chunk.score}</span>
                      </div>
                      <p className="chunk-text">{chunk.text}</p>
                    </div>
                  ))}
                </details>
              </>
            )}
          </div>
        </section>
      </div>

      {/* Error */}
      {error && <div className="error-banner">{error}</div>}

      {/* Controls */}
      {ingestionResult && (
        <div className="controls">
          <button className="btn btn-secondary" onClick={handleReset}>
            Reset &amp; Start Over
          </button>
        </div>
      )}

      {/* Pipeline info */}
      <footer className="footer">
        <p>
          <strong>Pipeline:</strong> PyMuPDF (extract) &rarr;
          LangChain RecursiveCharacterTextSplitter (chunk) &rarr;
          Nomic Embed (embedding) &rarr;
          ChromaDB (vector store) &rarr;
          Groq LLM (answer generation)
        </p>
      </footer>
    </div>
  )
}

function Step({ label, active, count, model, sub }) {
  return (
    <div className={`flow-step ${active ? 'active' : ''}`}>
      <div className="step-dot">{active ? '✓' : '○'}</div>
      <div className="step-label">{label}</div>
      {count !== undefined && <div className="step-meta">{count}</div>}
      {model && <div className="step-meta step-model">&#9881; {model.split('/').pop()}</div>}
      {sub && <div className="step-meta">{sub}</div>}
    </div>
  )
}
