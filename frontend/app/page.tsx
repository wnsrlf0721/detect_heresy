import { Analyzer } from "@/components/analyzer";

export default function Home() {
  return (
    <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-10">
      <header className="mb-8">
        <h1 className="text-2xl font-bold">이단성 분석</h1>
        <p className="mt-2 text-zinc-600">
          영상이나 문장을 정통 개신교 교리와 비교해, 어떤 발언이 왜 문제인지 근거와 함께 보여 줍니다.
        </p>
      </header>
      <Analyzer />
      <footer className="mt-10 text-sm leading-6 text-zinc-500">
        이 결과는 AI가 만든 참고 자료이며 최종 판단이 아닙니다. 비교 기준이 되는 교리 자료는 아직 원출처와 대조하지 않은 초안입니다.
      </footer>
    </main>
  );
}
