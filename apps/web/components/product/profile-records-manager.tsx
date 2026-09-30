'use client';

import { useState } from 'react';
import { Pencil, Plus, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { CompanyProfile } from '@/lib/qualification-api';
import {
  createCertification,
  createPerformance,
  deleteCertification,
  deletePerformance,
  updateCertification,
  updatePerformance,
} from '@/lib/profile-records-api';

type Props = {
  company: CompanyProfile;
  onChanged: () => Promise<void> | void;
};

type Busy = string | null;

export function ProfileRecordsManager({ company, onChanged }: Props) {
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState('');
  const [performance, setPerformance] = useState({ name: '', client_name: '', amount: '', completed_at: '', fields: '' });
  const [certification, setCertification] = useState({ name: '', certificate_number: '', issuer_name: '', issued_at: '', expires_at: '' });

  async function execute(key: string, action: () => Promise<unknown>) {
    setBusy(key);
    setError('');
    try {
      await action();
      await onChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '프로필 정보를 저장하지 못했습니다.');
    } finally {
      setBusy(null);
    }
  }

  async function addPerformance() {
    if (!performance.name.trim() || !performance.amount || !performance.completed_at) {
      setError('수행실적명, 금액, 완료일은 필수입니다.');
      return;
    }
    await execute('performance:create', async () => {
      await createPerformance(company.id, {
        name: performance.name.trim(),
        client_name: performance.client_name.trim() || undefined,
        amount: Number(performance.amount),
        completed_at: performance.completed_at,
        fields: performance.fields.split(',').map((item) => item.trim()).filter(Boolean),
        verified: false,
      });
      setPerformance({ name: '', client_name: '', amount: '', completed_at: '', fields: '' });
    });
  }

  async function addCertification() {
    if (!certification.name.trim()) {
      setError('인증·등록명은 필수입니다.');
      return;
    }
    await execute('certification:create', async () => {
      await createCertification(company.id, {
        name: certification.name.trim(),
        certificate_number: certification.certificate_number.trim() || undefined,
        issuer_name: certification.issuer_name.trim() || undefined,
        issued_at: certification.issued_at || undefined,
        expires_at: certification.expires_at || undefined,
        verified: false,
      });
      setCertification({ name: '', certificate_number: '', issuer_name: '', issued_at: '', expires_at: '' });
    });
  }

  return (
    <section className="mt-7 grid gap-5 xl:grid-cols-2">
      {error && <div className="xl:col-span-2 rounded-[14px] border border-rose-200 bg-rose-50 px-4 py-3 text-[13px] text-rose-700">{error}</div>}

      {/* 위 「비어 있는 항목」에서 바로 여기로 보낸다. id를 바꾸면 app/company/page.tsx의 앵커도 같이 고칠 것. */}
      <div id="profile-performance" className="scroll-mt-24 rounded-[20px] border border-[var(--product-line)] bg-white p-6">
        <div className="flex items-center justify-between gap-3">
          <div><h3 className="text-[19px] font-bold">수행 실적</h3><p className="mt-1 text-[12.5px] text-[var(--product-muted)]">건수·금액·경험 분야 판정에 사용합니다.</p></div>
          <span className="text-[12px] text-[var(--product-muted)]">{company.performances.length}건</span>
        </div>
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          <Input placeholder="실적명 *" value={performance.name} onChange={(e) => setPerformance({ ...performance, name: e.target.value })} />
          <Input placeholder="발주처" value={performance.client_name} onChange={(e) => setPerformance({ ...performance, client_name: e.target.value })} />
          <Input type="number" min="0" placeholder="계약금액(원) *" value={performance.amount} onChange={(e) => setPerformance({ ...performance, amount: e.target.value })} />
          <Input type="date" value={performance.completed_at} onChange={(e) => setPerformance({ ...performance, completed_at: e.target.value })} />
          <Input className="sm:col-span-2" placeholder="경험 분야 (쉼표 구분)" value={performance.fields} onChange={(e) => setPerformance({ ...performance, fields: e.target.value })} />
        </div>
        <Button className="mt-3 rounded-full" onClick={() => void addPerformance()} disabled={busy !== null}><Plus /> 수행 실적 추가</Button>

        <div className="mt-5 divide-y divide-[var(--product-line-2)]">
          {company.performances.map((item) => <div key={item.id} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center"><div className="min-w-0 flex-1"><strong className="block truncate text-[14px]">{item.name}</strong><p className="mt-1 text-[12px] text-[var(--product-muted)]">{item.amount.toLocaleString()}원 · {item.completed_at}{item.fields.length ? ` · ${item.fields.join(', ')}` : ''}</p></div><div className="flex gap-2"><Button size="sm" variant="outline" className="rounded-full" onClick={() => void execute(`p:verify:${item.id}`, () => updatePerformance(company.id, item.id, { verified: !item.verified }))}><Pencil /> {item.verified ? '증빙 보유' : '증빙 표시'}</Button><Button size="sm" variant="outline" className="rounded-full" onClick={() => void execute(`p:delete:${item.id}`, () => deletePerformance(company.id, item.id))}><Trash2 /> 삭제</Button></div></div>)}
          {!company.performances.length && <p className="py-5 text-center text-[13px] text-[var(--product-muted)]">등록된 수행 실적이 없습니다.</p>}
        </div>
      </div>

      <div id="profile-certification" className="scroll-mt-24 rounded-[20px] border border-[var(--product-line)] bg-white p-6">
        <div className="flex items-center justify-between gap-3">
          <div><h3 className="text-[19px] font-bold">인증 · 등록</h3><p className="mt-1 text-[12.5px] text-[var(--product-muted)]">등록·면허·인증 보유 사실 판정에 사용합니다.</p></div>
          <span className="text-[12px] text-[var(--product-muted)]">{company.certifications.length}건</span>
        </div>
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          <Input placeholder="인증·등록명 *" value={certification.name} onChange={(e) => setCertification({ ...certification, name: e.target.value })} />
          <Input placeholder="번호" value={certification.certificate_number} onChange={(e) => setCertification({ ...certification, certificate_number: e.target.value })} />
          <Input placeholder="발급기관" value={certification.issuer_name} onChange={(e) => setCertification({ ...certification, issuer_name: e.target.value })} />
          <Input type="date" value={certification.issued_at} onChange={(e) => setCertification({ ...certification, issued_at: e.target.value })} />
          <label className="sm:col-span-2 text-[12px] text-[var(--product-muted)]" htmlFor="certification-expires-at">만료일<Input id="certification-expires-at" className="mt-1" type="date" value={certification.expires_at} onChange={(e) => setCertification({ ...certification, expires_at: e.target.value })} /></label>
        </div>
        <Button className="mt-3 rounded-full" onClick={() => void addCertification()} disabled={busy !== null}><Plus /> 인증·등록 추가</Button>

        <div className="mt-5 divide-y divide-[var(--product-line-2)]">
          {company.certifications.map((item) => <div key={item.id} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center"><div className="min-w-0 flex-1"><strong className="block truncate text-[14px]">{item.name}</strong><p className="mt-1 text-[12px] text-[var(--product-muted)]">{item.issuer_name ?? '발급기관 미입력'}{item.expires_at ? ` · 만료 ${item.expires_at}` : ''}</p></div><div className="flex gap-2"><Button size="sm" variant="outline" className="rounded-full" onClick={() => void execute(`c:verify:${item.id}`, () => updateCertification(company.id, item.id, { verified: !item.verified }))}><Pencil /> {item.verified ? '증빙 보유' : '증빙 표시'}</Button><Button size="sm" variant="outline" className="rounded-full" onClick={() => void execute(`c:delete:${item.id}`, () => deleteCertification(company.id, item.id))}><Trash2 /> 삭제</Button></div></div>)}
          {!company.certifications.length && <p className="py-5 text-center text-[13px] text-[var(--product-muted)]">등록된 인증·등록 정보가 없습니다.</p>}
        </div>
      </div>
    </section>
  );
}
