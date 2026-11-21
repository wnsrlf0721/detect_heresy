"use client";

import { useEffect, useRef, useState } from "react";

import {
  AnalysisResult,
  ApiError,
  createAnalysis,
  createVideo,
  formatDate,
  getAnalysis,
  getVideo,
  getVideoPreview,
  JobStatus,
  Segment,
  toSeconds,
  TranscriptResult,
  VideoPreview,
  VideoResponse,
  youtubeId,
} from "@/lib/api";
import { FindingCard, Gauge, RelatedList, ThinkingLog, Timeline, TopicPanel, TranscriptPanel } from "@/components/result";

type Mode = "video" | "text";
type Phase = "idle" | "extracting" | "analyzing" | "done" | "error";

const POLL_MS = 2000;
// 주소를 입력하는 동안에는 확인하지 않고, 입력이 멈추면 한 번 확인한다.
const PREVIEW_DELAY_MS = 500;
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

type Preview =
  | { state: "checking"; url: string }
  | { state: "found"; url: string; video: VideoPreview }
  | { state: "missing"; url: string; message: string } // 잘못된 주소이거나 영상이 없다
  | { state: "error"; url: string; message: string }; // 확인하지 못했다 (분석은 해 볼 수 있다)

/** 입력한 주소가 볼 수 있는 유튜브 영상인지 확인한다. 주소가 비어 있으면 null 이다. */
function usePreview(url: string): Preview | null {
  const [preview, setPreview] = useState<Preview | null>(null);
  useEffect(() => {
    if (!url) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setPreview({ state: "checking", url });
      try {
        const video = await getVideoPreview(url, controller.signal);
        if (!controller.signal.aborted) setPreview({ state: "found", url, video });
      } catch (e) {
        if (controller.signal.aborted) return;
        const message = e instanceof Error ? e.message : "영상을 확인하지 못했습니다.";
        const missing = e instanceof ApiError && (e.status === 404 || e.status === 422);
        setPreview({ state: missing ? "missing" : "error", url, message });
      }
    }, PREVIEW_DELAY_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [url]);
  // 주소가 바뀐 직후에는 이전 주소의 결과를 보여 주지 않는다.
  return url && preview?.url === url ? preview : null;
}

function PreviewBox({ preview }: { preview: Preview }) {
  if (preview.state === "checking") {
    return <p className="text-sm text-zinc-500">영상을 확인하는 중…</p>;
  }
  if (preview.state !== "found") {
    return (
      <p className={`text-sm ${preview.state === "missing" ? "text-red-700" : "text-amber-700"}`}>
        {preview.state === "missing" ? "✕ " : "! "}
        {preview.message}
      </p>
    );
  }
  const { video } = preview;
  return (
    <div className="max-w-sm">
      <p className="text-sm text-emerald-700">✓ 영상을 찾았습니다</p>
      {video.embeddable ? (
        <iframe
          src={`https://www.youtube-nocookie.com/embed/${video.video_id}`}
          title={video.title ?? "영상 미리보기"}
          allow="encrypted-media; picture-in-picture"
          allowFullScreen
          className="mt-2 aspect-video w-full rounded-lg border border-zinc-200"
        />
      ) : (
        // eslint-disable-next-line @next/next/no-img-element -- 외부 썸네일 한 장이라 next/image 설정을 두지 않는다.
        <img src={video.thumbnail_url} alt="" className="mt-2 aspect-video w-full rounded-lg border border-zinc-200 object-cover" />
      )}
      {video.title && <p className="mt-2 text-sm font-medium leading-5">{video.title}</p>}
      {video.author && <p className="text-xs text-zinc-500">{video.author}</p>}
      {!video.embeddable && <p className="mt-1 text-xs text-zinc-500">퍼가기가 막힌 영상이라 여기서는 재생할 수 없습니다.</p>}
    </div>
  );
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

function Step({ label, state }: { label: string; state: "wait" | "run" | "done" }) {
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
    </li>
  );
}

export function Analyzer() {
  const [mode, setMode] = useState<Mode>("video");
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");

  const [phase, setPhase] = useState<Phase>("idle");
  const [log, setLog] = useState<string[]>([]);
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
  const preview = usePreview(mode === "video" ? url.trim() : "");

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
    const analysis = await waitFor(
      await createAnalysis(segments),
      getAnalysis,
      () => run === runId.current,
      (job) => setLog(job.log),
    );
    if (!analysis) return;
    if (analysis.status !== "done" || !analysis.result) {
      throw new Error(analysis.error ?? "판별에 실패했습니다.");
    }
    setResult(analysis.result);
    setPhase("done");
  }

  /** 추출 → 요약과 판별까지 한 작업이다. 같은 영상의 저장된 분석이 있으면 바로 끝난다.
   * 추출이 끝나면 합친 텍스트를, 요약이 끝나면 요약을 판별 결과보다 먼저 보여 준다. */
  async function runVideo(run: number, force: boolean) {
    setPhase("extracting");
    const job = await waitFor(
      await createVideo(url.trim(), force),
      getVideo,
      () => run === runId.current,
      (job) => {
        setLog(job.log);
        setVideo(job);
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
    setLog([]);
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
      setVideoId(youtubeId(job.url));
      setVideo({ ...job, cached: true });
      setLog(job.log);
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

  const canSubmit =
    !busy &&
    (mode === "video" ? url.trim() !== "" && preview?.state !== "missing" : text.trim() !== "");
  // 아래 결과에 같은 영상의 플레이어가 이미 있으면 미리보기는 숨긴다.
  const showPreview =
    preview !== null && !busy && !(preview.state === "found" && preview.video.video_id === videoId && (transcript || result));
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
            <p className="mt-2 text-xs text-zinc-500">
              사람이 작성한 한국어 자막을 우선 사용합니다. 자막을 가져올 수 없으면 음성을 받아씁니다. 화면 글자도 함께 분석합니다.
            </p>
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

        {mode === "video" && showPreview && (
          <div className="mt-4 border-t border-zinc-100 pt-4" aria-live="polite">
            <PreviewBox preview={preview} />
          </div>
        )}
      </form>

      {error && (
        <p role="alert" className="rounded-2xl border border-red-200 bg-red-50 p-4 text-red-800">
          {error}
        </p>
      )}

      {(busy || transcript || result) && (
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

          {/* 요약은 판별보다 먼저 끝나므로, 판별을 기다리는 동안 읽을 수 있다. */}
          {transcript && (video?.topic || busy) && <TopicPanel topic={video?.topic ?? null} />}

          {busy && (
            <section className="rounded-2xl border border-zinc-200 bg-white p-6" aria-live="polite">
              <ol className="space-y-3">
                {mode === "video" && (
                  <Step label="영상에서 텍스트 추출" state={phase === "extracting" ? "run" : "done"} />
                )}
                <Step label="정통 교리와 비교해 이단성 판별" state={phase === "analyzing" ? "run" : "wait"} />
              </ol>
              <h3 className="mt-6 text-xs font-semibold text-zinc-500">AI 진행 과정</h3>
              <div className="mt-2">
                <ThinkingLog lines={log} running />
              </div>
              <p className="mt-4 text-sm text-zinc-500">
                {Math.floor(elapsed / 60)}분 {elapsed % 60}초 경과 · 분석 시간은 영상과 판별할 구간 수에 따라 달라집니다.
              </p>
            </section>
          )}

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

          {result && video?.topic && <RelatedList related={video.related} onOpen={openVideo} />}

          {transcript && (
            <TranscriptPanel
              segments={transcript.segments}
              merged={transcript.merged}
              findings={result?.findings ?? []}
              included={video?.sources ?? []}
              onSeek={videoId ? setStartAt : null}
            />
          )}
        </div>
      )}

      {!busy && log.length > 0 && (
        <details className="rounded-2xl border border-zinc-200 bg-white p-6">
          <summary className="cursor-pointer text-sm font-semibold text-zinc-500 hover:text-zinc-800">
            AI 진행 과정 {log.length}단계 보기
          </summary>
          <div className="mt-4">
            <ThinkingLog lines={log} running={false} />
          </div>
        </details>
      )}
    </div>
  );
}
