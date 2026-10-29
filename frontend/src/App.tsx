import React, { useState, useEffect, useCallback } from 'react';
import {
  Building2, Users, IndianRupee, BedDouble, CalendarCheck, Award,
  ArrowRightLeft, UploadCloud, ShieldCheck, FileText, Bell, LogOut,
  Search, CheckCircle2, AlertTriangle, XCircle, RefreshCw, PlusCircle,
  Lock, UserCheck, Eye, Download, Sliders
} from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, PieChart, Pie, Cell
} from 'recharts';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '/api';

const DEMO_ACCOUNTS = [
  { id: 'M1001', role: 'Trust Management', label: 'M1001 — Trust Chairman (Cumulative & 6-Campus Executive View)' },
  { id: 'A1001', role: 'College Admin', label: 'A1001 — College Admin (Campus 1: VVE Bengaluru)' },
  { id: 'A1002', role: 'College Admin', label: 'A1002 — College Admin (Campus 2: VVE Mysuru)' },
  { id: 'W1001', role: 'Hostel Warden', label: 'W1001 — Hostel Warden (Campus 1 Bed Map & Allocation)' },
  { id: 'S10001', role: 'Student', label: 'S10001 — Student Portal (Campus 1 Engineering)' },
  { id: 'P10001', role: 'Parent', label: 'P10001 — Linked Parent Portal (Verified Guardian)' },
];

export default function App() {
  const [token, setToken] = useState<string | null>(localStorage.getItem('trustos_token'));
  const [user, setUser] = useState<any>(
    localStorage.getItem('trustos_user') ? JSON.parse(localStorage.getItem('trustos_user')!) : null
  );
  const [authView, setAuthView] = useState<'LOGIN' | 'REGISTER' | 'STATUS' | 'RESET'>('LOGIN');
  const [activeTab, setActiveTab] = useState<string>('DASHBOARD');
  const [selectedCampusId, setSelectedCampusId] = useState<string>('ALL');
  const [campuses, setCampuses] = useState<any[]>([]);
  const [courses, setCourses] = useState<any[]>([]);
  const [toast, setToast] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Auth form states
  const [loginId, setLoginId] = useState('M1001');
  const [loginPw, setLoginPw] = useState('TrustOS@2026');
  const [regForm, setRegForm] = useState({
    requested_role: 'STUDENT',
    full_name: '',
    email: '',
    phone: '',
    campus_id: '',
    verification_usn: '1VV26EC0001',
    password: 'TrustOS@2026',
  });
  const [regStatusId, setRegStatusId] = useState('1VV26EC0001');
  const [regStatusResult, setRegStatusResult] = useState<any>(null);
  const [resetForm, setResetForm] = useState({ display_user_id: 'S10001', verified_email: 'student.c1@vidyavikas.edu.in', new_password: 'TrustOS@2026' });

  // Module data states
  const [dashboard, setDashboard] = useState<any>(null);
  const [studentsData, setStudentsData] = useState<any>({ total: 0, students: [] });
  const [studentSearch, setStudentSearch] = useState('');
  const [selectedStudentDetail, setSelectedStudentDetail] = useState<any>(null);
  const [duplicatesData, setDuplicatesData] = useState<any>(null);
  const [transfersList, setTransfersList] = useState<any[]>([]);
  const [transferForm, setTransferForm] = useState({ source_usn: '1VV26CS0005', destination_campus_id: '', reason: 'Family relocation & academic continuity' });
  const [transferPreview, setTransferPreview] = useState<any>(null);
  const [feesData, setFeesData] = useState<any>({ assessments: [], recent_payments: [] });
  const [hostelData, setHostelData] = useState<any>({ summary: {}, buildings: [], beds: [] });
  const [selectedBed, setSelectedBed] = useState<any>(null);
  const [allocUsn, setAllocUsn] = useState('1VV26EC0002');
  const [attendanceData, setAttendanceData] = useState<any>({ summary: {}, records: [] });
  const [reimbursementsData, setReimbursementsData] = useState<any>({ schemes: [], claims: [] });
  const [importsMeta, setImportsMeta] = useState<any>({ raw_source_files: [], import_history: [], data_quality_issues: [] });
  const [profileResult, setProfileResult] = useState<any>(null);
  const [selectedRawFile, setSelectedRawFile] = useState('campus_1_admissions.csv');
  const [selectedImportModule, setSelectedImportModule] = useState('ADMISSIONS');
  const [policiesList, setPoliciesList] = useState<any[]>([]);
  const [regRequestsList, setRegRequestsList] = useState<any[]>([]);
  const [privacyData, setPrivacyData] = useState<any>(null);
  const [notificationsList, setNotificationsList] = useState<any[]>([]);
  const [auditLogsList, setAuditLogsList] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  // New Admission modal form
  const [newAdmission, setNewAdmission] = useState({
    full_name: '',
    date_of_birth: '2006-04-15',
    gender: 'Female',
    phone: '9880011223',
    guardian_name: 'Sri Narayana Rao',
    guardian_phone: '9880011224',
    category: 'GENERAL',
    course_id: '',
    quota: 'MERIT',
  });

  // New Payment modal form
  const [paymentModalAss, setPaymentModalAss] = useState<any>(null);
  const [paymentForm, setPaymentForm] = useState({ amount: 25000, transaction_ref: '', payment_mode: 'UPI_SIMULATED' });

  const showToast = (type: 'success' | 'error', text: string) => {
    setToast({ type, text });
    setTimeout(() => setToast(null), 5000);
  };

  const safeJson = async (res: Response) => {
    const text = await res.text();
    try {
      return text ? JSON.parse(text) : {};
    } catch {
      return { detail: text || res.statusText || 'Server error' };
    }
  };

  const apiFetch = useCallback(
    async (path: string, options: RequestInit = {}) => {
      const headers: Record<string, string> = {
        ...(options.headers as Record<string, string>),
      };
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }
      if (!(options.body instanceof FormData) && !headers['Content-Type']) {
        headers['Content-Type'] = 'application/json';
      }
      const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
      const data = await safeJson(res);
      if (!res.ok) {
        throw new Error(data.detail || res.statusText || 'Request failed');
      }
      return data;
    },
    [token]
  );

  // Load public campuses on mount
  useEffect(() => {
    fetch(`${API_BASE}/public/campuses`)
      .then((r) => r.json())
      .then((d) => {
        setCampuses(d.campuses || []);
        setCourses(d.courses || []);
        if (d.campuses?.length > 1) {
          setTransferForm((f) => ({ ...f, destination_campus_id: d.campuses[1].id }));
          setRegForm((f) => ({ ...f, campus_id: d.campuses[0].id }));
        }
        if (d.courses?.length > 0) {
          setNewAdmission((a) => ({ ...a, course_id: d.courses[0].id }));
        }
      })
      .catch(() => {});
  }, []);

  // Load active tab data when logged in
  const refreshActiveTab = useCallback(async () => {
    if (!token || !user) return;
    setLoading(true);
    try {
      if (activeTab === 'DASHBOARD') {
        const d = await apiFetch(`/dashboard/summary?campus_id=${selectedCampusId}`);
        setDashboard(d);
        if (user.role_code === 'STUDENT' || user.role_code === 'PARENT') {
          if (user.linked_student_id) {
            const st = await apiFetch(`/students/${user.linked_student_id}`);
            setSelectedStudentDetail(st);
          }
        }
      } else if (activeTab === 'ADMISSIONS') {
        const d = await apiFetch(`/students?campus_id=${selectedCampusId}&q=${encodeURIComponent(studentSearch)}&limit=50`);
        setStudentsData(d);
      } else if (activeTab === 'DUPLICATES') {
        const d = await apiFetch('/duplicates');
        setDuplicatesData(d);
      } else if (activeTab === 'TRANSFERS') {
        const d = await apiFetch('/transfers');
        setTransfersList(d.transfers || []);
      } else if (activeTab === 'FEES') {
        const d = await apiFetch(`/fees/assessments?campus_id=${selectedCampusId}&q=${encodeURIComponent(studentSearch)}`);
        setFeesData(d);
      } else if (activeTab === 'HOSTEL') {
        const d = await apiFetch(`/hostels/inventory?campus_id=${selectedCampusId}`);
        setHostelData(d);
      } else if (activeTab === 'ATTENDANCE') {
        const d = await apiFetch(`/attendance?campus_id=${selectedCampusId}`);
        setAttendanceData(d);
        if (user.linked_student_id) {
          const st = await apiFetch(`/students/${user.linked_student_id}`);
          setSelectedStudentDetail(st);
        }
      } else if (activeTab === 'SCHOLARSHIPS') {
        const d = await apiFetch(`/scholarships/reimbursements?campus_id=${selectedCampusId}&usn=${encodeURIComponent(studentSearch)}`);
        setReimbursementsData(d);
      } else if (activeTab === 'IMPORTS') {
        const d = await apiFetch('/imports/raw-files');
        setImportsMeta(d);
      } else if (activeTab === 'POLICIES') {
        const d = await apiFetch('/policies');
        setPoliciesList(d.policies || []);
      } else if (activeTab === 'ACCOUNTS') {
        const d = await apiFetch('/admin/registration-requests');
        setRegRequestsList(d.requests || []);
      } else if (activeTab === 'PRIVACY') {
        const d = await apiFetch('/privacy/overview');
        setPrivacyData(d);
      } else if (activeTab === 'NOTIFICATIONS') {
        const d = await apiFetch('/notifications');
        setNotificationsList(d.notifications || []);
      } else if (activeTab === 'AUDIT') {
        const d = await apiFetch('/audit-logs');
        setAuditLogsList(d.audit_logs || []);
      }
    } catch (err: any) {
      showToast('error', err.message);
    } finally {
      setLoading(false);
    }
  }, [token, user, activeTab, selectedCampusId, studentSearch, apiFetch]);

  useEffect(() => {
    refreshActiveTab();
  }, [refreshActiveTab]);

  // Handlers
  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id_or_email: loginId, password: loginPw }),
      });
      const data = await safeJson(res);
      if (!res.ok) throw new Error(data.detail || 'Sign-in failed');
      localStorage.setItem('trustos_token', data.access_token);
      localStorage.setItem('trustos_user', JSON.stringify(data.user));
      setToken(data.access_token);
      setUser(data.user);
      setSelectedCampusId(data.user.role_code === 'TRUST_MANAGEMENT' ? 'ALL' : data.user.primary_campus_id || 'ALL');
      setActiveTab(data.user.role_code === 'HOSTEL_WARDEN' ? 'HOSTEL' : 'DASHBOARD');
      showToast('success', `Signed in as ${data.user.display_user_id} (${data.user.role_code})`);
    } catch (err: any) {
      showToast('error', err.message);
    }
  };

  const handleLogout = async () => {
    try {
      await apiFetch('/auth/logout', { method: 'POST' });
    } catch {}
    localStorage.removeItem('trustos_token');
    localStorage.removeItem('trustos_user');
    setToken(null);
    setUser(null);
  };

  const handleRegisterRequest = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await fetch(`${API_BASE}/auth/register-request`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(regForm),
      });
      const data = await safeJson(res);
      if (!res.ok) throw new Error(data.detail || 'Registration failed');
      setRegStatusId(data.request_id);
      setAuthView('STATUS');
      showToast('success', `Registration request submitted! Request ID: ${data.request_id}`);
    } catch (err: any) {
      showToast('error', err.message);
    }
  };

  const handleCheckRegStatus = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await fetch(`${API_BASE}/auth/registration-status/${encodeURIComponent(regStatusId.trim())}`);
      const data = await safeJson(res);
      if (!res.ok) throw new Error(data.detail || 'Not found');
      setRegStatusResult(data);
      showToast('success', `Found status: ${data.status}`);
    } catch (err: any) {
      setRegStatusResult(null);
      showToast('error', err.message);
    }
  };

  const handlePasswordReset = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await fetch(`${API_BASE}/auth/password-reset`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(resetForm),
      });
      const data = await safeJson(res);
      if (!res.ok) throw new Error(data.detail || 'Reset failed');
      showToast('success', `Password updated for ${data.display_user_id}. You may now sign in.`);
      setAuthView('LOGIN');
    } catch (err: any) {
      showToast('error', err.message);
    }
  };

  // ===========================================================================
  // AUTHENTICATION SCREENS (LOGIN, REGISTRATION REQUEST, STATUS, PASSWORD RESET)
  // ===========================================================================
  if (!token || !user) {
    return (
      <div className="min-h-screen bg-slate-900 flex flex-col justify-center py-10 px-4 sm:px-6 lg:px-8">
        {toast && (
          <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg text-sm font-medium ${toast.type === 'success' ? 'bg-emerald-600 text-white' : 'bg-rose-600 text-white'}`}>
            {toast.text}
          </div>
        )}
        <div className="sm:mx-auto sm:w-full sm:max-w-xl">
          <div className="flex items-center justify-center gap-3 text-white">
            <div className="p-2.5 rounded-xl bg-indigo-600 shadow-lg">
              <Building2 className="w-8 h-8" />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight">TrustOS Enterprise</h1>
              <p className="text-xs text-slate-400">AI-Powered Multi-Campus Educational Trust Management Platform</p>
            </div>
          </div>

          <div className="mt-6 bg-slate-800/90 border border-slate-700 py-7 px-6 shadow-2xl rounded-2xl sm:px-10 text-slate-100">
            <div className="flex border-b border-slate-700 mb-6 text-xs font-semibold">
              {[
                { id: 'LOGIN', label: '1. Sign In' },
                { id: 'REGISTER', label: '2. Request Registration' },
                { id: 'STATUS', label: '3. Registration Status' },
                { id: 'RESET', label: '4. Password Reset' },
              ].map((t) => (
                <button
                  key={t.id}
                  onClick={() => setAuthView(t.id as any)}
                  className={`pb-3 px-3 border-b-2 transition ${authView === t.id ? 'border-indigo-400 text-indigo-300' : 'border-transparent text-slate-400 hover:text-slate-200'}`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {authView === 'LOGIN' && (
              <form onSubmit={handleLogin} className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Quick Demo Role Switcher (Synthetic Environment)</label>
                  <select
                    value={loginId}
                    onChange={(e) => {
                      setLoginId(e.target.value);
                      setLoginPw('TrustOS@2026');
                    }}
                    className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-100"
                  >
                    {DEMO_ACCOUNTS.map((acc) => (
                      <option key={acc.id} value={acc.id}>{acc.label}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">User ID or Institutional Email</label>
                  <input
                    type="text"
                    required
                    value={loginId}
                    onChange={(e) => setLoginId(e.target.value)}
                    className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-white"
                    placeholder="e.g. M1001, A1001, W1001, S10001, P10001"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Password</label>
                  <input
                    type="password"
                    required
                    value={loginPw}
                    onChange={(e) => setLoginPw(e.target.value)}
                    className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-white"
                  />
                </div>

                <button
                  type="submit"
                  className="w-full py-2.5 px-4 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-sm shadow transition"
                >
                  Sign In to TrustOS
                </button>

                <div className="mt-4 p-3 rounded-lg bg-slate-900/80 border border-slate-700/80 text-xs text-slate-400 space-y-1">
                  <div className="font-semibold text-slate-300 flex items-center gap-1.5">
                    <ShieldCheck className="w-4 h-4 text-emerald-400" />
                    PostgreSQL Row-Level Security (RLS) Active
                  </div>
                  <p>6 Campuses • 14,000 Canonical Students • Permanent UUID Identity • Immutable Ledger Receipts</p>
                </div>
              </form>
            )}

            {authView === 'REGISTER' && (
              <form onSubmit={handleRegisterRequest} className="space-y-3 text-sm">
                <div className="p-2.5 rounded bg-amber-950/60 border border-amber-700/60 text-amber-200 text-xs">
                  Selecting a role submits a verification request. Privileged access is never granted automatically until approved by an authorized administrator.
                </div>
                <div>
                  <label className="block text-xs text-slate-300 mb-1">Requested Role</label>
                  <select
                    value={regForm.requested_role}
                    onChange={(e) => setRegForm({ ...regForm, requested_role: e.target.value })}
                    className="w-full rounded bg-slate-900 border border-slate-700 px-3 py-2 text-sm"
                  >
                    <option value="STUDENT">Student (S...)</option>
                    <option value="PARENT">Parent / Lawful Guardian (P...)</option>
                    <option value="COLLEGE_ADMIN">College Administrator (A...)</option>
                    <option value="HOSTEL_WARDEN">Hostel Warden (W...)</option>
                    <option value="TRUST_MANAGEMENT">Trust Management (M...)</option>
                  </select>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-slate-300 mb-1">Full Name</label>
                    <input
                      required
                      value={regForm.full_name}
                      onChange={(e) => setRegForm({ ...regForm, full_name: e.target.value })}
                      className="w-full rounded bg-slate-900 border border-slate-700 px-3 py-1.5"
                      placeholder="Applicant Name"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-300 mb-1">Email</label>
                    <input
                      type="email"
                      required
                      value={regForm.email}
                      onChange={(e) => setRegForm({ ...regForm, email: e.target.value })}
                      className="w-full rounded bg-slate-900 border border-slate-700 px-3 py-1.5"
                      placeholder="name@example.com"
                    />
                  </div>
                </div>
                {(regForm.requested_role === 'STUDENT' || regForm.requested_role === 'PARENT') && (
                  <div>
                    <label className="block text-xs text-slate-300 mb-1">Verified Institutional Student USN</label>
                    <input
                      required
                      value={regForm.verification_usn}
                      onChange={(e) => setRegForm({ ...regForm, verification_usn: e.target.value })}
                      className="w-full rounded bg-slate-900 border border-slate-700 px-3 py-1.5"
                      placeholder="e.g. 1VV26CS0001"
                    />
                  </div>
                )}
                <div>
                  <label className="block text-xs text-slate-300 mb-1">Password (min 8 chars)</label>
                  <input
                    type="password"
                    required
                    minLength={8}
                    value={regForm.password}
                    onChange={(e) => setRegForm({ ...regForm, password: e.target.value })}
                    className="w-full rounded bg-slate-900 border border-slate-700 px-3 py-1.5"
                  />
                </div>
                <button type="submit" className="w-full py-2 rounded bg-indigo-600 hover:bg-indigo-500 text-white font-semibold">
                  Submit Registration Request
                </button>
              </form>
            )}

            {authView === 'STATUS' && (
              <div className="space-y-4 text-sm">
                <form onSubmit={handleCheckRegStatus} className="flex gap-2">
                  <input
                    required
                    value={regStatusId}
                    onChange={(e) => setRegStatusId(e.target.value)}
                    placeholder="Enter Request UUID, Student USN (e.g. 1VV26CS0001), or User ID"
                    className="flex-1 rounded bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-white"
                  />
                  <button type="submit" className="px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-500 font-semibold text-white">
                    Check
                  </button>
                </form>
                {regStatusResult && (
                  <div className="p-4 rounded-lg bg-slate-900 border border-slate-700 space-y-1.5 text-xs">
                    <div><span className="text-slate-400">Applicant / Student:</span> <strong className="text-white">{regStatusResult.full_name}</strong> ({regStatusResult.requested_role})</div>
                    <div><span className="text-slate-400">Status:</span> <span className="font-bold text-emerald-400">{regStatusResult.status}</span></div>
                    <div><span className="text-slate-400">Issued User ID:</span> <code className="font-mono text-indigo-300 font-bold">{regStatusResult.generated_user_id || 'Awaiting Admin Approval'}</code></div>
                    {regStatusResult.review_notes && (
                      <div><span className="text-slate-400">Details:</span> <span className="text-slate-300">{regStatusResult.review_notes}</span></div>
                    )}
                  </div>
                )}
              </div>
            )}

            {authView === 'RESET' && (
              <form onSubmit={handlePasswordReset} className="space-y-3 text-sm">
                <div>
                  <label className="block text-xs text-slate-300 mb-1">User ID</label>
                  <input
                    required
                    value={resetForm.display_user_id}
                    onChange={(e) => setResetForm({ ...resetForm, display_user_id: e.target.value })}
                    className="w-full rounded bg-slate-900 border border-slate-700 px-3 py-1.5"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-300 mb-1">Verified Registered Email</label>
                  <input
                    type="email"
                    required
                    value={resetForm.verified_email}
                    onChange={(e) => setResetForm({ ...resetForm, verified_email: e.target.value })}
                    className="w-full rounded bg-slate-900 border border-slate-700 px-3 py-1.5"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-300 mb-1">New Password</label>
                  <input
                    type="password"
                    required
                    minLength={8}
                    value={resetForm.new_password}
                    onChange={(e) => setResetForm({ ...resetForm, new_password: e.target.value })}
                    className="w-full rounded bg-slate-900 border border-slate-700 px-3 py-1.5"
                  />
                </div>
                <button type="submit" className="w-full py-2 rounded bg-indigo-600 hover:bg-indigo-500 text-white font-semibold">
                  Verify & Reset Password
                </button>
              </form>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ===========================================================================
  // ROLE-BASED NAVIGATION ITEMS
  // ===========================================================================
  const role = user.role_code;
  const navItems = [
    { id: 'DASHBOARD', label: role === 'TRUST_MANAGEMENT' ? 'Executive Dashboard' : `${role.replace('_', ' ')} Dashboard`, icon: Building2, roles: ['TRUST_MANAGEMENT', 'COLLEGE_ADMIN', 'STUDENT', 'PARENT', 'HOSTEL_WARDEN'] },
    { id: 'ADMISSIONS', label: 'Admissions & Student Identity', icon: Users, roles: ['TRUST_MANAGEMENT', 'COLLEGE_ADMIN'] },
    { id: 'DUPLICATES', label: 'Duplicate Identity Review', icon: UserCheck, roles: ['TRUST_MANAGEMENT', 'COLLEGE_ADMIN'] },
    { id: 'TRANSFERS', label: 'Request & Approve Transfers', icon: ArrowRightLeft, roles: ['TRUST_MANAGEMENT', 'COLLEGE_ADMIN'] },
    { id: 'FEES', label: 'Fees & Immutable Receipts', icon: IndianRupee, roles: ['TRUST_MANAGEMENT', 'COLLEGE_ADMIN', 'STUDENT', 'PARENT'] },
    { id: 'HOSTEL', label: 'Hostel Vacancy & Allocation', icon: BedDouble, roles: ['TRUST_MANAGEMENT', 'COLLEGE_ADMIN', 'HOSTEL_WARDEN', 'STUDENT', 'PARENT'] },
    { id: 'ATTENDANCE', label: 'Attendance & Exam Results', icon: CalendarCheck, roles: ['TRUST_MANAGEMENT', 'COLLEGE_ADMIN', 'STUDENT', 'PARENT'] },
    { id: 'SCHOLARSHIPS', label: 'Scholarships & Reimbursements', icon: Award, roles: ['TRUST_MANAGEMENT', 'COLLEGE_ADMIN', 'STUDENT', 'PARENT'] },
    { id: 'IMPORTS', label: 'Multi-Dataset Import Pipeline', icon: UploadCloud, roles: ['TRUST_MANAGEMENT', 'COLLEGE_ADMIN'] },
    { id: 'POLICIES', label: 'Campus Policy Rule Engine', icon: Sliders, roles: ['TRUST_MANAGEMENT', 'COLLEGE_ADMIN'] },
    { id: 'ACCOUNTS', label: 'Account & Role Approvals', icon: Lock, roles: ['TRUST_MANAGEMENT', 'COLLEGE_ADMIN'] },
    { id: 'PRIVACY', label: 'DPDP Act Privacy & Consents', icon: ShieldCheck, roles: ['TRUST_MANAGEMENT', 'COLLEGE_ADMIN', 'STUDENT', 'PARENT'] },
    { id: 'NOTIFICATIONS', label: 'Notifications Centre', icon: Bell, roles: ['TRUST_MANAGEMENT', 'COLLEGE_ADMIN', 'STUDENT', 'PARENT', 'HOSTEL_WARDEN'] },
    { id: 'AUDIT', label: 'Tamper-Evident Audit Logs', icon: FileText, roles: ['TRUST_MANAGEMENT', 'COLLEGE_ADMIN'] },
  ].filter((item) => item.roles.includes(role));

  const formatINR = (val: number) =>
    new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(val || 0);

  return (
    <div className="min-h-screen flex bg-slate-50 text-slate-900">
      {toast && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg text-sm font-medium flex items-center gap-2 ${toast.type === 'success' ? 'bg-emerald-600 text-white' : 'bg-rose-600 text-white'}`}>
          {toast.type === 'success' ? <CheckCircle2 className="w-4 h-4" /> : <AlertTriangle className="w-4 h-4" />}
          {toast.text}
        </div>
      )}

      {/* Sidebar */}
      <aside className="w-64 bg-slate-900 text-slate-100 flex flex-col shrink-0">
        <div className="p-4 border-b border-slate-800 flex items-center gap-3">
          <div className="p-2 rounded-lg bg-indigo-600">
            <Building2 className="w-6 h-6 text-white" />
          </div>
          <div>
            <div className="font-bold text-base tracking-tight">TrustOS</div>
            <div className="text-[11px] text-slate-400">VidyaVikas Educational Trust</div>
          </div>
        </div>

        <div className="px-4 py-3 bg-slate-800/70 border-b border-slate-800 text-xs space-y-1">
          <div className="font-semibold text-white">{user.full_name}</div>
          <div className="flex items-center justify-between text-slate-400">
            <span className="px-1.5 py-0.5 rounded bg-indigo-950 text-indigo-300 font-mono">{user.display_user_id}</span>
            <span>{user.role_code}</span>
          </div>
          {user.campus_name && <div className="text-[11px] text-emerald-400 truncate">{user.campus_name}</div>}
        </div>

        <nav className="flex-1 p-2 space-y-1 overflow-y-auto">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition ${
                  active ? 'bg-indigo-600 text-white shadow' : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                }`}
              >
                <Icon className="w-4 h-4 shrink-0" />
                <span className="truncate">{item.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="p-3 border-t border-slate-800">
          <button
            onClick={handleLogout}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-slate-800 hover:bg-rose-600 text-xs font-semibold text-slate-200 hover:text-white transition"
          >
            <LogOut className="w-4 h-4" />
            Sign Out
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Header with Campus Selector */}
        <header className="bg-white border-b border-slate-200 px-6 py-3.5 flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-slate-900">
                {navItems.find((n) => n.id === activeTab)?.label || 'TrustOS Platform'}
              </h2>
              <span className="px-2 py-0.5 text-[11px] font-semibold rounded-full bg-amber-100 text-amber-800 border border-amber-300">
                SYNTHETIC DEMO DATA (14,000 Canonical Students)
              </span>
            </div>
            <p className="text-xs text-slate-500">
              PostgreSQL Row-Level Security (RLS) enforced under restricted role <code className="font-mono text-indigo-700">trustos_app</code>
            </p>
          </div>

          <div className="flex items-center gap-3">
            {role === 'TRUST_MANAGEMENT' ? (
              <div className="flex items-center gap-2">
                <label className="text-xs font-semibold text-slate-600">Campus Scope:</label>
                <select
                  value={selectedCampusId}
                  onChange={(e) => setSelectedCampusId(e.target.value)}
                  className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-800 shadow-sm"
                >
                  <option value="ALL">Cumulative View (All 6 Campuses — Deduplicated)</option>
                  {campuses.map((c) => (
                    <option key={c.id} value={c.id}>
                      Campus {c.campus_number}: {c.name} ({c.code})
                    </option>
                  ))}
                </select>
              </div>
            ) : (
              <div className="px-3 py-1.5 rounded-lg bg-slate-100 border border-slate-200 text-xs font-medium text-slate-700">
                Scoped Campus: <span className="font-bold">{user.campus_name || 'Assigned Institution'}</span>
              </div>
            )}

            <button
              onClick={refreshActiveTab}
              className="p-2 rounded-lg border border-slate-200 hover:bg-slate-100 text-slate-600"
              title="Refresh Live Database Metrics"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-indigo-600' : ''}`} />
            </button>
          </div>
        </header>

        {/* Page Body */}
        <main className="flex-1 p-6 overflow-y-auto space-y-6">
          {/* =============================================================== */}
          {/* VIEW 1: EXECUTIVE / ROLE DASHBOARD                              */}
          {/* =============================================================== */}
          {activeTab === 'DASHBOARD' && dashboard && (
            <div className="space-y-6">
              {/* Student / Parent Personal Banner if logged in as S... or P... */}
              {(role === 'STUDENT' || role === 'PARENT') && selectedStudentDetail?.student && (
                <div className="bg-indigo-900 text-white p-5 rounded-xl shadow-md flex flex-wrap items-center justify-between gap-4">
                  <div>
                    <div className="text-xs uppercase tracking-wider text-indigo-300 font-semibold">
                      {role === 'PARENT' ? 'Verified Guardian View — Linked Student Record' : 'Authenticated Student Profile'}
                    </div>
                    <h3 className="text-xl font-bold mt-0.5">{selectedStudentDetail.student.full_name}</h3>
                    <div className="text-xs text-indigo-200 mt-1 flex flex-wrap gap-4">
                      <span>Permanent UUID: <code className="font-mono bg-indigo-950 px-1.5 py-0.5 rounded">{selectedStudentDetail.student.student_id}</code></span>
                      <span>Active USN: <strong className="text-white">{selectedStudentDetail.student.current_usn}</strong></span>
                      <span>Campus: {selectedStudentDetail.student.campus_name}</span>
                    </div>
                  </div>
                  <div className="flex gap-3">
                    <button onClick={() => setActiveTab('FEES')} className="px-3 py-2 rounded-lg bg-white text-indigo-900 text-xs font-bold shadow">
                      View Fee Receipts
                    </button>
                    <button onClick={() => setActiveTab('ATTENDANCE')} className="px-3 py-2 rounded-lg bg-indigo-700 hover:bg-indigo-600 text-white text-xs font-semibold">
                      View Attendance & Results
                    </button>
                  </div>
                </div>
              )}

              {/* Primary KPI Cards */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <div onClick={() => setActiveTab('ADMISSIONS')} className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm cursor-pointer hover:border-indigo-400 transition">
                  <div className="flex items-center justify-between text-xs text-slate-500 font-medium">
                    <span>Canonical Students (Deduplicated)</span>
                    <Users className="w-4 h-4 text-indigo-600" />
                  </div>
                  <div className="text-2xl font-bold mt-2 text-slate-900">
                    {dashboard.metrics.canonical_student_count.toLocaleString()}
                  </div>
                  <div className="text-[11px] text-slate-500 mt-1">
                    Active Enrollments: {dashboard.metrics.active_enrollments.toLocaleString()} • Transfers: {dashboard.metrics.total_transfers}
                  </div>
                </div>

                <div onClick={() => setActiveTab('FEES')} className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm cursor-pointer hover:border-indigo-400 transition">
                  <div className="flex items-center justify-between text-xs text-slate-500 font-medium">
                    <span>Fee Collections vs Outstanding</span>
                    <IndianRupee className="w-4 h-4 text-emerald-600" />
                  </div>
                  <div className="text-xl font-bold mt-2 text-emerald-700">
                    {formatINR(dashboard.metrics.total_collections)}
                  </div>
                  <div className="text-[11px] text-rose-600 font-medium mt-1">
                    Outstanding: {formatINR(dashboard.metrics.total_outstanding_fees)} (Verify Backlog: {dashboard.metrics.fee_verification_backlog})
                  </div>
                </div>

                <div onClick={() => setActiveTab('HOSTEL')} className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm cursor-pointer hover:border-indigo-400 transition">
                  <div className="flex items-center justify-between text-xs text-slate-500 font-medium">
                    <span>Hostel Bed Occupancy</span>
                    <BedDouble className="w-4 h-4 text-amber-600" />
                  </div>
                  <div className="text-2xl font-bold mt-2 text-slate-900">
                    {dashboard.metrics.hostel.occupancy_percentage}%
                  </div>
                  <div className="text-[11px] text-slate-500 mt-1">
                    {dashboard.metrics.hostel.occupied_beds} Occupied / {dashboard.metrics.hostel.available_beds} Available ({dashboard.metrics.hostel.total_beds} Total Beds in {dashboard.metrics.hostel.total_rooms} Rooms)
                  </div>
                </div>

                <div onClick={() => setActiveTab('ATTENDANCE')} className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm cursor-pointer hover:border-indigo-400 transition">
                  <div className="flex items-center justify-between text-xs text-slate-500 font-medium">
                    <span>Attendance Eligibility Risk</span>
                    <CalendarCheck className="w-4 h-4 text-rose-600" />
                  </div>
                  <div className="text-2xl font-bold mt-2 text-rose-600">
                    {dashboard.metrics.attendance.below_threshold_count.toLocaleString()} <span className="text-xs font-normal text-slate-500">Ineligible</span>
                  </div>
                  <div className="text-[11px] text-slate-500 mt-1">
                    Approaching Threshold (At-Risk): {dashboard.metrics.attendance.at_risk_count.toLocaleString()} • Avg: {dashboard.metrics.attendance.avg_attendance_pct}%
                  </div>
                </div>
              </div>

              {/* Secondary KPI Cards */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div onClick={() => setActiveTab('SCHOLARSHIPS')} className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm cursor-pointer">
                  <div className="text-xs text-slate-500 font-medium">Govt Scholarship & Reimbursement Claims</div>
                  <div className="text-lg font-bold mt-1">{dashboard.metrics.reimbursements.total_claims.toLocaleString()} Claims</div>
                  <div className="text-xs text-slate-600 mt-1">
                    Disbursed: {formatINR(dashboard.metrics.reimbursements.total_disbursed)} • Pending: <span className="text-amber-700 font-semibold">{formatINR(dashboard.metrics.reimbursements.pending_reimbursement_amount)}</span>
                  </div>
                </div>

                <div onClick={() => setActiveTab('DUPLICATES')} className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm cursor-pointer">
                  <div className="text-xs text-slate-500 font-medium">AI Identity Reconciliation Queue</div>
                  <div className="text-lg font-bold mt-1 text-indigo-700">
                    {dashboard.metrics.data_quality.pending_duplicate_candidates} Ambiguous Candidates
                  </div>
                  <div className="text-xs text-slate-500 mt-1">
                    Homonyms & spelling variations held for human verification
                  </div>
                </div>

                <div onClick={() => setActiveTab('FEES')} className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm cursor-pointer">
                  <div className="text-xs text-slate-500 font-medium">Concessions, Scholarships & Refunds</div>
                  <div className="text-lg font-bold mt-1 text-slate-800">
                    {formatINR(dashboard.metrics.total_concessions_and_scholarships)}
                  </div>
                  <div className="text-xs text-slate-500 mt-1">
                    Completed Refunds: {formatINR(dashboard.metrics.total_refunds)}
                  </div>
                </div>
              </div>

              {/* Charts Row */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                  <h3 className="text-sm font-bold text-slate-800 mb-1">Campus-Wise Collections vs. Outstanding Fees (INR)</h3>
                  <p className="text-xs text-slate-500 mb-4">Computed live from posted ledger transactions and student fee assessments</p>
                  <div className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={dashboard.campus_breakdown}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis dataKey="campus_code" tick={{ fontSize: 11 }} />
                        <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `${(v / 10000000).toFixed(1)}Cr`} />
                        <Tooltip formatter={(val: any) => formatINR(Number(val))} />
                        <Legend wrapperStyle={{ fontSize: 12 }} />
                        <Bar dataKey="collected_fees" name="Posted Collections" fill="#10b981" radius={[4, 4, 0, 0]} />
                        <Bar dataKey="outstanding_fees" name="Outstanding Dues" fill="#f43f5e" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                  <h3 className="text-sm font-bold text-slate-800 mb-1">Attendance Risk & Hostel Bed Capacity by Campus</h3>
                  <p className="text-xs text-slate-500 mb-4">Students below campus policy threshold vs. available hostel beds</p>
                  <div className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={dashboard.campus_breakdown}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis dataKey="campus_code" tick={{ fontSize: 11 }} />
                        <YAxis tick={{ fontSize: 11 }} />
                        <Tooltip />
                        <Legend wrapperStyle={{ fontSize: 12 }} />
                        <Bar dataKey="below_threshold_students" name="Ineligible (< Policy %)" fill="#ef4444" radius={[4, 4, 0, 0]} />
                        <Bar dataKey="at_risk_students" name="At-Risk (Warning Band)" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                        <Bar dataKey="available_beds" name="Available Hostel Beds" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </div>

              {/* Consolidated Campus Comparison Table */}
              <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
                <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-bold text-slate-900">Six-Campus Consolidated Matrix</h3>
                    <p className="text-xs text-slate-500">Click any campus row to scope metrics or export statutory CSV report</p>
                  </div>
                  {role !== 'STUDENT' && role !== 'PARENT' && (
                    <a
                      href={`${API_BASE}/attendance/export-csv`}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 text-white text-xs font-semibold hover:bg-slate-800"
                    >
                      <Download className="w-3.5 h-3.5" />
                      Export Consolidated CSV
                    </a>
                  )}
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse text-xs">
                    <thead>
                      <tr className="bg-slate-100 text-slate-600 border-b border-slate-200">
                        <th className="py-2.5 px-4">Campus</th>
                        <th className="py-2.5 px-4">City</th>
                        <th className="py-2.5 px-4 text-right">Canonical Students</th>
                        <th className="py-2.5 px-4 text-right">Assessed Fees</th>
                        <th className="py-2.5 px-4 text-right">Posted Collections</th>
                        <th className="py-2.5 px-4 text-right">Outstanding</th>
                        <th className="py-2.5 px-4 text-right">Beds (Occ / Avail)</th>
                        <th className="py-2.5 px-4 text-right">Below Att. Threshold</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200">
                      {dashboard.campus_breakdown.map((c: any) => (
                        <tr
                          key={c.campus_id}
                          onClick={() => role === 'TRUST_MANAGEMENT' && setSelectedCampusId(c.campus_id)}
                          className="hover:bg-slate-50 cursor-pointer"
                        >
                          <td className="py-2.5 px-4 font-semibold text-indigo-700">
                            #{c.campus_number} {c.campus_name} ({c.campus_code})
                          </td>
                          <td className="py-2.5 px-4">{c.city}</td>
                          <td className="py-2.5 px-4 text-right font-mono">{c.student_count.toLocaleString()}</td>
                          <td className="py-2.5 px-4 text-right font-mono">{formatINR(c.assessed_fees)}</td>
                          <td className="py-2.5 px-4 text-right font-mono text-emerald-700 font-semibold">{formatINR(c.collected_fees)}</td>
                          <td className="py-2.5 px-4 text-right font-mono text-rose-600 font-semibold">{formatINR(c.outstanding_fees)}</td>
                          <td className="py-2.5 px-4 text-right font-mono">{c.occupied_beds} / {c.available_beds}</td>
                          <td className="py-2.5 px-4 text-right font-mono text-rose-600">{c.below_threshold_students}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* =============================================================== */}
          {/* VIEW 2: ADMISSIONS & PERMANENT STUDENT IDENTITY                 */}
          {/* =============================================================== */}
          {activeTab === 'ADMISSIONS' && (
            <div className="space-y-6">
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* New Admission Form */}
                <form
                  onSubmit={async (e) => {
                    e.preventDefault();
                    try {
                      const res = await apiFetch('/admissions', {
                        method: 'POST',
                        body: JSON.stringify(newAdmission),
                      });
                      showToast('success', `Admitted! Permanent ID: ${res.student_id} | Assigned USN: ${res.usn}`);
                      refreshActiveTab();
                    } catch (err: any) {
                      showToast('error', err.message);
                    }
                  }}
                  className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-3 text-xs"
                >
                  <div className="font-bold text-sm text-slate-900 flex items-center gap-2">
                    <PlusCircle className="w-4 h-4 text-indigo-600" />
                    Register New Student Admission
                  </div>
                  <p className="text-slate-500">
                    Automatically checks for duplicate student identities and generates a collision-safe USN.
                  </p>
                  <div>
                    <label className="block font-medium text-slate-700 mb-1">Student Full Name</label>
                    <input
                      required
                      value={newAdmission.full_name}
                      onChange={(e) => setNewAdmission({ ...newAdmission, full_name: e.target.value })}
                      className="w-full rounded border border-slate-300 px-2.5 py-1.5"
                      placeholder="e.g. Ananya Deshpande"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="block font-medium text-slate-700 mb-1">Date of Birth</label>
                      <input
                        type="date"
                        required
                        value={newAdmission.date_of_birth}
                        onChange={(e) => setNewAdmission({ ...newAdmission, date_of_birth: e.target.value })}
                        className="w-full rounded border border-slate-300 px-2.5 py-1.5"
                      />
                    </div>
                    <div>
                      <label className="block font-medium text-slate-700 mb-1">Student Mobile</label>
                      <input
                        required
                        value={newAdmission.phone}
                        onChange={(e) => setNewAdmission({ ...newAdmission, phone: e.target.value })}
                        className="w-full rounded border border-slate-300 px-2.5 py-1.5"
                      />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="block font-medium text-slate-700 mb-1">Guardian Name</label>
                      <input
                        required
                        value={newAdmission.guardian_name}
                        onChange={(e) => setNewAdmission({ ...newAdmission, guardian_name: e.target.value })}
                        className="w-full rounded border border-slate-300 px-2.5 py-1.5"
                      />
                    </div>
                    <div>
                      <label className="block font-medium text-slate-700 mb-1">Course</label>
                      <select
                        value={newAdmission.course_id}
                        onChange={(e) => setNewAdmission({ ...newAdmission, course_id: e.target.value })}
                        className="w-full rounded border border-slate-300 px-2 py-1.5"
                      >
                        {courses
                          .filter((c) => role === 'TRUST_MANAGEMENT' || c.campus_id === user.primary_campus_id)
                          .map((c) => (
                            <option key={c.id} value={c.id}>{c.code} — {c.name}</option>
                          ))}
                      </select>
                    </div>
                  </div>
                  <button type="submit" className="w-full py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold">
                    Create Canonical Identity & Enroll
                  </button>
                </form>

                {/* Student Directory & Identifier Inspector */}
                <div className="lg:col-span-2 bg-white rounded-xl border border-slate-200 shadow-sm flex flex-col">
                  <div className="p-4 border-b border-slate-200 flex items-center justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-bold">Canonical Student Registry ({studentsData.total.toLocaleString()} Matching)</h3>
                      <p className="text-xs text-slate-500">Click any student to inspect permanent UUID, USN history, fees & attendance</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <input
                        value={studentSearch}
                        onChange={(e) => setStudentSearch(e.target.value)}
                        placeholder="Search USN, Name, Phone..."
                        className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
                      />
                    </div>
                  </div>
                  <div className="overflow-x-auto max-h-96">
                    <table className="w-full text-left border-collapse text-xs">
                      <thead>
                        <tr className="bg-slate-100 text-slate-600 border-b border-slate-200">
                          <th className="py-2 px-3">Permanent UUID</th>
                          <th className="py-2 px-3">Active USN</th>
                          <th className="py-2 px-3">Full Name</th>
                          <th className="py-2 px-3">Campus & Course</th>
                          <th className="py-2 px-3 text-right">Fee Balance</th>
                          <th className="py-2 px-3">Attendance</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-200">
                        {studentsData.students.map((s: any) => (
                          <tr
                            key={s.student_id}
                            onClick={async () => {
                              const d = await apiFetch(`/students/${s.student_id}`);
                              setSelectedStudentDetail(d);
                            }}
                            className="hover:bg-indigo-50/60 cursor-pointer"
                          >
                            <td className="py-2 px-3 font-mono text-[11px] text-slate-500">{s.student_id.slice(0, 13)}…</td>
                            <td className="py-2 px-3 font-mono font-bold text-indigo-700">{s.current_usn}</td>
                            <td className="py-2 px-3 font-medium">{s.full_name}</td>
                            <td className="py-2 px-3">{s.campus_code} • {s.course_code}</td>
                            <td className="py-2 px-3 text-right font-mono">{formatINR(s.outstanding_balance)}</td>
                            <td className="py-2 px-3">
                              <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                                s.eligibility_status === 'ELIGIBLE' ? 'bg-emerald-100 text-emerald-800' :
                                s.eligibility_status === 'AT_RISK' ? 'bg-amber-100 text-amber-800' : 'bg-rose-100 text-rose-800'
                              }`}>
                                {s.attendance_percentage ?? 'N/A'}% ({s.eligibility_status})
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>

              {/* Selected Student 360-Degree Identity Drawer */}
              {selectedStudentDetail?.student && (
                <div className="bg-white p-5 rounded-xl border-2 border-indigo-500 shadow-md space-y-4">
                  <div className="flex items-center justify-between border-b border-slate-200 pb-3">
                    <div>
                      <span className="text-[11px] font-bold uppercase tracking-wider text-indigo-600">Canonical 360° Student Identity Record</span>
                      <h4 className="text-base font-bold text-slate-900">
                        {selectedStudentDetail.student.full_name} — Permanent ID: <code className="font-mono text-indigo-700">{selectedStudentDetail.student.student_id}</code>
                      </h4>
                    </div>
                    <button onClick={() => setSelectedStudentDetail(null)} className="text-xs text-slate-500 hover:text-slate-800">Close</button>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
                    <div className="p-3 rounded-lg bg-slate-50 border border-slate-200 space-y-1">
                      <div className="font-bold text-slate-700 mb-1">Identifier History (USNs & Roll Nos)</div>
                      {selectedStudentDetail.identifiers.map((idRow: any) => (
                        <div key={idRow.id} className="flex items-center justify-between">
                          <span className="font-mono font-semibold">{idRow.id_value}</span>
                          <span className={`px-1.5 py-0.5 rounded text-[10px] ${idRow.is_active ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-200 text-slate-600'}`}>
                            {idRow.is_active ? 'ACTIVE USN' : 'HISTORICAL (TRANSFERRED)'}
                          </span>
                        </div>
                      ))}
                    </div>
                    <div className="p-3 rounded-lg bg-slate-50 border border-slate-200 space-y-1">
                      <div className="font-bold text-slate-700 mb-1">Campus Enrollment Continuity</div>
                      {selectedStudentDetail.enrollments.map((enr: any) => (
                        <div key={enr.id} className="flex items-center justify-between">
                          <span>{enr.campus_code} ({enr.course_code}) — USN {enr.usn}</span>
                          <span className="font-semibold">{enr.status}</span>
                        </div>
                      ))}
                    </div>
                    <div className="p-3 rounded-lg bg-slate-50 border border-slate-200 space-y-1">
                      <div className="font-bold text-slate-700 mb-1">Financial & Hostel Status</div>
                      <div>Outstanding Fee Balance: <strong className="text-rose-600">{formatINR(selectedStudentDetail.fee_assessments?.[0]?.outstanding_balance || 0)}</strong></div>
                      <div>Posted Payments: <strong className="text-emerald-700">{formatINR(selectedStudentDetail.fee_assessments?.[0]?.net_posted_payments || 0)}</strong></div>
                      <div>Hostel Allocations: {selectedStudentDetail.hostel_allocations?.length || 0}</div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* =============================================================== */}
          {/* VIEW 3: DUPLICATE IDENTITY RESOLUTION & GROUND-TRUTH BENCHMARK  */}
          {/* =============================================================== */}
          {activeTab === 'DUPLICATES' && duplicatesData && (
            <div className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-white p-5 rounded-xl border border-emerald-300 shadow-sm">
                  <div className="text-xs font-bold uppercase text-emerald-700">TrustOS Multi-Signal Identity Resolver (Ground-Truth Evaluated)</div>
                  <div className="grid grid-cols-4 gap-2 mt-3 text-center">
                    <div className="p-2 rounded bg-emerald-50">
                      <div className="text-[11px] text-slate-500">Precision</div>
                      <div className="text-lg font-bold text-emerald-700">{(duplicatesData.evaluation_metrics.trustos_multi_signal_model.precision * 100).toFixed(1)}%</div>
                    </div>
                    <div className="p-2 rounded bg-emerald-50">
                      <div className="text-[11px] text-slate-500">Recall</div>
                      <div className="text-lg font-bold text-emerald-700">{(duplicatesData.evaluation_metrics.trustos_multi_signal_model.recall * 100).toFixed(1)}%</div>
                    </div>
                    <div className="p-2 rounded bg-emerald-50">
                      <div className="text-[11px] text-slate-500">F1 Score</div>
                      <div className="text-lg font-bold text-emerald-700">{(duplicatesData.evaluation_metrics.trustos_multi_signal_model.f1_score * 100).toFixed(1)}%</div>
                    </div>
                    <div className="p-2 rounded bg-emerald-50">
                      <div className="text-[11px] text-slate-500">False Positives</div>
                      <div className="text-lg font-bold text-emerald-700">{duplicatesData.evaluation_metrics.trustos_multi_signal_model.false_positives}</div>
                    </div>
                  </div>
                </div>

                <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                  <div className="text-xs font-bold uppercase text-slate-500">Baseline Naive Name-Only Matcher (Comparison)</div>
                  <div className="grid grid-cols-4 gap-2 mt-3 text-center">
                    <div className="p-2 rounded bg-slate-100">
                      <div className="text-[11px] text-slate-500">Precision</div>
                      <div className="text-lg font-bold text-slate-700">{(duplicatesData.evaluation_metrics.baseline_name_only_model.precision * 100).toFixed(1)}%</div>
                    </div>
                    <div className="p-2 rounded bg-slate-100">
                      <div className="text-[11px] text-slate-500">Recall</div>
                      <div className="text-lg font-bold text-slate-700">{(duplicatesData.evaluation_metrics.baseline_name_only_model.recall * 100).toFixed(1)}%</div>
                    </div>
                    <div className="p-2 rounded bg-slate-100">
                      <div className="text-[11px] text-slate-500">F1 Score</div>
                      <div className="text-lg font-bold text-slate-700">{(duplicatesData.evaluation_metrics.baseline_name_only_model.f1_score * 100).toFixed(1)}%</div>
                    </div>
                    <div className="p-2 rounded bg-rose-50">
                      <div className="text-[11px] text-rose-600">False Positives</div>
                      <div className="text-lg font-bold text-rose-600">{duplicatesData.evaluation_metrics.baseline_name_only_model.false_positives} (Homonyms)</div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
                <div className="p-4 border-b border-slate-200">
                  <h3 className="text-sm font-bold">Human Review Queue for Duplicate & Homonym Candidates</h3>
                  <p className="text-xs text-slate-500">{duplicatesData.evaluation_metrics.methodology_summary}</p>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse text-xs">
                    <thead>
                      <tr className="bg-slate-100 text-slate-600 border-b border-slate-200">
                        <th className="py-2.5 px-3">Source Key</th>
                        <th className="py-2.5 px-3">Source Record (Raw)</th>
                        <th className="py-2.5 px-3">Candidate Canonical Student</th>
                        <th className="py-2.5 px-3">Confidence</th>
                        <th className="py-2.5 px-3">Matching / Conflicting Signals</th>
                        <th className="py-2.5 px-3">Ground Truth</th>
                        <th className="py-2.5 px-3">Review Status & Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200">
                      {duplicatesData.candidates.map((c: any) => (
                        <tr key={c.id} className="hover:bg-slate-50">
                          <td className="py-2.5 px-3 font-mono font-semibold">{c.source_record_key}</td>
                          <td className="py-2.5 px-3">
                            <div className="font-bold">{c.source_student_name}</div>
                            <div className="text-slate-500">DOB: {c.source_dob} • Ph: {c.source_phone}</div>
                          </td>
                          <td className="py-2.5 px-3">
                            <div className="font-bold text-indigo-700">{c.candidate_student_name}</div>
                            <div className="font-mono text-slate-500">USN: {c.candidate_usn}</div>
                          </td>
                          <td className="py-2.5 px-3 font-bold">{c.match_confidence}%</td>
                          <td className="py-2.5 px-3">
                            <div className="text-emerald-700">Match: {(c.matching_attributes || []).join(', ')}</div>
                            {c.conflicting_attributes?.length > 0 && (
                              <div className="text-rose-600">Conflict: {c.conflicting_attributes.join(', ')}</div>
                            )}
                          </td>
                          <td className="py-2.5 px-3">
                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${c.ground_truth_is_duplicate ? 'bg-amber-100 text-amber-800' : 'bg-sky-100 text-sky-800'}`}>
                              {c.ground_truth_is_duplicate ? 'TRUE DUPLICATE' : 'DISTINCT HOMONYM'}
                            </span>
                          </td>
                          <td className="py-2.5 px-3">
                            <div className="flex items-center gap-1.5">
                              <span className="font-semibold">{c.review_status}</span>
                              {c.review_status === 'PENDING_REVIEW' && (
                                <>
                                  <button
                                    onClick={async () => {
                                      await apiFetch(`/duplicates/${c.id}/review`, {
                                        method: 'POST',
                                        body: JSON.stringify({ decision: 'CONFIRMED_DUPLICATE' }),
                                      });
                                      showToast('success', 'Linked to existing permanent student identity');
                                      refreshActiveTab();
                                    }}
                                    className="px-2 py-1 rounded bg-emerald-600 text-white text-[10px] font-semibold"
                                  >
                                    Confirm Duplicate
                                  </button>
                                  <button
                                    onClick={async () => {
                                      await apiFetch(`/duplicates/${c.id}/review`, {
                                        method: 'POST',
                                        body: JSON.stringify({ decision: 'DISTINCT_STUDENTS' }),
                                      });
                                      showToast('success', 'Marked as distinct student (homonym kept separate)');
                                      refreshActiveTab();
                                    }}
                                    className="px-2 py-1 rounded bg-slate-700 text-white text-[10px] font-semibold"
                                  >
                                    Keep Separate
                                  </button>
                                </>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* =============================================================== */}
          {/* VIEW 4: CAMPUS TRANSFER WORKFLOW (Request Transfer)             */}
          {/* =============================================================== */}
          {activeTab === 'TRANSFERS' && (
            <div className="space-y-6">
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-4 text-xs">
                  <div className="font-bold text-sm text-slate-900 flex items-center gap-2">
                    <ArrowRightLeft className="w-4 h-4 text-indigo-600" />
                    Request Inter-Campus Student Transfer
                  </div>
                  <p className="text-slate-500">
                    Preserves the student's permanent internal <code className="font-mono">student_id</code> UUID while assigning a new destination USN via a collision-safe database sequence.
                  </p>
                  <div>
                    <label className="block font-medium text-slate-700 mb-1">Current Student USN</label>
                    <input
                      value={transferForm.source_usn}
                      onChange={(e) => setTransferForm({ ...transferForm, source_usn: e.target.value })}
                      className="w-full rounded border border-slate-300 px-3 py-1.5 font-mono"
                      placeholder="e.g. 1VV26CS0005"
                    />
                  </div>
                  <div>
                    <label className="block font-medium text-slate-700 mb-1">Destination Campus (6-Campus List)</label>
                    <select
                      value={transferForm.destination_campus_id}
                      onChange={(e) => setTransferForm({ ...transferForm, destination_campus_id: e.target.value })}
                      className="w-full rounded border border-slate-300 px-2.5 py-1.5"
                    >
                      {campuses.map((c) => (
                        <option key={c.id} value={c.id}>Campus {c.campus_number}: {c.name} ({c.code})</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block font-medium text-slate-700 mb-1">Transfer Reason</label>
                    <input
                      value={transferForm.reason}
                      onChange={(e) => setTransferForm({ ...transferForm, reason: e.target.value })}
                      className="w-full rounded border border-slate-300 px-3 py-1.5"
                    />
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={async () => {
                        try {
                          const p = await apiFetch('/transfers/preview', {
                            method: 'POST',
                            body: JSON.stringify(transferForm),
                          });
                          setTransferPreview(p);
                        } catch (err: any) {
                          showToast('error', err.message);
                        }
                      }}
                      className="flex-1 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-white font-semibold"
                    >
                      1. Preview USN & Eligibility
                    </button>
                    <button
                      type="button"
                      onClick={async () => {
                        try {
                          const res = await apiFetch('/transfers/request', {
                            method: 'POST',
                            body: JSON.stringify(transferForm),
                          });
                          setTransferPreview(res.preview);
                          showToast('success', `Transfer Request Submitted! ID: ${res.transfer_request_id}`);
                          refreshActiveTab();
                        } catch (err: any) {
                          showToast('error', err.message);
                        }
                      }}
                      className="flex-1 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold"
                    >
                      2. Submit Transfer Request
                    </button>
                  </div>

                  {transferPreview && (
                    <div className="p-3.5 rounded-lg bg-indigo-50 border border-indigo-200 space-y-1.5">
                      <div className="font-bold text-indigo-900">Transfer Verification Preview</div>
                      <div>Student: <strong>{transferPreview.student_name}</strong></div>
                      <div>Permanent UUID (Unchanged): <code className="font-mono text-[11px]">{transferPreview.permanent_student_id}</code></div>
                      <div>Old USN: <code className="font-mono font-bold">{transferPreview.old_usn}</code> → Proposed New USN: <code className="font-mono font-bold text-emerald-700">{transferPreview.proposed_new_usn_preview}</code></div>
                      <div>Route: {transferPreview.source_campus.code} → {transferPreview.destination_campus.code}</div>
                      <div className="text-[11px] text-slate-600">{transferPreview.policy_notes}</div>
                    </div>
                  )}
                </div>

                <div className="lg:col-span-2 bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
                  <div className="p-4 border-b border-slate-200">
                    <h3 className="text-sm font-bold">Inter-Campus Transfer Requests & Audit Trail</h3>
                    <p className="text-xs text-slate-500">Approving a transfer commits enrollment migration, identifier history, and hostel bed release in one atomic transaction</p>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left border-collapse text-xs">
                      <thead>
                        <tr className="bg-slate-100 text-slate-600 border-b border-slate-200">
                          <th className="py-2.5 px-3">Student & Permanent ID</th>
                          <th className="py-2.5 px-3">Source → Destination</th>
                          <th className="py-2.5 px-3">Old USN → New USN</th>
                          <th className="py-2.5 px-3">Status</th>
                          <th className="py-2.5 px-3">Action</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-200">
                        {transfersList.map((tr: any) => (
                          <tr key={tr.id} className="hover:bg-slate-50">
                            <td className="py-2.5 px-3">
                              <div className="font-bold">{tr.student_name}</div>
                              <div className="font-mono text-[10px] text-slate-500">{tr.student_id}</div>
                            </td>
                            <td className="py-2.5 px-3">{tr.source_campus_code} → {tr.destination_campus_code}</td>
                            <td className="py-2.5 px-3 font-mono">
                              <span className="text-slate-500">{tr.source_usn}</span> → <strong className="text-indigo-700">{tr.proposed_destination_usn}</strong>
                            </td>
                            <td className="py-2.5 px-3">
                              <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                                tr.status === 'COMPLETED' ? 'bg-emerald-100 text-emerald-800' :
                                tr.status === 'PENDING' ? 'bg-amber-100 text-amber-800' : 'bg-rose-100 text-rose-800'
                              }`}>
                                {tr.status}
                              </span>
                            </td>
                            <td className="py-2.5 px-3">
                              {tr.status === 'PENDING' && (
                                <button
                                  onClick={async () => {
                                    try {
                                      const res = await apiFetch(`/transfers/${tr.id}/approve`, {
                                        method: 'POST',
                                        body: JSON.stringify({ decision: 'APPROVED', comments: 'Verified & committed' }),
                                      });
                                      showToast('success', `Transfer Committed! New USN: ${res.new_usn} (Permanent ID preserved)`);
                                      refreshActiveTab();
                                    } catch (err: any) {
                                      showToast('error', err.message);
                                    }
                                  }}
                                  className="px-2.5 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-semibold"
                                >
                                  Approve & Commit Transfer
                                </button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* =============================================================== */}
          {/* VIEW 5: FEE MANAGEMENT, TWO-LEVEL VERIFICATION & RECEIPTS       */}
          {/* =============================================================== */}
          {activeTab === 'FEES' && (
            <div className="space-y-6">
              <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex flex-wrap items-center justify-between gap-4 text-xs">
                <div>
                  <div className="font-bold text-sm text-slate-900">Ledger Formula & Two-Level Payment Verification</div>
                  <div className="text-slate-600 mt-0.5">
                    <code>Outstanding = Assessed + Adjustments − Approved Concessions − Scholarships − (Posted Payments − Completed Refunds)</code>
                  </div>
                </div>
                <input
                  value={studentSearch}
                  onChange={(e) => setStudentSearch(e.target.value)}
                  placeholder="Filter by USN or Student Name..."
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
                />
              </div>

              {paymentModalAss && (
                <form
                  onSubmit={async (e) => {
                    e.preventDefault();
                    try {
                      await apiFetch('/fees/payments', {
                        method: 'POST',
                        body: JSON.stringify({
                          assessment_id: paymentModalAss.id,
                          amount: Number(paymentForm.amount),
                          transaction_ref: paymentForm.transaction_ref || `TXN-SIM-${Date.now()}`,
                          payment_mode: paymentForm.payment_mode,
                        }),
                      });
                      showToast('success', 'Simulated payment recorded in PENDING_COLLEGE_VERIFICATION state');
                      setPaymentModalAss(null);
                      refreshActiveTab();
                    } catch (err: any) {
                      showToast('error', err.message);
                    }
                  }}
                  className="bg-indigo-50 p-4 rounded-xl border border-indigo-300 flex flex-wrap items-end gap-3 text-xs"
                >
                  <div>
                    <div className="font-bold text-indigo-900">Record Simulated Payment for {paymentModalAss.student_name} ({paymentModalAss.current_usn})</div>
                    <div className="text-indigo-700">Current Outstanding: {formatINR(paymentModalAss.outstanding_balance)}</div>
                  </div>
                  <div>
                    <label className="block font-medium mb-1">Amount (INR)</label>
                    <input
                      type="number"
                      required
                      value={paymentForm.amount}
                      onChange={(e) => setPaymentForm({ ...paymentForm, amount: Number(e.target.value) })}
                      className="rounded border border-slate-300 px-2.5 py-1.5 bg-white"
                    />
                  </div>
                  <div>
                    <label className="block font-medium mb-1">Unique Transaction Reference</label>
                    <input
                      required
                      value={paymentForm.transaction_ref}
                      onChange={(e) => setPaymentForm({ ...paymentForm, transaction_ref: e.target.value })}
                      className="rounded border border-slate-300 px-2.5 py-1.5 bg-white font-mono"
                      placeholder="TXN-UPI-998877"
                    />
                  </div>
                  <button type="submit" className="px-4 py-1.5 rounded bg-indigo-600 text-white font-semibold">Submit Payment</button>
                  <button type="button" onClick={() => setPaymentModalAss(null)} className="px-3 py-1.5 rounded bg-slate-200">Cancel</button>
                </form>
              )}

              {/* Student Fee Assessments Table */}
              <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
                <div className="p-4 border-b border-slate-200">
                  <h3 className="text-sm font-bold">Student Fee Assessments & Balances</h3>
                </div>
                <div className="overflow-x-auto max-h-80">
                  <table className="w-full text-left border-collapse text-xs">
                    <thead>
                      <tr className="bg-slate-100 text-slate-600 border-b border-slate-200">
                        <th className="py-2 px-3">USN & Student</th>
                        <th className="py-2 px-3 text-right">Assessed</th>
                        <th className="py-2 px-3 text-right">Concessions + Scholarships</th>
                        <th className="py-2 px-3 text-right">Net Posted Paid</th>
                        <th className="py-2 px-3 text-right">Refunded</th>
                        <th className="py-2 px-3 text-right">Outstanding</th>
                        <th className="py-2 px-3">Status</th>
                        {(role === 'TRUST_MANAGEMENT' || role === 'COLLEGE_ADMIN') && <th className="py-2 px-3">Actions</th>}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200">
                      {feesData.assessments.map((fa: any) => (
                        <tr key={fa.id} className="hover:bg-slate-50">
                          <td className="py-2 px-3">
                            <div className="font-bold text-indigo-700 font-mono">{fa.current_usn}</div>
                            <div>{fa.student_name}</div>
                          </td>
                          <td className="py-2 px-3 text-right font-mono">{formatINR(fa.assessed_amount)}</td>
                          <td className="py-2 px-3 text-right font-mono text-amber-700">
                            {formatINR(Number(fa.concession_amount) + Number(fa.scholarship_amount))}
                          </td>
                          <td className="py-2 px-3 text-right font-mono text-emerald-700 font-semibold">{formatINR(fa.net_posted_payments)}</td>
                          <td className="py-2 px-3 text-right font-mono">{formatINR(fa.refunded_amount)}</td>
                          <td className="py-2 px-3 text-right font-mono font-bold text-rose-600">{formatINR(fa.outstanding_balance)}</td>
                          <td className="py-2 px-3">
                            <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                              fa.status === 'PAID' ? 'bg-emerald-100 text-emerald-800' :
                              fa.status === 'PARTIAL' ? 'bg-amber-100 text-amber-800' : 'bg-rose-100 text-rose-800'
                            }`}>
                              {fa.status}
                            </span>
                          </td>
                          {(role === 'TRUST_MANAGEMENT' || role === 'COLLEGE_ADMIN') && (
                            <td className="py-2 px-3 space-x-1.5">
                              <button
                                onClick={() => {
                                  setPaymentModalAss(fa);
                                  setPaymentForm({ amount: Math.max(1000, Number(fa.outstanding_balance)), transaction_ref: `TXN-SIM-${Math.floor(Math.random() * 900000 + 100000)}`, payment_mode: 'UPI_SIMULATED' });
                                }}
                                className="px-2 py-1 rounded bg-indigo-600 text-white text-[10px] font-semibold"
                              >
                                + Payment
                              </button>
                              <button
                                onClick={async () => {
                                  try {
                                    await apiFetch(`/fees/send-reminder/${fa.id}`, { method: 'POST' });
                                    showToast('success', 'Verified fee balance reminder sent to parent');
                                  } catch (err: any) {
                                    showToast('error', err.message);
                                  }
                                }}
                                className="px-2 py-1 rounded bg-slate-700 text-white text-[10px] font-semibold"
                              >
                                Send Reminder
                              </button>
                            </td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Immutable Receipts & Two-Level Verification Queue */}
              <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
                <div className="p-4 border-b border-slate-200">
                  <h3 className="text-sm font-bold">Two-Level Payment Verification & Immutable Receipt Ledger</h3>
                  <p className="text-xs text-slate-500">Once POSTED, database triggers forbid deleting or altering the transaction; corrections require linked Refunds or Reversals</p>
                </div>
                <div className="overflow-x-auto max-h-80">
                  <table className="w-full text-left border-collapse text-xs">
                    <thead>
                      <tr className="bg-slate-100 text-slate-600 border-b border-slate-200">
                        <th className="py-2 px-3">Transaction Ref</th>
                        <th className="py-2 px-3">Immutable Receipt #</th>
                        <th className="py-2 px-3">Student</th>
                        <th className="py-2 px-3 text-right">Amount</th>
                        <th className="py-2 px-3">Verification State</th>
                        {(role === 'TRUST_MANAGEMENT' || role === 'COLLEGE_ADMIN') && <th className="py-2 px-3">Workflow Action</th>}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200">
                      {feesData.recent_payments.map((p: any) => (
                        <tr key={p.id} className="hover:bg-slate-50">
                          <td className="py-2 px-3 font-mono font-semibold">{p.transaction_ref}</td>
                          <td className="py-2 px-3 font-mono text-indigo-700 font-bold">{p.receipt_number || 'UNPOSTED'}</td>
                          <td className="py-2 px-3">{p.student_name} ({p.current_usn})</td>
                          <td className="py-2 px-3 text-right font-mono font-bold">{formatINR(p.amount)}</td>
                          <td className="py-2 px-3">
                            <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                              p.status === 'POSTED' ? 'bg-emerald-100 text-emerald-800' :
                              p.status === 'REVERSED' ? 'bg-rose-100 text-rose-800' : 'bg-amber-100 text-amber-800'
                            }`}>
                              {p.status} (SYNTHETIC)
                            </span>
                          </td>
                          {(role === 'TRUST_MANAGEMENT' || role === 'COLLEGE_ADMIN') && (
                            <td className="py-2 px-3 space-x-1.5">
                              {p.status === 'PENDING_COLLEGE_VERIFICATION' && (
                                <button
                                  onClick={async () => {
                                    await apiFetch(`/fees/payments/${p.id}/verify-college`, { method: 'POST' });
                                    showToast('success', 'Level 1 College Verification complete');
                                    refreshActiveTab();
                                  }}
                                  className="px-2 py-1 rounded bg-amber-600 text-white text-[10px] font-semibold"
                                >
                                  1. College Verify
                                </button>
                              )}
                              {(p.status === 'COLLEGE_VERIFIED' || p.status === 'PENDING_COLLEGE_VERIFICATION') && (
                                <button
                                  onClick={async () => {
                                    const res = await apiFetch(`/fees/payments/${p.id}/verify-trust`, { method: 'POST' });
                                    showToast('success', `Level 2 Posted! Receipt: ${res.payment.receipt_number}`);
                                    refreshActiveTab();
                                  }}
                                  className="px-2 py-1 rounded bg-emerald-600 text-white text-[10px] font-semibold"
                                >
                                  2. Trust Reconcile & Post
                                </button>
                              )}
                              {p.status === 'POSTED' && (
                                <button
                                  onClick={async () => {
                                    await apiFetch('/fees/refunds-reversals', {
                                      method: 'POST',
                                      body: JSON.stringify({
                                        payment_id: p.id,
                                        action_type: 'REFUND',
                                        amount: Math.min(2000, Number(p.amount)),
                                        reason: 'Audited partial fee refund',
                                      }),
                                    });
                                    showToast('success', 'Linked refund recorded & balance recalculated');
                                    refreshActiveTab();
                                  }}
                                  className="px-2 py-1 rounded bg-slate-200 hover:bg-slate-300 text-slate-800 text-[10px] font-semibold"
                                >
                                  Issue Refund
                                </button>
                              )}
                            </td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* =============================================================== */}
          {/* VIEW 6: HOSTEL MANAGEMENT FOR WARDENS (Visual Seat/Bed Map)     */}
          {/* =============================================================== */}
          {activeTab === 'HOSTEL' && (
            <div className="space-y-6">
              {/* Summary Strip */}
              <div className="grid grid-cols-2 sm:grid-cols-6 gap-3 text-xs">
                <div className="bg-white p-3.5 rounded-xl border border-slate-200">
                  <div className="text-slate-500">Hostel Blocks / Rooms</div>
                  <div className="text-lg font-bold mt-1">{hostelData.summary.total_hostels} Blocks / {hostelData.summary.total_rooms} Rooms</div>
                </div>
                <div className="bg-white p-3.5 rounded-xl border border-slate-200">
                  <div className="text-slate-500">Total Individual Beds</div>
                  <div className="text-lg font-bold mt-1">{hostelData.summary.total_beds} Beds</div>
                </div>
                <div className="bg-emerald-50 p-3.5 rounded-xl border border-emerald-300">
                  <div className="text-emerald-800 font-semibold">Available (Green)</div>
                  <div className="text-lg font-bold text-emerald-700 mt-1">{hostelData.summary.available_beds} Beds</div>
                </div>
                <div className="bg-rose-50 p-3.5 rounded-xl border border-rose-300">
                  <div className="text-rose-800 font-semibold">Occupied (Red)</div>
                  <div className="text-lg font-bold text-rose-700 mt-1">{hostelData.summary.occupied_beds} Beds</div>
                </div>
                <div className="bg-amber-50 p-3.5 rounded-xl border border-amber-300">
                  <div className="text-amber-800 font-semibold">Reserved (Amber)</div>
                  <div className="text-lg font-bold text-amber-700 mt-1">{hostelData.summary.reserved_beds} Beds</div>
                </div>
                <div className="bg-slate-100 p-3.5 rounded-xl border border-slate-300">
                  <div className="text-slate-700 font-semibold">Out of Service (Grey)</div>
                  <div className="text-lg font-bold text-slate-700 mt-1">{hostelData.summary.out_of_service_beds} Beds</div>
                </div>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Interactive Vacancy Chart (Bus/Train Seat Map Style) */}
                <div className="lg:col-span-2 bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-3">
                    <div>
                      <h3 className="text-sm font-bold">Interactive Room & Individual Bed Vacancy Map</h3>
                      <p className="text-xs text-slate-500">Select any bed to inspect occupant or allocate/release with row-level lock protection</p>
                    </div>
                    <div className="flex items-center gap-3 text-[11px] font-semibold">
                      <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-emerald-500 inline-block"></span> [AVAIL] Available</span>
                      <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-rose-500 inline-block"></span> [OCC] Occupied</span>
                      <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-amber-500 inline-block"></span> [RES] Reserved</span>
                      <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-slate-400 inline-block"></span> [OOS] Unavailable</span>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 gap-2.5 max-h-[420px] overflow-y-auto p-1">
                    {hostelData.beds.map((bed: any) => {
                      const badgeMap: Record<string, { cls: string; tag: string }> = {
                        AVAILABLE: { cls: 'bg-emerald-50 border-emerald-400 text-emerald-900 hover:bg-emerald-100', tag: 'AVAIL' },
                        OCCUPIED: { cls: 'bg-rose-50 border-rose-400 text-rose-900 hover:bg-rose-100', tag: 'OCC' },
                        RESERVED: { cls: 'bg-amber-50 border-amber-400 text-amber-900 hover:bg-amber-100', tag: 'RES' },
                        OUT_OF_SERVICE: { cls: 'bg-slate-200 border-slate-400 text-slate-600', tag: 'OOS' },
                      };
                      const st = badgeMap[bed.status] || badgeMap.AVAILABLE;
                      return (
                        <button
                          key={bed.bed_id}
                          onClick={() => setSelectedBed(bed)}
                          className={`p-2.5 rounded-lg border-2 text-left transition flex flex-col justify-between ${st.cls} ${selectedBed?.bed_id === bed.bed_id ? 'ring-2 ring-indigo-600' : ''}`}
                        >
                          <div className="flex items-center justify-between w-full">
                            <span className="font-mono font-bold text-xs">{bed.bed_code}</span>
                            <span className="text-[9px] font-extrabold px-1 rounded bg-white/80">{st.tag}</span>
                          </div>
                          <div className="text-[10px] truncate mt-1.5 font-medium">
                            {bed.occupant_usn || bed.building_code}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Bed Action Panel */}
                <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-4 text-xs">
                  <div className="font-bold text-sm text-slate-900">Warden Bed Allocation Desk</div>
                  {selectedBed ? (
                    <div className="space-y-3">
                      <div className="p-3 rounded-lg bg-slate-50 border border-slate-200 space-y-1">
                        <div>Bed Code: <strong className="font-mono text-sm">{selectedBed.bed_code}</strong> ({selectedBed.building_name})</div>
                        <div>Room: {selectedBed.room_number} (Floor {selectedBed.floor_number})</div>
                        <div>Current Status: <span className="font-bold">{selectedBed.status}</span></div>
                        {selectedBed.occupant_name && (
                          <div>Occupant: <strong>{selectedBed.occupant_name}</strong> ({selectedBed.occupant_usn})</div>
                        )}
                      </div>

                      {selectedBed.status === 'AVAILABLE' && (role === 'HOSTEL_WARDEN' || role === 'COLLEGE_ADMIN' || role === 'TRUST_MANAGEMENT') && (
                        <div className="space-y-2">
                          <label className="block font-semibold text-slate-700">Enter Verified Student USN to Allocate</label>
                          <input
                            value={allocUsn}
                            onChange={(e) => setAllocUsn(e.target.value)}
                            className="w-full rounded border border-slate-300 px-3 py-1.5 font-mono"
                            placeholder="e.g. 1VV26EC0002"
                          />
                          <button
                            onClick={async () => {
                              try {
                                await apiFetch('/hostels/allocate', {
                                  method: 'POST',
                                  body: JSON.stringify({
                                    usn: allocUsn,
                                    bed_id: selectedBed.bed_id,
                                    allocation_type: 'ACTIVE',
                                  }),
                                });
                                showToast('success', `Allocated Bed ${selectedBed.bed_code} to ${allocUsn}`);
                                setSelectedBed(null);
                                refreshActiveTab();
                              } catch (err: any) {
                                showToast('error', err.message);
                              }
                            }}
                            className="w-full py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold"
                          >
                            Confirm Transactional Bed Allocation
                          </button>
                        </div>
                      )}

                      {(selectedBed.status === 'OCCUPIED' || selectedBed.status === 'RESERVED') && selectedBed.active_allocation_id && (
                        <button
                          onClick={async () => {
                            try {
                              await apiFetch('/hostels/release', {
                                method: 'POST',
                                body: JSON.stringify({
                                  allocation_id: selectedBed.active_allocation_id,
                                  reason: 'Warden authorized bed release',
                                }),
                              });
                              showToast('success', `Released Bed ${selectedBed.bed_code}`);
                              setSelectedBed(null);
                              refreshActiveTab();
                            } catch (err: any) {
                              showToast('error', err.message);
                            }
                          }}
                          className="w-full py-2 rounded-lg bg-rose-600 hover:bg-rose-500 text-white font-semibold"
                        >
                          Release Bed & Mark Available
                        </button>
                      )}
                    </div>
                  ) : (
                    <div className="p-6 text-center text-slate-400 border border-dashed border-slate-200 rounded-lg">
                      Click any bed tile on the vacancy chart to allocate or release.
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* =============================================================== */}
          {/* VIEW 7: ATTENDANCE, ELIGIBILITY & EXAMINATION RESULTS           */}
          {/* =============================================================== */}
          {activeTab === 'ATTENDANCE' && (
            <div className="space-y-6">
              <div className="p-3.5 rounded-xl bg-amber-50 border border-amber-300 text-xs text-amber-900 flex items-center justify-between">
                <span><strong>Institutional Policy Notice:</strong> {attendanceData.policy_disclaimer}</span>
                <span className="font-bold">Below Threshold: {attendanceData.summary?.below_threshold_percentage ?? 0}%</span>
              </div>

              {selectedStudentDetail?.examination_results?.length > 0 && (
                <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                  <h3 className="text-sm font-bold mb-1">
                    Student Academic Progress & Examination Results ({selectedStudentDetail.student.full_name} — {selectedStudentDetail.student.current_usn})
                  </h3>
                  <p className="text-xs text-slate-500 mb-4">Synthetic demonstration examination marks across subjects and terms</p>
                  <div className="h-56">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={selectedStudentDetail.examination_results}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="exam_term" tick={{ fontSize: 11 }} />
                        <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
                        <Tooltip />
                        <Bar dataKey="marks_obtained" name="Marks Obtained (out of 100)" fill="#4f46e5" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}

              <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
                <div className="p-4 border-b border-slate-200 flex items-center justify-between">
                  <h3 className="text-sm font-bold">Student Attendance & Policy Eligibility Register</h3>
                  {(role === 'TRUST_MANAGEMENT' || role === 'COLLEGE_ADMIN') && (
                    <a
                      href={`${API_BASE}/attendance/export-csv`}
                      target="_blank"
                      rel="noreferrer"
                      className="px-3 py-1.5 rounded bg-slate-900 text-white text-xs font-semibold"
                    >
                      Export CSV
                    </a>
                  )}
                </div>
                <div className="overflow-x-auto max-h-96">
                  <table className="w-full text-left border-collapse text-xs">
                    <thead>
                      <tr className="bg-slate-100 text-slate-600 border-b border-slate-200">
                        <th className="py-2 px-3">USN</th>
                        <th className="py-2 px-3">Student Name</th>
                        <th className="py-2 px-3">Campus & Course</th>
                        <th className="py-2 px-3 text-right">Attended / Held</th>
                        <th className="py-2 px-3 text-right">Attendance %</th>
                        <th className="py-2 px-3 text-right">Campus Policy Threshold</th>
                        <th className="py-2 px-3">Eligibility Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200">
                      {attendanceData.records.map((r: any) => (
                        <tr key={r.id} className="hover:bg-slate-50">
                          <td className="py-2 px-3 font-mono font-bold text-indigo-700">{r.current_usn}</td>
                          <td className="py-2 px-3 font-medium">{r.student_name}</td>
                          <td className="py-2 px-3">{r.campus_code} • {r.course_code}</td>
                          <td className="py-2 px-3 text-right font-mono">{r.total_classes_attended} / {r.total_classes_held}</td>
                          <td className="py-2 px-3 text-right font-mono font-bold">{r.attendance_percentage ?? 'NO_DATA'}%</td>
                          <td className="py-2 px-3 text-right font-mono">{r.applicable_threshold_pct}%</td>
                          <td className="py-2 px-3">
                            <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                              r.eligibility_status === 'ELIGIBLE' ? 'bg-emerald-100 text-emerald-800' :
                              r.eligibility_status === 'AT_RISK' ? 'bg-amber-100 text-amber-800' : 'bg-rose-100 text-rose-800'
                            }`}>
                              {r.eligibility_status}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* =============================================================== */}
          {/* VIEW 8: SCHOLARSHIPS & GOVERNMENT REIMBURSEMENTS                */}
          {/* =============================================================== */}
          {activeTab === 'SCHOLARSHIPS' && (
            <div className="space-y-6">
              <div className="p-3.5 rounded-xl bg-indigo-50 border border-indigo-200 text-xs text-indigo-900 flex items-center justify-between">
                <span>{reimbursementsData.simulation_notice}</span>
                <input
                  value={studentSearch}
                  onChange={(e) => setStudentSearch(e.target.value)}
                  placeholder="Search Student by USN..."
                  className="rounded border border-indigo-300 bg-white px-3 py-1 text-xs"
                />
              </div>

              <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
                <div className="p-4 border-b border-slate-200">
                  <h3 className="text-sm font-bold">Unified Government Scholarship & Reimbursement Claims</h3>
                </div>
                <div className="overflow-x-auto max-h-96">
                  <table className="w-full text-left border-collapse text-xs">
                    <thead>
                      <tr className="bg-slate-100 text-slate-600 border-b border-slate-200">
                        <th className="py-2 px-3">Claim Ref</th>
                        <th className="py-2 px-3">USN & Student</th>
                        <th className="py-2 px-3">Scheme</th>
                        <th className="py-2 px-3 text-right">Sanctioned</th>
                        <th className="py-2 px-3 text-right">Disbursed</th>
                        <th className="py-2 px-3 text-right">Pending Govt Dues</th>
                        <th className="py-2 px-3">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200">
                      {reimbursementsData.claims.map((c: any) => (
                        <tr key={c.id} className="hover:bg-slate-50">
                          <td className="py-2 px-3 font-mono font-semibold">{c.claim_reference}</td>
                          <td className="py-2 px-3">
                            <div className="font-mono font-bold text-indigo-700">{c.current_usn}</div>
                            <div>{c.student_name} ({c.category})</div>
                          </td>
                          <td className="py-2 px-3">{c.scheme_code} ({c.sponsoring_agency})</td>
                          <td className="py-2 px-3 text-right font-mono">{formatINR(c.sanctioned_amount)}</td>
                          <td className="py-2 px-3 text-right font-mono text-emerald-700 font-semibold">{formatINR(c.disbursed_amount)}</td>
                          <td className="py-2 px-3 text-right font-mono text-rose-600 font-bold">{formatINR(c.pending_amount)}</td>
                          <td className="py-2 px-3">
                            <span className="px-2 py-0.5 rounded bg-slate-100 font-semibold text-[10px]">{c.claim_status} (SIMULATED)</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* =============================================================== */}
          {/* VIEW 9: MULTI-DATASET IMPORT & RECONCILIATION PIPELINE          */}
          {/* =============================================================== */}
          {activeTab === 'IMPORTS' && (
            <div className="space-y-6">
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-3 text-xs">
                  <h3 className="text-sm font-bold flex items-center gap-2">
                    <UploadCloud className="w-4 h-4 text-indigo-600" />
                    Profile & Import Disconnected Campus Dataset
                  </h3>
                  <p className="text-slate-500">
                    Supports CSV, XLSX, JSON, and safe regex-parsed SQL dumps. Re-importing the same file is idempotent and never duplicates records.
                  </p>
                  <div>
                    <label className="block font-medium mb-1">Target Module</label>
                    <select
                      value={selectedImportModule}
                      onChange={(e) => setSelectedImportModule(e.target.value)}
                      className="w-full rounded border border-slate-300 px-2.5 py-1.5"
                    >
                      <option value="ADMISSIONS">ADMISSIONS</option>
                      <option value="STUDENTS">STUDENTS</option>
                      <option value="FEES">FEES</option>
                      <option value="ATTENDANCE">ATTENDANCE</option>
                      <option value="HOSTEL">HOSTEL</option>
                      <option value="SCHOLARSHIPS">SCHOLARSHIPS</option>
                    </select>
                  </div>
                  <div>
                    <label className="block font-medium mb-1">Select Imperfect Raw Source Dataset (`data/raw_sources/`)</label>
                    <select
                      value={selectedRawFile}
                      onChange={(e) => setSelectedRawFile(e.target.value)}
                      className="w-full rounded border border-slate-300 px-2.5 py-1.5 font-mono"
                    >
                      {importsMeta.raw_source_files.map((f: any) => (
                        <option key={f.filename} value={f.filename}>{f.filename} ({f.size_bytes} B)</option>
                      ))}
                    </select>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={async () => {
                        const fd = new FormData();
                        fd.append('target_module', selectedImportModule);
                        fd.append('sample_filename', selectedRawFile);
                        const res = await apiFetch('/imports/profile', { method: 'POST', body: fd });
                        setProfileResult(res);
                        showToast('success', `Profiled ${res.filename}: ${res.total_rows} rows`);
                      }}
                      className="flex-1 py-2 rounded bg-slate-800 text-white font-semibold"
                    >
                      1. Profile & Map Columns
                    </button>
                    <button
                      onClick={async () => {
                        const fd = new FormData();
                        fd.append('target_module', selectedImportModule);
                        fd.append('sample_filename', selectedRawFile);
                        const res = await apiFetch('/imports/execute', { method: 'POST', body: fd });
                        showToast(
                          'success',
                          `Import Complete! Accepted: ${res.import.accepted_rows}, Skipped Duplicates: ${res.import.skipped_duplicate_rows}, Reconciled: ${res.import.reconciled_rows}`
                        );
                        refreshActiveTab();
                      }}
                      className="flex-1 py-2 rounded bg-indigo-600 text-white font-semibold"
                    >
                      2. Run Validated Import
                    </button>
                  </div>
                </div>

                <div className="lg:col-span-2 bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-3 text-xs">
                  <h3 className="text-sm font-bold">Dataset Profiler & Automatic Column Mapping Preview</h3>
                  {profileResult ? (
                    <div className="space-y-3">
                      <div className="grid grid-cols-4 gap-2 text-center">
                        <div className="p-2 rounded bg-slate-100">
                          <div className="text-slate-500">Format</div>
                          <div className="font-bold">{profileResult.file_format}</div>
                        </div>
                        <div className="p-2 rounded bg-slate-100">
                          <div className="text-slate-500">Total Rows</div>
                          <div className="font-bold">{profileResult.total_rows}</div>
                        </div>
                        <div className="p-2 rounded bg-slate-100">
                          <div className="text-slate-500">Detected Columns</div>
                          <div className="font-bold">{profileResult.columns.length}</div>
                        </div>
                        <div className="p-2 rounded bg-amber-50">
                          <div className="text-amber-700">Columns w/ Missing Values</div>
                          <div className="font-bold text-amber-800">{Object.keys(profileResult.missing_values_by_column || {}).length}</div>
                        </div>
                      </div>
                      <div className="p-3 rounded bg-indigo-50 border border-indigo-200">
                        <div className="font-bold text-indigo-900 mb-1">Auto-Detected Source Column → Canonical Schema Mapping</div>
                        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                          {Object.entries(profileResult.suggested_mapping || {}).map(([srcCol, destCol]: any) => (
                            <div key={srcCol} className="bg-white px-2 py-1 rounded border border-indigo-200 font-mono text-[11px]">
                              {srcCol} → <strong className="text-indigo-700">{destCol}</strong>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="p-8 text-center text-slate-400 border border-dashed rounded-lg">
                      Select a raw source dataset and click "1. Profile & Map Columns" to inspect metadata, missing values, and schema mapping.
                    </div>
                  )}
                </div>
              </div>

              {/* Import Run History */}
              <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
                <div className="p-4 border-b border-slate-200">
                  <h3 className="text-sm font-bold">Idempotent Dataset Import History</h3>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse text-xs">
                    <thead>
                      <tr className="bg-slate-100 text-slate-600 border-b border-slate-200">
                        <th className="py-2 px-3">Filename</th>
                        <th className="py-2 px-3">Format / Module</th>
                        <th className="py-2 px-3 text-right">Total</th>
                        <th className="py-2 px-3 text-right">Accepted</th>
                        <th className="py-2 px-3 text-right">Skipped (Idempotent)</th>
                        <th className="py-2 px-3 text-right">Reconciled</th>
                        <th className="py-2 px-3 text-right">Rejected</th>
                        <th className="py-2 px-3">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200">
                      {importsMeta.import_history.map((imp: any) => (
                        <tr key={imp.id}>
                          <td className="py-2 px-3 font-mono font-semibold">{imp.filename}</td>
                          <td className="py-2 px-3">{imp.file_format} • {imp.target_module}</td>
                          <td className="py-2 px-3 text-right font-mono">{imp.total_rows}</td>
                          <td className="py-2 px-3 text-right font-mono text-emerald-700 font-bold">{imp.accepted_rows}</td>
                          <td className="py-2 px-3 text-right font-mono text-indigo-700 font-bold">{imp.skipped_duplicate_rows}</td>
                          <td className="py-2 px-3 text-right font-mono text-amber-700">{imp.reconciled_rows}</td>
                          <td className="py-2 px-3 text-right font-mono text-rose-600">{imp.rejected_rows}</td>
                          <td className="py-2 px-3 font-bold text-emerald-700">{imp.status}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* =============================================================== */}
          {/* VIEW 10: CAMPUS POLICY RULE ENGINE                              */}
          {/* =============================================================== */}
          {activeTab === 'POLICIES' && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {policiesList.map((pol: any) => (
                <div key={pol.id} className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-3 text-xs">
                  <div className="flex items-center justify-between border-b border-slate-200 pb-2">
                    <div>
                      <div className="font-bold text-sm text-indigo-900">Campus #{pol.campus_number}: {pol.campus_name}</div>
                      <div className="text-slate-500">Active Policy Version v{pol.version}</div>
                    </div>
                    <span className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 font-bold">ACTIVE</span>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-slate-600 mb-1">Attendance Eligibility Threshold (%)</label>
                      <input
                        type="number"
                        defaultValue={pol.attendance_threshold_pct}
                        onBlur={async (e) => {
                          try {
                            await apiFetch('/policies', {
                              method: 'PUT',
                              body: JSON.stringify({
                                campus_id: pol.campus_id,
                                attendance_threshold_pct: Number(e.target.value),
                                warning_threshold_pct: Number(pol.warning_threshold_pct),
                                late_fee_per_day: Number(pol.late_fee_per_day),
                                grace_period_days: Number(pol.grace_period_days),
                                max_concession_pct: Number(pol.max_concession_pct),
                                transfer_min_attendance_pct: Number(pol.transfer_min_attendance_pct),
                                require_zero_dues_for_transfer: Boolean(pol.require_zero_dues_for_transfer),
                              }),
                            });
                            showToast('success', `Updated ${pol.campus_code} policy to new version & recalculated campus eligibility`);
                            refreshActiveTab();
                          } catch (err: any) {
                            showToast('error', err.message);
                          }
                        }}
                        className="w-full rounded border border-slate-300 px-2.5 py-1.5 font-bold"
                      />
                    </div>
                    <div>
                      <label className="block text-slate-600 mb-1">Late Fee / Day (INR)</label>
                      <input
                        type="number"
                        readOnly
                        value={pol.late_fee_per_day}
                        className="w-full rounded border border-slate-200 bg-slate-50 px-2.5 py-1.5"
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* =============================================================== */}
          {/* VIEW 11: ACCOUNT & REGISTRATION APPROVALS                       */}
          {/* =============================================================== */}
          {activeTab === 'ACCOUNTS' && (
            <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
              <div className="p-4 border-b border-slate-200">
                <h3 className="text-sm font-bold">Pending Registration Requests & Role Provisioning</h3>
                <p className="text-xs text-slate-500">Approving a request generates a role-prefixed User ID (M..., A..., S..., P..., W...) from the database sequence</p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="bg-slate-100 text-slate-600 border-b border-slate-200">
                      <th className="py-2.5 px-3">Applicant</th>
                      <th className="py-2.5 px-3">Requested Role</th>
                      <th className="py-2.5 px-3">Verification USN</th>
                      <th className="py-2.5 px-3">Status</th>
                      <th className="py-2.5 px-3">Issued User ID</th>
                      <th className="py-2.5 px-3">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200">
                    {regRequestsList.map((r: any) => (
                      <tr key={r.id}>
                        <td className="py-2.5 px-3 font-medium">{r.full_name} ({r.email})</td>
                        <td className="py-2.5 px-3 font-bold">{r.requested_role}</td>
                        <td className="py-2.5 px-3 font-mono">{r.verification_usn || '—'}</td>
                        <td className="py-2.5 px-3 font-bold">{r.status}</td>
                        <td className="py-2.5 px-3 font-mono text-indigo-700 font-bold">{r.generated_user_id || 'Pending'}</td>
                        <td className="py-2.5 px-3 space-x-1.5">
                          {r.status === 'PENDING' && (
                            <>
                              <button
                                onClick={async () => {
                                  const res = await apiFetch(`/admin/registration-requests/${r.id}/decide`, {
                                    method: 'POST',
                                    body: JSON.stringify({ decision: 'APPROVED', review_notes: 'Verified institutional link' }),
                                  });
                                  showToast('success', `Approved! Issued User ID: ${res.generated_user_id}`);
                                  refreshActiveTab();
                                }}
                                className="px-2.5 py-1 rounded bg-emerald-600 text-white font-semibold"
                              >
                                Approve & Issue ID
                              </button>
                              <button
                                onClick={async () => {
                                  await apiFetch(`/admin/registration-requests/${r.id}/decide`, {
                                    method: 'POST',
                                    body: JSON.stringify({ decision: 'REJECTED', review_notes: 'Unverified' }),
                                  });
                                  refreshActiveTab();
                                }}
                                className="px-2.5 py-1 rounded bg-rose-600 text-white font-semibold"
                              >
                                Reject
                              </button>
                            </>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* =============================================================== */}
          {/* VIEW 12: DPDP ACT 2023 PRIVACY & COMPLIANCE CENTRE              */}
          {/* =============================================================== */}
          {activeTab === 'PRIVACY' && privacyData && (
            <div className="space-y-6 text-xs">
              <div className="p-4 rounded-xl bg-slate-900 text-slate-100 space-y-1">
                <div className="font-bold text-sm text-indigo-300">DPDP Act, 2023 & DPDP Rules, 2025 — Engineering Controls</div>
                <p className="text-slate-300">{privacyData.legal_disclaimer}</p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-3">
                  <h3 className="text-sm font-bold">Statutory & Institutional Retention Policies</h3>
                  {privacyData.retention_policies.map((rp: any) => (
                    <div key={rp.id} className="p-3 rounded bg-slate-50 border border-slate-200 flex items-center justify-between">
                      <div>
                        <div className="font-bold">{rp.record_category}</div>
                        <div className="text-slate-500">{rp.statutory_basis}</div>
                      </div>
                      <span className="font-mono font-bold text-indigo-700">{rp.retention_years} Years ({rp.disposal_action})</span>
                    </div>
                  ))}
                </div>

                <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-3">
                  <h3 className="text-sm font-bold">Data Principal Requests & Consent Records</h3>
                  {privacyData.data_requests.map((dr: any) => (
                    <div key={dr.id} className="p-3 rounded bg-slate-50 border border-slate-200 space-y-1">
                      <div className="flex justify-between font-bold">
                        <span>{dr.request_type}</span>
                        <span className="text-amber-700">{dr.status}</span>
                      </div>
                      <div>{dr.details}</div>
                      {dr.resolution_notes && <div className="text-slate-500 italic">{dr.resolution_notes}</div>}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* =============================================================== */}
          {/* VIEW 13 & 14: NOTIFICATIONS & TAMPER-EVIDENT AUDIT LOGS         */}
          {/* =============================================================== */}
          {activeTab === 'NOTIFICATIONS' && (
            <div className="bg-white rounded-xl border border-slate-200 shadow-sm divide-y divide-slate-200 text-xs">
              {notificationsList.map((n: any) => (
                <div key={n.id} className="p-4 flex items-start justify-between gap-4">
                  <div>
                    <span className="px-2 py-0.5 rounded bg-indigo-100 text-indigo-800 font-bold text-[10px] mr-2">{n.category}</span>
                    <strong className="text-slate-900">{n.title}</strong>
                    <p className="text-slate-600 mt-1">{n.message}</p>
                  </div>
                  <span className="text-slate-400 shrink-0">{new Date(n.created_at).toLocaleString()}</span>
                </div>
              ))}
            </div>
          )}

          {activeTab === 'AUDIT' && (
            <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
              <div className="p-4 border-b border-slate-200">
                <h3 className="text-sm font-bold">Append-Only Tamper-Evident Security & Financial Audit Log</h3>
                <p className="text-xs text-slate-500">Protected by PostgreSQL trigger <code className="font-mono">trg_protect_audit_logs</code> against modification or deletion</p>
              </div>
              <div className="overflow-x-auto max-h-[500px]">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="bg-slate-100 text-slate-600 border-b border-slate-200">
                      <th className="py-2 px-3">Timestamp</th>
                      <th className="py-2 px-3">Role</th>
                      <th className="py-2 px-3">Action</th>
                      <th className="py-2 px-3">Entity</th>
                      <th className="py-2 px-3">Summary</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200">
                    {auditLogsList.map((al: any) => (
                      <tr key={al.id}>
                        <td className="py-2 px-3 font-mono text-[11px] text-slate-500">{new Date(al.created_at).toLocaleString()}</td>
                        <td className="py-2 px-3 font-semibold">{al.actor_role}</td>
                        <td className="py-2 px-3 font-mono font-bold text-indigo-700">{al.action}</td>
                        <td className="py-2 px-3 font-mono">{al.entity_type}</td>
                        <td className="py-2 px-3">{al.summary}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
