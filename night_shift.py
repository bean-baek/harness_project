import io
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exit_codes   # stdlib only — main.py 와 종료 코드 규약을 공유한다 (TS-005)

def _wrap_utf8(stream):
    buf = getattr(stream, "buffer", None)
    if buf is None:
        return stream
    return io.TextIOWrapper(buf, encoding='utf-8', errors='replace', line_buffering=True)

sys.stdout = _wrap_utf8(sys.stdout)
sys.stderr = _wrap_utf8(sys.stderr)

PROJECT_DIR   = Path(__file__).parent
TARGET_DIR    = PROJECT_DIR / "web_target"
FEATURES_PATH = TARGET_DIR / "features.json"


def _resolve_python() -> str:
    if sys.executable and Path(sys.executable).exists():
        return sys.executable
    win_venv = PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
    if win_venv.exists():
        return str(win_venv)
    posix_venv = PROJECT_DIR / ".venv" / "bin" / "python"
    if posix_venv.exists():
        return str(posix_venv)
    return "python"


PYTHON_EXE    = _resolve_python()
LOG_FILE      = PROJECT_DIR / "harness_runtime.log"

MAX_ATTEMPTS_PER_FEATURE = 3
TASK_TIMEOUT_SEC         = 1800  # 30 minutes


class FeaturesFileMissing(Exception):
    pass


def load_features():
    if not FEATURES_PATH.exists():
        raise FeaturesFileMissing(f"features.json not found at {FEATURES_PATH}")
    with FEATURES_PATH.open('r', encoding='utf-8') as fp:
        return json.load(fp)


def get_next_task(skip_ids: set[str]):
    features = load_features()
    for feat in features:
        if feat.get('passes', False):
            continue
        if feat.get('id') in skip_ids:
            continue
        return feat
    return None


def run_harness(task_description: str, session_id: str | None = None) -> int:
    print(f"\n[🚀 High-Speed Mode] 작업 시작: {task_description}")
    print(f"상세 로그: {LOG_FILE} 에서 확인 가능")
    if session_id:
        print(f"세션 ID: {session_id} (반성 메모리 누적)")

    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"\n{'='*60}\n")
        f.write(f"TASK START: {task_description}\n")
        f.write(f"SESSION: {session_id or '(auto)'}\n")
        f.write(f"TIME: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"{'='*60}\n")
        f.flush()

        cmd = [
            PYTHON_EXE, "-u", str(PROJECT_DIR / "main.py"),   # -u: stdout 언버퍼드
            "--task", task_description,
            "--project", str(TARGET_DIR),
        ]
        if session_id:
            cmd += ["--session", session_id]

        child_env = os.environ.copy()
        child_env["PYTHONIOENCODING"] = "utf-8"
        child_env["PYTHONUTF8"] = "1"
        child_env["PYTHONUNBUFFERED"] = "1"   # 파이프 출력 즉시 flush → 타임아웃·로그 정상 동작

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=str(PROJECT_DIR),
            env=child_env,
            bufsize=1,   # 라인 버퍼링
        )

        start     = time.monotonic()
        timed_out = False

        # 별도 스레드에서 stdout 을 읽어 파일/터미널로 중계 —
        # 이렇게 해야 자식이 출력 없이 멈췄을 때도 메인 스레드가 타임아웃을 감지할 수 있다.
        import threading
        def _pump():
            for line in process.stdout:
                print(line, end='', flush=True)
                f.write(line)
                f.flush()
        pump_thread = threading.Thread(target=_pump, daemon=True)
        pump_thread.start()

        while True:
            if process.poll() is not None:
                break
            if time.monotonic() - start > TASK_TIMEOUT_SEC:
                timed_out = True
                break
            time.sleep(1)

        if timed_out:
            process.kill()
            process.wait()
            pump_thread.join(timeout=2)
            msg = f"[⏱ Timeout] {TASK_TIMEOUT_SEC}s 초과 — 프로세스 강제 종료"
            print(msg)
            f.write(f"\n{msg}\n")
            return -1

        pump_thread.join(timeout=2)
        process.wait()

        if process.returncode in exit_codes.FATAL_INFRA:
            # 기능 문제가 아니다 — LLM 공급자 장애 등 인프라 결함 (TS-005).
            # 여기서 attempt 를 소모하면 멀쩡한 기능들이 줄줄이 stuck 으로 마킹된다.
            print(f"[🚨 인프라 장애] {exit_codes.label(process.returncode)} "
                  f"— 기능 탓이 아니므로 attempt 를 소모하지 않습니다")
            f.write(f"\n[INFRA] exit={process.returncode} "
                    f"({exit_codes.label(process.returncode)}) — run aborted\n")
        elif process.returncode != 0:
            print(f"[❌ Error] 작업 중단됨 (Exit Code: {process.returncode})")
            f.write(f"\n[ERROR] Task failed with exit code {process.returncode}\n")
        else:
            print(f"[✅ Success] {task_description} 완료")
            f.write(f"\n[SUCCESS] Task completed\n")

        return process.returncode


def feature_still_failing(feature_id: str) -> bool:
    try:
        features = load_features()
    except FeaturesFileMissing:
        return True
    for feat in features:
        if feat.get('id') == feature_id:
            return not feat.get('passes', False)
    return True


def main() -> int:
    print("=== ⚡ 하네스 엔지니어링 '고속 나이트 시프트' 모드 가동 ===")
    print("유료 API 티어를 감지했습니다. 대기 시간 없이 모든 기능을 순차적으로 정복합니다.\n")

    attempts: dict[str, int] = {}
    stuck: set[str]          = set()

    while True:
        try:
            next_feature = get_next_task(skip_ids=stuck)
        except FeaturesFileMissing as e:
            print(f"[❌ Fatal] {e}")
            return 2

        if not next_feature:
            print("[✅ Success] 모든 기능 구현 완료!")
            break

        feat_id = next_feature.get('id', next_feature.get('description', '<unknown>'))
        attempts[feat_id] = attempts.get(feat_id, 0) + 1
        print(f"\n--- Feature {feat_id} (attempt {attempts[feat_id]}/{MAX_ATTEMPTS_PER_FEATURE}) ---")

        # feature 별로 고정된 session_id 사용 → 이전 시도의 반성 메모리를 자동 로드
        safe_feat_id = re.sub(r'[^A-Za-z0-9_-]', '-', str(feat_id))
        feature_session_id = f"feature-{safe_feat_id}"

        returncode = run_harness(next_feature['description'], session_id=feature_session_id)

        # 인프라 장애(쿼터 초과·인증 실패 등)는 기능 실패가 아니다 (TS-005).
        # attempt 를 되돌리고 런 전체를 즉시 중단한다 — 그대로 계속하면 남은 기능 전부를
        # 몇 초씩 소모하며 stuck 으로 오염시킨다.
        if returncode in exit_codes.FATAL_INFRA:
            attempts[feat_id] -= 1
            print(f"\n=== ⛔ 나이트 시프트 중단 — {exit_codes.label(returncode)} ===")
            print(f"  마지막 작업:  {feat_id} (attempt 미소모, 재실행 시 이어서 시도)")
            print(f"  남은 작업:    features.json 의 passes=false 항목은 그대로 보존됨")
            print(f"  조치:         위 보고서의 '조치' 항목을 처리한 뒤 night_shift.py 를 재실행하십시오")
            return returncode

        # 실패 판정: features.json 에 passes=true 로 업데이트되지 않았으면 실패로 간주 —
        # returncode 0 이어도 (silent-success 포함) feature 가 여전히 fail 이면 stuck 후보.
        still_failing = feature_still_failing(feat_id)
        if still_failing and attempts[feat_id] >= MAX_ATTEMPTS_PER_FEATURE:
            print(f"[⚠ Stuck] {feat_id} — {MAX_ATTEMPTS_PER_FEATURE}회 시도 실패, 건너뜀")
            stuck.add(feat_id)
        elif still_failing:
            print(f"[↻ Retry] {feat_id} — 아직 passes=false (attempt {attempts[feat_id]}/{MAX_ATTEMPTS_PER_FEATURE})")

        time.sleep(2)

    if stuck:
        print("\n=== 건너뛴(stuck) 기능 목록 ===")
        for sid in sorted(stuck):
            print(f"  - {sid}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
