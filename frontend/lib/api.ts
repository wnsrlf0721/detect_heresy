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

export interface TranscriptResponse {
  id: string;
  status: JobStatus;
  progress: string | null;
  result: TranscriptResult | null;
  error: string | null;
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
    throw new Error(message || `요청이 실패했습니다 (${response.status}).`);
  }
  return response.json();
}

export function createTranscript(url: string): Promise<TranscriptResponse> {
  return request("/transcripts", { method: "POST", body: JSON.stringify({ url }) });
}

export function getTranscript(id: string): Promise<TranscriptResponse> {
  return request(`/transcripts/${id}`);
}

export function createAnalysis(segments: Segment[]): Promise<AnalysisResponse> {
  return request("/analyses", { method: "POST", body: JSON.stringify({ segments }) });
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
