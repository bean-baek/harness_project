# .harness_memory/ — Reflexion 에피소드 메모리 (1차 자료, 보존)

유료 경로의 Reflector 노드(`harness/nodes/agents.py`)가 **실제 실행 중에 남긴**
반성 기록이다. 27개 세션, 67개 파일, 전부 2026-04-14 자.

```
.harness_memory/
  session-<8자리>/reflection_NNN.json   ← 정상 실행
  debug-00N/reflection_NNN.json         ← 디버깅 실행
  trace-NNNNNN/reflection_NNN.json      ← 추적 실행
```

```json
{
  "iteration": 0,
  "timestamp": "2026-04-14T19:27:04.847527",
  "reflection": "<reflection><attempt>0</attempt><root_cause>…</root_cause>…",
  "metadata": {}
}
```

## 왜 추적(커밋)하는가

**재생성할 수 없는 1차 자료다.** Gemini 프로젝트의 지출 한도가 소진돼 유료 경로를
다시 돌릴 수 없으므로, 이 파일들은 **그 경로가 실제로 작동했다는 유일한 증거**다.
TS-018 에서 "langchain 을 진짜 쓰는가"를 판정할 때 이 파일들이 근거가 됐다.

또한 분석 가치가 있다. `troubleshooting/evidence/F-004-reflexion-confabulation/` 의
"Reflexion 이 오류 신호 없이 근본 원인을 날조한다"는 결론이 이 코퍼스에서 나왔고,
TS-018 이 그 **기계적 원인**(오류 신호가 프롬프트에 아예 들어가지 않았다)을 찾았다.

## 주의

- **읽기 전용으로 다룰 것.** 손으로 고치면 1차 자료로서의 가치가 사라진다.
- 큐레이션된 발췌는 `troubleshooting/evidence/` 에 있다. 결론을 인용할 때는
  그쪽을, 원본을 확인할 때는 이쪽을 본다.
- 같은 세션 ID 로 유료 경로를 재실행하면 `load_episodic_memory` 가 **이 기록을
  프롬프트에 주입**한다. 실험을 격리하려면 새 세션 ID 를 쓰거나
  `HARNESS_MEMORY_DIR` 로 경로를 바꾼다.
- `harness/deadcode.py` 의 감사 범위에서 제외된다 (파이썬 코드가 아니다).
