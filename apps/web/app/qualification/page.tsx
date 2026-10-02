'use client';

import { useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, ChevronDown, ChevronUp, FileSearch, GitCompareArrows, LoaderCircle, Play, RefreshCw } from 'lucide-react';

import { loadCaseWorkspace } from '@/lib/case-workspace';
import { ActionCard } from '@/components/copilot/action-card';
import { useActions } from '@/components/copilot/provider';
import { NavigationLink } from '@/components/navigation-link';
import { currentRevalidation, isLocked } from '@/lib/copilot-actions';
import { CaseTabs } from '@/components/product/case-header';
import { ConclusionBox } from '@/components/product/conclusion-box';
import { EvidenceQuote } from '@/components/product/evidence-quote';
import { ANALYSIS_STATUS_COPY, COMPANY_SIZE_LABEL, DROPPED_REASON_LABEL, OVERALL_STATUS_COPY, REQUIREMENT_TYPE_LABEL, analysisBadgeLabel, analysisStatusLabel, diagnosticText, evidenceLocationText, labelOf } from '@/lib/status-copy';
import { QualificationRow, type QualificationRowStatus } from '@/components/product/qualification-row';
import { QualificationSourceOverview } from '@/components/product/qualification-source-overview';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { navigateTo, replaceWith } from '@/lib/navigation';
import {
  getNotice,
  getNoticeVersions,
  listNotices,
  listPreflightCases,
  type BidNoticeDetail,
  type BidNoticeSummary,
  type BidNoticeVersion,
  type PreflightCase,
} from '@/lib/api';
import {
  createPreflightCaseWithCompany,
  getQualificationAnalysis,
  listCompanies,
  listQualificationQuestions,
  runQualificationAnalysis,
  runQualificationJudgment,
  type CanonicalRequirement,
  type CompanyProfile,
  type QualificationAnalysisRun,
  type QualificationAnalysisSummary,
  type QualificationJudgment,
  type QualificationJudgmentRun,
  type QualificationQuestion,
} from '@/lib/qualification-api';

type Busy = 'load' | 'create' | 'review' | null;
type ReviewStep = 'idle' | 'analysis' | 'judgment' | 'done';
const SELECTED_EVIDENCE_SECTION_ID = 'selected-evidence-section';
type RequirementView = {
  requirement: CanonicalRequirement;
  judgment: QualificationJudgment | null;
  status: QualificationRowStatus;
  /* 택일 묶음을 한 줄로 접었을 때, 어느 요건으로 갈렸는지 적는 자리. 묶음이 아니면 null. */
  groupPeerNote: string | null;
  /* 조치(확인하기)는 묶음 안 어느 구성원에 걸려 있을지 모른다. 전부 들고 본다. */
  memberKeys: string[];
  evidenceLabel: string;
};


function judgmentStatus(value: QualificationJudgment | null): QualificationRowStatus {
  return value?.status ?? 'UNJUDGED';
}

/*
  ── 택일(ANY_OF) 그룹 ──────────────────────────────────────────────
  백엔드는 요건 하나하나에 판정을 내려준다. 그런데 「폐기물중간처분업(1257) 또는
  폐기물중간재활용업(6770) 또는 폐기물종합재활용업(6786)」처럼 requirement_group_key를
  공유하고 group_operator가 ANY_OF인 묶음은 하나만 충족해도 그룹 전체가 충족이다.
  이걸 화면이 모르면 1257을 가진 회사가 6770·6786 미보유 때문에 미달로 표시된다.
  요건별 판정을 그대로 합산하지 말고 그룹 단위로 접어서 쓴다.
*/
function anyOfGroupKey(requirement: CanonicalRequirement) {
  return requirement.group_operator === 'ANY_OF' ? requirement.requirement_group_key : null;
}

function resolveRequirementStatuses(
  requirements: CanonicalRequirement[],
  judgments: QualificationJudgment[],
): Map<string, QualificationRowStatus> {
  const statusOf = new Map<string, QualificationRowStatus>(judgments.map((item) => [item.requirement_key, item.status]));
  const resolved = new Map<string, QualificationRowStatus>();
  const groups = new Map<string, CanonicalRequirement[]>();

  for (const requirement of requirements) {
    const groupKey = anyOfGroupKey(requirement);
    if (groupKey) {
      groups.set(groupKey, [...(groups.get(groupKey) ?? []), requirement]);
      continue;
    }
    resolved.set(requirement.requirement_key, statusOf.get(requirement.requirement_key) ?? 'UNJUDGED');
  }

  for (const members of groups.values()) {
    const statuses = members.map((item) => statusOf.get(item.requirement_key) ?? 'UNJUDGED');
    // 하나라도 충족이면 그룹 충족. 아니면 아직 모르는 게 남았는지 보고, 그것도 없을 때만 미달이다.
    const groupStatus: QualificationRowStatus = statuses.includes('SATISFIED')
      ? 'SATISFIED'
      : statuses.includes('UNKNOWN')
        ? 'UNKNOWN'
        : statuses.includes('UNSATISFIED')
          ? 'UNSATISFIED'
          : 'UNJUDGED';
    for (const member of members) resolved.set(member.requirement_key, groupStatus);
  }

  return resolved;
}

/* 결론 카드의 충족·확인 필요·미달 건수. 택일 그룹은 구성원 수만큼이 아니라 한 건으로 센다. */
function countByStatus(requirements: CanonicalRequirement[], statuses: Map<string, QualificationRowStatus>) {
  const counted = new Set<string>();
  const counts: Record<QualificationRowStatus, number> = { SATISFIED: 0, UNSATISFIED: 0, UNKNOWN: 0, UNJUDGED: 0 };
  for (const requirement of requirements) {
    const groupKey = anyOfGroupKey(requirement);
    if (groupKey) {
      if (counted.has(groupKey)) continue;
      counted.add(groupKey);
    }
    counts[statuses.get(requirement.requirement_key) ?? 'UNJUDGED'] += 1;
  }
  return counts;
}

function overallCopy(status: QualificationJudgmentRun['overall_status'] | undefined) {
  const copy = status ? OVERALL_STATUS_COPY[status] : null;
  if (copy) return [copy.label, copy.description];
  return ['검토 전', '검토를 시작하면 공고 원문 분석과 회사 프로필 비교를 순서대로 실행합니다.'];
}

function companyValue(requirement: CanonicalRequirement, company: CompanyProfile | null, judgment: QualificationJudgment | null) {
  if (judgment?.basis_type === 'USER_ANSWER') return '사용자 답변으로 판정 · 회사 프로필에는 반영하지 않음';
  if (!company) return '회사 프로필 없음';
  switch (requirement.type) {
    case 'INDUSTRY': return company.industries.length ? company.industries.map((item) => `${item.code} · ${item.name}`).join(', ') : '비어 있음';
    case 'REGION': return company.region_name ?? company.region_code ?? '비어 있음';
    case 'COMPANY_SIZE': return company.company_size;
    case 'STAFF': return company.staff ? `${company.staff.total_count}명${company.staff.roles.length ? ` · ${company.staff.roles.map((role) => `${role.role_name} ${role.headcount}명`).join(', ')}` : ''}` : '비어 있음';
    case 'PERFORMANCE_COUNT': return `${company.performances.length}건`;
    case 'PERFORMANCE_AMOUNT': {
      const total = company.performances.reduce((sum, item) => sum + item.amount, 0);
      const max = Math.max(0, ...company.performances.map((item) => item.amount));
      return company.performances.length ? `합계 ${(total / 100_000_000).toFixed(1)}억 · 단일 최대 ${(max / 100_000_000).toFixed(1)}억` : '비어 있음';
    }
    case 'REGISTRATION_CERTIFICATION': return company.certifications.length ? company.certifications.map((item) => item.name).join(', ') : '비어 있음';
    case 'EXPERIENCE_FIELD': {
      const fields = [...new Set(company.performances.flatMap((item) => item.fields))];
      return fields.length ? fields.join(', ') : '비어 있음';
    }
    default: return '프로필 값 확인';
  }
}

function canReuseAnalysis(summary: QualificationAnalysisSummary | null) {
  return Boolean(summary && summary.status === 'SUCCEEDED' && summary.requirement_count > 0);
}

export default function QualificationPage() {
  const requestedCaseId = useSearchParams().get('caseId');
  return <QualificationWorkspace key={requestedCaseId} requestedCaseId={requestedCaseId} />;
}

function QualificationWorkspace({ requestedCaseId }: { requestedCaseId: string | null }) {
  const [notices, setNotices] = useState<BidNoticeSummary[]>([]);
  const [companies, setCompanies] = useState<CompanyProfile[]>([]);
  const [cases, setCases] = useState<PreflightCase[]>([]);
  const [noticeId, setNoticeId] = useState('');
  const [companyId, setCompanyId] = useState('');
  const [activeCase, setActiveCase] = useState<PreflightCase | null>(null);
  const [versions, setVersions] = useState<BidNoticeVersion[]>([]);
  const [baselineAnalysis, setBaselineAnalysis] = useState<QualificationAnalysisSummary | null>(null);
  const [currentAnalysis, setCurrentAnalysis] = useState<QualificationAnalysisSummary | null>(null);
  const [analysisDetail, setAnalysisDetail] = useState<QualificationAnalysisRun | null>(null);
  const [baselineAnalysisDetail, setBaselineAnalysisDetail] = useState<QualificationAnalysisRun | null>(null);
  // 어느 차수 기준으로 볼지. 기본은 현재 차수다. 기준 차수가 없는 검토 건에서는 토글 자체가 안 뜬다.
  const [judgmentView, setJudgmentView] = useState<'baseline' | 'current'>('current');
  const [sourceJudgment, setSourceJudgment] = useState<QualificationJudgmentRun | null>(null);
  const [displayJudgment, setDisplayJudgment] = useState<QualificationJudgmentRun | null>(null);
  const [questions, setQuestions] = useState<QualificationQuestion[]>([]);
  const { controller, action } = useActions(requestedCaseId ?? '');
  const actionLocked = isLocked(action);
  const revalidation = currentRevalidation(action.result, {
    caseId: requestedCaseId ?? '', baselineAnalysisId: baselineAnalysis?.id,
    currentAnalysisId: currentAnalysis?.id, judgmentId: displayJudgment?.id,
  });
  const [selectedEvidenceKey, setSelectedEvidenceKey] = useState<string | null>(null);
  const revealEvidence = useCallback((evidenceKey: string) => {
    if (selectedEvidenceKey === evidenceKey) {
      document.getElementById(SELECTED_EVIDENCE_SECTION_ID)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }
    setSelectedEvidenceKey(evidenceKey);
  }, [selectedEvidenceKey]);
  useEffect(() => {
    if (!selectedEvidenceKey) return;
    const frame = window.requestAnimationFrame(() => {
      document.getElementById(SELECTED_EVIDENCE_SECTION_ID)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [selectedEvidenceKey]);
  const [busy, setBusy] = useState<Busy>('load');
  const [reviewStep, setReviewStep] = useState<ReviewStep>('idle');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  /**
   * 결과 배너의 색. 분석이 온전히 끝나지 않았는데 초록으로 「완료했습니다」를 띄우면
   * 바로 아래 「일부만 읽었습니다」 경고와 모순된다. 같은 배너 안에서 톤을 바꾼다.
   */
  const [messageTone, setMessageTone] = useState<'ok' | 'warn'>('ok');
  // 판정 밖 조건은 10건 넘게 나오는 게 보통이라, 다 펼쳐두면 판정 2건보다 블록이 다섯 배 커진다.
  // 기본은 접어두고 필요할 때 편다. 건수는 접혀 있어도 제목에 그대로 보인다.
  const [showAllUnjudged, setShowAllUnjudged] = useState(false);
  /*
    「판정에 들어가지 않은 조건」은 원문을 그대로 늘어놓아서 이 블록 하나가 화면 3분의 1을 차지했다.
    제출 전에 꼭 봐야 하는 항목이지만 화면에 들어오자마자 읽어야 하는 것은 아니라서 접어 둔다.
    빠진 조건이 없을 때는 접을 것도 없으므로 한 줄로만 말한다.
  */
  const [unjudgedOpen, setUnjudgedOpen] = useState(false);

  /*
    「검토 건 만들기」 드롭다운이 고른 공고다. 목록(상위 100건)에서 찾는다.
    화면 위쪽 제목·공고기관과 나라장터 공고 요약은 이 값을 쓰면 안 된다 — 아래 caseNotice 참고.
  */
  const selectedNotice = useMemo(() => notices.find((item) => item.id === noticeId) ?? null, [noticeId, notices]);

  /*
    지금 보고 있는 검토 건의 공고. id로 직접 받아온다.
    전에는 위의 selectedNotice를 같이 썼는데, 그 값은 목록 첫 번째 공고로 초기화되는
    드롭다운 선택값이라 이 화면이 다른 공고의 기관명·사업유형을 보여주고 있었다.
    목록은 상위 100건뿐이라 검토 건의 공고가 거기 없으면 아예 「미상」으로 떨어지기도 했다.
  */
  const [caseNoticeState, setCaseNoticeState] = useState<{ noticeId: string; notice: BidNoticeDetail | null } | null>(null);
  const caseNoticeId = activeCase?.notice_id;
  useEffect(() => {
    if (!caseNoticeId) return;
    let alive = true;
    void getNotice(caseNoticeId)
      .then((notice) => { if (alive) setCaseNoticeState({ noticeId: caseNoticeId, notice }); })
      /*
        받지 못했다는 것도 결과로 남긴다. null로 비워두면 「아직 못 받았다」와 구분이 안 돼서
        화면이 「공고기관 확인 중」에 영원히 머문다. (#132 리뷰)
        화면 전체를 실패로 만들지는 않는다 — Case에 저장된 제목·공고번호로 계속 그린다.
      */
      .catch(() => { if (alive) setCaseNoticeState({ noticeId: caseNoticeId, notice: null }); });
    return () => { alive = false; };
  }, [caseNoticeId]);
  const caseNoticeSettled = caseNoticeState?.noticeId === caseNoticeId;
  const caseNotice = caseNoticeSettled ? caseNoticeState?.notice ?? null : null;
  const company = useMemo(() => companies.find((item) => item.id === companyId) ?? null, [companies, companyId]);
  const currentVersion = useMemo(() => versions.find((item) => item.version_number === activeCase?.current_version_number) ?? null, [activeCase, versions]);
  const baselineVersion = useMemo(() => versions.find((item) => item.version_number === activeCase?.baseline_version_number) ?? null, [activeCase, versions]);

  async function loadAnalysisDetail(summary: QualificationAnalysisSummary | QualificationAnalysisRun | null, request: number) {
    if (!summary) return setAnalysisDetail(null);
    if ('requirements' in summary) return setAnalysisDetail(summary);
    const detail = await getQualificationAnalysis(summary.id);
    if (request === generation.current) setAnalysisDetail(detail);
  }

  async function loadBaselineAnalysisDetail(summary: QualificationAnalysisSummary | QualificationAnalysisRun | null, request: number) {
    if (!summary) return setBaselineAnalysisDetail(null);
    if ('requirements' in summary) return setBaselineAnalysisDetail(summary);
    const detail = await getQualificationAnalysis(summary.id);
    if (request === generation.current) setBaselineAnalysisDetail(detail);
  }

  const generation = useRef(0);

  const initialize = useCallback(async () => {
    async function hydrateCase(caseId: string, request: number) {
      const workspace = await loadCaseWorkspace(caseId);
      if (request !== generation.current) return;
      // Case ID가 있는 진입에서는 검토 상세만으로 첫 화면을 그릴 수 있다.
      // 전체 공고/Case 목록을 기다리지 않고 현재 항목을 먼저 넣어 로딩 화면을 끝낸다.
      setNotices((previous) => previous.length ? previous : [workspace.notice]);
      setCompanies((previous) => previous.length || !workspace.company ? previous : [workspace.company]);
      setCases((previous) => previous.some((item) => item.id === workspace.caseItem.id)
        ? previous
        : [workspace.caseItem, ...previous]);
      setActiveCase(workspace.caseItem);
      setNoticeId(workspace.caseItem.notice_id);
      setCompanyId(workspace.caseItem.company_id ?? '');
      setVersions(workspace.versions);
      setBaselineAnalysis(workspace.baselineAnalysis);
      setCurrentAnalysis(workspace.currentAnalysis);
      setAnalysisDetail(workspace.currentAnalysisDetail);
      setBaselineAnalysisDetail(workspace.baselineAnalysisDetail);
      setJudgmentView('current');
      setSourceJudgment(workspace.sourceJudgment);
      setDisplayJudgment(workspace.displayJudgment);
      setQuestions(workspace.questions);
      setReviewStep(workspace.displayJudgment ? 'done' : 'idle');
      setSelectedEvidenceKey(null);
    }

    generation.current += 1;
    const request = generation.current;
    setActiveCase(null);
    setAnalysisDetail(null);
    setDisplayJudgment(null);
    setSourceJudgment(null);
    setQuestions([]);
    setMessage('');
    setMessageTone('ok');
    setBusy('load');
    setError('');
    try {
      const targetCase = requestedCaseId;
      if (targetCase) {
        // 공고 100건과 Case 드롭다운 자료는 보조 데이터다. 검토 상세와 동시에 요청하되
        // 첫 화면 렌더링을 막지 않고 도착하는 대로 갱신한다.
        const supportingData = Promise.allSettled([listNotices(), listPreflightCases()]);
        await hydrateCase(targetCase, request);
        void supportingData.then(([noticeResult, caseResult]) => {
          if (request !== generation.current) return;
          if (noticeResult.status === 'fulfilled') setNotices(noticeResult.value.items);
          if (caseResult.status === 'fulfilled') setCases(caseResult.value.items);
        });
        return;
      }
      const [noticeResult, companyResult, caseResult] = await Promise.all([listNotices(), listCompanies(), listPreflightCases()]);
      if (request !== generation.current) return;
      setNotices(noticeResult.items);
      setCompanies(companyResult);
      setCases(caseResult.items);
      setNoticeId(noticeResult.items[0]?.id ?? '');
      setCompanyId(companyResult[0]?.id ?? '');
      if (caseResult.items[0]) {
        // 로그인한 회사에 허용된 가장 최근 Case로 바로 진입한다.
        replaceWith(`/qualification?caseId=${encodeURIComponent(caseResult.items[0].id)}`);
      }
    } catch (cause) {
      if (request === generation.current) setError(cause instanceof Error ? cause.message : '초기 데이터를 불러오지 못했습니다.');
    } finally {
      if (request === generation.current) setBusy(null);
    }
  }, [requestedCaseId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void initialize(), 0);
    return () => { window.clearTimeout(timer); generation.current += 1; };
  }, [initialize]);

  useEffect(() => {
    if (action.stage !== 'COMPLETED') return;
    const timer = window.setTimeout(() => void initialize(), 0);
    return () => window.clearTimeout(timer);
  }, [action.stage, action.result?.result_judgment_run_id, initialize]);

  async function createCase() {
    if (!selectedNotice || !companyId) return;
    setBusy('create');
    setError('');
    try {
      const fetchedVersions = await getNoticeVersions(selectedNotice.id);
      const current = fetchedVersions.find((item) => item.is_current) ?? fetchedVersions[0];
      if (!current) throw new Error('공고 버전을 찾을 수 없습니다.');
      const baseline = fetchedVersions.filter((item) => item.version_number < current.version_number).sort((a, b) => b.version_number - a.version_number)[0];
      const created = await createPreflightCaseWithCompany({ notice_id: selectedNotice.id, company_id: companyId, baseline_version_number: baseline?.version_number, current_version_number: current.version_number, title: `${selectedNotice.bid_notice_no} 자격 검토` });
      const refreshed = await listPreflightCases();
      setCases(refreshed.items);
      navigateTo(`/qualification?caseId=${created.id}`);
      setMessageTone('ok');
      setMessage('검토 건을 만들었습니다. 이제 참가자격 검토를 시작할 수 있습니다.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '검토 건 생성에 실패했습니다.');
    } finally {
      setBusy(null);
    }
  }

  async function getOrRunAnalysis(versionNumber: number, existing: QualificationAnalysisSummary | null, force: boolean) {
    if (!force && canReuseAnalysis(existing)) return existing!;
    return runQualificationAnalysis(activeCase!.notice_id, versionNumber);
  }

  async function runFullReview(force = false) {
    if (!activeCase || busy !== null || isLocked(controller.get(activeCase.id))) return;
    if (!controller.acquireReview(activeCase.id)) return;
    setBusy('review');
    setError('');
    setMessage('');
    setMessageTone('ok');
    const request = generation.current;
    setDisplayJudgment(null);
    setSourceJudgment(null);
    setQuestions([]);
    setReviewStep('analysis');
    try {
      const sameVersion = activeCase.baseline_version_number === activeCase.current_version_number;
      let baseline: QualificationAnalysisSummary | QualificationAnalysisRun | null;
      let current: QualificationAnalysisSummary | QualificationAnalysisRun;
      if (sameVersion) {
        // 기존 데이터에 기준/현재 차수가 같은 Case가 남아 있어도 동일 LLM 분석을 두 번 실행하거나
        // 같은 버전끼리 변경 재검증하지 않는다. 이 경우 기준 버전이 없는 Case처럼 취급한다.
        current = await getOrRunAnalysis(
          activeCase.current_version_number,
          currentAnalysis ?? baselineAnalysis,
          force,
        );
        baseline = null;
      } else {
        [baseline, current] = await Promise.all([
          activeCase.baseline_version_number
            ? getOrRunAnalysis(activeCase.baseline_version_number, baselineAnalysis, force)
            : Promise.resolve(null),
          getOrRunAnalysis(activeCase.current_version_number, currentAnalysis, force),
        ]);
      }
      if (request !== generation.current) return;
      setBaselineAnalysis(baseline);
      setCurrentAnalysis(current);
      // 기준 차수 본문도 같이 갱신한다. 판정만 새로 받고 분석을 그대로 두면
      // 기준 차수 보기에서 옛 요건과 새 판정의 requirement_key가 어긋나 전부 미판정으로 나온다.
      await Promise.all([
        loadAnalysisDetail(current, request),
        loadBaselineAnalysisDetail(sameVersion ? null : baseline, request),
      ]);
      if (request !== generation.current) return;

      setReviewStep('judgment');
      let baselineJudgment: QualificationJudgmentRun | null = null;
      if (baseline && !sameVersion) baselineJudgment = await runQualificationJudgment(activeCase.id, baseline.id);
      if (request !== generation.current) return;
      const currentJudgment = await runQualificationJudgment(activeCase.id, current.id);

      if (request !== generation.current) return;
      setSourceJudgment(baselineJudgment ?? currentJudgment);
      setDisplayJudgment(currentJudgment);
      const nextQuestions = await listQualificationQuestions(activeCase.id, currentJudgment.id);
      if (request !== generation.current) return;
      setQuestions(nextQuestions);
      setReviewStep('done');
      const analyzedCount = 'requirements' in current && Array.isArray(current.requirements) ? current.requirements.length : current.requirement_count;
      const analysisIncomplete = current.status !== 'SUCCEEDED';
      setMessageTone(analysisIncomplete ? 'warn' : 'ok');
      setMessage(analysisIncomplete
        ? `자격조건 ${analyzedCount}건을 판정했습니다. 첨부 일부를 읽지 못해 빠진 조건이 있을 수 있습니다.`
        : `자격조건 ${analyzedCount}건을 분석하고 판정했습니다.`);
    } catch (cause) {
      if (request !== generation.current) return;
      setReviewStep('idle');
      setError(cause instanceof Error ? cause.message : '참가자격 검토에 실패했습니다.');
    } finally {
      controller.releaseReview(activeCase.id);
      if (request === generation.current) setBusy(null);
    }
  }

  /*
    1차 / 2차 보기.

    요건 목록은 분석 결과에서 오고, 판정은 「그 분석」을 기준으로 내려진 것이다.
    그래서 둘을 한 쌍으로 같이 바꾼다. 판정만 바꾸면 2차 요건 목록에 1차 판정이 붙어
    실제로는 없는 화면이 만들어진다.

    기준 차수 보기는 읽기 전용이다. 확인 필요 답변과 재검토는 현재 차수 판정에 묶여 있다.
  */
  const canViewBaseline = Boolean(
    baselineVersion
      && currentVersion
      && baselineVersion.id !== currentVersion.id
      && baselineAnalysisDetail
      && sourceJudgment
      && sourceJudgment.notice_version_id === baselineVersion.id,
  );
  const viewingBaseline = judgmentView === 'baseline' && canViewBaseline;
  const shownAnalysis = viewingBaseline ? baselineAnalysisDetail : analysisDetail;
  const shownJudgment = viewingBaseline ? sourceJudgment : displayJudgment;

  /*
    차수 간 요건 구성 차이.

    요건 수가 다르면 미달이 줄어든 것만 보고 「좋아졌다」고 읽기 쉽다. 빠진 요건은 판정에 아예 들어가지
    않았을 뿐이라 충족된 것이 아니다. 왜 빠졌는지(공고가 조건을 뺐는지, 분석이 놓쳤는지)를 가르는 건
    원문을 나란히 놓는 변경 이력의 일이라, 여기서는 사실만 알리고 그쪽으로 보낸다.
  */
  const versionRequirementGap = useMemo(() => {
    if (!canViewBaseline || !baselineAnalysisDetail || !analysisDetail) return null;
    // requirement_key는 차수마다 새로 만들어져서 같은 요건이라도 값이 달라진다.
    // 키로 비교하면 업종 하나가 양쪽 목록에 동시에 뜨므로 요건 종류로 비교한다.
    const typeLabels = (list: typeof baselineAnalysisDetail.requirements) => new Set(
      list.map((item) => REQUIREMENT_TYPE_LABEL[item.type] ?? item.type),
    );
    const baselineTypes = typeLabels(baselineAnalysisDetail.requirements);
    const currentTypes = typeLabels(analysisDetail.requirements);
    const droppedInCurrent = Array.from(baselineTypes).filter((label) => !currentTypes.has(label));
    const addedInCurrent = Array.from(currentTypes).filter((label) => !baselineTypes.has(label));
    const baselineCount = baselineAnalysisDetail.requirements.length;
    const currentCount = analysisDetail.requirements.length;
    /*
      종류만 비교하면 값이 바뀐 변경을 통째로 놓친다 — 남원처럼 v1 INDUSTRY 1224가
      v2 INDUSTRY 1227로 바뀌면 양쪽 다 「업종」이고 건수도 같아서 아무 안내도 안 뜬다.
      완전한 diff는 변경 이력 화면의 일이고, 여기서는 내용이 달라졌다는 사실까지만 잡는다. (#147 리뷰)
    */
    const signatures = (list: typeof baselineAnalysisDetail.requirements) => new Set(
      list.map((item) => [item.type, item.operator ?? '', String(item.value ?? ''), item.group_operator ?? ''].join('|')),
    );
    const baselineSignatures = signatures(baselineAnalysisDetail.requirements);
    const currentSignatures = signatures(analysisDetail.requirements);
    const contentDiffers = baselineSignatures.size !== currentSignatures.size
      || Array.from(baselineSignatures).some((item) => !currentSignatures.has(item));
    // 종류는 같아도 건수가 달라질 수 있고(업종 2건 → 4건), 건수는 같아도 종류가 바뀔 수 있다.
    // 둘 중 하나라도 어긋나면 두 차수의 숫자를 그대로 비교할 수 없으므로 알린다.
    const countsDiffer = baselineCount !== currentCount;
    if (!countsDiffer && !droppedInCurrent.length && !addedInCurrent.length && !contentDiffers) return null;
    return {
      baselineCount,
      currentCount,
      countsDiffer,
      contentDiffers,
      droppedInCurrent,
      addedInCurrent,
    };
  }, [canViewBaseline, baselineAnalysisDetail, analysisDetail]);

  const resolvedStatuses = useMemo(
    () => resolveRequirementStatuses(shownAnalysis?.requirements ?? [], shownJudgment?.judgments ?? []),
    [shownAnalysis, shownJudgment],
  );

  /*
    택일(ANY_OF) 묶음은 화면에 한 줄로만 나와야 한다.
    구성원마다 한 줄씩 그리면 「1257 또는 6770 또는 6786」 한 조건이 똑같은 문장 세 줄로 반복된다.
    셋 다 충족으로 칠해도 마찬가지다 — 보유하지 않은 6770·6786이 충족으로 보이기 때문이다.
    결론 카드(countByStatus)는 이미 묶음을 한 건으로 세고 있어서, 접지 않으면 위아래 건수도 어긋난다.
  */
  const views: RequirementView[] = useMemo(() => {
    if (!shownAnalysis) return [];
    const judgmentOf = (key: string) => shownJudgment?.judgments.find((item) => item.requirement_key === key) ?? null;
    const seenGroups = new Set<string>();
    const rows: RequirementView[] = [];

    for (const requirement of shownAnalysis.requirements) {
      const groupKey = anyOfGroupKey(requirement);

      if (!groupKey) {
        const judgment = judgmentOf(requirement.requirement_key);
        rows.push({
          requirement,
          judgment,
          status: resolvedStatuses.get(requirement.requirement_key) ?? judgmentStatus(judgment),
          groupPeerNote: null,
          memberKeys: [requirement.requirement_key],
          // evidence_key(REQ-004-EVD)는 내부 식별자다. 누르면 원문이 열리므로 무엇을 하는 버튼인지 쓴다.
          evidenceLabel: requirement.evidence_keys[0] ? '근거 보기' : '근거 없음',
        });
        continue;
      }

      if (seenGroups.has(groupKey)) continue;
      seenGroups.add(groupKey);

      const members = shownAnalysis.requirements.filter((item) => anyOfGroupKey(item) === groupKey);
      // 묶음을 대표할 줄 — 실제로 충족시킨 요건이 있으면 그것을 세운다. 근거도 그 요건 것이어야 맞다.
      const satisfiedMember = members.find((item) => judgmentOf(item.requirement_key)?.status === 'SATISFIED') ?? null;
      const representative = satisfiedMember ?? members[0];
      const judgment = judgmentOf(representative.requirement_key);

      rows.push({
        requirement: representative,
        judgment,
        status: resolvedStatuses.get(representative.requirement_key) ?? judgmentStatus(judgment),
        groupPeerNote: members.length > 1
          ? satisfiedMember
            ? `택일 조건 ${members.length}개 중 ${satisfiedMember.value ?? '1개'} 보유로 충족`
            : `택일 조건 ${members.length}개 · 충족된 것 없음`
          : null,
        memberKeys: members.map((item) => item.requirement_key),
        evidenceLabel: representative.evidence_keys[0] ? '근거 보기' : '근거 없음',
      });
    }

    return rows;
  }, [shownAnalysis, shownJudgment, resolvedStatuses]);

  const selectedEvidence = selectedEvidenceKey ? shownAnalysis?.evidence.find((item) => item.evidence_key === selectedEvidenceKey) ?? null : null;
  const statusCounts = useMemo(
    () => countByStatus(shownAnalysis?.requirements ?? [], resolvedStatuses),
    [shownAnalysis, resolvedStatuses],
  );
  const satisfied = statusCounts.SATISFIED;
  const unknown = statusCounts.UNKNOWN;
  const unsatisfied = statusCounts.UNSATISFIED;
  const [conclusionTitle, conclusionDescription] = overallCopy(shownJudgment?.overall_status);
  const canRevalidate = Boolean(
    activeCase?.baseline_version_number
      && activeCase.baseline_version_number !== activeCase.current_version_number
      && baselineAnalysis
      && currentAnalysis
      && sourceJudgment
      && baselineVersion
      && sourceJudgment.notice_version_id === baselineVersion.id,
  );
  // 확인 필요 답변은 현재 차수 판정에만 붙는다. 기준 차수를 보는 중에는 조치를 걸지 않는다.
  const askableQuestionKeys = new Set(
    viewingBaseline ? [] : questions.filter((item) => item.askable).map((item) => item.requirement_key),
  );
  const analysisNeedsRetry = Boolean(analysisDetail && (analysisDetail.status !== 'SUCCEEDED' || analysisDetail.requirements.length === 0));

  /**
   * 진행 중일 때만 띄운다. 완료 문구는 위 결과 배너가 이미 말한다.
   * 여기서 또 쓰면 「완료했습니다」가 두 번 나오고 그 사이에 「일부만 읽었습니다」가 껴서
   * 완료인지 아닌지 알 수 없는 화면이 된다.
   */
  const reviewProgress = reviewStep === 'analysis'
    ? '1/2 공고 원문에서 자격조건과 근거를 분석하고 있습니다.'
    : reviewStep === 'judgment'
      ? '2/2 회사 프로필과 자격조건을 비교해 판정하고 있습니다.'
      : null;

  // P0-5 · 판정에 들어가지 못한 조건은 두 갈래로 들어온다. 성격이 달라서 한 자리에 섞어 그리면 안 된다.
  //  · NOTICE_FACT 진단 — 공고에서 확인했지만 회사 프로필과 대조할 수 없는 사실. 근거(evidence_keys)가 있다.
  //  · dropped_requirements — 공고 원문 대조를 통과하지 못해 구조화에서 빠진 후보. raw·reason_code만 온다.
  // 아래 블록들은 보고 있는 차수(shownAnalysis)를 따라간다. 현재 차수 고정으로 두면
  // 기준 v1을 보는 중에도 v2의 진단·제외 요건·건수가 섞여 나온다. (#147 리뷰 필수 1)
  const noticeFacts = shownAnalysis?.diagnostics.filter((item) => item.kind === 'NOTICE_FACT') ?? [];
  const pipelineDiagnostics = shownAnalysis?.diagnostics.filter((item) => item.kind !== 'NOTICE_FACT') ?? [];
  const shownDiagnostics = pipelineDiagnostics
    .map((item) => ({ code: item.code, text: diagnosticText(item.code) }))
    .filter((item): item is { code: string; text: string } => Boolean(item.text));
  const droppedRequirements = shownAnalysis?.dropped_requirements ?? [];

  // 판정 밖 조건도 셋으로 갈린다 — 아직 안 돌렸다 / 못 읽었다 / 확인했더니 없다.
  // 0건일 때도 이 자리에서 말해야 한다. 아무 말도 안 하면 「빠진 게 없다」를 사용자가 알 수 없다.
  const unjudgedCount = noticeFacts.length + droppedRequirements.length;
  const unjudgedState: 'NOT_RUN' | 'FAILED' | 'DONE' = !shownAnalysis
    ? 'NOT_RUN'
    : shownAnalysis.status === 'FAILED'
      ? 'FAILED'
      : 'DONE';

  // 접었을 때 보여줄 개수. 공고 쪽 확인사항을 먼저 채우고 남으면 제외 요건을 채운다.
  const UNJUDGED_PREVIEW = 3;
  const previewNoticeFacts = showAllUnjudged ? noticeFacts : noticeFacts.slice(0, UNJUDGED_PREVIEW);
  const previewDropped = showAllUnjudged
    ? droppedRequirements
    : droppedRequirements.slice(0, Math.max(0, UNJUDGED_PREVIEW - previewNoticeFacts.length));
  const hiddenUnjudgedCount = unjudgedCount - previewNoticeFacts.length - previewDropped.length;

  // 문구는 code별 고정이다. 걸린 code가 하나뿐이면 열 줄 모두 같은 문장이 되므로
  // 항목마다 반복하지 않고 목록 머리에 한 번만 쓴다. 종류가 섞여 있으면 항목별로 둔다.
  const noticeFactMessages = Array.from(
    new Set(noticeFacts.map((item) => diagnosticText(item.code)).filter((text): text is string => Boolean(text))),
  );
  const sharedNoticeFactMessage = noticeFactMessages.length === 1 ? noticeFactMessages[0] : null;

  // 실행 전·실패는 「세어본 적이 없는」 상태다. 0으로 적으면 확인 후 0건으로 읽힌다 — #119 리뷰.
  const countedAnalysis = shownAnalysis && shownAnalysis.status !== 'FAILED' ? shownAnalysis : null;

  /*
    첨부가 0종이면 「읽지 못했다」가 아니라 「읽을 것이 없었다」다.
    다만 0인 이유까지는 화면이 모른다 — 취소공고라 원래 없는 차수일 수도, 수집이 안 된 것일 수도 있다.
    그래서 사실(0종)만 말하고 원인은 단정하지 않는다. 백엔드가 문서 없는 공고의 상태를
    (취소공고 / 첨부 누락 / 추출 실패 / 정상)로 구분해 내려주면 그때 원인을 쓴다.
  */
  const currentVersionHasNoDocument = Boolean(currentVersion && currentVersion.documents.length === 0);
  const analysisNotice = currentAnalysis && currentAnalysis.status !== 'SUCCEEDED'
    ? currentAnalysis.status === 'FAILED' && currentVersionHasNoDocument
      ? {
          label: '현재 차수에 수집된 첨부 문서가 없습니다',
          description: '읽을 원문이 없어 판정하지 않았습니다. 취소공고처럼 원래 첨부가 없는 차수일 수도 있고, 수집이 되지 않았을 수도 있습니다. 공고 원문을 직접 확인해 주세요.',
        }
      : ANALYSIS_STATUS_COPY[currentAnalysis.status]
    : null;

  // 분석이 실패했을 때 「없습니다」라고 하면 「확인했는데 없더라」로 읽힌다.
  // 「확인하지 못했다」와 구분한다 — 화면필드명세 공통원칙 3.
  const emptyRequirementCopy = busy === 'review'
    ? '자격요건을 분석하고 있습니다. 잠시만 기다려 주세요.'
    : !analysisDetail
      ? '아직 자격검토를 실행하지 않았습니다.'
      : analysisDetail.status === 'FAILED'
        ? currentVersionHasNoDocument
          ? '현재 차수에 수집된 첨부 문서가 없어 읽을 원문이 없습니다. 위 안내를 확인해 주세요.'
          : '분석이 완료되지 않아 자격요건을 표시할 수 없습니다. 위 안내를 확인해 주세요.'
        : '이번 분석에서 안전하게 구조화된 자격요건이 없습니다.';

  if (busy === 'load' || (requestedCaseId && activeCase?.id !== requestedCaseId && !error)) return <main className="app-shell-container py-12">
    {requestedCaseId && <ActionCard caseId={requestedCaseId} />}
    <output>검토 데이터를 불러오고 있습니다.</output>
  </main>;
  if (requestedCaseId && !activeCase) return <main className="app-shell-container py-12">
    <ActionCard caseId={requestedCaseId} />
    <p role="alert">{error || '검토 건을 찾을 수 없습니다.'}</p>
    <Button variant="outline" className="mt-4" onClick={() => void initialize()}>화면 정보 다시 조회</Button>
    <NavigationLink href="/notices" className="ml-4 underline">공고 찾기</NavigationLink>
  </main>;

  return (
    <main className="bg-white text-[var(--product-body)]">
      <div className="app-shell-container py-10">
        {(error || message) && <div className={`mb-6 flex items-start gap-2 rounded-[14px] border px-4 py-3 text-[15px] ${error ? 'border-rose-200 bg-rose-50 text-rose-700' : messageTone === 'warn' ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>{error || messageTone === 'warn' ? <AlertCircle className="mt-0.5 size-4" /> : <CheckCircle2 className="mt-0.5 size-4" />}<span>{error || message}</span></div>}

        {!activeCase ? (
          <section className="rounded-[22px] border border-[var(--product-line)] bg-white p-7 shadow-sm">
            <h2 className="text-[28px] font-extrabold tracking-[-0.03em]">새 참가자격 검토</h2>
            <p className="mt-2 text-[15px] text-[var(--product-muted)]">회사 프로필과 공고를 연결해 검토 건을 만듭니다.</p>
            <div className="mt-6 grid gap-4 md:grid-cols-2"><NativeSelect value={companyId} onChange={(event) => setCompanyId(event.target.value)}>{companies.map((item) => <NativeSelectOption key={item.id} value={item.id}>{item.name}</NativeSelectOption>)}</NativeSelect><NativeSelect value={noticeId} onChange={(event) => setNoticeId(event.target.value)}>{notices.map((item) => <NativeSelectOption key={item.id} value={item.id}>{item.bid_notice_no} · {item.title}</NativeSelectOption>)}</NativeSelect></div>
            <Button className="mt-4" onClick={() => void createCase()} disabled={!companyId || !noticeId || busy !== null}>검토 건 만들기</Button>
          </section>
        ) : (
          <>
            {/* ── 1 공고 · 검토 건 ── */}
            <section className="flex flex-col justify-between gap-5 lg:flex-row lg:items-start">
              <div className="min-w-0"><div className="flex flex-wrap gap-2"><Badge variant="outline">현재 v{activeCase.current_version_number}</Badge>{activeCase.baseline_version_number && <Badge variant="secondary">기준 v{activeCase.baseline_version_number}</Badge>}{analysisDetail?.status && <Badge variant="outline">{analysisBadgeLabel(analysisDetail.status)}</Badge>}</div><h2 className="mt-4 text-[28px] font-extrabold leading-10 tracking-[-0.035em] text-[var(--product-ink)]">{caseNotice?.title ?? activeCase.notice_title}</h2><p className="mt-2 text-[15px] text-[var(--product-muted)]">공고번호 {activeCase.bid_notice_no} · {caseNotice?.announcing_institution_name ?? caseNotice?.demanding_institution_name ?? (caseNoticeSettled ? '공고기관 정보를 불러오지 못했습니다' : '공고기관 확인 중')}</p></div>
              {/* 검토 건 이동은 화면 맨 아래 카드에 있어서 아무도 못 찾았다. 제목 옆으로 올린다. */}
              <div className="flex flex-wrap items-center gap-2">
                <NativeSelect aria-label="다른 검토 건으로 이동" className="w-full sm:w-[300px]" value={activeCase.id} onChange={(event) => navigateTo(`/qualification?caseId=${encodeURIComponent(event.target.value)}`)}>{cases.map((item) => <NativeSelectOption key={item.id} value={item.id}>{item.bid_notice_no} · {item.title}</NativeSelectOption>)}</NativeSelect>
                <Button variant="outline" onClick={() => void initialize()} disabled={busy !== null}><RefreshCw /> 새로고침</Button>
                <NavigationLink href="/notices" className={buttonVariants({ variant: 'outline' })}>공고 목록</NavigationLink>
              </div>
            </section>

            <CaseTabs caseId={activeCase.id} active="qualification" />

            {/* ── 1-1 어느 차수 기준으로 보는가 ── */}
            {canViewBaseline && (
              <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2">
                <div className="inline-flex rounded-full border border-[var(--product-line)] bg-white p-1">
                  <button
                    type="button"
                    aria-pressed={viewingBaseline}
                    onClick={() => setJudgmentView('baseline')}
                    className={`rounded-full px-4 py-1.5 text-[13px] font-semibold transition-colors ${viewingBaseline ? 'bg-[var(--product-ink)] text-white' : 'text-[var(--product-muted)] hover:bg-[var(--product-tint)]'}`}
                  >
                    기준 v{activeCase.baseline_version_number}
                  </button>
                  <button
                    type="button"
                    aria-pressed={!viewingBaseline}
                    onClick={() => setJudgmentView('current')}
                    className={`rounded-full px-4 py-1.5 text-[13px] font-semibold transition-colors ${!viewingBaseline ? 'bg-[var(--product-ink)] text-white' : 'text-[var(--product-muted)] hover:bg-[var(--product-tint)]'}`}
                  >
                    현재 v{activeCase.current_version_number}
                  </button>
                </div>
                <p className="text-[13px] text-[var(--product-muted)]">
                  {viewingBaseline
                    ? `기준 차수(v${activeCase.baseline_version_number}) 공고문으로 내린 판정입니다. 읽기 전용이라 답변과 재검토는 현재 차수에서만 됩니다.`
                    : `현재 차수(v${activeCase.current_version_number}) 공고문으로 내린 판정입니다.`}
                </p>
              </div>
            )}

            {versionRequirementGap && (
              <section className="mt-4 rounded-[18px] border border-[var(--product-warn-line)] bg-[var(--product-warn-soft)] px-5 py-4">
                <strong className="text-[15px] text-[var(--product-warn)]">
                  {versionRequirementGap.countsDiffer
                    ? '두 차수의 요건 수가 다릅니다'
                    : versionRequirementGap.droppedInCurrent.length || versionRequirementGap.addedInCurrent.length
                      ? '두 차수의 요건 구성이 다릅니다'
                      : '두 차수의 요건 내용이 다릅니다'} — 기준 v{activeCase.baseline_version_number} {versionRequirementGap.baselineCount}건 · 현재 v{activeCase.current_version_number} {versionRequirementGap.currentCount}건
                </strong>
                {versionRequirementGap.droppedInCurrent.length > 0 && (
                  <p className="mt-1 text-[15px] leading-6 text-[var(--product-body)]">
                    현재 차수에 없는 요건 — {versionRequirementGap.droppedInCurrent.join(' · ')}
                  </p>
                )}
                {versionRequirementGap.addedInCurrent.length > 0 && (
                  <p className="mt-1 text-[15px] leading-6 text-[var(--product-body)]">
                    기준 차수에 없던 요건 — {versionRequirementGap.addedInCurrent.join(' · ')}
                  </p>
                )}
                <p className="mt-2 text-[13px] leading-[1.7] text-[var(--product-muted)]">
                  {versionRequirementGap.droppedInCurrent.length > 0
                    ? '빠진 요건은 판정에서 제외됩니다. 미달이 줄어도 충족된 것은 아닙니다. 요건이 왜 빠졌는지는 변경 이력에서 원문으로 확인해 주세요.'
                    : versionRequirementGap.addedInCurrent.length > 0 || versionRequirementGap.countsDiffer
                      ? '요건 구성이 달라 두 차수의 건수를 그대로 비교할 수 없습니다. 무엇이 달라졌는지는 변경 이력에서 원문으로 확인해 주세요.'
                      : '요건 수와 종류는 같지만 조건 값이 달라진 요건이 있습니다. 무엇이 달라졌는지는 변경 이력에서 원문으로 확인해 주세요.'}
                </p>
              </section>
            )}

            {/* ── 2 결론 — 이 화면에 온 이유에 먼저 답한다 ── */}
            <div className="mt-6"><ConclusionBox title={conclusionTitle} description={conclusionDescription} satisfied={satisfied} unknown={unknown} unsatisfied={unsatisfied} action={<div className="flex gap-2"><Button onClick={() => void runFullReview(Boolean(analysisDetail))} disabled={busy !== null || actionLocked || viewingBaseline}>{busy === 'review' ? <LoaderCircle className="animate-spin" /> : <Play />}{displayJudgment ? '다시 검토' : '참가자격 검토 시작'}</Button>{!viewingBaseline && analysisNeedsRetry && <Badge className="self-center bg-amber-100 text-amber-800">기존 분석 {analysisDetail ? analysisStatusLabel(analysisDetail.status) : '없음'} · 새로 분석합니다</Badge>}</div>} /></div>

            {/* ── 3 결론의 신뢰도 — 첨부를 다 읽지 못했으면 여기서 말한다 ── */}
            {/* S-9 · 첨부를 다 읽지 못한 경우를 판정과 같은 화면에서 말한다. PARTIAL을 SUCCEEDED처럼 그리면 빠진 조건이 사용자에게 안 보인다. */}
            {analysisNotice && (
              <section className="mt-6 rounded-[18px] border border-[var(--product-warn-line)] bg-[var(--product-warn-soft)] px-5 py-4">
                <strong className="text-[15px] text-[var(--product-warn)]">{analysisNotice.label}</strong>
                <p className="mt-1 text-[15px] leading-6 text-[var(--product-body)]">{analysisNotice.description}</p>
              </section>
            )}

            {reviewProgress && <section className="mt-6 rounded-[18px] border border-[#d9def7] bg-[#f5f6ff] px-5 py-4"><div className="flex items-center gap-3">{busy === 'review' ? <LoaderCircle className="size-5 animate-spin text-[var(--product-accent)]" /> : <CheckCircle2 className="size-5 text-emerald-600" />}<div><strong className="text-[15px]">{reviewProgress}</strong>{busy === 'review' && <p className="mt-1 text-[13px] text-[var(--product-muted)]">완료되면 새로고침 없이 이 화면에 즉시 결과가 반영됩니다.</p>}</div></div></section>}

            {/* ── 4 물어보기 ── */}
            <ActionCard caseId={activeCase.id} />

            {/* ── 5 왜 그 결론인지 — 요건별 판정과 근거 ── */}
            <section className="mt-10">
              <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end"><div><h2 className="text-[28px] font-extrabold tracking-[-0.035em]">참가 자격 (필수)</h2><p className="mt-1 text-[15px] text-[var(--product-muted)]">{canViewBaseline ? `v${viewingBaseline ? activeCase.baseline_version_number : activeCase.current_version_number} 공고 원문에서 구조화한 자격요건과 그 근거입니다.` : '공고 원문에서 구조화한 자격요건과 그 근거를 기준으로 표시합니다.'}</p></div><span className="text-[15px] text-[var(--product-muted)]">구조화 {views.length}건 · 판정 {views.filter((view) => view.status !== 'UNJUDGED').length}건</span></div>
              <div className="mt-4 overflow-hidden rounded-[18px] border border-[var(--product-line)] bg-white">
                <div className="hidden min-h-[45px] grid-cols-[152px_minmax(0,1.9fr)_minmax(190px,0.8fr)_170px_160px] items-center bg-[var(--product-tint)] text-[13px] font-semibold text-[var(--product-muted)] lg:grid"><div className="px-3">판정</div><div className="px-3">참가 자격 조건</div><div className="px-3">비교 값 / 판정 근거</div><div className="px-3">근거</div><div className="px-3">조치</div></div>
                {views.length ? views.map(({ requirement, judgment, status, groupPeerNote, memberKeys, evidenceLabel }) => {
                  // 묶음을 접었으므로 조치도 묶음 전체로 본다. 대표 줄만 보면 다른 구성원에 걸린 질문을 놓친다.
                  const askable = memberKeys.some((key) => askableQuestionKeys.has(key));
                  const evidenceHref = `/evidence?caseId=${activeCase.id}${requirement.evidence_keys[0] ? `&evidence=${encodeURIComponent(requirement.evidence_keys[0])}` : ''}`;
                  /*
                    조치는 ① 그룹 판정 기준으로 걸고 ② 현재 차수에서만 건다.
                    ①이 없으면 이미 충족된 택일 그룹인데 개별 요건이 UNKNOWN이라고 다시 묻는다.
                    ②가 없으면 기준 v1 요건에서 「원문 확인」을 눌렀을 때 Evidence 화면이 현재 차수 분석만 써서
                    같은 evidence key를 가진 v2 근거가 열린다. 기준 차수에서는 같은 화면의 「근거 보기」만 쓴다. (#147 리뷰 필수 2)
                  */
                  const actionable = !viewingBaseline && status === 'UNKNOWN';
                  const companyValueText = groupPeerNote
                    ? `${companyValue(requirement, company, judgment)} · ${groupPeerNote}`
                    : companyValue(requirement, company, judgment);
                  return <QualificationRow key={requirement.requirement_key} status={status} basisType={judgment?.basis_type ?? 'NONE'} condition={`${labelOf(REQUIREMENT_TYPE_LABEL, requirement.type)} · ${requirement.raw}`} companyValue={companyValueText} evidenceLabel={evidenceLabel} actionLabel={actionable ? (askable ? '확인하기' : '원문 확인') : judgment ? null : '판정 필요'} onEvidence={requirement.evidence_keys[0] ? () => revealEvidence(requirement.evidence_keys[0]) : undefined} onAction={actionable ? () => { navigateTo(askable ? `/ask-back?caseId=${activeCase.id}` : evidenceHref); } : undefined} />;
                }) :<div className="px-6 py-14 text-center">{busy === 'review' ? <LoaderCircle className="mx-auto size-8 animate-spin text-[var(--product-accent)]" /> : <FileSearch className="mx-auto size-8 text-[var(--product-faint)]" />}<p className="mt-3 text-[15px] font-semibold">{emptyRequirementCopy}</p><Button className="mt-4" onClick={() => void runFullReview(Boolean(analysisDetail))} disabled={busy !== null || actionLocked}>{busy === 'review' ? <LoaderCircle className="animate-spin" /> : <Play />}{analysisDetail ? '새로 분석하고 판정' : '참가자격 검토 시작'}</Button></div>}              </div>
            </section>

            {/*
              ── 6 변경공고 영향 ──
              판정 표 바로 뒤에 둔다. 이 화면에 온 사람이 「나는 되는가」 다음으로 묻는 것이
              「그 사이에 공고가 바뀌지 않았는가」이기 때문이다.
              전에는 「판정에 들어가지 않은 조건」 뒤 2단 그리드 한 칸에 있어서,
              결론을 본 사람이 화면을 한참 내려야 닿았다.
            */}
            <section className="mt-8 rounded-[20px] border border-[var(--product-line)] bg-white p-6">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <h2 className="text-[21px] font-extrabold">변경공고 영향 재검증</h2>
                  <p className="mt-2 text-[15px] leading-6 text-[var(--product-muted)]">기준 차수와 현재 차수가 모두 있으면 변경된 자격요건만 다시 판정합니다.</p>
                  {revalidation && <p className="mt-3 text-[15px]">다시 판정한 자격요건 <strong>{revalidation.revalidated_keys.length}건</strong></p>}
                </div>
                {/* 기준 차수는 읽기 전용이다. 「다시 검토」를 막아뒀으니 재검증 제안도 같이 막는다. (#147 리뷰) */}
                <Button variant="outline" className="shrink-0" onClick={() => void controller.propose(activeCase.id, true)} disabled={!canRevalidate || busy !== null || actionLocked || viewingBaseline}>{actionLocked ? <LoaderCircle className="animate-spin" /> : <GitCompareArrows />} 전체 변경 요건 재검증 제안</Button>
              </div>
            </section>

            {/* ── 7 판정 밖 조건 — 위 표에 없는 것 ── */}
            {/* P0-5 · 위 표에 없는 조건을 말한다. 이걸 안 그리면 사용자는 빠진 조건이 있는 줄 모른 채 판정을 믿는다 (NFR-1). */}
            <section id="analysis-scope" className={`mt-8 rounded-[20px] border px-6 py-5 ${unjudgedCount > 0 ? 'border-[var(--product-warn-line)] bg-[var(--product-warn-soft)]' : 'border-[var(--product-line)] bg-white'}`}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h2 className="text-[18px] font-extrabold text-[var(--product-ink)]">판정에 들어가지 않은 조건{unjudgedCount > 0 ? ` ${unjudgedCount}건` : ''}</h2>
                  {unjudgedCount > 0 && (
                    <Button type="button" variant="outline" size="sm" className="rounded-full bg-white" onClick={() => setUnjudgedOpen((value) => !value)}>
                      {unjudgedOpen ? <><ChevronUp /> 접기</> : <><ChevronDown /> 원문 보기</>}
                    </Button>
                  )}
                </div>
                {unjudgedCount > 0 && !unjudgedOpen && (
                  <p className="mt-1 text-[15px] leading-6 text-[var(--product-body)]">제출 전에 공고 원문에서 직접 확인해야 하는 항목입니다.</p>
                )}
                {(unjudgedCount === 0 || unjudgedOpen) && <>
                <p className="mt-1 text-[15px] leading-6 text-[var(--product-body)]">{unjudgedState === 'NOT_RUN'
                  ? '아직 자격검토를 실행하지 않았습니다. 검토를 실행하면 판정에서 빠진 조건을 여기에 표시합니다.'
                  : unjudgedState === 'FAILED'
                    ? unjudgedCount
                      // 실패했어도 중단 전까지 잡힌 항목은 남는다. 「확인 못 했다」로 끝내면 아래 목록과 말이 어긋난다.
                      ? '분석이 끝나지 않았습니다. 아래는 중단되기 전까지 확인된 항목이라 이 목록이 전부가 아닙니다.'
                      : '분석이 완료되지 않아 판정에서 빠진 조건을 확인하지 못했습니다.'
                    : unjudgedCount
                      ? '아래 항목은 위 표의 판정에 반영되지 않았습니다. 제출 전에 공고 원문에서 직접 확인해 주세요.'
                      : '이번 분석에서 판정 밖으로 빠진 조건이 없습니다.'}</p>

                {previewNoticeFacts.length > 0 && (
                  <div className="mt-4">
                    <strong className="text-[15px] text-[var(--product-warn)]">판정 대상이 아닌 확인사항 {noticeFacts.length}건</strong>
                    {sharedNoticeFactMessage && <p className="mt-1 text-[15px] leading-6 text-[var(--product-body)]">{sharedNoticeFactMessage}</p>}
                    <ul className="mt-2 space-y-2">
                      {/* 무엇이 걸렸는지는 근거 원문으로만 구분된다. 공통 문구는 위에서 한 번 말했다. */}
                      {previewNoticeFacts.map((item, index) => {
                        const evidenceKey = item.evidence_keys[0];
                        const evidence = evidenceKey ? shownAnalysis?.evidence.find((row) => row.evidence_key === evidenceKey) ?? null : null;
                        const locationText = evidence ? evidenceLocationText(evidence.location) : null;
                        return (
                          <li key={`${item.code}-${index}`} className="rounded-[14px] border border-[var(--product-line)] bg-white px-4 py-3">
                            {evidence && <p className="text-[15px] leading-6 text-[var(--product-ink)]">「{evidence.quote}」</p>}
                            {!sharedNoticeFactMessage && diagnosticText(item.code) && <p className={evidence ? 'mt-1 text-[15px] leading-6 text-[var(--product-body)]' : 'text-[15px] leading-6 text-[var(--product-body)]'}>{diagnosticText(item.code)}</p>}
                            {locationText && <p className="mt-1 text-[13px] text-[var(--product-muted)]">근거 위치 — {locationText}</p>}
                            {/* evidence_key만 보고 버튼을 띄우면 실제 Evidence가 없을 때 눌러도 아무것도 안 열린다. 객체가 resolve된 경우에만 노출한다. */}
                            {evidence && <Button variant="outline" size="sm" className="mt-2 rounded-full" onClick={() => revealEvidence(evidence.evidence_key)}>근거 원문 보기</Button>}
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                )}

                {previewDropped.length > 0 && (
                  <div className="mt-4">
                    <strong className="text-[15px] text-[var(--product-warn)]">구조화에서 제외된 요건 {droppedRequirements.length}건</strong>
                    <ul className="mt-2 space-y-2">
                      {/* MISSING_RAW는 raw가 비어 있을 수 있다. 빈 따옴표만 남기지 않고 확보하지 못했다고 말한다. */}
                      {previewDropped.map((item, index) => {
                        const raw = item.raw.trim();
                        return (
                          <li key={`${item.reason_code}-${index}`} className="rounded-[14px] border border-[var(--product-line)] bg-white px-4 py-3">
                            {raw
                              ? <p className="text-[15px] leading-6 text-[var(--product-ink)]">「{raw}」</p>
                              : <p className="text-[15px] leading-6 text-[var(--product-faint)]">원문 문구를 확보하지 못했습니다.</p>}
                            <p className="mt-1 text-[13px] text-[var(--product-muted)]">{labelOf(DROPPED_REASON_LABEL, item.reason_code)}</p>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                )}

                {hiddenUnjudgedCount > 0 && (
                  <Button type="button" variant="outline" size="sm" className="mt-4 rounded-full bg-white" onClick={() => setShowAllUnjudged(true)}>
                    <ChevronDown /> 나머지 {hiddenUnjudgedCount}건 더 보기
                  </Button>
                )}
                {showAllUnjudged && unjudgedCount > UNJUDGED_PREVIEW && (
                  <Button type="button" variant="outline" size="sm" className="mt-4 rounded-full bg-white" onClick={() => setShowAllUnjudged(false)}>
                    <ChevronUp /> 목록 접기
                  </Button>
                )}
                </>}
            </section>

            {selectedEvidence && <section id={SELECTED_EVIDENCE_SECTION_ID} className="mt-8 scroll-mt-32"><h2 className="mb-3 text-[21px] font-extrabold">선택한 원문 근거</h2><EvidenceQuote quote={selectedEvidence.quote} location={selectedEvidence.location} /></section>}

            {/*
              ── 8 이 판정에 쓴 것 ──
              전에는 「분석 완전성」 한 칸과 3칸 카드가 따로 있었는데, 둘 다 「무엇을 근거로 이 판정이 나왔나」를
              말하는 값이라 한 덩어리로 합친다. 카드 여섯 칸이 세로로 쌓이던 것이 한 줄이 된다.
            */}
            <section className="mt-10 rounded-[20px] border border-[var(--product-line)] p-6">
              <h2 className="text-[18px] font-extrabold">이 판정에 쓴 것</h2>
              <p className="mt-1 text-[15px] leading-6 text-[var(--product-muted)]">분석이 어디까지 돌았는지와 대조에 쓴 회사 정보입니다. 판정 결과와는 분리해서 봅니다.</p>
              <div className="mt-4 flex flex-wrap gap-x-8 gap-y-4">
                <div>
                  <span className="text-[13px] text-[var(--product-muted)]">회사 프로필</span>
                  <strong className="mt-0.5 block text-[15px]">{company?.name ?? '미연결'}</strong>
                  <p className="text-[13px] text-[var(--product-muted)]">{company?.region_name ?? '-'} · {labelOf(COMPANY_SIZE_LABEL, company?.company_size)}</p>
                </div>
                <div>
                  <span className="text-[13px] text-[var(--product-muted)]">분석 상태</span>
                  <strong className="mt-0.5 block text-[15px]">{shownAnalysis ? analysisStatusLabel(shownAnalysis.status) : '분석 전'}</strong>
                  {/* 재분석은 현재 차수에만 건다. 기준 차수는 읽기 전용이라 「재분석 권장」을 띄우면 안 된다. */}
                  <p className="text-[13px] text-[var(--product-muted)]">{viewingBaseline ? '기준 차수 · 읽기 전용' : analysisNeedsRetry ? '재분석 권장' : currentAnalysis ? '사용 가능' : '미실행'}</p>
                </div>
                <div>
                  <span className="text-[13px] text-[var(--product-muted)]">자격요건 · 근거</span>
                  <strong className="mt-0.5 block text-[15px]">{countedAnalysis ? `${countedAnalysis.requirements.length}건` : '-'} · 근거 {countedAnalysis ? `${countedAnalysis.evidence.length}건` : '-'}</strong>
                  {/* 요건 0건인데 근거만 여러 건이면 숫자만 보고는 뭐가 잘못됐는지 알 수 없다. */}
                  {countedAnalysis && countedAnalysis.requirements.length === 0 && countedAnalysis.evidence.length > 0 && (
                    <p className="mt-1 text-[13px] leading-[1.7] text-[var(--product-muted)]">근거 문장은 찾았지만 구조화된 자격요건으로 옮기지 못했습니다.</p>
                  )}
                  <p className="text-[13px] text-[var(--product-muted)]">공고 원문에서 구조화한 수</p>
                </div>
                <div>
                  <span className="text-[13px] text-[var(--product-muted)]">확인 필요</span>
                  <strong className="mt-0.5 block text-[15px]">{unknown}건</strong>
                  {/* 확인 필요 답변은 현재 차수 판정에만 붙는다. 기준 차수를 보는 중에는 질문 가능 건수도 0이다. */}
                  <p className="text-[13px] text-[var(--product-muted)]">사용자 질문 가능 {viewingBaseline ? 0 : questions.filter((item) => item.askable).length}건</p>
                </div>
              </div>
              {/* 문구가 없는 코드는 줄 자체를 그리지 않는다. 백엔드 개발자용 message는 화면에 내보내지 않는다. */}
              {shownDiagnostics.length ? <div className="mt-4 space-y-2">{shownDiagnostics.map((item, index) => <p key={`${item.code}-${index}`} title={item.code} className="rounded-xl bg-amber-50 px-3 py-2 text-[13px] leading-[1.7] text-amber-800">{item.text}</p>)}</div> : null}
            </section>

            {/* ── 9 공고 원본 정보 ── */}
            <QualificationSourceOverview caseItem={activeCase} notice={caseNotice} version={currentVersion} />

          </>
        )}
      </div>
    </main>
  );
}
