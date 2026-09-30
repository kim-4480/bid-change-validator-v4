import { useCallback, useEffect, useRef, useState } from 'react';
import {
  getNotice,
  getNoticeVersions,
  getPreflightCase,
  type BidNoticeDetail,
  type BidNoticeVersion,
  type PreflightCase,
} from '@/lib/api';
import {
  getQualificationAnalysis,
  getQualificationJudgment,
  listCompanies,
  listQualificationAnalyses,
  listQualificationJudgments,
  listQualificationQuestions,
  type CompanyProfile,
  type QualificationAnalysisRun,
  type QualificationAnalysisSummary,
  type QualificationJudgmentRun,
  type QualificationJudgmentSummary,
  type QualificationQuestion,
} from '@/lib/qualification-api';

const CURRENT_QUALIFICATION_RULE_VERSION = 'qualification-rules-v0.3';

export type CaseWorkspace = {
  caseItem: PreflightCase;
  notice: BidNoticeDetail;
  versions: BidNoticeVersion[];
  company: CompanyProfile | null;
  baselineAnalysis: QualificationAnalysisSummary | null;
  currentAnalysis: QualificationAnalysisSummary | null;
  currentAnalysisDetail: QualificationAnalysisRun | null;
  // 기준 차수의 분석 본문. 1차/2차 보기 전환은 분석과 판정을 한 쌍으로 같이 바꿔야 해서 둘 다 필요하다.
  baselineAnalysisDetail: QualificationAnalysisRun | null;
  sourceJudgment: QualificationJudgmentRun | null;
  displayJudgment: QualificationJudgmentRun | null;
  questions: QualificationQuestion[];
};

export async function loadCaseWorkspace(caseId: string): Promise<CaseWorkspace> {
  const caseItem = await getPreflightCase(caseId);
  const [notice, versions, companies, currentAnalyses, baselineAnalyses, judgmentSummaries] =
    await Promise.all([
      getNotice(caseItem.notice_id),
      getNoticeVersions(caseItem.notice_id),
      listCompanies(),
      listQualificationAnalyses(caseItem.notice_id, caseItem.current_version_number),
      caseItem.baseline_version_number
        ? listQualificationAnalyses(caseItem.notice_id, caseItem.baseline_version_number)
        : Promise.resolve([]),
      listQualificationJudgments(caseItem.id),
    ]);

  const currentAnalysis = currentAnalyses[0] ?? null;
  const baselineAnalysis = baselineAnalyses[0] ?? null;
  const baselineVersionId = versions.find(
    (item) => item.version_number === caseItem.baseline_version_number,
  )?.id;
  const currentVersionId = versions.find(
    (item) => item.version_number === caseItem.current_version_number,
  )?.id;
  if (!currentVersionId || (caseItem.baseline_version_number && !baselineVersionId)) {
    throw new Error('검토 건에 지정된 공고 차수를 찾을 수 없습니다.');
  }
  const baselineSummary = baselineVersionId
    ? judgmentSummaries.find((item) => judgmentMatchesAnalysis(item, baselineAnalysis, caseItem.company_id))
    : null;
  const displaySummary =
    judgmentSummaries.find((item) => judgmentMatchesAnalysis(item, currentAnalysis, caseItem.company_id));
  const sourceSummary = baselineVersionId ? baselineSummary : displaySummary;

  const [currentAnalysisDetail, baselineAnalysisDetail, source, display, questions] = await Promise.all([
    currentAnalysis
      ? getQualificationAnalysis(currentAnalysis.id)
      : Promise.resolve(null),
    baselineAnalysis && baselineAnalysis.id !== currentAnalysis?.id
      ? getQualificationAnalysis(baselineAnalysis.id)
      : Promise.resolve(null),
    sourceSummary && sourceSummary.id !== displaySummary?.id ? getQualificationJudgment(sourceSummary.id) : Promise.resolve(null),
    displaySummary ? getQualificationJudgment(displaySummary.id) : Promise.resolve(null),
    displaySummary
      ? listQualificationQuestions(caseItem.id, displaySummary.id)
      : Promise.resolve([]),
  ]);
  const displayJudgment = display?.rule_version === CURRENT_QUALIFICATION_RULE_VERSION ? display : null;
  const sourceJudgment = sourceSummary?.id === displaySummary?.id ? displayJudgment : source?.rule_version === CURRENT_QUALIFICATION_RULE_VERSION ? source : null;

  return {
    caseItem,
    notice,
    versions,
    company: companies.find((item) => item.id === caseItem.company_id) ?? null,
    baselineAnalysis,
    currentAnalysis,
    currentAnalysisDetail,
    baselineAnalysisDetail,
    sourceJudgment,
    displayJudgment,
    questions: displayJudgment ? questions : [],
  };
}

export function currentVersion(workspace: CaseWorkspace) {
  const version = workspace.versions.find(
      (item) => item.version_number === workspace.caseItem.current_version_number,
    );
  if (!version) throw new Error('검토 차수의 공고를 찾을 수 없습니다.');
  return version;
}

export function judgmentMatchesAnalysis(judgment: QualificationJudgmentSummary, analysis: QualificationAnalysisSummary | null, companyId: string | null) {
  return Boolean(
    analysis
    && analysis.status !== 'FAILED'
    && judgment.analysis_run_id === analysis.id
    && judgment.notice_version_id === analysis.notice_version_id
    && judgment.company_id === companyId
    && judgment.rule_version === CURRENT_QUALIFICATION_RULE_VERSION
  );
}

export async function loadCurrentJudgment(caseItem: PreflightCase) {
  const [analyses, judgments] = await Promise.all([
    listQualificationAnalyses(caseItem.notice_id, caseItem.current_version_number),
    listQualificationJudgments(caseItem.id),
  ]);
  const summary = judgments.find((item) => judgmentMatchesAnalysis(item, analyses[0] ?? null, caseItem.company_id));
  if (!summary) return null;
  const run = await getQualificationJudgment(summary.id);
  return run.rule_version === CURRENT_QUALIFICATION_RULE_VERSION ? run : null;
}

export function useCaseWorkspace(caseId: string | null) {
  const [loaded, setLoaded] = useState<CaseWorkspace | null>(null);
  const [error, setError] = useState('');
  const generation = useRef(0);
  const reload = useCallback(async () => {
    const request = ++generation.current;
    setError('');
    if (!caseId) return;
    try {
      const value = await loadCaseWorkspace(caseId);
      if (request === generation.current) setLoaded(value);
    } catch (cause) {
      if (request === generation.current) {
        // Preserve last verified content; the caller displays the refresh failure.
        setError(cause instanceof Error ? cause.message : '검토 데이터를 불러오지 못했습니다.');
      }
    }
  }, [caseId]);
  useEffect(() => {
    const timer = setTimeout(() => { setLoaded(null); void reload(); }, 0);
    return () => { clearTimeout(timer); generation.current += 1; };
  }, [reload]);
  return { workspace: loaded?.caseItem.id === caseId ? loaded : null, error, reload };
}

export function baselineVersion(workspace: CaseWorkspace) {
  return workspace.caseItem.baseline_version_number
    ? workspace.versions.find(
        (item) => item.version_number === workspace.caseItem.baseline_version_number,
      ) ?? null
    : null;
}

export function workspaceHref(path: string, caseId: string) {
  return `${path}?caseId=${encodeURIComponent(caseId)}`;
}
