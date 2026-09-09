# 더 읽을 것

Rift Foundry의 설계 근거와 계산 규칙을 담은 문서 색인입니다. 프로젝트
개요와 시작 방법은 [`../README.md`](../README.md)를 참고하세요.

| 문서 | 내용 |
|---|---|
| [`overview.md`](overview.md) | 설계 접근 방식, 교전/빌드 계산 상세, 범위 밖 근거 |
| [`../TASKS.md`](../TASKS.md) | 전체 작업 계획, 완료 조건, 현재 근거 — 단일 진실 공급원 |
| [`architecture.md`](architecture.md) | 패키지 경계와 의존 방향 |
| [`combat-math.md`](combat-math.md) | 저항·관통·EHP·가속 공식 |
| [`timeline-semantics.md`](timeline-semantics.md) | 이벤트 처리 순서와 CC 보정 경계 |
| [`candidate-generation.md`](candidate-generation.md) | 아이템 후보 생성과 하드 필터(비-릴리즈 프로토타입 경로 기준 — 실제 엔진은 별도 구현) |
| [`selection-semantics.md`](selection-semantics.md) | 실제 추천 엔진의 분기 게이트·순위 규칙과 3분기 선택 |
| [`response-channel-costs.md`](response-channel-costs.md) | 포지셔닝~아이템 6채널 대응 비용 모델 |
| [`cc-interaction-matrix.md`](cc-interaction-matrix.md) | CC 상호작용 검증 큐 |
| [`provenance-contract.md`](provenance-contract.md) | MEASURED/CALCULATED/UNVERIFIED 계약 |
| [`pipeline-readiness.md`](pipeline-readiness.md) | 추천 게이트 3축과 오프라인 실행 |
| [`web-ui.md`](web-ui.md) | Web UI 사용법과 JSON 엔드포인트 |
| [`champion-profile-jax-v1.md`](champion-profile-jax-v1.md) | 첫 챔피언 프로필 사례 — 지속형 근접 온히트 벤치마크 |
| [`rotation-preview.md`](rotation-preview.md) | 계산됐지만 미검증인 Jax 로테이션 프리뷰 |
| [`adr/0001-runtime-and-testing.md`](adr/0001-runtime-and-testing.md) | ADR-0001: 런타임·테스트 컨벤션 |
| [`adr/0002-restricted-numeric-expression.md`](adr/0002-restricted-numeric-expression.md) | ADR-0002: 제한된 수치 표현식 트리 |
| [`adr/0003-role-neutral-champion-cogs.md`](adr/0003-role-neutral-champion-cogs.md) | ADR-0003: 역할 중립 챔피언 Cog 설계 |
