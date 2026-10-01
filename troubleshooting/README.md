# Troubleshooting Log

하네스 프로젝트를 운영하면서 겪은 버그/장애/운영 이슈를 기록하는 저장소.
`web_target/` 내부 기능 구현 이슈가 아닌, **하네스 자체(harness/, main.py, night_shift.py, 환경설정)** 의 문제를 다룬다.

## 디렉토리

```
troubleshooting/
├── README.md        ← 이 파일 (프로토콜 + 인덱스)
├── _template.md     ← 새 엔트리 생성 시 복사용 템플릿
├── INDEX.md         ← 자동 생성 인덱스 (list_troubles 도구가 갱신)
└── TS-NNN-slug.md   ← 개별 엔트리
```

## 파일명 규칙

`TS-<zero-padded-3-digit-id>-<kebab-slug>.md`

예: `TS-001-features-json-path.md`

## 엔트리 스키마 (YAML frontmatter)

```yaml
---
id: TS-001
title: 한 줄 제목
date: 2026-04-14                # 발생 일자 (ISO)
category: runtime | build | config | encoding | concurrency | security | data | other
severity: low | medium | high | critical
status: open | resolved | wontfix
component: relative/path.py     # 가장 관련 깊은 파일 (하나만)
tags: [keyword, keyword]
---
```

## 본문 섹션 (필수)

1. **Symptoms** — 관측한 현상, 에러 메시지 원문, 재현 조건
2. **Root cause** — 왜 발생했는가. 코드 라인/로직까지 명시
3. **Fix** — 적용한 수정. 변경된 파일과 핵심 diff 요약
4. **Verification** — 수정이 실제로 문제를 해결했는지 확인한 절차
5. **Prevention** — 동일 부류 재발 방지 체크리스트 (없으면 생략 가능)

## 에이전트 통합

하네스 내부 도구 (`harness/tools.py`):

- `log_trouble(id, title, category, severity, component, body)` — [STATEFUL] 새 엔트리 생성
- `list_troubles(status)` — [READ_ONLY] 인덱스 조회 (open/resolved/all)
- `read_trouble(id)` — [READ_ONLY] 특정 엔트리 전문 읽기

에이전트는 **동일 증상을 두 번 이상 마주칠 가능성이 있는** 문제만 기록한다.
일회성 오타, 테스트 실패 노이즈는 기록하지 않는다.

## 인덱스

자동 관리: `list_troubles` 호출 시 `INDEX.md`가 갱신된다.
수동 조회는 아래 파일 목록을 참조.
