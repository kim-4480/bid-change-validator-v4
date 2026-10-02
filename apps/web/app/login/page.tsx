'use client';

import { useEffect, useState, type SyntheticEvent } from 'react';
import { Building2, LoaderCircle, LockKeyhole, ShieldCheck } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ApiError } from '@/lib/api';
import { getCurrentUser, login } from '@/lib/auth';
import { replaceWith } from '@/lib/navigation';

export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    void getCurrentUser()
      .then((current) => {
        if (current) replaceWith('/company');
      })
      .catch(() => undefined);
  }, []);

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(username, password);
      replaceWith('/company');
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : '로그인 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.',
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-[var(--product-tint)] px-5 py-10 sm:grid sm:place-items-center">
      <div className="mx-auto grid w-full max-w-5xl overflow-hidden rounded-3xl border border-[var(--product-line)] bg-white shadow-[0_24px_80px_rgba(20,33,61,0.12)] lg:grid-cols-[1.05fr_0.95fr]">
        <section className="hidden min-h-[620px] flex-col justify-between bg-[#14213d] p-12 text-white lg:flex">
          <div className="flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded-xl bg-[var(--product-accent)]">
              <Building2 className="size-5" />
            </span>
            <span className="text-lg font-bold">비드체크</span>
          </div>
          <div className="max-w-md">
            <p className="mb-4 text-sm font-semibold text-blue-200">입찰 참가자격 사전검토</p>
            <h1 className="text-4xl font-bold leading-[1.35] tracking-[-0.04em]">
              우리 회사 기준으로
              <br />공고를 바로 검토합니다
            </h1>
            <p className="mt-6 text-base leading-7 text-slate-300">
              로그인하면 소속 회사 프로필이 자동으로 연결되고, 공고 조건과 변경 영향을
              원문 근거와 함께 확인할 수 있습니다.
            </p>
          </div>
          <div className="flex items-center gap-3 text-sm text-slate-300">
            <ShieldCheck className="size-5 text-blue-300" />
            회사별 프로필과 검토 내역을 분리해 관리합니다.
          </div>
        </section>

        <section className="flex min-h-[620px] items-center px-6 py-12 sm:px-12">
          <Card className="w-full border-0 bg-transparent shadow-none ring-0">
            <CardHeader className="px-0">
              <div className="mb-6 grid size-12 place-items-center rounded-2xl bg-blue-50 text-[var(--product-accent)] lg:hidden">
                <Building2 className="size-6" />
              </div>
              <CardTitle className="text-2xl font-bold tracking-[-0.03em]">로그인</CardTitle>
              <CardDescription className="mt-2 text-base leading-6">
                회사 계정으로 접속해 입찰 검토를 시작하세요.
              </CardDescription>
            </CardHeader>
            <CardContent className="px-0 pt-4">
              <form className="space-y-5" onSubmit={submit}>
                <div className="space-y-2">
                  <Label htmlFor="username">아이디</Label>
                  <Input
                    id="username"
                    name="username"
                    autoComplete="username"
                    className="h-11 px-3 text-base"
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="password">비밀번호</Label>
                  <Input
                    id="password"
                    name="password"
                    type="password"
                    autoComplete="current-password"
                    className="h-11 px-3 text-base"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    required
                  />
                </div>
                {error && (
                  <p role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm leading-6 text-red-700">
                    {error}
                  </p>
                )}
                <Button type="submit" size="lg" className="mt-2 h-11 w-full text-base" disabled={loading}>
                  {loading ? <LoaderCircle className="animate-spin" /> : <LockKeyhole />}
                  {loading ? '로그인 중' : '로그인'}
                </Button>
              </form>
            </CardContent>
          </Card>
        </section>
      </div>
    </main>
  );
}
