// 검증 제약(`required`·`minLength`·`maxLength`·`pattern`)을 **일부러** 담은 픽스처.
//
// `web_target` 에는 이 네 가지가 하나도 없다(실측). 규칙만 써 두고 한 번도 매칭되지
// 않으면 '발견 0건'과 '검사기 고장'을 구별할 수 없다 (TS-016). 그래서 여기에 심어
// `repro_ts028.py` 가 고정한다 — 두 번째 모양으로 검증하는 TS-025 의 규약이다.
//
// 이 파일은 런너가 돌지 않는다. 명세 초안 추출기가 **읽기만** 한다.

export function SignupForm({ loading, nameError }) {
  return (
    <form>
      <label htmlFor="signup-name">이름</label>
      <input
        id="signup-name"
        type="text"
        required
        minLength={2}
        maxLength={40}
        aria-invalid={!!nameError}
        disabled={loading}
      />

      <label htmlFor="signup-zip">우편번호</label>
      <input id="signup-zip" type="text" pattern="[0-9]{5}" required />

      <button type="submit" disabled={loading}>
        가입
      </button>
    </form>
  );
}
