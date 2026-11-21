import Link from "next/link";
import { Suspense } from "react";

import { SavedVideo } from "@/components/saved-video";

export default function ResultPage() {
  return (
    <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-10">
      <Link href="/" className="text-sm text-zinc-600 underline">분석 홈</Link>
      <h1 className="mb-6 mt-2 text-2xl font-bold">영상 분석 결과</h1>
      <Suspense fallback={<p>결과를 불러오는 중…</p>}>
        <SavedVideo />
      </Suspense>
    </main>
  );
}
