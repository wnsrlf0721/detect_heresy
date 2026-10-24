"use client";

import { useEffect, useRef, useState } from "react";

import {
  AnalysisResult,
  Finding,
  RelatedVideo,
  Segment,
  Source,
  SOURCE_LABEL,
  toSeconds,
  Verdict,
  VERDICT_LABEL,
  verdictOf,
  VideoTopic,
} from "@/lib/api";

const TONE: Record<Verdict, { text: string; bg: string; border: string; stroke: string; dot: string }> = {
  safe: { text: "text-emerald-700", bg: "bg-emerald-50", border: "border-emerald-200", stroke: "#059669", dot: "bg-emerald-500" },
  caution: { text: "text-amber-700", bg: "bg-amber-50", border: "border-amber-200", stroke: "#d97706", dot: "bg-amber-500" },
  danger: { text: "text-red-700", bg: "bg-red-50", border: "border-red-200", stroke: "#dc2626", dot: "bg-red-500" },
};

const TOPIC_LABEL: Record<string, string> = {
  trinity: "신론·삼위일체",
  christology: "기독론",
  soteriology: "구원론",
  revelation: "성경론·계시론",
  ecclesiology: "교회론",
  eschatology: "종말론",
};

/** 종합 의심 지수: 반원 게이지와 등급. */
export function Gauge({ result }: { result: AnalysisResult }) {
  const tone = TONE[result.verdict];
  const length = Math.PI * 80; // 반지름 80 반원의 둘레
  return (
    <section className="rounded-2xl border border-zinc-200 bg-white p-6">
      <h2 className="text-sm font-semibold text-zinc-500">종합 의심 지수</h2>
      <div className="mt-2 flex flex-col items-center gap-6 sm:flex-row sm:items-start">
        <div className="relative w-52 shrink-0">
          <svg viewBox="0 0 200 110" className="w-full" role="img" aria-label={`의심 지수 ${result.score}퍼센트`}>
            <path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="#e4e4e7" strokeWidth="16" strokeLinecap="round" />
            <path
              d="M 20 100 A 80 80 0 0 1 180 100"
              fill="none"
              stroke={tone.stroke}
              strokeWidth="16"
              strokeLinecap="round"
              strokeDasharray={`${(result.score / 100) * length} ${length}`}
            />
          </svg>
          <div className="absolute inset-x-0 bottom-0 text-center">
            <span className="text-4xl font-bold tabular-nums">{result.score}</span>
            <span className="text-lg text-zinc-500">%</span>
          </div>
        </div>
        <div className="flex-1">
          <span className={`inline-block rounded-full border px-3 py-1 text-sm font-semibold ${tone.text} ${tone.bg} ${tone.border}`}>
            {VERDICT_LABEL[result.verdict]}
          </span>
          <span className="ml-2 text-sm text-zinc-500">
            의심 발언 {result.findings.length}건 · 30 이상 주의, 70 이상 위험
          </span>
          <p className="mt-3 leading-7 text-zinc-700">{result.summary}</p>
        </div>
      </div>
    </section>
  );
}

/** 타임라인: 의심 발언이 나온 시점을 영상 길이 위에 표시한다. */
export function Timeline({
  findings,
  duration,
  onSelect,
}: {
  findings: Finding[];
  duration: number;
  onSelect: (index: number) => void;
}) {
  const timed = findings
    .map((finding, index) => ({ finding, index, seconds: toSeconds(finding.time) }))
    .filter((item): item is { finding: Finding; index: number; seconds: number } => item.seconds !== null);
  const end = Math.max(duration, ...timed.map((item) => item.seconds), 1);

  return (
    <section className="rounded-2xl border border-zinc-200 bg-white p-6">
      <h2 className="text-sm font-semibold text-zinc-500">타임라인</h2>
      {timed.length === 0 ? (
        <p className="mt-3 text-sm text-zinc-500">표시할 의심 발언 시점이 없습니다.</p>
      ) : (
        <p className="mt-1 text-sm text-zinc-500">점을 누르면 해당 시점의 영상과 근거로 이동합니다.</p>
      )}
      <div className="relative mt-6 h-3 rounded-full bg-zinc-100">
        {timed.map(({ finding, index, seconds }) => (
          <button
            key={index}
            type="button"
            onClick={() => onSelect(index)}
            title={`${finding.time} · ${SOURCE_LABEL[finding.source]} · ${finding.score}점`}
            className={`absolute top-1/2 h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white shadow ${TONE[verdictOf(finding.score)].dot} hover:scale-125`}
            style={{ left: `${(seconds / end) * 100}%` }}
          >
            <span className="sr-only">{finding.time} 의심 발언으로 이동</span>
          </button>
        ))}
      </div>
      <div className="mt-2 flex justify-between text-xs tabular-nums text-zinc-400">
        <span>00:00</span>
        <span>
          {String(Math.floor(end / 60)).padStart(2, "0")}:{String(Math.floor(end % 60)).padStart(2, "0")}
        </span>
      </div>
    </section>
  );
}

function Column({ title, children, className }: { title: string; children: React.ReactNode; className: string }) {
  return (
    <div className={`rounded-xl border p-4 ${className}`}>
      <h4 className="text-xs font-semibold text-zinc-500">{title}</h4>
      <div className="mt-2 text-sm leading-6 text-zinc-800">{children}</div>
    </div>
  );
}

/** 적발 문장 하나의 3단 비교: 영상 속 발언 ↔ 정통 교리의 반증 ↔ 이단의 원래 의도. */
export function FindingCard({
  finding,
  id,
  active,
  onSeek,
}: {
  finding: Finding;
  id: string;
  active: boolean;
  onSeek: (() => void) | null;
}) {
  const tone = TONE[verdictOf(finding.score)];
  return (
    <article id={id} className={`scroll-mt-4 rounded-2xl border bg-white p-6 ${active ? "border-zinc-900 ring-2 ring-zinc-900/10" : "border-zinc-200"}`}>
      <header className="flex flex-wrap items-center gap-2 text-sm">
        <span className={`rounded-full border px-2.5 py-0.5 font-semibold ${tone.text} ${tone.bg} ${tone.border}`}>
          {VERDICT_LABEL[verdictOf(finding.score)]} {finding.score}점
        </span>
        {finding.time &&
          (onSeek ? (
            <button type="button" onClick={onSeek} className="rounded-full bg-zinc-900 px-2.5 py-0.5 font-medium tabular-nums text-white hover:bg-zinc-700">
              ▶ {finding.time}
            </button>
          ) : (
            <span className="rounded-full bg-zinc-100 px-2.5 py-0.5 tabular-nums">{finding.time}</span>
          ))}
        <span className="rounded-full bg-zinc-100 px-2.5 py-0.5 text-zinc-600">{SOURCE_LABEL[finding.source]}</span>
        {finding.group && <span className="rounded-full bg-zinc-100 px-2.5 py-0.5 text-zinc-600">유사 단체: {finding.group}</span>}
        {finding.topic && <span className="rounded-full bg-zinc-100 px-2.5 py-0.5 text-zinc-600">{TOPIC_LABEL[finding.topic] ?? finding.topic}</span>}
      </header>

      <div className="mt-4 grid gap-3 lg:grid-cols-3">
        <Column title="영상 속 발언" className="border-zinc-200 bg-zinc-50">
          <p className="font-medium">“{finding.quote}”</p>
        </Column>
        <Column title="정통 교리의 반증" className="border-emerald-200 bg-emerald-50/50">
          <p>{finding.orthodox_refutation}</p>
        </Column>
        <Column title="이단의 원래 의도" className="border-red-200 bg-red-50/50">
          <p>{finding.heresy_intent ?? "특정 단체의 교리와 연결할 근거가 없습니다."}</p>
        </Column>
      </div>

      <div className="mt-4">
        <h4 className="text-xs font-semibold text-zinc-500">왜 문제인가</h4>
        <p className="mt-1 text-sm leading-6 text-zinc-800">{finding.reason}</p>
      </div>

      {finding.scripture.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-1.5">
          {finding.scripture.map((verse) => (
            <span key={verse} className="rounded-md border border-zinc-200 px-2 py-0.5 text-xs text-zinc-600">
              {verse}
            </span>
          ))}
        </div>
      )}

      {finding.references.length > 0 && (
        <details className="mt-4 text-sm">
          <summary className="cursor-pointer text-zinc-500 hover:text-zinc-800">근거 문서 {finding.references.length}건</summary>
          <ul className="mt-2 space-y-2">
            {finding.references.map((reference) => (
              <li key={reference.id} className="rounded-lg bg-zinc-50 p-3">
                <span className={`text-xs font-semibold ${reference.kind === "orthodox" ? "text-emerald-700" : "text-red-700"}`}>
                  {reference.kind === "orthodox" ? "정통 교리" : "이단 사례"} · {reference.label}
                </span>
                <p className="mt-1 leading-6 text-zinc-700">{reference.excerpt}</p>
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}

const SPEECH: Source[] = ["caption", "stt"];

/** 적발 하나가 합친 텍스트의 어느 줄에 해당하는지. 자막을 쓴 영상에서 음성으로 적발된 발언은 그 시각의 자막 줄로 잇는다. */
function mergedLineOf(finding: Finding, merged: Segment[]): number {
  const exact = merged.findIndex((segment) => segment.source === finding.source && segment.time === finding.time);
  const seconds = toSeconds(finding.time);
  if (exact !== -1 || !SPEECH.includes(finding.source) || seconds === null) return exact;
  let line = -1;
  merged.forEach((segment, index) => {
    const at = toSeconds(segment.time);
    if (SPEECH.includes(segment.source) && at !== null && at <= seconds) line = index;
  });
  return line;
}

function SegmentLine({
  segment,
  score,
  onSeek,
  badge,
}: {
  segment: Segment;
  score: number | undefined;
  onSeek: ((seconds: number) => void) | null;
  badge?: string;
}) {
  const tone = score === undefined ? null : TONE[verdictOf(score)];
  const seconds = toSeconds(segment.time);
  return (
    <li className={`flex gap-2 rounded-md px-2 py-1 ${tone ? `${tone.bg} ${tone.text}` : ""}`}>
      {onSeek && seconds !== null ? (
        <button type="button" onClick={() => onSeek(seconds)} className="shrink-0 tabular-nums text-zinc-400 hover:text-zinc-900">
          {segment.time}
        </button>
      ) : (
        <span className="shrink-0 tabular-nums text-zinc-400">{segment.time}</span>
      )}
      <span className="leading-6">
        {badge && <span className="mr-1.5 rounded bg-sky-50 px-1.5 py-0.5 text-xs text-sky-700">{badge}</span>}
        {segment.text}
      </span>
    </li>
  );
}

/** 영상에서 추출한 텍스트. 기본은 세 출처를 합친 텍스트이고, 출처별 원문도 볼 수 있다. 적발된 구간은 색으로 표시한다. */
export function TranscriptPanel({
  segments,
  merged,
  findings,
  included,
  onSeek,
}: {
  segments: Segment[];
  merged: Segment[];
  findings: Finding[];
  included: Source[];
  onSeek: ((seconds: number) => void) | null;
}) {
  const [view, setView] = useState<"merged" | "sources">("merged");
  const flagged = new Map(findings.map((finding) => [`${finding.source}|${finding.time}`, finding.score]));
  const mergedScores = new Map<number, number>();
  for (const finding of findings) {
    const line = mergedLineOf(finding, merged);
    if (line !== -1) mergedScores.set(line, Math.max(finding.score, mergedScores.get(line) ?? 0));
  }
  const speech = merged.find((segment) => SPEECH.includes(segment.source))?.source;
  const sources: Source[] = ["caption", "stt", "ocr"];

  return (
    <section className="rounded-2xl border border-zinc-200 bg-white p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-zinc-500">영상 텍스트</h2>
        <div className="flex gap-1 rounded-lg bg-zinc-100 p-1 text-xs font-medium">
          {(["merged", "sources"] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setView(value)}
              className={`rounded-md px-3 py-1 ${view === value ? "bg-white shadow-sm" : "text-zinc-500 hover:text-zinc-800"}`}
            >
              {value === "merged" ? "합친 텍스트" : "출처별 원문"}
            </button>
          ))}
        </div>
      </div>

      {view === "merged" ? (
        <>
          <p className="mt-1 text-xs leading-5 text-zinc-500">
            자막·음성·화면 글자에서 겹치는 내용을 하나로 합쳤습니다. 말은 {speech ? SOURCE_LABEL[speech] : "자막(없으면 음성)"}을
            따르고, 화면 글자는 말과 겹치지 않는 것만 실었습니다.
          </p>
          <ol className="mt-3 max-h-[28rem] space-y-1 overflow-y-auto rounded-xl border border-zinc-200 p-2 text-sm">
            {merged.length === 0 && <li className="p-2 text-zinc-400">추출된 텍스트가 없습니다.</li>}
            {merged.map((segment, index) => (
              <SegmentLine
                key={index}
                segment={segment}
                score={mergedScores.get(index)}
                onSeek={onSeek}
                badge={SPEECH.includes(segment.source) ? undefined : SOURCE_LABEL[segment.source]}
              />
            ))}
          </ol>
        </>
      ) : (
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          {sources.map((source) => {
            const items = segments.filter((segment) => segment.source === source);
            return (
              <div key={source} className="rounded-xl border border-zinc-200">
                <h3 className="flex items-center justify-between border-b border-zinc-200 px-4 py-2 text-sm font-semibold">
                  <span>
                    {SOURCE_LABEL[source]} <span className="font-normal text-zinc-400">{items.length}구간</span>
                  </span>
                  {!included.includes(source) && <span className="text-xs font-normal text-zinc-400">판별 제외</span>}
                </h3>
                <ol className="max-h-96 space-y-1 overflow-y-auto p-2 text-sm">
                  {items.length === 0 && <li className="p-2 text-zinc-400">추출된 텍스트가 없습니다.</li>}
                  {items.map((segment, index) => (
                    <SegmentLine
                      key={index}
                      segment={segment}
                      score={flagged.get(`${segment.source}|${segment.time}`)}
                      onSeek={onSeek}
                    />
                  ))}
                </ol>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

/** 적발을 알린 줄("… (85점)")은 점수에 맞는 색으로 보여 준다. */
function logTone(line: string): string | null {
  const score = line.match(/\((\d+)점\)$/);
  return score ? TONE[verdictOf(Number(score[1]))].text : null;
}

/** AI 진행 과정. 추출과 판별에서 실제로 한 일이 한 줄씩 쌓인다. 진행 중이면 마지막 줄이 지금 하는 일이다. */
export function ThinkingLog({ lines, running }: { lines: string[]; running: boolean }) {
  const list = useRef<HTMLOListElement>(null);
  useEffect(() => {
    if (running) list.current?.scrollTo({ top: list.current.scrollHeight, behavior: "smooth" });
  }, [lines.length, running]);

  if (lines.length === 0) {
    return running ? <p className="animate-pulse text-sm text-zinc-500">작업을 준비하는 중입니다…</p> : null;
  }
  return (
    <ol ref={list} className="max-h-72 space-y-1.5 overflow-y-auto border-l-2 border-zinc-200 pl-4 text-sm leading-6">
      {lines.map((line, index) => {
        const current = running && index === lines.length - 1;
        return (
          <li key={index} className={`animate-log-in ${logTone(line) ?? (current ? "text-zinc-900" : "text-zinc-500")}`}>
            {current && <span className="mr-2 inline-block h-2 w-2 animate-ping rounded-full bg-zinc-900 align-middle" />}
            <span className={current ? "animate-pulse" : ""}>{line}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** 영상 요약. 판별보다 먼저 나와서 결과를 기다리는 동안 읽을 수 있다. 비슷한 주제의 이전 분석을 찾는 기준이기도 하다. */
export function TopicPanel({ topic }: { topic: VideoTopic | null }) {
  if (!topic) {
    return (
      <section className="rounded-2xl border border-zinc-200 bg-white p-6" aria-busy="true">
        <h2 className="text-sm font-semibold text-zinc-500">영상 요약</h2>
        <p className="mt-2 animate-pulse text-zinc-500">AI가 영상 내용을 요약하는 중입니다…</p>
      </section>
    );
  }
  return (
    <section className="rounded-2xl border border-zinc-200 bg-white p-6">
      <h2 className="text-sm font-semibold text-zinc-500">영상 요약</h2>
      <p className="mt-2 text-lg font-semibold">{topic.title}</p>
      <p className="mt-2 leading-7 text-zinc-700">{topic.summary}</p>
      <ul className="mt-3 flex flex-wrap gap-2 text-sm">
        {topic.keywords.map((keyword) => (
          <li key={keyword} className="rounded-full bg-zinc-100 px-2.5 py-0.5 text-zinc-600">
            {keyword}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** 대주제가 비슷한 이전 영상 분석. 누르면 그 분석을 연다. */
export function RelatedList({ related, onOpen }: { related: RelatedVideo[]; onOpen: (id: string) => void }) {
  return (
    <section className="rounded-2xl border border-zinc-200 bg-white p-6">
      <h2 className="text-sm font-semibold text-zinc-500">비슷한 주제의 이전 분석</h2>
      {related.length === 0 ? (
        <p className="mt-3 text-sm text-zinc-500">아직 주제가 비슷한 영상을 분석한 적이 없습니다.</p>
      ) : (
        <ul className="mt-3 divide-y divide-zinc-100">
          {related.map((video) => {
            const tone = TONE[video.verdict];
            return (
              <li key={video.id}>
                <button
                  type="button"
                  onClick={() => onOpen(video.id)}
                  className="flex w-full flex-col gap-1 rounded-lg px-2 py-3 text-left hover:bg-zinc-50 sm:flex-row sm:items-center sm:gap-4"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{video.title || video.url}</span>
                    <span className="block truncate text-sm text-zinc-500">{video.topic}</span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2 text-sm">
                    <span className={`rounded-full border px-2.5 py-0.5 font-semibold ${tone.text} ${tone.bg} ${tone.border}`}>
                      {VERDICT_LABEL[video.verdict]} {video.score}%
                    </span>
                    <span className="tabular-nums text-zinc-400">주제 유사도 {Math.round(video.similarity * 100)}%</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
