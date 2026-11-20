import { useCallback, useEffect, useState } from 'react';
import {
  LayoutDashboard,
  Activity,
  GitPullRequest,
  ShieldCheck,
  FileText,
  Wifi,
  WifiOff,
  AlertTriangle,
  CheckCircle2,
  Lock,
  X,
  Plus,
  Search,
  MapPin,
  Clock3,
  Sparkles,
  MessageSquareText
} from 'lucide-react';
import { syncManager } from './syncManager';
import geometricCstEmblem from './assets/geometric-cst-emblem.png';

const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL;
const API_BASE_URL = (
  configuredApiBaseUrl
    ? (/^https?:\/\//i.test(configuredApiBaseUrl)
      ? configuredApiBaseUrl
      : `https://${configuredApiBaseUrl}`)
    : `${window.location.protocol}//${window.location.hostname}:8000`
).replace(/\/+$/, '');

const DEMO_CLINICIANS = [
  { name: 'Dr. Tlhagiso', email: 'dr.tlhagiso@health.gov.bw', accessPin: '2026' },
  { name: 'Dr. Kabelo', email: 'dr.kabelo@health.gov.bw', accessPin: '2026' }
];

function apiFetch(path, options = {}) {
  return fetch(`${API_BASE_URL}${path}`, { credentials: 'include', ...options }).catch((error) => {
    if (error instanceof TypeError) {
      throw new Error('Could not reach the ScreenToCare API. Check that the backend is running and try again.');
    }
    throw error;
  });
}

export default function ScreenToCareDashboard() {
  const [selectedPortal, setSelectedPortal] = useState('welcome');
  const [clinicianSession, setClinicianSession] = useState(null);
  const [portalError, setPortalError] = useState('');
  const [selectedClinicianEmail, setSelectedClinicianEmail] = useState(DEMO_CLINICIANS[0].email);
  const [authForm, setAuthForm] = useState({
    email: DEMO_CLINICIANS[0].email,
    accessPin: DEMO_CLINICIANS[0].accessPin
  });

  const enterClinicianPortal = async (event) => {
    event.preventDefault();
    setPortalError('');
    try {
      const response = await apiFetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: authForm.email.trim(),
          password: authForm.accessPin
        })
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail || 'Could not sign in to the clinician command center.');
      }
      setClinicianSession({
        id: result.user_id,
        name: result.full_name,
        role: result.clinical_role,
        email: result.email,
        session_token: result.session_token
      });
      setSelectedPortal('clinician');
    } catch (error) {
      setPortalError(error.message);
    }
  };

  const signOut = () => {
    apiFetch('/api/v1/auth/logout', { method: 'POST' }).catch(() => {});
    setClinicianSession(null);
    setSelectedPortal('welcome');
  };

  if (selectedPortal === 'clinician' && clinicianSession) {
    return (
      <ClinicianDashboard
        key={clinicianSession.session_token}
        initialClinician={clinicianSession}
        onSignOut={signOut}
      />
    );
  }

  if (selectedPortal === 'patient') {
    return (
      <div className="animate-enter min-h-screen bg-[#DCE5DF] px-4 py-8 font-sans text-[#2E4742] sm:px-6">
        <PatientPortalView onExit={() => setSelectedPortal('welcome')} />
      </div>
    );
  }

  return (
    <main className="animate-enter flex min-h-screen items-center justify-center bg-[#DCE5DF] px-4 py-10 font-sans text-[#2E4742]">
      <div className="w-full max-w-5xl overflow-hidden rounded-[36px] border border-white/60 bg-[#E8EFEA] shadow-2xl">
        <header className="welcome-header bg-[#2E4742] px-6 py-10 text-center text-white sm:px-10 sm:py-14">
          <img
            src={geometricCstEmblem}
            alt="ScreenToCare CST emblem"
            className="welcome-mark mx-auto h-[117px] w-[117px] object-contain"
          />
          <p className="welcome-copy welcome-copy--eyebrow mt-5 text-xs font-bold uppercase tracking-[0.2em] text-[#D4A329]">
            Challenge 05 · ScreenToCare
          </p>
          <h1 className="welcome-copy welcome-copy--title mt-3 text-3xl font-bold sm:text-4xl">Welcome to ScreenToCare</h1>
          <p className="welcome-copy welcome-copy--subtitle mx-auto mt-3 max-w-2xl text-sm leading-relaxed text-[#D7E2DE] sm:text-base">
            Choose the view that matches what you want to do.
          </p>
        </header>

        <section className="grid gap-5 p-5 sm:grid-cols-2 sm:p-8">
          <article className="welcome-card welcome-card--patient flex flex-col rounded-3xl border border-[#2E4742]/10 bg-white p-6 shadow-sm sm:p-8">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#FBF8EE] text-xl font-bold text-[#D4A329]">
              P
            </div>
            <h2 className="mt-5 text-xl font-bold text-[#2E4742]">Patient portal</h2>
            <p className="mt-2 flex-1 text-sm leading-relaxed text-[#617873]">
              View your screening progress, urgency, clinic follow-up details, and next steps.
            </p>
            <button
              type="button"
              onClick={() => {
                setPortalError('');
                setSelectedPortal('patient');
              }}
              className="mt-6 min-h-12 rounded-xl bg-[#D4A329] px-5 py-3 text-sm font-bold text-[#2E4742] transition hover:bg-[#c49520]"
            >
              Continue as patient
            </button>
          </article>

          <article className="welcome-card welcome-card--hospital flex flex-col rounded-3xl border border-[#2E4742]/10 bg-white p-6 shadow-sm sm:p-8">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#E8EFEA] text-xl font-bold text-[#2E4742]">
              H
            </div>
            <h2 className="mt-5 text-xl font-bold text-[#2E4742]">Hospital / clinician access</h2>
            <p className="mt-2 flex-1 text-sm leading-relaxed text-[#617873]">
              Select a demo clinician and sign in with their credentials.
            </p>
            <form className="mt-5 space-y-3" onSubmit={enterClinicianPortal}>
              <select
                value={selectedClinicianEmail}
                onChange={(event) => {
                  const clinicianEmail = event.target.value;
                  const clinician = DEMO_CLINICIANS.find((item) => item.email === clinicianEmail);
                  setSelectedClinicianEmail(clinicianEmail);
                  setAuthForm({ email: clinicianEmail, accessPin: clinician?.accessPin || '' });
                  setPortalError('');
                }}
                className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-[#D4A329]"
                aria-label="Select clinician"
              >
                {DEMO_CLINICIANS.map((clinician) => (
                  <option key={clinician.email} value={clinician.email}>{clinician.name}</option>
                ))}
              </select>
              <input
                required
                type="password"
                value={authForm.accessPin}
                onChange={(event) => setAuthForm({ ...authForm, accessPin: event.target.value })}
                placeholder="Access PIN"
                autoComplete="current-password"
                className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-[#D4A329]"
              />
              <p className="text-xs text-emerald-800">
                Preloaded demo account. The demo PIN is filled in for you.
              </p>
              {portalError && (
                <p role="alert" className="rounded-xl bg-red-50 px-3 py-2 text-xs font-semibold text-red-800">
                  {portalError}
                </p>
              )}
              <button
                type="submit"
                className="min-h-12 w-full rounded-xl bg-[#2E4742] px-5 py-3 text-sm font-bold text-white transition hover:bg-[#233834] disabled:cursor-wait disabled:opacity-60"
              >
                Enter Clinician Command Center
              </button>
            </form>
          </article>
        </section>

        <footer className="px-6 pb-6 text-center text-[11px] leading-relaxed text-[#617873] sm:px-8 sm:pb-8">
          Demo accounts are locally authenticated. Do not enter real patient information or expose this prototype publicly.
        </footer>
      </div>
    </main>
  );
}

function formatTurnaroundHours(hours) {
  if (hours === null || hours === undefined) return '—';
  return hours >= 24 ? `${(hours / 24).toFixed(1)} days` : `${hours} hours`;
}

function PatientPortalView({ onExit }) {
  const [identifier, setIdentifier] = useState('');
  const [dateOfBirth, setDateOfBirth] = useState('');
  const [portalRecord, setPortalRecord] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  const handleLookup = async (event) => {
    event.preventDefault();
    setIsLoading(true);
    setError('');
    setPortalRecord(null);
    try {
      const response = await apiFetch('/api/v1/patient-portal/lookup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ identifier: identifier.trim(), date_of_birth: dateOfBirth })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'We could not load your screening update.');
      setPortalRecord(result);
    } catch (lookupError) {
      setError(lookupError.message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <section className="mx-auto w-full max-w-3xl">
      <div className="overflow-hidden rounded-[28px] border border-white/70 bg-white shadow-sm">
        <div className="bg-[#2E4742] px-5 py-6 text-white sm:px-8 sm:py-8">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-[#D4A329]">
                ScreenToCare Patient Portal
              </p>
              <h2 className="mt-2 text-2xl font-bold sm:text-3xl">Your care, one step at a time</h2>
              <p className="mt-2 max-w-xl text-sm leading-relaxed text-[#E8EFEA]">
                Check the latest update about your screening and what to do next.
              </p>
            </div>
            <button
              type="button"
              onClick={onExit}
              className="shrink-0 rounded-full border border-white/30 px-3 py-2 text-xs font-semibold text-white transition hover:bg-white/10"
            >
              Back
            </button>
          </div>
        </div>

        <div className="grid gap-6 p-5 sm:p-8">
          <form onSubmit={handleLookup} className="grid gap-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
            <label className="block text-sm font-bold text-[#2E4742]">
              Omang ID or tracking code
              <input
                type="text"
                required
                minLength={3}
                value={identifier}
                onChange={(event) => setIdentifier(event.target.value)}
                autoComplete="off"
                className="mt-1.5 w-full rounded-xl border border-slate-300 px-3.5 py-3 text-sm font-normal text-[#2E4742] outline-none focus:border-[#2E4742] focus:ring-2 focus:ring-[#2E4742]/10"
                placeholder="Enter your ID or case code"
              />
            </label>
            <label className="block text-sm font-bold text-[#2E4742]">
              Date of birth
              <input
                type="date"
                required
                value={dateOfBirth}
                onChange={(event) => setDateOfBirth(event.target.value)}
                className="mt-1.5 w-full rounded-xl border border-slate-300 px-3.5 py-3 text-sm font-normal text-[#2E4742] outline-none focus:border-[#2E4742] focus:ring-2 focus:ring-[#2E4742]/10"
              />
            </label>
            <button
              type="submit"
              disabled={isLoading}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-[#D4A329] px-5 py-3 text-sm font-bold text-[#2E4742] transition hover:bg-[#c49520] disabled:cursor-wait disabled:opacity-60"
            >
              <Search className="h-4 w-4" />
              {isLoading ? 'Checking…' : 'View update'}
            </button>
          </form>

          <p className="rounded-xl bg-[#F4F8F6] px-4 py-3 text-xs leading-relaxed text-[#617873]">
            For privacy, your date of birth is used to verify this record. If you need help, contact the clinic where you were screened.
          </p>

          {error && (
            <p role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-800">
              {error}
            </p>
          )}

          {portalRecord && (
            <article className="overflow-hidden rounded-2xl border-2 border-[#2E4742] bg-[#F8FAF9]">
              <div className="flex flex-wrap items-start justify-between gap-4 bg-[#2E4742] px-5 py-4 text-white">
                <div>
                  <p className="text-xs text-[#C4D3CF]">Hello, {portalRecord.patient_first_name}</p>
                  <h3 className="mt-1 text-xl font-bold">{portalRecord.status_text}</h3>
                </div>
                <span className="rounded-full bg-[#D4A329] px-3 py-1.5 text-xs font-bold text-[#2E4742]">
                  {portalRecord.urgency_level.replaceAll('_', ' ')}
                </span>
              </div>

              <div className="grid gap-4 p-5 sm:grid-cols-2 sm:p-6">
                <div className="rounded-xl border border-[#D4A329]/50 bg-[#FBF8EE] p-4 sm:col-span-2">
                  <p className="text-sm font-bold text-[#2E4742]">{portalRecord.urgency_text}</p>
                  <p className="mt-1 text-xs text-[#617873]">
                    Screening: {portalRecord.screening_type}
                  </p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-white p-4">
                  <p className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide text-[#617873]">
                    <MapPin className="h-4 w-4 text-[#D4A329]" /> Clinic
                  </p>
                  <p className="mt-2 text-sm font-bold text-[#2E4742]">{portalRecord.facility}</p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-white p-4">
                  <p className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide text-[#617873]">
                    <Clock3 className="h-4 w-4 text-[#D4A329]" /> Appointment details
                  </p>
                  <p className="mt-2 text-sm font-semibold text-[#2E4742]">
                    {portalRecord.appointment_details.message}
                  </p>
                  <p className="mt-1 text-xs text-[#617873]">
                    Follow-up target: {new Date(portalRecord.appointment_details.follow_up_by).toLocaleString()}
                  </p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-white p-4 sm:col-span-2">
                  <h4 className="text-sm font-bold text-[#2E4742]">What to do next</h4>
                  <ol className="mt-2 list-decimal space-y-2 pl-5 text-sm leading-relaxed text-[#425C56]">
                    {portalRecord.next_steps.map((step, index) => <li key={index}>{step}</li>)}
                  </ol>
                </div>
                <p className="text-[11px] text-[#617873] sm:col-span-2">
                  Tracking code: <span className="font-mono font-semibold">{portalRecord.tracking_code}</span>
                </p>
              </div>
            </article>
          )}
        </div>
      </div>
    </section>
  );
}

function ClinicianDashboard({ initialClinician, onSignOut }) {
  const [activeNav, setActiveNav] = useState('COMMAND CENTER');
  const [cases, setCases] = useState([]);
  const [referrals, setReferrals] = useState([]);
  const [auditEvents, setAuditEvents] = useState([]);
  const [impactMetrics, setImpactMetrics] = useState(null);
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [queuedCount, setQueuedCount] = useState(0);
  const [selectedCase, setSelectedCase] = useState(null);
  const [selectedFhirCase, setSelectedFhirCase] = useState(null);
  const [isIntakeOpen, setIsIntakeOpen] = useState(false);
  const [isAnalysisOpen, setIsAnalysisOpen] = useState(false);
  const [analysisNotes, setAnalysisNotes] = useState('');
  const [analysisScreeningType, setAnalysisScreeningType] = useState('Community Screening');
  const [analysisFacility, setAnalysisFacility] = useState('Mobile Outreach');
  const [analysisResult, setAnalysisResult] = useState(null);
  const [analysisError, setAnalysisError] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [pageError, setPageError] = useState('');
  const [statusMessage, setStatusMessage] = useState('');
  const [closureError, setClosureError] = useState('');
  const [intakeError, setIntakeError] = useState('');
  const activeClinician = initialClinician;
  const clinicianSessionToken = initialClinician.session_token;
  const [evidenceDocId, setEvidenceDocId] = useState('');
  const [dischargeDocumentId, setDischargeDocumentId] = useState('');
  const [clinicalOutcomeNote, setClinicalOutcomeNote] = useState('');
  const [clinicianSignoff, setClinicianSignoff] = useState('');
  const [escalationBanner, setEscalationBanner] = useState('');
  const [intakeForm, setIntakeForm] = useState({
    patient_national_id: '',
    patient_name: '',
    date_of_birth: '',
    gender: '',
    phone_number: '',
    consent_signed: false,
    preferred_channel: 'whatsapp',
    screening_type: '',
    facility: '',
    raw_screening_notes: ''
  });

  const refreshDashboardData = useCallback(async () => {
    const [casesResponse, referralsResponse, auditResponse, metricsResponse] = await Promise.all([
      apiFetch('/api/v1/cases'),
      apiFetch('/api/v1/referrals'),
      apiFetch('/api/v1/audit'),
      apiFetch('/api/v1/metrics/impact')
    ]);
    if (!casesResponse.ok || !referralsResponse.ok || !auditResponse.ok || !metricsResponse.ok) {
      throw new Error('Could not load dashboard data from the ScreenToCare API.');
    }
    const [caseData, referralData, auditData, metricsData] = await Promise.all([
      casesResponse.json(),
      referralsResponse.json(),
      auditResponse.json(),
      metricsResponse.json()
    ]);
    const formattedCases = caseData.map((item) => ({
      ...item,
      avatar: item.patient_name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase()
    }));
    setCases(formattedCases);
    setSelectedCase((currentCase) => currentCase
      ? formattedCases.find((item) => item.case_id === currentCase.case_id) || currentCase
      : currentCase);
    setSelectedFhirCase((currentCase) => currentCase
      ? formattedCases.find((item) => item.case_id === currentCase.case_id) || currentCase
      : currentCase);
    setReferrals(referralData);
    setAuditEvents(auditData);
    setImpactMetrics(metricsData);
    const latestAlert = formattedCases
      .map((item) => item.sla_escalation_alert)
      .filter(Boolean)
      .sort((left, right) => new Date(right.timestamp) - new Date(left.timestamp))[0];
    if (latestAlert) setEscalationBanner(latestAlert.message);
  }, []);

  useEffect(() => {
    syncManager.setEnabled(true);
    Promise.resolve()
      .then(refreshDashboardData)
      .catch((error) => setPageError(error.message));
    syncManager.getQueueCount()
      .then(setQueuedCount)
      .catch((error) => setPageError(error.message));
    const refreshTimer = window.setInterval(() => {
      refreshDashboardData().catch((error) => setPageError(error.message));
    }, 30000);

    const updateQueueCount = (event) => {
      if (Number.isInteger(event.detail?.count)) {
        setQueuedCount(event.detail.count);
      } else {
        syncManager.getQueueCount()
          .then(setQueuedCount)
          .catch((error) => setPageError(error.message));
      }
    };
    const handleNetworkChange = () => setIsOnline(navigator.onLine);
    const handleSyncComplete = (event) => {
      if (event.detail?.failed_count) {
        setPageError(`${event.detail.failed_count} queued record(s) still need attention.`);
        setStatusMessage('');
      } else if (event.detail?.records_processed) {
        setPageError('');
        setStatusMessage(`${event.detail.records_processed} queued record(s) synced and triaged.`);
      }
      refreshDashboardData().catch((error) => setPageError(error.message));
    };
    const handleSyncError = (event) => setPageError(event.detail || 'Offline sync failed.');

    window.addEventListener('cb_queue_updated', updateQueueCount);
    window.addEventListener('cb_sync_complete', handleSyncComplete);
    window.addEventListener('cb_sync_error', handleSyncError);
    window.addEventListener('online', handleNetworkChange);
    window.addEventListener('offline', handleNetworkChange);
    return () => {
      window.removeEventListener('cb_queue_updated', updateQueueCount);
      window.removeEventListener('cb_sync_complete', handleSyncComplete);
      window.removeEventListener('cb_sync_error', handleSyncError);
      window.removeEventListener('online', handleNetworkChange);
      window.removeEventListener('offline', handleNetworkChange);
      window.clearInterval(refreshTimer);
      syncManager.setEnabled(false);
    };
  }, [refreshDashboardData]);

  const queueIntakeForSync = async () => {
    setIsOnline(false);
    const queuedRecord = await syncManager.saveToLocalQueue({
      ...intakeForm,
      record_type: 'triage',
      actor_name: activeClinician.name
    });
    setCases((currentCases) => [{
      case_id: queuedRecord.queue_id,
      patient_name: queuedRecord.patient_name,
      screening_type: queuedRecord.screening_type,
      facility: queuedRecord.facility || 'Offline outreach',
      risk_level: 'PENDING_TRIAGE',
      sla_remaining: 'Queued',
      status: 'QUEUED_OFFLINE',
      avatar: queuedRecord.patient_name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase()
    }, ...currentCases]);
    setStatusMessage('Screening saved offline and will be triaged when the connection returns.');
    setIsIntakeOpen(false);
  };

  const handleIntakeSubmit = async (event) => {
    event.preventDefault();
    setIsSubmitting(true);
    setIntakeError('');
    setPageError('');
    try {
      if (!isOnline) {
        await queueIntakeForSync();
      } else {
        const response = await apiFetch('/api/v1/screening/triage', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...intakeForm, actor_name: activeClinician.name })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || 'Clinical intake triage failed.');
        await refreshDashboardData();
        setStatusMessage(
          `Demo triage: ${result.triage.risk_level}, ${result.triage.sla_hours}h SLA. Case added to the screening queue.`
        );
      }

      setIntakeForm({
        patient_national_id: '',
        patient_name: '',
        date_of_birth: '',
        gender: '',
        phone_number: '',
        consent_signed: false,
        preferred_channel: 'whatsapp',
        screening_type: '',
        facility: '',
        raw_screening_notes: ''
      });
      setIsIntakeOpen(false);
    } catch (error) {
      if (isOnline && error instanceof TypeError) {
        try {
          await queueIntakeForSync();
          setIntakeError('');
        } catch (queueError) {
          setIntakeError(queueError.message);
        }
      } else {
        setIntakeError(error.message);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleTriagePreview = async (event) => {
    event.preventDefault();
    setIsAnalyzing(true);
    setAnalysisError('');
    setAnalysisResult(null);
    try {
      const response = await apiFetch('/api/v1/screening/triage-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          raw_screening_notes: analysisNotes,
          screening_type: analysisScreeningType,
          facility: analysisFacility
        })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Could not analyze the screening notes.');
      setAnalysisResult(result);
    } catch (error) {
      setAnalysisError(error.message);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const useAnalysisInIntake = () => {
    setIntakeForm((form) => ({
      ...form,
      screening_type: analysisScreeningType,
      facility: analysisFacility,
      raw_screening_notes: analysisNotes
    }));
    setIntakeError('');
    setIsAnalysisOpen(false);
    setIsIntakeOpen(true);
  };

  const openTriageAnalyzer = () => {
    setAnalysisError('');
    setAnalysisResult(null);
    setAnalysisNotes('');
    setAnalysisScreeningType('Community Screening');
    setAnalysisFacility('Mobile Outreach');
    setIsAnalysisOpen(true);
  };

  const handleDualKeyClose = async (event) => {
    event.preventDefault();
    setPageError('');
    if (!evidenceDocId.trim()) {
      setClosureError('Enter the clinical evidence document ID.');
      return;
    }
    if (!selectedCase.discharge_summary) {
      setClosureError('Upload the receiving hospital discharge summary before closing this case.');
      return;
    }
    if (!selectedCase.signoffs?.primary || !selectedCase.signoffs?.secondary) {
      setClosureError('Record independent primary and secondary clinician sign-offs before closure.');
      return;
    }
    setIsSubmitting(true);
    try {
      const response = await apiFetch(
        `/api/v1/cases/${selectedCase.case_id}/close`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ clinical_evidence_doc_id: evidenceDocId.trim() })
        }
      );

      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail || 'Case closure failed.');
      }

      await refreshDashboardData();
      setSelectedCase(null);
      setEvidenceDocId('');
      setDischargeDocumentId('');
      setClinicalOutcomeNote('');
      setClinicianSignoff('');
      setClosureError('');
      setStatusMessage(result.message);
    } catch (error) {
      setClosureError(error.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClinicianSignoff = async () => {
    setClosureError('');
    if (!clinicianSessionToken) {
      setClosureError('Switch to an active clinician session before signing.');
      return;
    }
    if (!clinicianSignoff.trim()) {
      setClosureError('Enter the active clinician sign-off value.');
      return;
    }
    if (
      selectedCase.signoffs?.primary &&
      activeClinician.name.toLowerCase() === selectedCase.signoffs.primary.clinician.toLowerCase()
    ) {
      setClosureError('The primary clinician cannot provide the secondary sign-off. Sign out and use a different clinician account.');
      return;
    }
    setIsSubmitting(true);
    try {
      const response = await apiFetch(
        `/api/v1/cases/${selectedCase.case_id}/signoff`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_token: clinicianSessionToken,
            signature: clinicianSignoff.trim()
          })
        }
      );
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Clinician sign-off failed.');
      await refreshDashboardData();
      setClinicianSignoff('');
      setStatusMessage(`${result.role === 'primary' ? 'Primary' : 'Secondary'} sign-off recorded for ${activeClinician.name}.`);
    } catch (error) {
      setClosureError(error.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const toggleNetwork = async () => {
    const nextOnlineState = !isOnline;
    setIsOnline(nextOnlineState);
    if (nextOnlineState) {
      setPageError('');
      try {
        await syncManager.flushQueue();
        setQueuedCount(await syncManager.getQueueCount());
        await refreshDashboardData();
      } catch (error) {
        setPageError(error.message);
      }
    }
  };

  const handleGenerateAndDispatch = async (caseId) => {
    setPageError('');
    try {
      const response = await apiFetch(`/api/v1/cases/${caseId}/dispatch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actor_name: activeClinician.name })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'FHIR ServiceRequest dispatch failed.');
      await refreshDashboardData();
      setStatusMessage(`FHIR ServiceRequest ${result.service_request.id} generated and dispatched.`);
    } catch (error) {
      setPageError(error.message);
    }
  };

  const handlePatientArrival = async (caseId) => {
    setPageError('');
    try {
      const response = await apiFetch(`/api/v1/cases/${caseId}/arrival`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actor_name: 'Receiving Facility Check-In' })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Patient arrival check-in failed.');
      await refreshDashboardData();
      setStatusMessage(`${result.case.patient_name} checked in at the receiving facility.`);
    } catch (error) {
      setPageError(error.message);
    }
  };

  const handleSlaEscalation = async (caseId) => {
    setPageError('');
    try {
      const response = await apiFetch(`/api/v1/cases/${caseId}/escalate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          actor_name: 'DHMT Escalation Desk',
          alert_reason: 'Urgent DHMT escalation requested for referral SLA risk.'
        })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'SLA escalation failed.');
      await refreshDashboardData();
      setEscalationBanner(`${result.alert.message} Case ${caseId}.`);
    } catch (error) {
      setPageError(error.message);
    }
  };

  const handleDischargeSummaryUpload = async () => {
    setClosureError('');
    if (!dischargeDocumentId.trim() || !clinicalOutcomeNote.trim()) {
      setClosureError('Enter a discharge document ID and clinical outcome note before uploading.');
      return;
    }
    setIsSubmitting(true);
    try {
      const response = await apiFetch(
        `/api/v1/cases/${selectedCase.case_id}/discharge-summary`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            document_id: dischargeDocumentId.trim(),
            clinical_outcome_note: clinicalOutcomeNote.trim(),
            actor_name: activeClinician.name
          })
        }
      );
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Discharge summary upload failed.');
      await refreshDashboardData();
      setStatusMessage('Receiving hospital discharge summary uploaded; treatment marked complete.');
    } catch (error) {
      setClosureError(error.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const loadCaseRecord = async (caseItem) => {
    setPageError('');
    try {
      const response = await apiFetch(`/api/v1/cases/${caseItem.case_id}`);
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Could not open this case record.');
      const record = {
        ...caseItem,
        ...result,
        avatar: caseItem.avatar
      };
      setCases((current) => current.map((item) => (
        item.case_id === record.case_id ? { ...item, ...record } : item
      )));
      const auditResponse = await apiFetch('/api/v1/audit');
      if (auditResponse.ok) setAuditEvents(await auditResponse.json());
      return record;
    } catch (error) {
      setPageError(error.message);
      return null;
    }
  };

  const openClosureCase = async (caseItem) => {
    const record = await loadCaseRecord(caseItem);
    if (!record) return;
    setSelectedCase(record);
    setClosureError('');
    setDischargeDocumentId('');
    setClinicalOutcomeNote('');
  };

  const openFhirCase = async (caseItem) => {
    const record = await loadCaseRecord(caseItem);
    if (record) setSelectedFhirCase(record);
  };

  const navItems = [
    { name: 'COMMAND CENTER', icon: LayoutDashboard },
    { name: 'SCREENING QUEUE', icon: Activity },
    { name: 'REFERRAL HANDOFFS', icon: GitPullRequest },
    { name: 'DUAL-KEY CLOSURES', icon: ShieldCheck },
    { name: 'AUDIT LEDGER', icon: FileText }
  ];

  const screeningQueueCases = cases.filter(
    (item) => ['RESULT_INGESTED', 'QUEUED_OFFLINE'].includes(item.status)
  );
  const handoffReferrals = referrals.filter(
    (item) => ['REFERRAL_DISPATCHED', 'PATIENT_NOTIFIED'].includes(item.case_status)
  );
  const closureCases = cases.filter(
    (item) => ['ARRIVED_AT_FACILITY', 'TREATMENT_COMPLETED'].includes(item.status)
  );
  const activeCases = activeNav === 'DUAL-KEY CLOSURES' ? closureCases : screeningQueueCases;
  const pendingReferrals = handoffReferrals;
  const patientCommsLog = referrals
    .flatMap((item) => item.communication_log || [])
    .sort((left, right) => new Date(right.timestamp) - new Date(left.timestamp));
  const closedCaseCount = cases.filter((item) => item.status === 'CLOSED').length;
  const dispatchedCaseCount = cases.filter(
    (item) => ['REFERRAL_DISPATCHED', 'PATIENT_NOTIFIED'].includes(item.status)
  ).length;
  const ingestedCaseCount = cases.filter(
    (item) => item.status === 'RESULT_INGESTED'
  ).length;
  const arrivedCaseCount = cases.filter(
    (item) => ['ARRIVED_AT_FACILITY', 'TREATMENT_COMPLETED'].includes(item.status)
  ).length;
  const activeCaseCount = cases.filter(
    (item) => !['CLOSED', 'QUEUED_OFFLINE'].includes(item.status)
  ).length;
  const criticalCaseCount = cases.filter(
    (item) => item.risk_level === 'CRITICAL_RED_FLAG' && item.status !== 'CLOSED'
  ).length;
  const closureRate = cases.length
    ? Math.round((closedCaseCount / cases.length) * 1000) / 10
    : 0;
  const backendCaseCount = cases.filter((item) => item.status !== 'QUEUED_OFFLINE').length;
  const caseTotalForChart = Math.max(backendCaseCount, 1);
  const closedPercent = Math.round((closedCaseCount / caseTotalForChart) * 100);
  const dispatchedPercent = Math.round((dispatchedCaseCount / caseTotalForChart) * 100);
  const ingestedPercent = Math.round((ingestedCaseCount / caseTotalForChart) * 100);
  const arrivedPercent = Math.round((arrivedCaseCount / caseTotalForChart) * 100);
  const queueBarMax = Math.max(activeCaseCount, pendingReferrals.length, closedCaseCount, queuedCount, 1);
  const queueBars = [
    { label: 'Active', current: activeCaseCount, queued: queuedCount },
    { label: 'Handoffs', current: dispatchedCaseCount, queued: pendingReferrals.length },
    { label: 'Closed', current: closedCaseCount, queued: 0 }
  ];
  const latestTriageCase = cases.find((item) => item.triage_analysis);

  const pageDescriptions = {
    'SCREENING QUEUE': 'Review newly ingested screenings and dispatch FHIR ServiceRequests.',
    'REFERRAL HANDOFFS': 'Track dispatched referrals, patient arrival, and SLA escalations.',
    'DUAL-KEY CLOSURES': 'Upload the discharge summary, then complete dual-clinician sign-off.',
    'AUDIT LEDGER': 'Append-only events with timestamps, actors, FHIR references, and SHA-256 hashes.'
  };
  const primarySignoff = selectedCase?.signoffs?.primary;
  const secondarySignoff = selectedCase?.signoffs?.secondary;
  const nextSignoffRole = primarySignoff ? 'secondary' : 'primary';
  const canRecordClinicianSignoff = Boolean(clinicianSessionToken) &&
    !secondarySignoff &&
    (!primarySignoff || primarySignoff.clinician.toLowerCase() !== activeClinician.name.toLowerCase());

  return (
    <div className="animate-enter min-h-screen bg-[#DCE5DF] p-4 md:p-8 flex items-center justify-center font-sans text-[#2E4742]">
      <div className="w-full max-w-7xl bg-[#E8EFEA] rounded-[36px] shadow-2xl overflow-hidden flex flex-col lg:flex-row border border-white/60">
        
        {/* LEFT FOREST-SLATE SIDEBAR */}
        <aside className="relative flex w-full flex-col justify-between bg-[#2E4742] px-4 py-6 text-white lg:w-64 lg:py-8 lg:pl-5 lg:pr-3">
          <div>
            <div className="mb-6 flex flex-col items-center border-b border-white/10 pb-6">
              <div className="mb-3 h-[76px] w-[76px] rounded-full border-[3px] border-[#D4A329] p-1 shadow-[0_0_0_4px_rgba(212,163,41,0.12)]">
                <div className="flex h-full w-full items-center justify-center rounded-full bg-[#1F332F] text-xl font-bold text-[#D4A329]">
                  {activeClinician.name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase()}
                </div>
              </div>
              <h2 className="text-center text-sm font-bold uppercase tracking-wide">{activeClinician.name}</h2>
              <p className="mt-1 text-center text-[11px] text-[#B8C8C3]">{activeClinician.role}</p>
              <p className="mt-1 text-center text-[10px] text-[#B8C8C3]">{activeClinician.email}</p>
              <p className="mt-2 text-center text-[9px] text-emerald-200">
                Authenticated session · actions attributed
              </p>
              <button
                type="button"
                onClick={onSignOut}
                className="mt-3 rounded-full border border-white/20 px-3 py-1.5 text-[10px] font-semibold text-white transition hover:bg-white/10"
              >
                Sign out
              </button>
            </div>

            <nav aria-label="Primary navigation" className="space-y-1.5">
              {navItems.map((item) => {
                const Icon = item.icon;
                const isActive = activeNav === item.name;
                return (
                  <button
                    key={item.name}
                    onClick={() => setActiveNav(item.name)}
                    aria-current={isActive ? 'page' : undefined}
                    className={`flex w-full items-center gap-3.5 rounded-full px-4 py-3 text-[11px] font-semibold tracking-wider transition-all ${
                      isActive
                        ? 'bg-[#E8EFEA] text-[#2E4742] shadow-sm'
                        : 'text-[#C4D3CF] hover:bg-white/5 hover:text-white'
                    }`}
                  >
                    <Icon
                      className={`h-4 w-4 shrink-0 ${
                        isActive ? 'text-[#D4A329]' : 'text-[#D4A329]/90'
                      }`}
                    />
                    <span>{item.name}</span>
                  </button>
                );
              })}
            </nav>
          </div>

          <div className="mt-7">
            <p className="mb-3 text-[10px] font-bold uppercase tracking-widest text-[#D4A329]">
              Active Care Team
            </p>
            <div className="mb-5 flex items-center -space-x-2 pl-0.5">
              {['KM', 'EG', 'AA', 'LN'].map((initials, idx) => (
                <div
                  key={idx}
                  className="flex h-8 w-8 items-center justify-center rounded-full border-2 border-[#2E4742] bg-[#1F332F] text-[9px] font-bold text-white shadow-sm"
                >
                  {initials}
                </div>
              ))}
              <div className="flex h-8 w-8 items-center justify-center rounded-full border-2 border-[#2E4742] bg-[#D4A329] text-[9px] font-bold text-[#2E4742] shadow-sm">
                +18
              </div>
            </div>

            <div className="rounded-2xl border border-white/10 bg-[#233834]/75 p-3">
              <div className="mb-1.5 flex items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 text-[10px] font-semibold text-white">
                  {isOnline ? (
                    <>
                      <Wifi className="h-3.5 w-3.5 text-emerald-400" />
                      Network Online
                    </>
                  ) : (
                    <>
                      <WifiOff className="h-3.5 w-3.5 text-[#D4A329]" />
                      Offline Buffer Mode
                    </>
                  )}
                </span>
                <span
                  className={`rounded-full px-2 py-0.5 text-[9px] font-bold ${
                    queuedCount > 0
                      ? 'bg-[#D4A329] text-[#2E4742]'
                      : 'bg-emerald-500/20 text-emerald-300'
                  }`}
                >
                  {queuedCount} Queued
                </span>
              </div>
              <p className="text-[9px] leading-relaxed text-[#9BB0AB]">
                {isOnline
                  ? 'ScreenToCare API is available for screening, referral, and closure updates.'
                  : 'Screenings are queued in browser storage for triage on reconnect.'}
              </p>
            </div>
          </div>
        </aside>

        {/* RIGHT MAIN DASHBOARD CANVAS */}
        <main className="flex-1 p-6 md:p-8 space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h1 className="text-xl font-bold text-[#2E4742]">ScreenToCare Orchestration</h1>
              <p className="text-xs text-[#617873]">
                {activeNav === 'COMMAND CENTER'
                  ? 'Challenge 05 — Closing the Screening-to-Care Loop'
                  : activeNav}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={toggleNetwork}
                className="px-3.5 py-2 rounded-full text-xs font-semibold bg-white text-[#2E4742] shadow-sm hover:bg-slate-50 transition"
              >
                Toggle {isOnline ? 'Offline' : 'Online'} Test
              </button>
              <button
                onClick={() => {
                  setIntakeError('');
                  setIsIntakeOpen(true);
                }}
                className="px-4 py-2 rounded-full text-xs font-semibold bg-[#2E4742] text-white shadow-sm hover:bg-[#233834] transition flex items-center gap-1.5"
              >
                <Plus className="w-3.5 h-3.5 text-[#D4A329]" />
                Ingest Field Screening
              </button>
            </div>
          </div>

          {pageError && (
            <p role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-xs font-semibold text-red-700">
              {pageError}
            </p>
          )}
          {statusMessage && (
            <p role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-xs font-semibold text-emerald-800">
              {statusMessage}
            </p>
          )}

          {activeNav === 'COMMAND CENTER' ? (
            <>
          {/* TOP 3 KPI CARDS */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            <div className="bg-[#D4A329] text-white rounded-3xl p-5 shadow-sm relative overflow-hidden flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-white/90">Critical Red Flags</p>
                <p className="text-3xl font-bold mt-1">
                  {criticalCaseCount} Active
                </p>
                <span className="inline-block mt-2 text-[10px] font-semibold bg-black/15 px-2.5 py-0.5 rounded-full">
                  12h Strict SLA Window
                </span>
              </div>
              <AlertTriangle className="w-12 h-12 text-white/30" />
            </div>

            <div className="bg-[#2E4742] text-white rounded-3xl p-5 shadow-sm relative overflow-hidden flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-[#9BB0AB]">Pending Specialist Handoffs</p>
                <p className="text-3xl font-bold mt-1">{pendingReferrals.length} Cases</p>
                <span className="inline-block mt-2 text-[10px] font-semibold bg-white/10 text-[#D4A329] px-2.5 py-0.5 rounded-full">
                  FHIR ServiceRequest Active
                </span>
              </div>
              <GitPullRequest className="w-12 h-12 text-white/15" />
            </div>

            <div className="bg-[#2E4742] text-white rounded-3xl p-5 shadow-sm relative overflow-hidden flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-[#9BB0AB]">Verified Loop Closures</p>
                <p className="text-3xl font-bold mt-1">{closedCaseCount} Cases</p>
                <span className="inline-block mt-2 text-[10px] font-semibold bg-emerald-500/20 text-emerald-300 px-2.5 py-0.5 rounded-full">
                  {closureRate}% of all cases
                </span>
              </div>
              <ShieldCheck className="w-12 h-12 text-[#D4A329]/40" />
            </div>
          </div>

          <section aria-labelledby="impact-metrics-title" className="rounded-3xl border border-[#2E4742]/10 bg-white p-5 shadow-sm">
            <div className="mb-4 flex flex-wrap items-end justify-between gap-2">
              <div>
                <h2 id="impact-metrics-title" className="text-sm font-bold text-[#2E4742]">
                  Impact & Performance Metrics
                </h2>
                <p className="mt-1 text-[11px] text-[#617873]">
                  Recalculated from current case, SLA, referral, and closure records.
                </p>
              </div>
              {impactMetrics?.generated_at && (
                <p className="text-[10px] text-[#8A9E99]">
                  Updated {new Date(impactMetrics.generated_at).toLocaleTimeString()}
                </p>
              )}
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <article className="rounded-2xl bg-[#F4F8F6] p-4">
                <p className="text-[10px] font-bold uppercase tracking-wide text-[#617873]">Average Turnaround Time</p>
                <p className="mt-2 text-2xl font-bold text-[#2E4742]">
                  {impactMetrics ? formatTurnaroundHours(impactMetrics.average_turnaround_hours) : '…'}
                </p>
                <p className="mt-1 text-[10px] text-[#617873]">
                  {impactMetrics?.turnaround_sample_size
                    ? `Across ${impactMetrics.turnaround_sample_size} closed cases`
                    : 'No completed cases yet'}
                </p>
              </article>
              <article className="rounded-2xl bg-[#FBF8EE] p-4">
                <p className="text-[10px] font-bold uppercase tracking-wide text-[#617873]">Active SLA Breach</p>
                <p className="mt-2 text-2xl font-bold text-[#2E4742]">
                  {impactMetrics ? `${impactMetrics.active_sla_breach_percent}%` : '…'}
                </p>
                <p className="mt-1 text-[10px] text-[#617873]">
                  {impactMetrics
                    ? `${impactMetrics.active_sla_breached_cases} of ${impactMetrics.active_sla_case_count} active cases`
                    : 'Checking active SLAs'}
                </p>
              </article>
              <article className="rounded-2xl bg-[#F4F8F6] p-4">
                <p className="text-[10px] font-bold uppercase tracking-wide text-[#617873]">Referral Completion Rate</p>
                <p className="mt-2 text-2xl font-bold text-[#2E4742]">
                  {impactMetrics ? `${impactMetrics.referral_completion_rate_percent}%` : '…'}
                </p>
                <p className="mt-1 text-[10px] text-[#617873]">
                  {impactMetrics
                    ? `${impactMetrics.completed_referrals} of ${impactMetrics.total_referrals} referrals completed`
                    : 'Checking referral outcomes'}
                </p>
              </article>
              <article className="rounded-2xl bg-[#2E4742] p-4 text-white">
                <p className="text-[10px] font-bold uppercase tracking-wide text-[#C4D3CF]">Closed-Loop Conversion</p>
                <p className="mt-2 text-2xl font-bold text-[#D4A329]">
                  {impactMetrics ? `${impactMetrics.closed_loop_conversion_percent}%` : '…'}
                </p>
                <p className="mt-1 text-[10px] text-[#C4D3CF]">
                  {impactMetrics
                    ? `${impactMetrics.closed_cases} of ${impactMetrics.total_cases} registered cases closed`
                    : 'Checking closure outcomes'}
                </p>
              </article>
            </div>
          </section>

          <section aria-labelledby="triage-assistant-title" className="grid gap-4 rounded-3xl border border-[#D4A329]/35 bg-[#FBF8EE] p-5 shadow-sm lg:grid-cols-[1fr_1fr]">
            <div>
              <p className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-widest text-[#987117]">
                <Sparkles className="h-4 w-4" /> AI Assist · Demo triage engine
              </p>
              <h2 id="triage-assistant-title" className="mt-2 text-sm font-bold text-[#2E4742]">
                Latest screening assessment
              </h2>
              {latestTriageCase ? (
                <>
                  <p className="mt-2 text-xs font-semibold text-[#2E4742]">
                    {latestTriageCase.patient_name} · {latestTriageCase.risk_level.replaceAll('_', ' ')} ·{' '}
                    {latestTriageCase.triage_analysis.sla_hours}h recommended SLA
                  </p>
                  <p className="mt-2 text-xs leading-relaxed text-[#617873]">
                    {latestTriageCase.triage_analysis.rationale_summary}
                  </p>
                </>
              ) : (
                <p className="mt-2 text-xs leading-relaxed text-[#617873]">
                  Analyze raw notes for a triage preview, or use field intake to create a patient case. A preview does not save a case.
                </p>
              )}
              <button
                type="button"
                onClick={openTriageAnalyzer}
                className="mt-4 rounded-full bg-[#2E4742] px-4 py-2 text-xs font-semibold text-white transition hover:bg-[#233834]"
              >
                Analyze screening notes
              </button>
            </div>
            <div className="rounded-2xl border border-[#D4A329]/25 bg-white p-4">
              <h3 className="flex items-center gap-2 text-xs font-bold text-[#2E4742]">
                <MessageSquareText className="h-4 w-4 text-[#D4A329]" />
                Draft patient SMS
              </h3>
              {latestTriageCase?.triage_analysis?.draft_patient_sms ? (
                <>
                  <p className="mt-2 rounded-xl bg-[#F4F8F6] p-3 text-xs leading-relaxed text-[#425C56]">
                    {latestTriageCase.triage_analysis.draft_patient_sms.message}
                  </p>
                  <p className="mt-2 text-[10px] font-semibold uppercase tracking-wide text-[#987117]">
                    Draft only · not sent
                  </p>
                </>
              ) : (
                <p className="mt-2 text-xs leading-relaxed text-[#617873]">
                  A plain-language SMS draft will appear after triage. No message is sent from this panel.
                </p>
              )}
            </div>
            <p className="text-[10px] leading-relaxed text-[#617873] lg:col-span-2">
              Prototype only: transparent keyword rules are used; this is not a validated AI model or clinical decision-support system. A clinician must review the assessment.
            </p>
          </section>

          {/* MIDDLE ROW */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
            <div className="lg:col-span-7 bg-white rounded-3xl p-6 shadow-sm">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h3 className="text-base font-bold text-[#2E4742]">Active Screening-to-Care Queue</h3>
                  <p className="text-xs text-[#617873]">Cases become available for closure after facility check-in</p>
                </div>
                <span className="text-[11px] font-semibold text-[#617873]">Live State Machine</span>
              </div>

              <div className="grid grid-cols-12 text-[11px] font-semibold text-[#8A9E99] pb-2 border-b border-dashed border-slate-200">
                <div className="col-span-5">Patient & Screening</div>
                <div className="col-span-3">Receiving Facility</div>
                <div className="col-span-2 text-center">SLA Timer</div>
                <div className="col-span-2 text-right">State</div>
              </div>

              <div className="divide-y divide-dashed divide-slate-200">
                {cases.length === 0 ? (
                  <p className="py-8 text-center text-xs text-[#617873]">
                    No screenings yet. Add a field screening to start the care loop.
                  </p>
                ) : cases.map((item) => (
                  <div key={item.case_id} className="flex items-center gap-2 py-1">
                    <button
                      type="button"
                      onClick={() => {
                        if (['ARRIVED_AT_FACILITY', 'TREATMENT_COMPLETED'].includes(item.status)) {
                          openClosureCase(item);
                        }
                      }}
                      disabled={!['ARRIVED_AT_FACILITY', 'TREATMENT_COMPLETED'].includes(item.status)}
                      className={`grid min-w-0 flex-1 grid-cols-12 items-center rounded-xl px-2 py-3.5 text-left transition ${
                        ['ARRIVED_AT_FACILITY', 'TREATMENT_COMPLETED'].includes(item.status)
                          ? 'hover:bg-[#F4F8F6] cursor-pointer'
                          : 'opacity-65'
                      }`}
                    >
                      <div className="col-span-5 flex items-center gap-3">
                        <div className="w-9 h-9 rounded-full bg-[#2E4742] text-white flex items-center justify-center text-xs font-bold shrink-0">
                          {item.avatar}
                        </div>
                        <div className="min-w-0">
                          <p className="text-xs font-bold text-[#2E4742] truncate">{item.patient_name}</p>
                          <p className="text-[11px] text-[#617873] truncate">{item.screening_type}</p>
                        </div>
                      </div>

                      <div className="col-span-3 text-[11px] font-medium text-[#2E4742] pr-2 truncate">
                        {item.facility}
                      </div>

                      <div className="col-span-2 flex justify-center">
                        <span
                          className={`w-8 h-8 rounded-full flex items-center justify-center text-[11px] font-bold text-white ${
                            item.status === 'CLOSED'
                              ? 'bg-emerald-600'
                              : item.risk_level === 'CRITICAL_RED_FLAG'
                              ? 'bg-[#D4A329]'
                              : 'bg-[#2E4742]'
                          }`}
                        >
                          {item.sla_remaining}
                        </span>
                      </div>

                      <div className="col-span-2 text-right">
                        <span className="text-[10px] font-bold px-2 py-1 rounded-full bg-[#E8EFEA] text-[#2E4742]">
                          {item.status.replaceAll('_', ' ')}
                        </span>
                      </div>
                    </button>
                    <button
                      type="button"
                      onClick={() => openFhirCase(item)}
                      aria-label={`View FHIR R4 Payload for ${item.patient_name}`}
                      title="View FHIR R4 Payload"
                      className="shrink-0 rounded-full border border-[#2E4742]/20 px-3 py-2 text-[10px] font-semibold text-[#2E4742] transition hover:bg-[#F4F8F6]"
                    >
                      View FHIR
                    </button>
                  </div>
                ))}
              </div>
            </div>

            <div className="lg:col-span-5 bg-white rounded-3xl p-6 shadow-sm flex flex-col justify-between">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h3 className="text-base font-bold text-[#2E4742]">Live Workflow Counts</h3>
                  <p className="text-xs text-[#617873]">Current case states and offline records awaiting sync</p>
                </div>
              </div>

              <div className="h-44 flex items-end justify-between gap-3 pt-6 px-2">
                {queueBars.map((bar) => (
                  <div key={bar.label} className="flex flex-1 flex-col items-center gap-2">
                    <div className="flex h-32 items-end gap-1">
                      <div className="flex h-full w-3 items-end rounded-full bg-[#F0F4F2]">
                        <div
                          style={{ height: `${(bar.current / queueBarMax) * 100}%` }}
                          className="w-full rounded-full bg-[#2E4742]"
                        />
                      </div>
                      <div className="flex h-full w-3 items-end rounded-full bg-[#F0F4F2]">
                        <div
                          style={{ height: `${(bar.queued / queueBarMax) * 100}%` }}
                          className="w-full rounded-full bg-[#D4A329]"
                        />
                      </div>
                    </div>
                    <span className="text-[10px] font-semibold text-[#617873]">{bar.label}</span>
                  </div>
                ))}
              </div>

              <div className="flex items-center justify-center gap-6 mt-4 pt-3 border-t border-slate-100 text-[11px] font-semibold">
                <span className="flex items-center gap-1.5 text-[#2E4742]">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#2E4742]" /> Backend records
                </span>
                <span className="flex items-center gap-1.5 text-[#617873]">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#D4A329]" /> Pending / queued
                </span>
              </div>
            </div>
          </div>

          {/* BOTTOM ROW */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
            <div className="lg:col-span-5 bg-white rounded-3xl p-6 shadow-sm flex flex-col justify-between">
              <h3 className="text-base font-bold text-[#2E4742]">Lifecycle State Distribution</h3>
              <div className="flex items-center justify-around my-4">
                <div className="relative w-32 h-32 flex items-center justify-center">
                  <svg className="w-full h-full -rotate-90" viewBox="0 0 36 36">
                    <circle
                      cx="18"
                      cy="18"
                      r="14"
                      fill="none"
                      stroke="#2E4742"
                      strokeWidth="4.5"
                      strokeDasharray={`${closedPercent} ${100 - closedPercent}`}
                    />
                    <circle
                      cx="18"
                      cy="18"
                      r="14"
                      fill="none"
                      stroke="#D4A329"
                      strokeWidth="4.5"
                      strokeDasharray={`${dispatchedPercent} ${100 - dispatchedPercent}`}
                      strokeDashoffset={`-${closedPercent}`}
                    />
                    <circle
                      cx="18"
                      cy="18"
                      r="14"
                      fill="none"
                      stroke="#1A938A"
                      strokeWidth="4.5"
                      strokeDasharray={`${ingestedPercent} ${100 - ingestedPercent}`}
                      strokeDashoffset={`-${closedPercent + dispatchedPercent}`}
                    />
                    <circle
                      cx="18"
                      cy="18"
                      r="14"
                      fill="none"
                      stroke="#91A79F"
                      strokeWidth="4.5"
                      strokeDasharray={`${arrivedPercent} ${100 - arrivedPercent}`}
                      strokeDashoffset={`-${closedPercent + dispatchedPercent + ingestedPercent}`}
                    />
                  </svg>
                  <span className="absolute text-[11px] font-bold text-[#2E4742]">Loop Share</span>
                </div>
                <div className="space-y-2 text-xs font-semibold">
                  <div className="flex items-center gap-2">
                    <span className="w-3 h-3 rounded-full bg-[#2E4742]" />
                    <span>Closed ({closedPercent}%)</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="w-3 h-3 rounded-full bg-[#D4A329]" />
                    <span>Dispatched ({dispatchedPercent}%)</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="w-3 h-3 rounded-full bg-[#1A938A]" />
                    <span>Newly ingested ({ingestedPercent}%)</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="w-3 h-3 rounded-full bg-[#91A79F]" />
                    <span>At facility ({arrivedPercent}%)</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="lg:col-span-7 bg-white rounded-3xl p-6 shadow-sm flex flex-col justify-between relative">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-base font-bold text-[#2E4742]">Screening-to-Care Velocity</h3>
                  <p className="text-xs text-[#617873]">Actionable signals resolved within SLA window</p>
                </div>
                <div className="bg-[#2E4742] text-white px-3.5 py-1.5 rounded-2xl text-center shadow-sm">
                  <p className="text-xs font-bold text-[#D4A329]">{closedCaseCount}</p>
                  <p className="text-[9px] uppercase tracking-wider">Loops Closed</p>
                </div>
              </div>

              <div className="mt-4 space-y-3">
                <div className="flex items-center justify-between text-xs text-[#617873]">
                  <span>Cases closed through Dual-Key review</span>
                  <span className="font-bold text-[#2E4742]">{closedCaseCount} / {cases.length}</span>
                </div>
                <div className="h-3 overflow-hidden rounded-full bg-[#E8EFEA]">
                  <div
                    className="h-full rounded-full bg-[#D4A329] transition-all"
                    style={{ width: `${closureRate}%` }}
                    role="progressbar"
                    aria-label="Case closure rate"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={closureRate}
                  />
                </div>
                <div className="flex justify-between text-[10px] font-semibold text-[#617873]">
                  <span>{activeCaseCount} active</span>
                  <span>{pendingReferrals.length} pending handoffs</span>
                </div>
              </div>
            </div>
          </div>
            </>
          ) : (
            <section className="bg-white rounded-3xl p-6 shadow-sm">
              <div className="mb-5">
                <h2 className="text-base font-bold text-[#2E4742]">{activeNav}</h2>
                <p className="mt-1 text-xs text-[#617873]">{pageDescriptions[activeNav]}</p>
              </div>

              {activeNav === 'SCREENING QUEUE' ? (
                screeningQueueCases.length === 0 ? (
                  <p className="rounded-xl bg-[#F4F8F6] px-4 py-6 text-center text-sm text-[#617873]">
                    No newly ingested or offline-queued screenings.
                  </p>
                ) : (
                  <div className="divide-y divide-slate-100">
                    {screeningQueueCases.map((item) => (
                      <article key={item.case_id} className="flex flex-wrap items-center justify-between gap-4 py-4">
                        <div className="min-w-0">
                          <p className="text-sm font-bold text-[#2E4742]">
                            {item.patient_name} <span className="font-normal text-[#617873]">({item.case_id})</span>
                          </p>
                          <p className="mt-1 text-xs text-[#617873]">
                            {item.screening_type} · {item.facility} · {item.risk_level} · SLA {item.sla_remaining}
                          </p>
                        </div>
                        <div className="flex flex-wrap items-center gap-3">
                          <span className="rounded-full bg-[#E8EFEA] px-3 py-1 text-[10px] font-bold text-[#2E4742]">
                            {item.status.replaceAll('_', ' ')}
                          </span>
                          <button
                            type="button"
                            onClick={() => openFhirCase(item)}
                            className="rounded-full border border-[#2E4742]/20 px-3.5 py-2 text-xs font-semibold text-[#2E4742] transition hover:bg-[#F4F8F6]"
                          >
                            View FHIR R4 Payload
                          </button>
                          <button
                            type="button"
                            onClick={() => handleGenerateAndDispatch(item.case_id)}
                            disabled={!isOnline || item.status === 'QUEUED_OFFLINE'}
                            className="rounded-full bg-[#2E4742] px-4 py-2 text-xs font-semibold text-white transition hover:bg-[#233834] disabled:cursor-not-allowed disabled:opacity-50"
                            title={item.status === 'QUEUED_OFFLINE' ? 'Reconnect and sync this screening before dispatch.' : undefined}
                          >
                            {item.status === 'QUEUED_OFFLINE'
                              ? 'Waiting for sync'
                              : 'Generate FHIR ServiceRequest & Dispatch'}
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                )
              ) : activeNav === 'REFERRAL HANDOFFS' ? (
                <>
                  {handoffReferrals.length === 0 ? (
                    <p className="rounded-xl bg-[#F4F8F6] px-4 py-6 text-center text-sm text-[#617873]">
                      No referrals are currently in transit or awaiting patient arrival.
                    </p>
                  ) : (
                    <>
                      {(escalationBanner || handoffReferrals.find((item) => item.sla_escalation_alert)?.sla_escalation_alert) && (
                        <div role="alert" className="mb-4 flex items-start gap-2 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-xs font-semibold text-amber-900">
                          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[#D4A329]" />
                          <span>
                            {escalationBanner || handoffReferrals.find((item) => item.sla_escalation_alert).sla_escalation_alert.message}
                          </span>
                        </div>
                      )}
                      <div className="divide-y divide-slate-100">
                        {handoffReferrals.map((item) => (
                          <article key={item.service_request_id} className="flex flex-wrap items-center justify-between gap-4 py-4">
                            <div className="min-w-0">
                              <p className="text-sm font-bold text-[#2E4742]">
                                {item.patient_name} <span className="font-normal text-[#617873]">({item.case_id})</span>
                              </p>
                              <p className="mt-1 text-xs text-[#617873]">
                                {item.screening_type} · {item.facility} · {item.risk_level}
                              </p>
                              <p className="mt-1 text-[10px] text-[#617873]">
                                FHIR ServiceRequest {item.service_request_id}
                              </p>
                            </div>
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="rounded-full bg-[#E8EFEA] px-3 py-1 text-[10px] font-bold text-[#2E4742]">
                                {item.case_status.replaceAll('_', ' ')}
                              </span>
                              <button
                                type="button"
                                onClick={() => openFhirCase(item)}
                                className="rounded-full border border-[#2E4742]/20 px-3.5 py-2 text-xs font-semibold text-[#2E4742] transition hover:bg-[#F4F8F6]"
                              >
                                View FHIR R4 Payload
                              </button>
                              <button
                                type="button"
                                onClick={() => handlePatientArrival(item.case_id)}
                                className="rounded-full bg-[#2E4742] px-3.5 py-2 text-xs font-semibold text-white transition hover:bg-[#233834]"
                              >
                                Simulate Patient Arrival Check-In
                              </button>
                              <button
                                type="button"
                                onClick={() => handleSlaEscalation(item.case_id)}
                                className="rounded-full border border-[#D4A329] px-3.5 py-2 text-xs font-semibold text-[#2E4742] transition hover:bg-amber-50"
                              >
                                Trigger SLA Escalation Alert
                              </button>
                            </div>
                          </article>
                        ))}
                      </div>
                    </>
                  )}

                  <section className="mt-8 border-t border-slate-100 pt-5">
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <div>
                        <h3 className="text-sm font-bold text-[#2E4742]">Patient Comms Log</h3>
                        <p className="mt-1 text-[11px] text-[#617873]">Simulated WhatsApp/SMS notices; no messages are sent.</p>
                      </div>
                      <span className="rounded-full bg-[#E8EFEA] px-3 py-1 text-[10px] font-bold text-[#2E4742]">
                        {patientCommsLog.length} entries
                      </span>
                    </div>
                    {patientCommsLog.length === 0 ? (
                      <p className="rounded-xl bg-[#F4F8F6] px-4 py-5 text-center text-xs text-[#617873]">
                        Patient notices will appear here after referral dispatch.
                      </p>
                    ) : (
                      <div className="grid gap-3 md:grid-cols-2">
                        {patientCommsLog.map((entry) => (
                          <article key={entry.notification_id} className="rounded-2xl border border-slate-100 bg-[#F8FAF9] p-4">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <p className="text-[11px] font-bold text-[#2E4742]">
                                {entry.language} · {entry.channel} · {entry.phone_number}
                              </p>
                              <time className="text-[10px] text-[#617873]" dateTime={entry.timestamp}>
                                {new Date(entry.timestamp).toLocaleString()}
                              </time>
                            </div>
                            <p className="mt-2 text-xs leading-relaxed text-[#617873]">{entry.message}</p>
                            <p className="mt-2 text-[10px] font-semibold text-[#617873]">
                              Facility: {entry.facility} · SLA deadline: {new Date(entry.sla_deadline).toLocaleString()}
                            </p>
                          </article>
                        ))}
                      </div>
                    )}
                  </section>
                </>
              ) : activeNav === 'AUDIT LEDGER' ? (
                auditEvents.length === 0 ? (
                  <p className="rounded-xl bg-[#F4F8F6] px-4 py-6 text-center text-sm text-[#617873]">
                    No audit events have been recorded.
                  </p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[900px] border-collapse text-left text-xs">
                      <thead>
                        <tr className="border-b border-slate-200 text-[10px] uppercase tracking-wide text-[#8A9E99]">
                          <th className="px-3 py-3 font-bold">Timestamp</th>
                          <th className="px-3 py-3 font-bold">Event / State</th>
                          <th className="px-3 py-3 font-bold">Actor</th>
                          <th className="px-3 py-3 font-bold">FHIR Resource</th>
                          <th className="px-3 py-3 font-bold">SHA-256 Verification Hash</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {auditEvents.map((event) => (
                          <tr key={event.event_id} className="align-top">
                            <td className="whitespace-nowrap px-3 py-3 text-[#617873]">
                              <time dateTime={event.timestamp}>{new Date(event.timestamp).toLocaleString()}</time>
                            </td>
                            <td className="px-3 py-3">
                              <p className="font-bold text-[#2E4742]">{event.action_type}</p>
                              <p className="mt-1 text-[10px] text-[#617873]">
                                Case {event.case_id} · {event.new_state}
                              </p>
                            </td>
                            <td className="px-3 py-3 text-[#617873]">{event.actor_name}</td>
                            <td className="px-3 py-3 font-mono text-[10px] text-[#617873]">
                              {event.fhir_resource_reference || '—'}
                            </td>
                            <td className="max-w-[280px] break-all px-3 py-3 font-mono text-[10px] text-[#617873]">
                              {event.verification_hash}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )
              ) : activeCases.length === 0 ? (
                <p className="rounded-xl bg-[#F4F8F6] px-4 py-6 text-center text-sm text-[#617873]">
                  No arrived or treatment-completed cases are ready for dual-key review.
                </p>
              ) : (
                <div className="divide-y divide-slate-100">
                  {activeCases.map((item) => (
                    <article key={item.case_id} className="flex flex-wrap items-center justify-between gap-4 py-4">
                      <button
                        type="button"
                        onClick={() => openClosureCase(item)}
                        className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-4 rounded-xl py-2 text-left hover:bg-[#F4F8F6]"
                      >
                        <span className="min-w-0">
                          <span className="block text-sm font-bold text-[#2E4742]">
                            {item.patient_name} <span className="font-normal text-[#617873]">({item.case_id})</span>
                          </span>
                          <span className="mt-1 block text-xs text-[#617873]">
                            {item.screening_type} · {item.facility}
                          </span>
                        </span>
                        <span className="flex items-center gap-3">
                          <span className="rounded-full bg-[#E8EFEA] px-3 py-1 text-[10px] font-bold text-[#2E4742]">
                            {item.status.replaceAll('_', ' ')}
                          </span>
                          <span className="rounded-full bg-[#2E4742] px-4 py-2 text-xs font-semibold text-white">
                            {item.status === 'ARRIVED_AT_FACILITY' ? 'Upload discharge summary' : 'Complete dual-key review'}
                          </span>
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={() => openFhirCase(item)}
                        className="rounded-full border border-[#2E4742]/20 px-3.5 py-2 text-xs font-semibold text-[#2E4742] transition hover:bg-[#F4F8F6]"
                      >
                        View FHIR R4 Payload
                      </button>
                    </article>
                  ))}
                </div>
              )}
            </section>
          )}
        </main>
      </div>

      {/* DUAL-KEY CLOSURE PROTOCOL MODAL */}
      {selectedCase && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
          <div role="dialog" aria-modal="true" aria-labelledby="closure-modal-title" className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-3xl border border-slate-100 bg-white p-6 shadow-2xl">
            <div className="flex items-center justify-between pb-4 border-b border-slate-100">
              <div className="flex items-center gap-2">
                <Lock className="w-5 h-5 text-[#D4A329]" />
                <h3 id="closure-modal-title" className="text-base font-bold text-[#2E4742]">Dual-Key Case Closure</h3>
              </div>
              <button
                type="button"
                onClick={() => {
                  setSelectedCase(null);
                  setClosureError('');
                }}
                aria-label="Close dialog"
                className="text-slate-400 hover:text-slate-600"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="my-4 bg-[#F4F8F6] p-3.5 rounded-2xl text-xs space-y-1">
              <p className="font-bold text-[#2E4742]">
                {selectedCase.patient_name} ({selectedCase.case_id})
              </p>
              <p className="text-[#617873]">{selectedCase.screening_type}</p>
              <p className="text-[#617873]">Facility: {selectedCase.facility}</p>
            </div>

            <form onSubmit={handleDualKeyClose} className="space-y-4">
              <section className="rounded-2xl border border-[#D4A329]/40 bg-[#FBF8EE] p-4">
                <h4 className="text-xs font-bold text-[#2E4742]">
                  Receiving Hospital Discharge Summary
                </h4>
                {selectedCase.discharge_summary ? (
                  <div className="mt-2 space-y-1 text-[11px] text-[#617873]">
                    <p className="font-semibold text-emerald-800">
                      Treatment completed · Document {selectedCase.discharge_summary.document_id}
                    </p>
                    <p>{selectedCase.discharge_summary.clinical_outcome_note}</p>
                    <p>
                      Uploaded by {selectedCase.discharge_summary.uploaded_by} ·{' '}
                      {new Date(selectedCase.discharge_summary.uploaded_at).toLocaleString()}
                    </p>
                  </div>
                ) : (
                  <div className="mt-3 space-y-3">
                    <label className="block text-xs font-bold text-[#2E4742]">
                      Discharge document ID *
                      <input
                        type="text"
                        value={dischargeDocumentId}
                        onChange={(event) => setDischargeDocumentId(event.target.value)}
                        placeholder="Receiving hospital document reference"
                        className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-xs focus:border-[#2E4742] focus:outline-none"
                      />
                    </label>
                    <label className="block text-xs font-bold text-[#2E4742]">
                      Clinical outcome note *
                      <textarea
                        rows={3}
                        value={clinicalOutcomeNote}
                        onChange={(event) => setClinicalOutcomeNote(event.target.value)}
                        placeholder="Summarize the receiving hospital treatment outcome"
                        className="mt-1 w-full resize-y rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-xs focus:border-[#2E4742] focus:outline-none"
                      />
                    </label>
                    <button
                      type="button"
                      onClick={handleDischargeSummaryUpload}
                      disabled={isSubmitting || !['ARRIVED_AT_FACILITY'].includes(selectedCase.status)}
                      className="rounded-full bg-[#2E4742] px-4 py-2 text-xs font-semibold text-white transition hover:bg-[#233834] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {isSubmitting ? 'Uploading...' : 'Upload Receiving Hospital Discharge Summary'}
                    </button>
                  </div>
                )}
              </section>

              {selectedCase.discharge_summary && (
                <>
                  <section className="space-y-3 rounded-2xl border border-slate-100 p-4">
                    <h4 className="text-xs font-bold text-[#2E4742]">Dual-Key Clinician Sign-Off</h4>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div className="rounded-xl bg-[#F4F8F6] p-3">
                        <p className="text-[10px] font-bold uppercase tracking-wide text-[#617873]">Primary clinician</p>
                        <p className="mt-1 text-xs font-semibold text-[#2E4742]">
                          {primarySignoff?.clinician || activeClinician.name}
                        </p>
                        <p className="mt-1 text-[10px] text-[#617873]">
                          {primarySignoff
                            ? `Signed ${new Date(primarySignoff.signed_at).toLocaleString()}`
                            : `${activeClinician.role} · session locked`}
                        </p>
                      </div>
                      <div className="rounded-xl bg-[#F4F8F6] p-3">
                        <p className="text-[10px] font-bold uppercase tracking-wide text-[#617873]">Secondary clinician</p>
                        <p className="mt-1 text-xs font-semibold text-[#2E4742]">
                          {secondarySignoff?.clinician || (primarySignoff ? activeClinician.name : 'Available after primary sign-off')}
                        </p>
                        <p className="mt-1 text-[10px] text-[#617873]">
                          {secondarySignoff
                            ? `Signed ${new Date(secondarySignoff.signed_at).toLocaleString()}`
                            : primarySignoff ? `${activeClinician.role} · session locked` : 'Independent second session required'}
                        </p>
                      </div>
                    </div>
                    {!secondarySignoff && (
                      <div className="space-y-2">
                        <label className="block text-xs font-bold text-[#2E4742]">
                          {nextSignoffRole === 'primary' ? 'Primary' : 'Secondary'} sign-off — active session
                          <input
                            type="text"
                            value={clinicianSignoff}
                            onChange={(event) => setClinicianSignoff(event.target.value)}
                            placeholder="Enter this clinician's sign-off value"
                            className="mt-1 w-full rounded-xl border border-slate-200 px-3.5 py-2.5 text-xs focus:border-[#2E4742] focus:outline-none"
                          />
                        </label>
                        {primarySignoff &&
                          activeClinician.name.toLowerCase() === primarySignoff.clinician.toLowerCase() && (
                            <p className="text-[11px] font-semibold text-amber-800">
                              Close this dialog and switch Active Clinician before recording the independent secondary sign-off.
                            </p>
                          )}
                        <button
                          type="button"
                          onClick={handleClinicianSignoff}
                          disabled={isSubmitting || !canRecordClinicianSignoff}
                          className="rounded-full bg-[#2E4742] px-4 py-2 text-xs font-semibold text-white transition hover:bg-[#233834] disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {isSubmitting ? 'Recording...' : `Record ${nextSignoffRole} sign-off`}
                        </button>
                      </div>
                    )}
                    {primarySignoff && secondarySignoff && (
                      <p className="rounded-xl bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-800">
                        Independent primary and secondary clinician sessions recorded.
                      </p>
                    )}
                  </section>
                  <div>
                    <label className="block text-xs font-bold text-[#2E4742] mb-1">
                      Clinical evidence document ID *
                    </label>
                    <input
                      type="text"
                      required
                      value={evidenceDocId}
                      onChange={(event) => setEvidenceDocId(event.target.value)}
                      placeholder="Clinical record or evidence reference"
                      className="w-full rounded-xl border border-slate-200 px-3.5 py-2.5 text-xs focus:border-[#2E4742] focus:outline-none"
                    />
                  </div>
                </>
              )}

              {closureError && (
                <p className="text-xs font-semibold text-red-600 bg-red-50 p-2.5 rounded-xl">
                  {closureError}
                </p>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => {
                    setSelectedCase(null);
                    setClosureError('');
                  }}
                  className="px-4 py-2 rounded-full text-xs font-semibold text-[#617873] hover:bg-slate-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting || !selectedCase.discharge_summary || !primarySignoff || !secondarySignoff}
                  className="px-5 py-2 rounded-full text-xs font-semibold bg-[#2E4742] text-white hover:bg-[#233834] flex items-center gap-1.5"
                >
                  <CheckCircle2 className="w-4 h-4 text-[#D4A329]" />
                  {!selectedCase.discharge_summary
                    ? 'Upload summary to continue'
                    : primarySignoff && secondarySignoff
                      ? 'Verify & Close Loop'
                      : 'Record both sign-offs to continue'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {selectedFhirCase && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="fhir-modal-title"
            className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-3xl border border-slate-100 bg-white p-6 shadow-2xl"
          >
            <div className="mb-5 flex items-center justify-between border-b border-slate-100 pb-4">
              <div>
                <h3 id="fhir-modal-title" className="text-base font-bold text-[#2E4742]">
                  FHIR R4 Payload
                </h3>
                <p className="mt-1 text-xs text-[#617873]">
                  {selectedFhirCase.patient_name} · Case {selectedFhirCase.case_id}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSelectedFhirCase(null)}
                aria-label="Close FHIR payload"
                className="text-slate-400 hover:text-slate-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <section className="mb-4 rounded-2xl border border-[#D4A329]/40 bg-[#FBF8EE] p-4">
              <h4 className="text-xs font-bold text-[#2E4742]">Triage Rationale (demo rules)</h4>
              <p className="mt-2 text-xs leading-relaxed text-[#617873]">
                {selectedFhirCase.triage_analysis?.rationale_summary || 'No triage rationale is available for this case.'}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {(selectedFhirCase.triage_analysis?.risk_tags || []).map((tag, index) => (
                  <span
                    key={`${tag.display}-${index}`}
                    className="rounded-full bg-white px-3 py-1 text-[10px] font-semibold text-[#2E4742]"
                  >
                    {tag.display}
                  </span>
                ))}
              </div>
              <p className="mt-3 text-[10px] text-[#617873]">
                Coding cues are for demonstration and do not represent a confirmed diagnosis or an AI clinical recommendation.
              </p>
            </section>

            <details open className="rounded-2xl border border-slate-100 bg-[#F8FAF9] p-4">
              <summary className="cursor-pointer text-xs font-bold text-[#2E4742]">FHIR R4 Bundle</summary>
              <pre className="mt-3 overflow-x-auto whitespace-pre-wrap break-words rounded-xl bg-[#1F332F] p-4 text-[10px] leading-relaxed text-[#E8EFEA]">
                {JSON.stringify(selectedFhirCase.fhir_bundle, null, 2)}
              </pre>
            </details>
            <details className="mt-3 rounded-2xl border border-slate-100 bg-[#F8FAF9] p-4">
              <summary className="cursor-pointer text-xs font-bold text-[#2E4742]">ServiceRequest resource</summary>
              <pre className="mt-3 overflow-x-auto whitespace-pre-wrap break-words rounded-xl bg-[#1F332F] p-4 text-[10px] leading-relaxed text-[#E8EFEA]">
                {JSON.stringify(selectedFhirCase.service_request, null, 2)}
              </pre>
            </details>
          </div>
        </div>
      )}

      {isAnalysisOpen && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="triage-preview-title"
            className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-3xl border border-slate-100 bg-white p-5 shadow-2xl sm:p-6"
          >
            <div className="mb-5 flex items-start justify-between gap-4 border-b border-slate-100 pb-4">
              <div>
                <h3 id="triage-preview-title" className="text-base font-bold text-[#2E4742]">
                  AI Assist — Screening Notes Preview
                </h3>
                <p className="mt-1 text-xs text-[#617873]">
                  Analyze notes without creating a case. Do not include names, Omang IDs, or other identifying details.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsAnalysisOpen(false)}
                aria-label="Close notes analyzer"
                className="text-slate-400 hover:text-slate-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={handleTriagePreview} className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block text-xs font-bold text-[#2E4742]">
                  Screening type
                  <input
                    type="text"
                    required
                    maxLength={150}
                    value={analysisScreeningType}
                    onChange={(event) => setAnalysisScreeningType(event.target.value)}
                    className="mt-1 w-full rounded-xl border border-slate-200 px-3.5 py-2.5 text-xs font-normal focus:border-[#2E4742] focus:outline-none"
                  />
                </label>
                <label className="block text-xs font-bold text-[#2E4742]">
                  Clinic / facility
                  <input
                    type="text"
                    required
                    maxLength={150}
                    value={analysisFacility}
                    onChange={(event) => setAnalysisFacility(event.target.value)}
                    className="mt-1 w-full rounded-xl border border-slate-200 px-3.5 py-2.5 text-xs font-normal focus:border-[#2E4742] focus:outline-none"
                  />
                </label>
              </div>
              <label className="block text-xs font-bold text-[#2E4742]">
                Clinical screening notes
                <textarea
                  required
                  minLength={3}
                  maxLength={5000}
                  rows={5}
                  value={analysisNotes}
                  onChange={(event) => setAnalysisNotes(event.target.value)}
                  className="mt-1 w-full resize-y rounded-xl border border-slate-200 px-3.5 py-2.5 text-xs font-normal focus:border-[#2E4742] focus:outline-none"
                  placeholder="Enter non-identifying screening findings to preview a risk category and SLA."
                />
              </label>

              {analysisError && (
                <p role="alert" className="rounded-xl bg-red-50 p-3 text-xs font-semibold text-red-700">
                  {analysisError}
                </p>
              )}

              {analysisResult && (
                <section aria-label="Triage preview result" className="space-y-3 rounded-2xl border border-[#D4A329]/40 bg-[#FBF8EE] p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-wide text-[#987117]">Demo triage result</p>
                      <p className="mt-1 text-sm font-bold text-[#2E4742]">
                        {analysisResult.triage.risk_level.replaceAll('_', ' ')} · {analysisResult.triage.sla_hours}h recommended SLA
                      </p>
                    </div>
                    <span className="rounded-full bg-[#2E4742] px-3 py-1 text-[10px] font-bold text-white">
                      Preview only
                    </span>
                  </div>
                  <p className="text-xs leading-relaxed text-[#617873]">
                    {analysisResult.triage.rationale_summary}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {analysisResult.triage.risk_tags.map((tag, index) => (
                      <span key={`${tag.display}-${index}`} className="rounded-full bg-white px-3 py-1 text-[10px] font-semibold text-[#2E4742]">
                        {tag.display}
                      </span>
                    ))}
                  </div>
                  <div className="rounded-xl border border-slate-200 bg-white p-3">
                    <p className="text-[10px] font-bold uppercase tracking-wide text-[#617873]">Draft SMS · not sent</p>
                    <p className="mt-1 text-xs leading-relaxed text-[#425C56]">
                      {analysisResult.draft_patient_sms.message}
                    </p>
                  </div>
                  <p className="text-[10px] leading-relaxed text-[#617873]">
                    Transparent keyword-based prototype only. This is not a diagnosis or clinical decision-support recommendation.
                  </p>
                </section>
              )}

              <div className="flex flex-wrap justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => setIsAnalysisOpen(false)}
                  className="rounded-full px-4 py-2 text-xs font-semibold text-[#617873] hover:bg-slate-100"
                >
                  Close
                </button>
                {analysisResult && (
                  <button
                    type="button"
                    onClick={useAnalysisInIntake}
                    className="rounded-full border border-[#2E4742] px-4 py-2 text-xs font-semibold text-[#2E4742] transition hover:bg-[#F4F8F6]"
                  >
                    Use notes in field intake
                  </button>
                )}
                <button
                  type="submit"
                  disabled={isAnalyzing}
                  className="rounded-full bg-[#2E4742] px-5 py-2 text-xs font-semibold text-white transition hover:bg-[#233834] disabled:cursor-wait disabled:opacity-60"
                >
                  {isAnalyzing ? 'Analyzing…' : 'Analyze notes'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {isIntakeOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
          <div role="dialog" aria-modal="true" aria-labelledby="intake-modal-title" className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-3xl border border-slate-100 bg-white p-6 shadow-2xl">
            <div className="mb-5 flex items-center justify-between border-b border-slate-100 pb-4">
              <div>
                <h3 id="intake-modal-title" className="text-base font-bold text-[#2E4742]">Clinical Screening Intake</h3>
                <p className="mt-1 text-xs text-[#617873]">
                  {isOnline
                    ? 'Demo rules classify the notes and add the case to the Screening Queue.'
                    : 'This intake will be queued and triaged by the API when you reconnect.'}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsIntakeOpen(false)}
                aria-label="Close dialog"
                className="text-slate-400 hover:text-slate-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={handleIntakeSubmit} className="space-y-4">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                {[
                  ['patient_national_id', 'Patient / national ID', 'text'],
                  ['patient_name', 'Patient full name', 'text'],
                  ['date_of_birth', 'Date of birth', 'date'],
                  ['phone_number', 'Phone number', 'tel'],
                  ['screening_type', 'Screening type', 'text'],
                  ['facility', 'Facility', 'text']
                ].map(([name, label, type]) => (
                  <label key={name} className="block text-xs font-bold text-[#2E4742]">
                    {label} *
                    <input
                      type={type}
                      required
                      value={intakeForm[name]}
                      onChange={(event) => setIntakeForm((form) => ({ ...form, [name]: event.target.value }))}
                      className="mt-1 w-full rounded-xl border border-slate-200 px-3.5 py-2.5 text-xs font-normal focus:border-[#2E4742] focus:outline-none"
                    />
                  </label>
                ))}
                <label className="block text-xs font-bold text-[#2E4742]">
                  Gender *
                  <select
                    required
                    value={intakeForm.gender}
                    onChange={(event) => setIntakeForm((form) => ({ ...form, gender: event.target.value }))}
                    className="mt-1 w-full rounded-xl border border-slate-200 px-3.5 py-2.5 text-xs font-normal focus:border-[#2E4742] focus:outline-none"
                  >
                    <option value="">Select</option>
                    <option>Female</option>
                    <option>Male</option>
                    <option>Other</option>
                    <option>Unknown</option>
                  </select>
                </label>
                <label className="block text-xs font-bold text-[#2E4742]">
                  Preferred contact channel
                  <select
                    value={intakeForm.preferred_channel}
                    onChange={(event) => setIntakeForm((form) => ({ ...form, preferred_channel: event.target.value }))}
                    className="mt-1 w-full rounded-xl border border-slate-200 px-3.5 py-2.5 text-xs font-normal focus:border-[#2E4742] focus:outline-none"
                  >
                    <option value="whatsapp">WhatsApp</option>
                    <option value="sms">SMS</option>
                    <option value="phone">Phone</option>
                  </select>
                </label>
              </div>

              <label className="flex items-start gap-2.5 rounded-xl border border-[#D4A329]/40 bg-[#FBF8EE] px-3.5 py-3 text-[11px] leading-relaxed text-[#2E4742]">
                <input
                  type="checkbox"
                  required
                  checked={intakeForm.consent_signed}
                  onChange={(event) => setIntakeForm((form) => ({
                    ...form,
                    consent_signed: event.target.checked
                  }))}
                  className="mt-0.5 accent-[#2E4742]"
                />
                <span>
                  I confirm the patient has signed the POPIA / Data Protection Act consent for this screening and referral.
                  This confirmation is required before online submission or encrypted offline storage.
                </span>
              </label>

              <label className="block text-xs font-bold text-[#2E4742]">
                Raw screening notes *
                <textarea
                  required
                  minLength={3}
                  rows={4}
                  value={intakeForm.raw_screening_notes}
                  onChange={(event) => setIntakeForm((form) => ({ ...form, raw_screening_notes: event.target.value }))}
                  className="mt-1 w-full resize-y rounded-xl border border-slate-200 px-3.5 py-2.5 text-xs font-normal focus:border-[#2E4742] focus:outline-none"
                  placeholder="Enter screening findings for demo rule-based triage"
                />
              </label>

              <p className="rounded-xl bg-[#F4F8F6] px-3.5 py-3 text-[11px] text-[#617873]">
                Prototype only: keyword-based demo triage is not an AI model and must not be used to make real clinical decisions.
              </p>
              {intakeError && (
                <p role="alert" className="rounded-xl bg-red-50 p-2.5 text-xs font-semibold text-red-600">
                  {intakeError}
                </p>
              )}
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsIntakeOpen(false)}
                  className="rounded-full px-4 py-2 text-xs font-semibold text-[#617873] hover:bg-slate-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="rounded-full bg-[#2E4742] px-5 py-2 text-xs font-semibold text-white hover:bg-[#233834] disabled:opacity-60"
                >
                  {isSubmitting ? 'Saving…' : isOnline ? 'Triage & Create Case' : 'Save Offline'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
