"use client";

import { useEffect, useRef, useState } from "react";

import {
  AnalysisResult,
  createAnalysis,
  createVideo,
  formatDate,
  getAnalysis,
  getVideo,
  JobStatus,
  Segment,
  SOURCE_LABEL,
  toSeconds,
  TranscriptResult,
  VideoResponse,
  VideoSource,
  youtubeId,
} from "@/lib/api";
import { FindingCard, Gauge, RelatedList, Timeline, TopicPanel, TranscriptPanel } from "@/components/result";

type Mode = "video" | "text";
type Phase = "idle" | "extracting" | "analyzing" | "done" | "error";

const VIDEO_SOURCES: VideoSource[] = ["caption", "stt", "ocr"];
const POLL_MS = 2000;
// POST /analyses 가 한 번에 받는 구간 수 (backend AnalysisRequest.segments 의 max_length)
const MAX_SEGMENTS = 500;

/** 작업이 끝날 때까지 상태를 확인한다. 그 사이 새 분석이 시작되면 null 을 돌려준다. */
async function waitFor<T extends { id: string; status: JobStatus }>(
  job: T,
  fetchJob: (id: string) => Promise<T>,
  isCurrent: () => boolean,
  onUpdate: (job: T) => void = () => {},
): Promise<T | null> {
  onUpdate(job);
  while (job.status === "pending" || job.status === "running") {
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
    if (!isCurrent()) return null;
    job = await fetchJob(job.id);
    onUpdate(job);
  }
  return isCurrent() ? job : null;
}

function useElapsed(running: boolean): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!running) return;
    const started = Date.now();
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [running]);
  return seconds;
}

function Step({ label, state, detail }: { label: string; state: "wait" | "run" | "done"; detail?: string }) {
  return (
    <li className="flex items-center gap-3">
      <span
        className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
          state === "done" ? "bg-emerald-600 text-white" : state === "run" ? "bg-zinc-900 text-white" : "bg-zinc-200 text-zinc-500"
        }`}
      >
        {state === "done" ? "✓" : state === "run" ? <span className="h-2 w-2 animate-ping rounded-full bg-white" /> : ""}
      </span>
      <span className={state === "wait" ? "text-zinc-400" : "text-zinc-900"}>{label}</span>
      {detail && <span className="text-sm text-zinc-500">{detail}</span>}
    </li>
  );
}

export function Analyzer() {
  const [mode, setMode] = useState<Mode>("video");
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [included, setIncluded] = useState<VideoSource[]>(VIDEO_SOURCES);

  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [video, setVideo] = useState<VideoResponse | null>(null);
  const [transcript, setTranscript] = useState<TranscriptResult | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [videoId, setVideoId] = useState<string | null>(null);
  const [startAt, setStartAt] = useState<number | null>(null);
  const [active, setActive] = useState<number | null>(null);

  // 새 분석을 시작하면 이전 분석의 폴링 결과는 버린다.
  const runId = useRef(0);
  const busy = phase === "extracting" || phase === "analyzing";
  const elapsed = useElapsed(busy);

  async function runText(run: number) {
    const segments: Segment[] = text
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => ({ time: null, text: line, source: "user" }));
    if (segments.length > MAX_SEGMENTS) {
      throw new Error(`구간이 ${segments.length}개로 너무 많습니다. (최대 ${MAX_SEGMENTS}개)`);
    }
    setPhase("analyzing");
    const analysis = await waitFor(await createAnalysis(segments), getAnalysis, () => run === runId.current);
    if (!analysis) return;
    if (analysis.status !== "done" || !analysis.result) {
      throw new Error(analysis.error ?? "판별에 실패했습니다.");
    }
    setResult(analysis.result);
    setPhase("done");
  }

  /** 추출부터 대주제 정리까지 한 작업이다. 같은 영상의 저장된 분석이 있으면 바로 끝난다. */
  async function runVideo(run: number, force: boolean) {
    setPhase("extracting");
    const job = await waitFor(
      await createVideo(url.trim(), included, force),
      getVideo,
      () => run === runId.current,
      (job) => {
        setProgress(job.progress);
        if (job.transcript) {
          setTranscript(job.transcript);
          setPhase("analyzing");
        }
      },
    );
    if (!job) return;
    if (job.status !== "done" || !job.result) {
      throw new Error(job.error ?? "영상 분석에 실패했습니다.");
    }
    setVideo(job);
    setResult(job.result);
    setPhase("done");
  }

  function reset(): number {
    setError(null);
    setProgress(null);
    setVideo(null);
    setTranscript(null);
    setResult(null);
    setActive(null);
    setStartAt(null);
    return ++runId.current;
  }

  async function start(force: boolean) {
    const run = reset();
    setVideoId(mode === "video" ? youtubeId(url.trim()) : null);
    try {
      await (mode === "video" ? runVideo(run, force) : runText(run));
    } catch (e) {
      if (run !== runId.current) return;
      setError(e instanceof Error ? e.message : "알 수 없는 오류가 났습니다.");
      setPhase("error");
    }
  }

  /** 비슷한 주제의 이전 분석을 연다. 입력란도 그 영상으로 바꿔서 '다시 분석'할 수 있게 한다. */
  async function openVideo(id: string) {
    const run = reset();
    try {
      const job = await getVideo(id);
      if (run !== runId.current) return;
      setMode("video");
      setUrl(job.url);
      setIncluded(job.sources);
      setVideoId(youtubeId(job.url));
      setVideo({ ...job, cached: true });
      setTranscript(job.transcript);
      setResult(job.result);
      setPhase("done");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      if (run !== runId.current) return;
      setError(e instanceof Error ? e.message : "알 수 없는 오류가 났습니다.");
      setPhase("error");
    }
  }

  function selectFinding(index: number) {
    setActive(index);
    const seconds = toSeconds(result?.findings[index]?.time ?? null);
    if (videoId && seconds !== null) setStartAt(seconds);
    document.getElementById(`finding-${index}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  const canSubmit = !busy && (mode === "video" ? url.trim() !== "" && included.length > 0 : text.trim() !== "");
  const playerSrc = videoId
    ? `https://www.youtube-nocookie.com/embed/${videoId}` + (startAt !== null ? `?start=${startAt}&autoplay=1` : "")
    : null;

  return (
    <div className="space-y-6">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          start(false);
        }}
        className="rounded-2xl border border-zinc-200 bg-white p-6"
      >
        <div className="flex gap-1 rounded-lg bg-zinc-100 p-1 text-sm font-medium sm:w-fit">
          {(["video", "text"] as const).map((value) => (
            <button
              key={value}
              type="button"
              disabled={busy}
              onClick={() => setMode(value)}
              className={`flex-1 whitespace-nowrap rounded-md px-4 py-1.5 ${mode === value ? "bg-white shadow-sm" : "text-zinc-500 hover:text-zinc-800"}`}
            >
              {value === "video" ? "영상 링크" : "텍스트 직접 입력"}
            </button>
          ))}
        </div>

        {mode === "video" ? (
          <>
            <label className="mt-4 block text-sm font-medium" htmlFor="url">
              유튜브 영상 주소
            </label>
            <input
              id="url"
              type="url"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              disabled={busy}
              placeholder="https://youtu.be/..."
              className="mt-1 w-full rounded-lg border border-zinc-300 px-3 py-2 outline-none focus:border-zinc-900 disabled:bg-zinc-50"
            />
            <fieldset className="mt-4">
              <legend className="text-sm font-medium">판별에 포함할 텍스트</legend>
              <div className="mt-1 flex flex-wrap gap-x-5 gap-y-1 text-sm">
                {VIDEO_SOURCES.map((source) => (
                  <label key={source} className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      disabled={busy}
                      checked={included.includes(source)}
                      onChange={(event) =>
                        setIncluded(event.target.checked ? [...included, source] : included.filter((s) => s !== source))
                      }
                    />
                    {SOURCE_LABEL[source]}
                  </label>
                ))}
              </div>
              <p className="mt-1 text-xs text-zinc-500">
                세 가지 모두 영상에서 추출해 보여 주고, 선택한 것만 판별에 씁니다. 자막과 음성에서 같은 발언이 함께 적발되면 하나로 합쳐 보여 줍니다.
                이미 분석한 영상은 저장된 결과를 바로 보여 줍니다.
              </p>
            </fieldset>
          </>
        ) : (
          <>
            <label className="mt-4 block text-sm font-medium" htmlFor="text">
              분석할 문장 (한 줄이 한 구간)
            </label>
            <textarea
              id="text"
              rows={6}
              value={text}
              onChange={(event) => setText(event.target.value)}
              disabled={busy}
              placeholder="설교나 강의에서 들은 문장을 붙여 넣어 주세요."
              className="mt-1 w-full rounded-lg border border-zinc-300 px-3 py-2 outline-none focus:border-zinc-900 disabled:bg-zinc-50"
            />
          </>
        )}

        <button
          type="submit"
          disabled={!canSubmit}
          className="mt-4 rounded-lg bg-zinc-900 px-5 py-2 font-medium text-white hover:bg-zinc-700 disabled:cursor-not-allowed disabled:bg-zinc-300"
        >
          {busy ? "분석 중…" : "분석 시작"}
        </button>
      </form>

      {busy && (
        <section className="rounded-2xl border border-zinc-200 bg-white p-6" aria-live="polite">
          <ol className="space-y-3">
            {mode === "video" && (
              <Step
                label="영상에서 텍스트 추출"
                state={phase === "extracting" ? "run" : "done"}
                detail={phase === "extracting" ? (progress ?? "대기 중") : undefined}
              />
            )}
            <Step
              label="정통 교리와 비교해 판별"
              state={phase === "analyzing" ? "run" : "wait"}
              detail={phase === "analyzing" ? (progress ?? undefined) : undefined}
            />
          </ol>
          <p className="mt-4 text-sm text-zinc-500">
            {Math.floor(elapsed / 60)}분 {elapsed % 60}초 경과 · 몇 분짜리 영상이면 1~2분쯤 걸립니다. 창을 닫지 마세요.
          </p>
        </section>
      )}

      {error && (
        <p role="alert" className="rounded-2xl border border-red-200 bg-red-50 p-4 text-red-800">
          {error}
        </p>
      )}

      {(transcript || result) && (
        <div className="space-y-6">
          {transcript && (
            <section className="rounded-2xl border border-zinc-200 bg-white p-6">
              <h2 className="text-lg font-semibold">{transcript.title}</h2>
              {video?.cached && (
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-zinc-500">
                  <span>저장된 분석 결과 · {formatDate(video.created_at)} 분석</span>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => start(true)}
                    className="rounded-md border border-zinc-300 px-2.5 py-0.5 font-medium text-zinc-700 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:text-zinc-400"
                  >
                    다시 분석
                  </button>
                </div>
              )}
              {playerSrc && (
                <iframe
                  key={playerSrc}
                  src={playerSrc}
                  title={transcript.title}
                  allow="autoplay; encrypted-media; picture-in-picture"
                  allowFullScreen
                  className="mt-4 aspect-video w-full max-w-2xl rounded-xl"
                />
              )}
              {transcript.warnings.map((warning) => (
                <p key={warning} className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
                  {warning}
                </p>
              ))}
            </section>
          )}

          {video?.topic && <TopicPanel topic={video.topic} />}

          {result && (
            <>
              <Gauge result={result} />
              {transcript && <Timeline findings={result.findings} duration={transcript.duration} onSelect={selectFinding} />}
              <section className="space-y-4">
                <h2 className="text-sm font-semibold text-zinc-500">교리 비교 {result.findings.length}건</h2>
                {result.findings.length === 0 && (
                  <p className="rounded-2xl border border-zinc-200 bg-white p-6 text-zinc-600">
                    정통 교리에서 벗어난 발언을 찾지 못했습니다.
                  </p>
                )}
                {result.findings.map((finding, index) => (
                  <FindingCard
                    key={index}
                    id={`finding-${index}`}
                    finding={finding}
                    active={active === index}
                    onSeek={videoId && finding.time ? () => selectFinding(index) : null}
                  />
                ))}
              </section>
            </>
          )}

          {video?.topic && <RelatedList related={video.related} onOpen={openVideo} />}

          {transcript && (
            <TranscriptPanel
              segments={transcript.segments}
              findings={result?.findings ?? []}
              included={video?.sources ?? included}
              onSeek={videoId ? setStartAt : null}
            />
          )}
        </div>
      )}
    </div>
  );
}
