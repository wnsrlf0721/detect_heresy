import Link from "next/link";

export default function PrivacyPage() {
  return (
    <main className="mx-auto w-full max-w-3xl flex-1 space-y-6 px-4 py-10">
      <Link href="/" className="text-sm text-zinc-600 underline">분석 홈</Link>
      <h1 className="text-2xl font-bold">개인정보 처리 안내</h1>
      <section className="space-y-2">
        <h2 className="font-semibold">확장 프로그램에서 보내는 정보</h2>
        <p>팝업에서 동의하고 자동 분석을 켠 뒤 유튜브에서 영상을 재생하면, 영상 ID가 포함된 주소를 분석 서버에 보냅니다. 유튜브 계정과 재생 목록, 주소의 추적 매개변수는 보내지 않습니다.</p>
      </section>
      <section className="space-y-2">
        <h2 className="font-semibold">분석과 결과 저장</h2>
        <p>서버는 영상 주소와 추출한 자막·음성 인식 텍스트·화면 글자, 요약과 판별 결과를 DB에 저장합니다. 결과는 결과 링크나 서비스의 관련 영상 목록을 통해 표시될 수 있습니다.</p>
        <p>영상 분석에는 Anthropic, Voyage AI와 서버 설정에 따라 OpenAI의 API를 사용합니다. 분석에 필요한 영상 프레임, 음성, 텍스트를 해당 기능을 수행하는 API로 보냅니다.</p>
      </section>
      <section className="space-y-2">
        <h2 className="font-semibold">자동 분석 끄기</h2>
        <p>팝업에서 자동 분석을 끄면 새 영상 전송과 상태 확인을 멈추고 브라우저에 저장된 작업 목록을 지웁니다. 이미 접수된 작업은 서버에서 처리될 수 있으며 서버에 저장된 결과는 유지됩니다.</p>
      </section>
    </main>
  );
}
