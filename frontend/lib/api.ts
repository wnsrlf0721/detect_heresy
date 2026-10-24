// 백엔드 API 타입과 호출. 타입은 backend/app/schemas/ 의 Pydantic 모델과 맞춘다.

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Source = "user" | "stt" | "ocr" | "caption";
export type Verdict = "safe" | "caution" | "danger";
export type JobStatus = "pending" | "running" | "done" | "failed";

export interface Segment {
  time: string | null;
  text: string;
  source: Source;
}

export interface Reference {
  id: string;
  kind: "orthodox" | "heresy";
  label: string;
  excerpt: string;
}

export interface Finding {
  time: string | null;
  source: Source;
  quote: string;
  score: number;
  group: string | null;
  topic: string | null;
  reason: string;
  orthodox_refutation: string;
  heresy_intent: string | null;
  scripture: string[];
  references: Reference[];
}

export interface AnalysisResult {
  verdict: Verdict;
  score: number;
  summary: string;
  findings: Finding[];
}

export interface AnalysisResponse {
  id: string;
  status: JobStatus;
  result: AnalysisResult | null;
  error: string | null;
}

export interface TranscriptResult {
  title: string;
  duration: number;
  segments: Segment[];
  warnings: string[];
}

export type VideoSource = "caption" | "stt" | "ocr";

export interface VideoTopic {
  title: string;
  summary: string;
  keywords: string[];
}

export interface RelatedVideo {
  id: string;
  url: string;
  title: string;
  topic: string;
  verdict: Verdict;
  score: number;
  similarity: number;
  created_at: string;
}

export interface VideoResponse {
  id: string;
  status: JobStatus;
  url: string;
  sources: VideoSource[];
  created_at: string;
  progress: string | null;
  cached: boolean;
  transcript: TranscriptResult | null;
  result: AnalysisResult | null;
  topic: VideoTopic | null;
  related: RelatedVideo[];
  error: string | null;
}

export interface VideoPreview {
  video_id: string;
  title: string | null;
  author: string | null;
  thumbnail_url: string;
  embeddable: boolean;
}

/** 서버가 응답한 실패. 서버에 닿지 못한 실패는 그냥 Error 다. */
export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    throw new Error(`서버(${API_URL})에 연결하지 못했습니다. 백엔드가 실행 중인지 확인해 주세요.`);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    const message = Array.isArray(detail) ? detail.map((d) => d.msg).join(" ") : detail;
    throw new ApiError(message || `요청이 실패했습니다 (${response.status}).`, response.status);
  }
  return response.json();
}

export function createAnalysis(segments: Segment[]): Promise<AnalysisResponse> {
  return request("/analyses", { method: "POST", body: JSON.stringify({ segments }) });
}

export function getAnalysis(id: string): Promise<AnalysisResponse> {
  return request(`/analyses/${id}`);
}

/** 영상 분석. 같은 영상·출처의 저장된 분석이 있으면 done 으로 바로 돌아온다. force 면 처음부터 다시 한다. */
export function createVideo(url: string, sources: VideoSource[], force = false): Promise<VideoResponse> {
  return request("/videos", { method: "POST", body: JSON.stringify({ url, sources, force }) });
}

export function getVideo(id: string): Promise<VideoResponse> {
  return request(`/videos/${id}`);
}

/** 분석 전에 주소가 맞는 영상인지 확인한다. 주소가 잘못되면 422, 영상이 없거나 비공개면 404 다. */
export function getVideoPreview(url: string, signal?: AbortSignal): Promise<VideoPreview> {
  return request(`/videos/preview?url=${encodeURIComponent(url)}`, { signal });
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
}

/** "02:15" 또는 "1:02:15" 를 초로 바꾼다. */
export function toSeconds(time: string | null): number | null {
  if (!time) return null;
  return time.split(":").reduce((total, part) => total * 60 + Number(part), 0);
}

export function youtubeId(url: string): string | null {
  try {
    const parsed = new URL(url);
    if (parsed.hostname === "youtu.be") return parsed.pathname.slice(1) || null;
    if (parsed.pathname.startsWith("/shorts/")) return parsed.pathname.split("/")[2] || null;
    return parsed.searchParams.get("v");
  } catch {
    return null;
  }
}

export const SOURCE_LABEL: Record<Source, string> = {
  caption: "자막",
  stt: "음성",
  ocr: "화면 글자",
  user: "직접 입력",
};

export const VERDICT_LABEL: Record<Verdict, string> = {
  safe: "안전",
  caution: "주의",
  danger: "위험",
};

// 등급 기준은 backend/app/rag/engine.py 의 CAUTION_MIN, DANGER_MIN 과 같다.
export function verdictOf(score: number): Verdict {
  if (score >= 70) return "danger";
  if (score >= 30) return "caution";
  return "safe";
}
