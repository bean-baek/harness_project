"""
TS-008 검증 스크립트
────────────────────
'스위트 녹색'을 '이 기능이 검증됨'으로 오인하지 않는지 — 판정 로직 자체를 검증한다.

  1) 태그 매칭 경계 (F-004 가 F-0041 / F-004b 에 오매칭되지 않는가)
  2) 단계 태그 표기 3종 (F-004.5 / F-004-5 / F-004#5) 과 오매칭 방어
  3) 수준별 판정: suite / feature / step
  4) 회귀 우선: 스위트가 빨간불이면 태그가 있어도 통과 불가
  5) 태그 테스트가 실패 중이면 통과 불가
  6) 증거 기록 형식 (to_dict)
  7) jest 런처 안전장치 — jest 설정 없는 디렉터리에서 사용자 홈을 스캔하지 않는다
  8) audit_features — jest 1회 실행으로 여러 기능 일괄 감사

jest 실행은 전부 스텁/가짜 JSON. 실제 API·네트워크 접근 없음.
"""
import json
import sys
import tempfile
import time
from pathlib import Path

# 재현 스크립트는 verification/ 에 있으므로 루트는 한 단계 위다.
# 주의: 일부 검증이 "web_target" 을 **상대 경로**로 쓰므로 반드시
# 레포 루트에서 실행해야 한다 (`python verification/repro_tsXXX.py`).
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from harness import verify
from harness.verify import (
    Verification,
    audit_features,
    feature_tag_pattern,
    jest_launcher,
    run_jest_json,
    step_tag_pattern,
    verify_feature,
)

ok = 0
fail = 0


def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1
        print(f"  PASS  {name}  -> {got!r}")
    else:
        fail += 1
        print(f"  FAIL  {name}  got={got!r} want={want!r}")


def fake_results(tests):
    passed = sum(1 for _, s in tests if s == "passed")
    failed = sum(1 for _, s in tests if s == "failed")
    return {
        "numTotalTests": len(tests),
        "numPassedTests": passed,
        "numFailedTests": failed,
        "numTotalTestSuites": 1,
        "numFailedTestSuites": 1 if failed else 0,
        "testResults": [{
            "name": "fake.test.tsx",
            "assertionResults": [
                {"fullName": n, "title": n, "ancestorTitles": [], "status": s}
                for n, s in tests
            ],
        }],
    }


FEATURE = {
    "id": "F-004",
    "description": "사용자가 로그아웃할 수 있다",
    "steps": ["대시보드 접속", "메뉴 클릭", "로그아웃 클릭", "/login 이동", "토큰 삭제"],
}


print("\n[1] 기능 태그 매칭 경계")
pat = feature_tag_pattern("F-004")
check("정확 매칭", bool(pat.search("F-004: 로그아웃")), True)
check("문장 중간 매칭", bool(pat.search("로그아웃 (F-004) 검증")), True)
check("F-0041 오매칭 방어", bool(pat.search("F-0041: 다른 기능")), False)
check("F-004b 오매칭 방어", bool(pat.search("F-004b: 변형")), False)
check("XF-004 오매칭 방어", bool(pat.search("XF-004")), False)
check("다른 기능 ID 불일치", bool(pat.search("F-015: 순위표")), False)

print("\n[2] 단계 태그 표기")
check("점 표기", bool(step_tag_pattern("F-004", 5).search("F-004.5: 토큰 삭제")), True)
check("하이픈 표기", bool(step_tag_pattern("F-004", 5).search("F-004-5 토큰 삭제")), True)
check("샵 표기", bool(step_tag_pattern("F-004", 5).search("F-004#5 토큰 삭제")), True)
check("0 패딩 허용", bool(step_tag_pattern("F-004", 5).search("F-004.05")), True)
check("단계 5 가 50 에 오매칭 안 됨", bool(step_tag_pattern("F-004", 5).search("F-004.50")), False)
check("단계 3 과 4 구분", bool(step_tag_pattern("F-004", 3).search("F-004.4")), False)

print("\n[3] 수준별 판정 — 태그 없는 녹색 스위트")
untagged = fake_results([("완전히 무관한 테스트", "passed")])
v = verify_feature("x", FEATURE, level="suite", results=untagged)
check("suite 수준: 통과 (하위 호환)", v.ok, True)
v = verify_feature("x", FEATURE, level="feature", results=untagged)
check("feature 수준: 거부", v.ok, False)
check("거부 사유", "이 기능의 증거가 아닙니다" in v.reason, True)
check("태그 작성법 안내 포함", 'describe("F-004' in v.reason, True)

print("\n[4] 수준별 판정 — 기능 태그만 있고 단계 태그는 일부")
partial = fake_results([
    ("F-004: 로그아웃 동작", "passed"),
    ("F-004.5: 토큰 삭제", "passed"),
    ("무관한 테스트", "passed"),
])
v = verify_feature("x", FEATURE, level="feature", results=partial)
check("feature 수준: 통과", v.ok, True)
check("증거 2건", len(v.tagged_passed), 2)
check("단계 커버리지 측정", (v.steps_covered, v.steps_uncovered), ([5], [1, 2, 3, 4]))
v = verify_feature("x", FEATURE, level="step", results=partial)
check("step 수준: 거부", v.ok, False)
check("미검증 단계 명시", "[1, 2, 3, 4]" in v.reason, True)

print("\n[5] 전 단계 태그 → step 수준도 통과")
full = fake_results([
    (f"F-004.{i}: 단계 {i}", "passed") for i in range(1, 6)
])
v = verify_feature("x", FEATURE, level="step", results=full)
check("step 수준: 통과", v.ok, True)
check("단계 5/5", v.steps_covered, [1, 2, 3, 4, 5])
check("미검증 없음", v.steps_uncovered, [])

print("\n[6] 회귀 우선 — 스위트 빨간불이면 태그가 있어도 불가")
regressed = fake_results([
    ("F-004: 로그아웃 동작", "passed"),
    ("다른 기능의 테스트", "failed"),
])
for lvl in ("suite", "feature", "step"):
    v = verify_feature("x", FEATURE, level=lvl, results=regressed)
    check(f"{lvl} 수준 거부", v.ok, False)
check("사유가 회귀", "실패 테스트" in verify_feature("x", FEATURE, results=regressed).reason, True)

print("\n[7] 태그 테스트 자체가 실패 중")
tag_failed = fake_results([
    ("F-004.3: 로그아웃 클릭", "failed"),
    ("무관한 테스트", "passed"),
])
v = verify_feature("x", FEATURE, results=tag_failed)
check("거부", v.ok, False)
check("실패한 태그 테스트 보고", len(v.tagged_failed), 1)

print("\n[8] 테스트 0건")
v = verify_feature("x", FEATURE, results=fake_results([]))
check("거부", v.ok, False)
check("사유", "테스트가 0건" in v.reason, True)

print("\n[9] 증거 기록 형식")
v = verify_feature("x", FEATURE, level="feature", results=partial)
d = v.to_dict()
check("level 기록", d["level"], "feature")
check("스위트 통계 기록", d["suite"]["total"], 3)
check("증거 테스트 이름 기록", "F-004.5: 토큰 삭제" in d["evidence_tests"], True)
check("미검증 단계 기록", d["steps_uncovered"], [1, 2, 3, 4])
check("요약 문자열", "tagged 2 passed" in d["summary"], True)
check("JSON 직렬화 가능", bool(json.dumps(d, ensure_ascii=False)), True)

print("\n[10] jest 런처 안전장치 (사용자 홈 스캔 방지)")
empty = Path(tempfile.mkdtemp(prefix="ts008-empty-"))
(empty / "features.json").write_text("[]", encoding="utf-8")
check("jest 설정 없으면 런처 None", jest_launcher(str(empty)), None)
t0 = time.monotonic()
results, diag = run_jest_json(str(empty))
elapsed = time.monotonic() - t0
check("즉시 실패 (홈 디렉터리 스캔 안 함)", elapsed < 5.0, True)
check("결과 없음", results, None)
check("진단 메시지", "jest" in diag, True)
v = verify_feature(str(empty), FEATURE)
check("검증도 거부", v.ok, False)

pkg_only = Path(tempfile.mkdtemp(prefix="ts008-pkg-"))
(pkg_only / "package.json").write_text('{"name":"x"}', encoding="utf-8")
check("jest 설정 없는 package.json 만으로는 폴백 안 함", jest_launcher(str(pkg_only)), None)
(pkg_only / "jest.config.js").write_text("module.exports={};", encoding="utf-8")
launcher = jest_launcher(str(pkg_only))
check("jest.config 있으면 npx 폴백", launcher is not None and "--no-install" in launcher, True)

print("\n[11] audit_features — jest 1회로 일괄 감사")
calls = []
original = verify.run_jest_json


def _stub(project_root):
    calls.append(project_root)
    return partial, ""


verify.run_jest_json = _stub
try:
    features = [
        FEATURE,
        {"id": "F-015", "description": "순위표", "steps": ["a", "b"]},
    ]
    audited = audit_features("x", features)
    check("감사 결과 2건", len(audited), 2)
    check("jest 는 1회만 실행", len(calls), 1)
    check("F-004 통과", audited[0][1].ok, True)
    check("F-015 거부", audited[1][1].ok, False)
finally:
    verify.run_jest_json = original

print(f"\n{'='*60}")
print(f"TS-008 검증 결과: PASS {ok} / FAIL {fail}")
print(f"{'='*60}")
sys.exit(1 if fail else 0)
