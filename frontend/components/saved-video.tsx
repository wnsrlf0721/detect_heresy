"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Analyzer } from "@/components/analyzer";
import { getVideo, type VideoResponse } from "@/lib/api";

const ANALYSIS_ID = /^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i;

function LoadVideo({ id }: { id: string }) {
  const [job, setJob] = useState<VideoResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    void getVideo(id, controller.signal).then(
      (response) => {
        if (!controller.signal.aborted) setJob(response);
      },
      (reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "결과를 불러오지 못했습니다.");
        }
      },
    );
    return () => controller.abort();
  }, [id]);

  if (error) return <p role="alert" className="text-red-800">{error}</p>;
  if (!job) return <p role="status">결과를 불러오는 중…</p>;
  if (job.status === "failed") return <p role="alert">{job.error ?? "분석에 실패했습니다."}</p>;
  if (job.status !== "done" || !job.result) return <p role="status">분석 결과가 아직 준비되지 않았습니다.</p>;
  return <Analyzer initialVideo={{ ...job, cached: true }} />;
}

export function SavedVideo() {
  const id = useSearchParams().get("analysis") ?? "";
  if (!ANALYSIS_ID.test(id)) return <p role="alert">올바른 분석 결과 링크를 입력해 주세요.</p>;
  return <LoadVideo key={id} id={id} />;
}
