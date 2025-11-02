import type { ChangeEvent, JSX } from 'react'
import { useState } from 'react'
import {
  AlertCircle,
  CheckCircle,
  Download,
  FileText,
  Upload,
} from 'lucide-react'
import './App.css'

type InspectionStatus =
  | 'idle'
  | 'json-loaded'
  | 'pdf-loaded'
  | 'ready'
  | 'processing'
  | 'complete'
  | 'error'

interface Address {
  fullAddress?: string
  street?: string
  city?: string
  state?: string
  zipcode?: string
}

interface Inspector {
  name?: string
  license?: string
}

interface Schedule {
  date?: string | number | null
}

interface ClientInfo {
  name?: string
}

interface MediaWithUrl {
  url?: string
}

interface Comment {
  commentText?: string
  text?: string
  photos?: (string | MediaWithUrl)[]
  videos?: (string | MediaWithUrl)[]
}

interface LineItem {
  inspectionStatus?: string
  title?: string
  name?: string
  comments?: Comment[]
}

interface Section {
  name?: string
  sectionNumber?: string
  lineItems?: LineItem[]
}

interface InspectionInfo {
  address?: Address
  clientInfo?: ClientInfo
  schedule?: Schedule
  inspector?: Inspector
  sections?: Section[]
}

interface InspectionJson {
  inspection?: InspectionInfo
  [key: string]: unknown
}

interface HeaderData {
  nameOfClient: string
  dateOfInspection: string
  addressOfInspectedProperty: string
  nameOfInspector: string
  trecLicense: string
  nameOfSponsor: string
  sponsorLicense: string
}

interface InspectionItem {
  section: string
  sectionNumber: string
  title: string
  status: string
  text: string
  photos: string[]
  videos: string[]
}

interface PreviewData {
  header: HeaderData
  items: InspectionItem[]
}

const App = (): JSX.Element => {
  const [jsonData, setJsonData] = useState<InspectionJson | null>(null)
  const [pdfTemplate, setPdfTemplate] = useState<File | null>(null)
  const [status, setStatus] = useState<InspectionStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<PreviewData | null>(null)

  const formatDate = (timestamp: Schedule['date']): string => {
    if (!timestamp) return 'Data not found'
    const date = new Date(timestamp)
    if (Number.isNaN(date.getTime())) return 'Data not found'

    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    })
  }

  const extractHeaderData = (data: InspectionJson): HeaderData => {
    const inspection = data.inspection ?? (data as InspectionInfo)
    const address: Address = inspection?.address ?? {}

    let fullAddress = address.fullAddress ?? ''
    if (!fullAddress) {
      const parts = [
        address.street ?? '',
        address.city ?? '',
        address.state ?? '',
        address.zipcode ?? '',
      ].filter(Boolean)
      fullAddress = parts.join(', ')
    }

    return {
      nameOfClient: inspection?.clientInfo?.name ?? 'Data not found',
      dateOfInspection: formatDate(inspection?.schedule?.date ?? null),
      addressOfInspectedProperty: fullAddress || 'Data not found',
      nameOfInspector: inspection?.inspector?.name ?? 'Data not found',
      trecLicense: inspection?.inspector?.license ?? '',
      nameOfSponsor: '',
      sponsorLicense: '',
    }
  }

  const extractInspectionItems = (data: InspectionJson): InspectionItem[] => {
    const inspection = data.inspection ?? (data as InspectionInfo)
    const items: InspectionItem[] = []

    ;(inspection?.sections ?? []).forEach((section) => {
      ;(section?.lineItems ?? []).forEach((lineItem) => {
        const status = (lineItem?.inspectionStatus ?? '').toUpperCase()
        const title = lineItem?.title ?? lineItem?.name ?? ''

        const commentTexts = (lineItem?.comments ?? [])
          .map((comment) => comment?.commentText ?? comment?.text ?? '')
          .filter((text) => text.trim().length > 0)
          .join('\n\n')

        const photos: string[] = []
        const videos: string[] = []

        ;(lineItem?.comments ?? []).forEach((comment) => {
          ;(comment?.photos ?? []).forEach((photo) => {
            const url =
              typeof photo === 'string' ? photo : photo.url ?? undefined
            if (url) photos.push(url)
          })
          ;(comment?.videos ?? []).forEach((video) => {
            const url =
              typeof video === 'string' ? video : video.url ?? undefined
            if (url) videos.push(url)
          })
        })

        if (title || commentTexts) {
          items.push({
            section: section?.name ?? '',
            sectionNumber: section?.sectionNumber ?? '',
            title,
            status,
            text: commentTexts,
            photos,
            videos,
          })
        }
      })
    })

    return items
  }

  const handleJsonUpload = (event: ChangeEvent<HTMLInputElement>): void => {
    const file = event.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (loadEvent: ProgressEvent<FileReader>) => {
      try {
        const result = loadEvent.target?.result
        if (typeof result !== 'string') {
          throw new Error('File could not be read as text')
        }

        const parsed = JSON.parse(result) as InspectionJson
        setJsonData(parsed)
        setError(null)

        const header = extractHeaderData(parsed)
        const items = extractInspectionItems(parsed)
        setPreview({ header, items })
        setStatus(pdfTemplate ? 'ready' : 'json-loaded')
      } catch (err) {
        const message =
          err instanceof Error ? err.message : 'Unknown parsing error'
        setError(`Invalid JSON file: ${message}`)
        setStatus('error')
      }
    }
    reader.readAsText(file)
  }

  const handlePdfUpload = (event: ChangeEvent<HTMLInputElement>): void => {
    const file = event.target.files?.[0]
    if (!file) return

    setPdfTemplate(file)
    setError(null)
    setStatus(jsonData ? 'ready' : 'pdf-loaded')
  }

  const generatePdf = (): void => {
    if (status !== 'ready') return
    setStatus('processing')

    window.setTimeout(() => {
      setStatus('complete')
      window.alert(
        'PDF generation complete! In a real implementation, this would use pdf-lib to fill the TREC form and generate a downloadable PDF.',
      )
    }, 2000)
  }

  return (
    <div className="app">
      <div className="layout">
        <header className="hero">
          <div className="hero__icon">
            <FileText className="icon icon--hero" />
          </div>
          <h1 className="hero__title">TREC Inspection Report Generator</h1>
          <p className="hero__subtitle">
            Upload your inspection JSON and TREC template to generate a filled
            PDF report
          </p>
        </header>

        <section className="card-grid">
          <article
            className={`card ${jsonData ? 'card--active' : ''}`}
            aria-live="polite"
          >
            <div className="card__header">
              <h2 className="card__title">1. Upload Inspection Data (JSON)</h2>
              {jsonData && <CheckCircle className="status-icon status-icon--success" />}
            </div>
            <label
              className={`upload-zone ${jsonData ? 'upload-zone--active' : ''}`}
            >
              <Upload className="icon icon--upload" />
              <p className="upload-zone__hint">
                {jsonData ? '✓ JSON file loaded' : 'Click to upload JSON file'}
              </p>
              <p className="upload-zone__filename">inspection.json</p>
              <input
                type="file"
                accept=".json"
                onChange={handleJsonUpload}
                className="upload-zone__input"
              />
            </label>
          </article>

          <article
            className={`card ${pdfTemplate ? 'card--active' : ''}`}
            aria-live="polite"
          >
            <div className="card__header">
              <h2 className="card__title">2. Upload TREC Template (PDF)</h2>
              {pdfTemplate && <CheckCircle className="status-icon status-icon--success" />}
            </div>
            <label
              className={`upload-zone ${pdfTemplate ? 'upload-zone--active' : ''}`}
            >
              <Upload className="icon icon--upload" />
              <p className="upload-zone__hint">
                {pdfTemplate
                  ? '✓ PDF template loaded'
                  : 'Click to upload PDF template'}
              </p>
              <p className="upload-zone__filename">TREC_Template_Blank.pdf</p>
              <input
                type="file"
                accept=".pdf"
                onChange={handlePdfUpload}
                className="upload-zone__input"
              />
            </label>
          </article>
        </section>

        {error && (
          <section className="alert alert--error" role="alert">
            <AlertCircle className="alert__icon" />
            <div className="alert__content">
              <h3 className="alert__title">Error</h3>
              <p className="alert__message">{error}</p>
            </div>
          </section>
        )}

        {preview && (
          <section className="preview">
            <h2 className="preview__title">Data Preview</h2>

            <div className="preview__panel">
              <h3 className="preview__panel-title">
                Report Header Information
              </h3>
              <div className="preview__grid">
                <div className="preview__item">
                  <span className="preview__label">Client Name:</span>
                  <p className="preview__value">
                    {preview.header.nameOfClient}
                  </p>
                </div>
                <div className="preview__item">
                  <span className="preview__label">Inspection Date:</span>
                  <p className="preview__value">
                    {preview.header.dateOfInspection}
                  </p>
                </div>
                <div className="preview__item preview__item--full">
                  <span className="preview__label">Property Address:</span>
                  <p className="preview__value">
                    {preview.header.addressOfInspectedProperty}
                  </p>
                </div>
                <div className="preview__item">
                  <span className="preview__label">Inspector:</span>
                  <p className="preview__value">
                    {preview.header.nameOfInspector}
                  </p>
                </div>
                <div className="preview__item">
                  <span className="preview__label">TREC License:</span>
                  <p className="preview__value">
                    {preview.header.trecLicense || 'N/A'}
                  </p>
                </div>
              </div>
            </div>

            <div className="stats">
              <div className="stats__header">
                <h3 className="preview__panel-title">Inspection Items</h3>
              </div>
              <div className="stats__grid">
                <div className="stat">
                  <p className="stat__value">{preview.items.length}</p>
                  <p className="stat__label">Total Items</p>
                </div>
                <div className="stat stat--deficient">
                  <p className="stat__value">
                    {preview.items.filter((item) => item.status === 'D').length}
                  </p>
                  <p className="stat__label">Deficient</p>
                </div>
                <div className="stat stat--inspected">
                  <p className="stat__value">
                    {preview.items.filter((item) => item.status === 'I').length}
                  </p>
                  <p className="stat__label">Inspected</p>
                </div>
                <div className="stat stat--pending">
                  <p className="stat__value">
                    {
                      preview.items.filter((item) => item.status === 'NI')
                        .length
                    }
                  </p>
                  <p className="stat__label">Not Inspected</p>
                </div>
              </div>

              <div className="samples">
                <p className="samples__label">Sample Items:</p>
                {preview.items.slice(0, 3).map((item, index) => (
                  <div className="sample-card" key={index}>
                    <div className="sample-card__header">
                      <span className="sample-card__title">{item.title}</span>
                      <span className={`status-chip status-chip--${item.status.toLowerCase() || 'na'}`}>
                        {item.status || 'N/A'}
                      </span>
                    </div>
                    <p className="sample-card__meta">
                      Section: {item.sectionNumber}. {item.section}
                    </p>
                    {item.text && (
                      <p className="sample-card__excerpt">
                        {item.text.substring(0, 150)}...
                      </p>
                    )}
                  </div>
                ))}
                {preview.items.length > 3 && (
                  <p className="samples__more">
                    ... and {preview.items.length - 3} more items
                  </p>
                )}
              </div>
            </div>
          </section>
        )}

        <section className="cta-section">
          <button
            onClick={generatePdf}
            disabled={status !== 'ready'}
            className={`cta ${status === 'ready' ? 'cta--ready' : ''} ${
              status === 'processing' ? 'cta--processing' : ''
            }`}
          >
            <Download className="icon icon--cta" />
            <span>
              {status === 'processing'
                ? 'Generating PDF...'
                : status === 'complete'
                  ? 'PDF Generated!'
                  : status === 'ready'
                    ? 'Generate Filled TREC Report'
                    : 'Upload Both Files to Continue'}
            </span>
          </button>

          {status === 'ready' && (
            <p className="cta__helper">
              This will fill the TREC form with inspection data and generate a
              downloadable PDF
            </p>
          )}
        </section>
      </div>
    </div>
  )
}

export default App
