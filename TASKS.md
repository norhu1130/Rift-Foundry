# Tasks — Rift Foundry (LoL Build Recommendation Engine)

Phase 0(M0) 작업과 이후 Phase 1(`P1-*`)·연기(`D-*`) 작업을 함께 관리한다.

Phase 0 목표: 한 챔피언과 한 개의 결정론적 전투 시나리오에서 패치가 잠긴 로컬
데이터만 사용해 기본안·공격 분기·방어 분기를 재현 가능하게 생성한다.

기간: 5주, 1~2인 사이드 프로젝트 기준

## 상태와 우선순위

- 상태:
  - `TODO` — 미착수
  - `IN_PROGRESS` — 진행 중
  - `DONE` — 완료 조건 전부 충족
  - `DONE_NON_RELEASE` — 구현 완료, 단 결과가 미검증 근거에 의존해
    `release_eligible=false`
  - `PARTIAL` — 핵심 결정·산출물은 있으나 완료 조건 일부만 충족
  - `BLOCKED` — 코드 밖 선행 조건(주로 16.17.1 클라이언트 실측) 대기
  - `DEFERRED` — 의도적으로 연기
  - `MERGED` — 다른 Task로 흡수
- 게이트 상태: `PASS`, `PARTIAL`, `BLOCKED_CLIENT_MEASUREMENT`
- 우선순위: `P0`은 M0 필수, `P1`은 시간이 허용되면 수행
- 각 Task는 완료 조건을 모두 만족해야 `DONE`으로 바꾼다.
- 패치가 검증되지 않은 메커니즘은 계산에서 조용히 추정하지 않는다.

## 의존성 경로

```text
P0-010 ─┬─ P0-014 ─ P0-015 ─ P0-017
        └─ P0-016

P0-011 ─┬─ P0-013 ─ P0-016
        └─ P0-020 ─ P0-021 ─ P0-022

P0-012 ─ P0-013 ─ P0-040 ─ P0-041 ─ P0-042

P0-030..035 ─┬─ P0-044 ─ P0-045 ─ P0-051
P0-042..043 ─┘                    └─ P0-052..054
```

## 이미 완료된 작업

### P0-001 — 시나리오 JSON Schema v1

- 상태: `DONE`
- 산출물: `schemas/scenario-profile.schema.json`
- 포함 범위:
  - actor, 룬, 소환사 주문
  - 결정론적 CC 이벤트
  - 재현 레시피와 검증 스탯 스냅샷
  - 물리/마법/고정 피해 비중
  - 목적함수 벡터와 분기 선택 정책

### P0-002 — 후보 선택 의미론 v1

- 상태: `DONE`
- 산출물: `docs/selection-semantics.md`
- 포함 범위:
  - branch-local kill gate
  - epsilon-Pareto 적용 순서
  - 혼합 피해 EHP 정의
  - 미검증 메커니즘 처리 원칙

---

## Week 1 — 계약을 실행 가능하게 만들기

### P0-010 — 구현 런타임과 프로젝트 규약 결정

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 0.5일
- 선행: 없음
- 작업:
  - 구현 언어와 지원 버전을 결정한다.
  - JSON Schema validator, 테스트 러너, 포매터를 결정한다.
  - 부동소수점 허용 오차와 결정론적 직렬화 규칙을 정한다.
- 산출물: `docs/adr/0001-runtime-and-testing.md`, 최소 프로젝트 골격
- 완료 조건:
  - 빈 테스트 스위트가 로컬에서 실행된다.
  - CI와 로컬이 같은 명령을 사용하도록 명령 하나로 고정돼 있다.

### P0-011 — 패치 락 스키마와 잠금 파일 작성

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 0.5일
- 선행: 없음
- 작업:
  - region, game patch, Data Dragon build, Community Dragon revision을 기록한다.
  - 각 원본 파일의 URL, 수집 시각, SHA-256, locale을 기록한다.
  - Data Dragon과 지역 클라이언트 버전 불일치 상태를 표현한다.
- 산출물: `schemas/patch-lock.schema.json`, `patch.lock.json`
- 완료 조건:
  - 잠금 파일이 스키마를 통과한다.
  - 해시가 하나라도 다르면 데이터 로딩이 실패한다.

### P0-012 — 메커니즘 사실 레코드 스키마 작성

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 0.5일
- 선행: 없음
- 작업:
  - `tenacity_reducible`, `cleanse_removable`, `qss_removable`,
    `immunity_resistible`을 분리한다.
  - `UNVERIFIED`, `VERIFIED`, `STALE`, `REJECTED` 상태를 둔다.
  - 마지막 변경 근거, 이후 변경 검색 범위, 실측 근거를 저장한다.
- 산출물: `schemas/mechanic-fact.schema.json`
- 완료 조건:
  - 실명·기절·둔화 레코드를 각각 작성할 수 있다.
  - 미검증 레코드는 release-eligible 계산에 사용할 수 없다.

### P0-013 — 첫 시나리오 fixture 확정

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 1일
- 선행: P0-011, P0-012
- 작업:
  - actor 챔피언과 역할을 하나 선택한다.
  - 상대 챔피언, 13레벨, 고정 아이템 2개를 선택한다.
  - 8초 회전과 3초 처치 문턱을 재현하는 절차를 적는다.
  - 결정론적 실명 이벤트의 시점과 지속시간을 정한다.
  - 상대의 원시 피해 비중 산출 방법을 기록한다.
- 산출물: `fixtures/scenarios/duel_l13_8s_blind_v1.json`
- 완료 조건:
  - 모든 수치가 `patch.lock.json` 또는 실측 근거로 추적된다.
  - 연습 도구로 불가능한 CC 재현은 `CUSTOM_GAME`으로 명시한다.
  - fixture가 시나리오 스키마를 통과한다.

### P0-014 — 최소 수치 식 트리 정의

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 1일
- 선행: P0-010
- 작업:
  - `Constant`, `Stat`, `Add`, `Multiply`, `LevelCurve`만 도입한다.
  - stat scope를 base, bonus, total, target으로 구분한다.
  - 트리거와 조건은 enum으로 유지한다.
  - v1 노드로 표현할 수 없는 효과의 예외 형식을 정의한다.
- 산출물: 식 트리 타입/스키마, 설계 결정 문서
- 완료 조건:
  - 임의 실행 코드나 문자열 수식을 허용하지 않는다.
  - 잘못된 stat scope와 알 수 없는 노드는 로딩 시 거부된다.

### P0-015 — 고난도 아이템 2개 수작업 큐레이션

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 0.5일
- 선행: P0-011, P0-014
- 작업:
  - 실명 대응 또는 강인함 관련 아이템 1개를 고른다.
  - 스택·조건부 계수·근접/원거리 중 하나가 있는 아이템 1개를 고른다.
  - 구매 제한 그룹, 동일 패시브 그룹, 공유 쿨다운 그룹을 분리한다.
- 산출물: `data/curated/items/*.json` 2개
- 완료 조건:
  - 원문 패시브와 구조체 간 누락 체크리스트가 완료돼 있다.
  - 아이템당 작성 시간을 기록한다.

### P0-016 — JSON 및 의미 검증기 구현

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 0.5일
- 선행: P0-010, P0-011, P0-012, P0-013
- 작업:
  - JSON Schema 검증 뒤 의미 불변식을 검증한다.
  - damage mix 합계, 이벤트 시간 범위, kill horizon, 분기 중복을 검사한다.
  - 시나리오와 메커니즘의 패치 검증 상태를 검사한다.
- 산출물: validator와 실패 테스트
- 완료 조건:
  - 각 불변식마다 최소 한 개의 실패 fixture가 있다.
  - 오류가 JSON 경로와 원인을 함께 출력한다.

### P0-017 — 최소 식 평가기와 결정성 테스트

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 0.5일
- 선행: P0-014, P0-015, P0-016
- 작업:
  - 두 아이템의 식 트리를 평가한다.
  - 동일 입력을 반복 평가해 정규화된 출력이 같은지 검사한다.
- 산출물: evaluator, deterministic-output test
- 완료 조건:
  - 동일 입력의 정규화된 결과가 byte-identical이다.
  - 미검증 메커니즘 입력은 명시적인 unknown/failure를 반환한다.

### Week 1 Gate

- 상태: `PASS`
- 실제 시나리오 fixture 1개가 검증기를 통과한다.
- 아이템 2개가 자연어 파싱 없이 로딩되고 수치 식이 평가된다.
- 동일 입력은 동일 출력을 내며, 미검증 사실은 조용히 추정되지 않는다.

---

## Week 2 — 데이터 스냅샷과 아이템 표현력 검증

### P0-020 — 정적 데이터 수집기 구현

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 1일
- 선행: P0-010, P0-011
- 작업:
  - Data Dragon 아이템·챔피언·룬 원본을 build-time에 받는다.
  - 필요한 Community Dragon 원본만 별도 스냅샷한다.
  - 런타임 코드에는 네트워크 모듈 의존성이 없도록 경계를 둔다.
- 산출물: fetch 명령, `data/raw/<patch>/...`
- 완료 조건:
  - 깨끗한 디렉터리에서 스냅샷을 재생성할 수 있다.
  - 수집 이후 오프라인 상태에서 모든 테스트가 실행된다.

### P0-021 — 버전·해시·드리프트 검사기 구현

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 1일
- 선행: P0-020
- 작업:
  - 잠금 파일과 스냅샷의 버전·해시를 대조한다.
  - 이전 패치와 비교해 변경 아이템·챔피언만 출력한다.
- 산출물: verify-lock 명령, drift report
- 완료 조건:
  - 변조 파일, 지역 불일치, 누락 파일을 각각 탐지한다.
  - 변경 없는 데이터에는 빈 drift 결과가 나온다.

### P0-022 — 고난도 아이템 5개 추가

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 2일
- 선행: P0-015, P0-020
- 작업:
  - 잃은 체력 또는 대상 체력 계수
  - 스택 획득과 만료
  - 근접/원거리 차등
  - 공유 쿨다운 또는 구매 제한
  - 능력치 변환
  을 합쳐 총 7개 아이템의 표현력을 검증한다.
- 산출물: 큐레이션 아이템 5개, coverage report
- 완료 조건:
  - 각 새 식 노드가 실제로 사용되는 아이템 수를 보고한다.
  - 단일 아이템만 사용하는 특수 동작은 범용 노드 추가와 예외 중 하나로 결정 기록한다.
  - 총 큐레이션 시간을 기록한다.

### P0-023 — 효과 스키마 비용 검토

- 상태: `PARTIAL`
- 현황: 스키마 결정(5노드 수치 AST 동결)은 `reports/effect-schema-spike.md`에
  기록됐고 P0-054가 이를 근거로 쓴다. 과거 두 아이템의 개별 작성 시간이 없어
  "아이템당 중앙 작성 시간" 조건만 미충족이다.
- 우선순위: `P0`
- 예상: 0.5일
- 선행: P0-022
- 작업:
  - 아이템당 중앙 작성 시간을 계산한다.
  - 새 노드 수, 예외 수, 원문 대비 누락 수를 기록한다.
- 산출물: `reports/effect-schema-spike.md`
- 완료 조건:
  - 스키마 확장 또는 축소 결정을 근거와 함께 남긴다.
  - 다음 30개 아이템의 예상 큐레이션 시간을 제시한다.

### P0-024 — 볼리베어 숙련자 문서 증거 분리

- 상태: `DONE`
- 우선순위: `P0`
- 선행: 없음
- 작업:
  - 요약본을 fixture가 아닌 검증 전 가설 목록으로 재분류한다.
  - 원본 영상과 챕터를 식별하고 연구 단계와 최종안을 분리한다.
  - 목표를 해설기로 낮추지 않고 시나리오 한정 추천기로 유지한다.
- 산출물: `docs/evidence/volibear-build-hypotheses.md`
- 완료 조건:
  - 출처 없는 아이템·룬 매핑이 계산 입력에 들어가지 않는다.
  - 불일치가 목표 변경이 아니라 명시적 상태로 남는다.

### P0-025 — 볼리베어 아이템 매핑 및 W 가속 가설 검증

- 상태: `DONE`
- 우선순위: `P0`
- 선행: P0-024
- 작업:
  - 영상 공개 시점 Data Dragon에서 핵심 아이템 ID를 확인한다.
  - 공격속도, 스킬 가속, 간접적인 평타·접근 효과를 분리한다.
- 완료 조건:
  - `공격속도 → W 직접 쿨다운 감소`를 근거 없이 채택하지 않는다.
  - 원본 주장, 데이터 지지, 별도 가설 상태가 구분돼 있다.

### Week 2 Gate

- 상태: `PARTIAL` — 자동 드리프트 검사와 오프라인 로딩은 통과, 작성 비용
  측정은 P0-023의 신뢰도 낮은 추정치뿐이다.
- 패치 잠금과 드리프트 검사가 자동으로 실행된다.
- 고난도 아이템 7개가 표현되고 작성 비용이 측정된다.
- 런타임 네트워크 호출 없이 스냅샷을 로딩한다.

---

## Week 3 — 최소 계산 엔진

### P0-030 — 저항과 피해 배율 구현

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 0.5일
- 선행: P0-010
- 완료 조건:
  - 양수·0·음수 방어력/MR 구간을 각각 테스트한다.
  - 물리·마법·고정 피해가 분리돼 있다.

### P0-031 — 감소·관통 파이프라인 구현

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 1일
- 선행: P0-030
- 완료 조건:
  - 감소와 관통 종류별 적용 순서를 명시하고 테스트한다.
  - 적용 하한과 음수 저항 전이를 테스트한다.

### P0-032 — 스킬 가속과 쿨다운 구현

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 0.5일
- 선행: P0-010
- 완료 조건:
  - AH에서 실제 쿨다운과 등가 감소율을 별도 값으로 반환한다.
  - 0과 큰 AH 경계값을 테스트한다.

### P0-033 — EHP와 혼합 피해 생존력 구현

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 1일
- 선행: P0-030
- 완료 조건:
  - 물리 EHP, 마법 EHP, mixed damage EHP가 분리돼 있다.
  - 혼합 EHP가 두 EHP의 단순 가중평균이 아님을 회귀 테스트로 고정한다.

### P0-034 — 결정론적 전투 타임라인 구현

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 1.5일
- 선행: P0-030, P0-031, P0-032
- 작업:
  - 기본 공격과 스킬 회전을 시간순으로 처리한다.
  - 3초 피해, 8초 피해, 3초 시점 생존 상태를 산출한다.
- 완료 조건:
  - `KILL_THRESHOLD_MET_3S`는 실제 타임라인의 사망 상태에서만 파생된다.
  - 피해 유형, 보호막, 회복 이벤트의 적용 순서가 로그에 남는다.

### P0-035 — 계산 검증 스위트 작성

- 상태: `BLOCKED`
- 우선순위: `P0`
- 예상: 0.5일
- 선행: P0-030, P0-031, P0-032, P0-033, P0-034
- 작업:
  - golden, 경계값, 단조성, 라운딩 테스트를 작성한다.
- 완료 조건:
  - 정수 피해에는 절대 오차, 누적 피해에는 상대 오차가 정의돼 있다.
  - 연습 도구 실측 fixture와 계산 결과의 차이가 보고된다.

### Week 3 Gate

- 상태: `BLOCKED_CLIENT_MEASUREMENT`

- 첫 시나리오에서 CC를 제외한 3초·8초 피해와 EHP를 계산한다.
- 모든 결과는 중간 계산 로그로 역추적할 수 있다.
- 공식 경계값과 실측 golden test가 통과한다.

---

## Week 4 — CC, 대응 채널, 후보 선택

### P0-040 — 실명·기절·둔화 상호작용 행렬 작성

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 0.5일
- 선행: P0-012
- 작업:
  - 강인함, 정화, QSS, 면역과 세 CC의 교차표를 작성한다.
- 산출물: `data/curated/mechanics/*.json`, 사람이 읽는 행렬 문서
- 완료 조건:
  - 확인되지 않은 칸은 `false`가 아니라 `UNVERIFIED`다.

### P0-041 — CC 사실 4단계 검증

- 상태: `BLOCKED`
- 우선순위: `P0`
- 예상: 1일
- 선행: P0-013, P0-040
- 작업:
  - 마지막 공식 변경 문서를 기록한다.
  - 이후 패치의 관련 변경 범위를 검색한다.
  - 현재 잠금 패치 클라이언트에서 실측한다.
  - `verified_patch`와 근거를 기록한다.
- 완료 조건:
  - 최소 실명 메커니즘은 `VERIFIED` 또는 명시적 `BLOCKED`다.
  - 검색 부재를 규칙 유지의 증거로 기록하지 않는다.
- 차단 사유:
  - 공식 변경 근거와 잠금 데이터의 대상 식별은 완료했다.
  - 16.17.1 클라이언트 2인 커스텀 게임 실측이 없어 모든 상호작용을
    `UNVERIFIED`로 유지한다.
  - 실측 절차와 빈 원시 결과 양식은 각각
    `docs/verification/cc-blind-16.17.1.md`,
    `fixtures/measurements/cc_blind_16.17.1.pending.json`에 고정했다.
- 추가 진행:
  - B0–B6 측정 스키마와 의미 검사 CLI를 구현했다. B6는 실명으로 빗나간
    기본 공격의 Jax 패시브 스택 획득 여부를 별도 관측한다.
  - 각 케이스 5회, boolean 관측 일치, 동일 FPS, 1프레임 모호성 차단을
    자동 검사한다.

### P0-042 — CC 보정 가동률 구현

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 1일
- 선행: P0-034, P0-041
- 완료 조건:
  - CC가 차단하는 행동 채널만 중단된다.
  - 정화 사용 시점과 지속 강인함을 타임라인 이벤트로 처리한다.
  - 미검증 상호작용은 점수를 생성하지 않는다.
- 구현 메모:
  - 행동 채널별 uptime을 유지하고 임의의 단일 가중치로 접지 않는다.
  - 강인함 중첩은 이 계층에서 추측하지 않는다. 검증된 상위 계산이 만든
    단일 지속시간 multiplier만 받고, 겹치는 multiplier는 오류로 차단한다.

### P0-043 — 대응 채널 비용 모델 구현

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 0.5일
- 선행: P0-012
- 작업:
  - 포지셔닝, 고유 능력, 소환사 주문, 룬, 신발, 아이템을 후보로 만든다.
  - 골드·슬롯·쿨다운·기회비용을 별도 필드로 유지한다.
- 완료 조건:
  - 채널 순위는 정렬 힌트이며 후보 배제 조건이 아니다.
  - 정화 보유만으로 강인함 후보가 삭제되지 않는다.
- 구현 메모:
  - 골드·인벤토리 슬롯·쿨다운·기회비용은 서로 다른 필드로 유지하며
    근거 없는 총비용 스칼라를 만들지 않는다.

### P0-044 — 아이템 경로와 후보 생성기 구현

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 1일
- 선행: P0-021, P0-022, P0-035, P0-042, P0-043
- 선행 예외: P0-035는 자동 검증 스위트까지만 의존한다. P0-035의 남은
  차단(클라이언트 실측 승격)은 후보 생성 구현을 막지 않는다.
- 완료 조건:
  - 1·2·3코어 시점별 순서 있는 후보를 생성한다.
  - 구매 제한, 동일 패시브, 공유 쿨다운 그룹을 구분한다.
  - 마나 없음, 치명타 상한, 예산, 슬롯 제약을 검사한다.
- 구현 메모:
  - `purchase_limit` 중복만 하드 거부한다. `same_passive`와
    `shared_cooldown` 중복은 합법 후보에 주석으로 남겨 후속 평가가 중복
    계산하지 않게 한다.
  - 부품 경로는 보존하지만 구매 타이밍 시뮬레이션은 v1.5 범위다.

### P0-045 — Pareto와 3분기 선택 구현

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 1일
- 선행: P0-044
- 완료 조건:
  - kill gate는 기본안·공격 분기 안에서만 작동한다.
  - 아무 후보도 문턱을 넘지 못하면 전 후보를 유지한다.
  - 방어 분기는 허용된 primary metric 손실 안에서 mixed EHP를 비교한다.
  - 동률 해소가 결정론적이다.

### Week 4 Gate

- 상태: `BLOCKED_CLIENT_MEASUREMENT`
- 실명 이벤트가 실제로 공격 가동률과 후보 결과를 바꾼다.
- 정화와 강인함은 보완 가능한 별도 대응 후보로 남는다.
- 같은 후보 집합에서 기본·공격·방어 분기가 결정론적으로 선택된다.

---

## Week 5 — 챔피언 1개 end-to-end

### P0-050 — 첫 챔피언 모델 작성

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 1일
- 선행: P0-013, P0-034
- 작업:
  - 역할, 회전, 자원 제약, primary metric, 특수 규칙을 구조화한다.
- 완료 조건:
  - 챔피언 이름을 규칙 엔진의 분기 키로 사용하지 않는다.
  - 모든 계수와 쿨다운은 잠긴 데이터 근거를 가진다.
- 구현 메모:
  - Jax는 데이터 식별자일 뿐이며 정책은 지속딜·온힛·자원·사거리·회전
    규칙에서 파생한다.
  - 공식 26.12 Q 마나 변경과 잠긴 CDragon 값이 충돌하므로 스킬별 마나
    비용은 모델에서 제외하고 프로필을 `CURATED_UNVERIFIED`로 유지한다.

### P0-051 — 추천 파이프라인 연결

- 상태: `BLOCKED`
- 우선순위: `P0`
- 예상: 1.5일
- 선행: P0-045, P0-050
- 작업:
  - 입력 검증부터 후보 생성, 시뮬레이션, 필터, 선택까지 연결한다.
- 완료 조건:
  - 로컬 명령 하나로 세 분기를 출력한다.
  - 런타임 네트워크 호출이 0회다.
  - 같은 입력의 정규화된 출력이 byte-identical이다.
- 현재 진행:
  - 로컬 readiness 명령과 `READY` / `NO_FEASIBLE_ITEM_RESPONSE` /
    `INSUFFICIENT_EVIDENCE` / `OUT_OF_SCOPE` 상태 분리를 구현했다.
  - scope와 blocker 목록은 canonical JSON으로 결정론적으로 출력한다.
  - runtime 최상위 모듈의 네트워크 및 build-time import 금지를 AST
    회귀 테스트로 고정했다.
  - 미검증 사실을 승격하지 않은 채 후보 생성 → 1·2·3코어 prefix 합성 계산
    → Pareto → 세 분기 → provenance를 연결하는 비배포 미리보기를 구현했다.
  - 합성 출력은 항상 `INSUFFICIENT_EVIDENCE`, `SYNTHETIC_NON_RELEASE`,
    `release_eligible: false`로 표시한다.
  - 임의 피해 가중치를 잠긴 Jax 기본 능력치·레벨 성장·패시브 공속과
    W/E/R 이벤트 회전 계산으로 교체했다.
  - 실명 중 빗나간 평타가 패시브 스택을 주는 경우와 주지 않는 경우를 모두
    계산하며, 현재 후보 풀에서는 세 분기 순서가 두 변형에서 동일하다.
- 차단 사유:
  - 시나리오, 실명 상호작용, 챔피언 회전, 7개 아이템이 모두 검증 승격
    전이므로 실제 목적 벡터와 세 추천 분기를 생성할 수 없다.

### P0-052 — 근거와 provenance 출력

- 상태: `BLOCKED`
- 우선순위: `P0`
- 예상: 0.5일
- 선행: P0-051
- 완료 조건:
  - 각 추천이 사용한 패치, 원본 파일, 계산식, 메커니즘 상태를 추적할 수 있다.
  - 숫자와 설명의 근거 유형을 `MEASURED`, `CALCULATED`, `UNVERIFIED`로 표시한다.
- 현재 진행:
  - 수치와 설명의 근거 타입, 메커니즘 의존성, 추천 단위 provenance 계약을
    구현했다.
  - `CALCULATED`의 공식·입력 누락, `MEASURED`의 관측 누락,
    `UNVERIFIED` 수치의 점수 포함을 생성 시점에 거부한다.
  - release eligibility는 호출자가 지정하지 못하며 근거 상태에서 파생된다.
- 남은 조건:
  - P0-051의 실제 세 분기 추천이 생성된 뒤 각 출력에 provenance 레코드를
    연결해야 한다.

### P0-053 — 부정 회귀 테스트 작성

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 0.5일
- 선행: P0-051
- 테스트:
  - 존재하지 않거나 다른 패치의 아이템
  - 구매 제한 그룹 위반
  - 동일 패시브 및 공유 쿨다운 충돌
  - 마나 없는 챔피언의 순수 마나 후보
  - 치명타 상한, 예산, 슬롯 위반
  - 정화 보유를 이유로 강인함 후보를 삭제하는 회귀
- 완료 조건: 전 항목이 자동 테스트이며 위반 추천은 0건이다.
- 현재 진행:
  - 잠긴 패치에 없는 아이템 ID, 패치·구매 제한·마나·치명타·예산·슬롯
    위반을 후보 생성 단계에서 감사 가능한 사유와 함께 거부한다.
  - 정화 보유가 신발·아이템 강인함 후보를 삭제하지 않는 회귀 테스트가 있다.
  - 동일 패시브·공유 쿨다운이 겹치거나 temporal handler가 미구현이면
    포트폴리오 수치 전체를 `UNKNOWN`으로 반환해 중복 점수를 차단한다.

### P0-054 — M0 비용 및 설계 리뷰

- 상태: `DONE`
- 우선순위: `P0`
- 예상: 0.5일
- 선행: P0-052, P0-053
- 작업:
  - 큐레이션 시간, 스키마 변경 횟수, 미검증 사실 수를 집계한다.
  - Phase 1 진행, 스키마 축소, Phase 0 반복 중 하나를 결정한다.
- 산출물: `reports/m0-review.md`
- 선행 예외: P0-052는 계약 구현까지만 의존한다. 실제 세 분기에 provenance를
  연결하는 남은 조건은 비용·설계 리뷰 판단을 바꾸지 않는다.
- 완료 조건:
  - 판단 근거와 다음 단계가 기록돼 있다.
- 결과:
  - 결정은 `Phase 1 진행`이다. P0-023이 고정한 5노드 수치 AST가 큐레이션
    아이템이 7개에서 201개로 늘어나는 동안 구조 변경 없이 효과 프로그램
    311개를 흡수했고, 핵심 효과 미표현 아이템은 0개다. 스키마 축소는 실제로
    쓰이는 표현력을 버리는 선택이고, Phase 0 반복은 이미 확보한 답을 다시
    구하는 일이다.
  - 미검증 사실 집계: 아이템 효과 문서 201개 전부 `CURATED_UNVERIFIED`,
    메커니즘 사실 4개 전부 `UNVERIFIED`, 모델링된 Cog 109개 전부
    `MODELED_UNVERIFIED`, `VERIFIED` 0개. 결투 추천은 blocker 16개와 함께
    `release_eligible: false`를 반환한다.
  - M0 게이트를 막는 것은 코드가 아니라 16.17.1 클라이언트 실측이다.

### Week 5 / M0 Gate

- 챔피언 1개와 시나리오 1개에서 세 분기를 출력한다.
- 계산 결과와 선택 이유를 입력 데이터까지 역추적할 수 있다.
- 부정 테스트 위반이 0건이다.
- 미검증 메커니즘으로 release-eligible 추천을 만들지 않는다.
- 아이템 7개의 실제 큐레이션 비용을 근거로 확장 여부를 결정한다.

---

## 명시적으로 연기하는 작업

### P1-060 — 전체 아이템 패시브·액티브 구현

- 상태: `DONE`
- 우선순위: `P1`
- 범위:
  - 잠긴 16.17.1 Data Dragon에서 맵 11 구매 가능으로 표시된 모든 아이템
  - 완성 아이템뿐 아니라 부품·소모품·장신구·특수/중복 ID를 분류 후 포함
- 작업:
  - 원본의 핵심 패시브와 사용 효과를 전수 인벤토리화한다.
  - 지속시간, 중첩, 충전, 쿨다운, 대상 선택을 공통 이벤트 계약으로 구현한다.
  - 아이템별 효과를 핸들러에 연결하고 원본 수치 provenance를 기록한다.
  - 핵심 효과가 미구현인 아이템은 후보 점수를 `UNKNOWN`으로 처리한다.
- 현재 진행:
  - 맵 11 구매 가능 아이템 254개를 누락 없이 읽는 인벤토리와 분류기를
    구현했다. 패시브·액티브 태그 및 CDragon active 플래그를 함께 감사한다.
  - 명시적으로 구현 등록되지 않은 효과를 `ITEM_EFFECTS_UNIMPLEMENTED:<id>`로
    차단하는 기본 계약을 추가했다.
  - 공통 런타임에 체력 문턱, 쿨다운, N번째 적중, 시간 제한 스택, 동적 배율,
    현재 체력 피해와 저항 감소 상태를 구현했다.
  - 발걸음 분쇄기, 유령 무희, 망자의 갑옷, 스테락, 칠흑의 양날 도끼,
    몰락한 왕의 검, 티아맷, 불경한 히드라의 효과 프로그램을 연결했다.
  - 수은 장식띠·헤르메스 시미터의 CC 해제, 존야·추적자의 팔목 보호대의
    경직/단일 사용 변환, 솔라리의 레벨 비례 광역 보호막을 연결했다.
  - 상태 적용·만료·제거를 실제 전투 타임라인에 연결해 경직 중 행동/피해
    차단과 QSS의 에어본 제외 해제를 경계값 테스트로 고정했다.
  - 슈렐리아의 광역 이동속도, 구원의 2.5초 지연 광역 회복/고정 피해,
    미카엘의 선택 아군 CC 해제/레벨 비례 회복을 연결했다.
  - 란두인의 치명타 피해 보정/광역 둔화, 요우무의 전투 이탈 및 사용
    이동속도·유체화, 로켓벨트의 돌진/마법 피해, 건블레이드의 레벨·AP 비례
    피해/둔화를 연결했다.
  - 수호천사의 4초 지연 부활/마나 회복, 맬모셔스·주문포식자의 마법 전용
    Lifeline, 철갑궁의 레벨·사거리 비례 Lifeline, 피바라기의 생명력 흡수
    초과 회복 보호막을 연결했다.
  - 필멸자의 운명·처형인의 대검·모렐로노미콘·망각의 구·화공 펑크 사슬검의
    40% 치유 감소를 피해 발동, 3초 만료, 실제 회복량 보정까지 연결했다.
  - 곡궁·마법사의 최후·내셔의 이빨의 적중 피해와 광휘의 검·리치베인·
    삼위일체의 주문검 계수/재사용 대기시간을 연결했다. 현재 254개 중
    효과가 있는 36개 아이템이 완전한 원문 라벨 대응 상태다.
  - 굶주린 히드라의 총 공격력 비례 광역 피해와 거대한 히드라의 최대 체력
    비례 주 대상/후방 피해를 근접·원거리 배율 및 사용 효과까지 연결했다.
    현재 완전한 원문 라벨 대응 아이템은 38개다.
  - 가시 갑옷·덤불 조끼의 피격 방향 트리거, 마법 반사 피해, 공격자 대상
    40% 치유 감소를 연결했다. 현재 완전한 원문 라벨 대응 아이템은 40개다.
  - 맵 11에 별도 ID로 잠긴 슈렐리아·솔라리·구원·미카엘·건블레이드 변형과
    가고일 돌갑옷의 사용 효과를 원본별 수치로 연결했다. 현재 완전한 원문
    라벨 대응 아이템은 46개다.
  - 정령의 형상·라바돈·얼어붙은 심장·판금 장화·신속의 장화·명석함의
    아이오니아 장화의 상시 배율과 라일라이의 스킬 피해 둔화를 연결했다.
    현재 완전한 원문 라벨 대응 아이템은 53개다.
  - `GRANT_STAT`/`DAMAGE_MODIFIER`를 타임라인 출력으로 승격해 정령의 형상
    회복·보호막 증폭, 판금 장화 기본 공격 피해 감소, 신속의 장화 둔화
    저항이 실제 이벤트 결과를 바꾸도록 구현했다.
  - 탐식의 망치·우주의 추진력 이동 효과, 기괴한 가면·쇼진·균열 생성기의
    시간/적중 중첩 피해 증폭, 라일라이와 분리된 세릴다 조건부 둔화,
    도미닉의 대상 추가 체력 비례 증폭을 연결했다. 현재 완전한 원문 라벨
    대응 아이템은 60개다.
  - 반복 간격을 효과 계약에 추가하고 잿빛 재·검은불꽃 횃불·리안드리의
    3초 지속 피해를 0.5초 간격 6틱으로 연결했다. 현재 완전한 원문 라벨
    대응 아이템은 63개다.
  - 충전형 추가 피해 4종과 구인수의 적중/공속/환영 타격, 포식의 각반 및
    업그레이드 신발 4종의 처치 중첩·체력 문턱·피해 유형 보호막을 연결했다.
    현재 완전한 원문 라벨 대응 아이템은 74개다.
  - 주문 방어막이 한 스킬 이벤트의 피해와 CC를 함께 막고 한 번만 소모되게
    구현하고 밴시·밤끝·신록 장벽, 케이닉, 부서진 여왕의 왕관을 연결했다.
    현재 완전한 원문 라벨 대응 아이템은 79개다.
  - 물약 2종의 총 회복량/지속시간, 도란 방패·반지의 피해 후 회복과 자원
    분기, 수호자 아이템 회복, 워모그의 0.5초 회복 및 아이템 체력 증폭을
    연결했다.
  - 영겁의 지팡이·억겁의 카탈리스트의 피해-마나/마나-회복 변환과 분당
    스택·레벨 획득, 별도 변형 ID를 연결했다. 현재 완전한 원문 라벨 대응
    아이템은 89개다.
  - 여신의 눈물·대천사·마나무네·혹한의 손길·속삭이는 서클릿과 변형 ID의
    마나 충전, 자원 비례 능력치, 360 마나 변환을 연결했다.
  - 암흑의 인장·메자이·도태의 중첩/골드/회복, 오만의 처치 공격력과
    수집가의 5% 이산 처형 및 골드 효과를 연결했다. 현재 완전한 원문 라벨
    대응 아이템은 105개다.
  - 특수 방어·치명타 아이템과 가시 갑옷/얼어붙은 심장 변형 ID, 아군 강화
    아이템 7종 및 동일 변형 7종의 연쇄 회복·충전·피해 취약 효과를 연결했다.
  - 바미·태양불꽃·공허한 광휘의 1초 광역 틱, 끝없는 절망의 4초 피해/회복,
    지크와 변형 ID의 궁극기 폭풍을 연결했다. 현재 완전한 원문 라벨 대응
    아이템은 133개다.
  - 소모품·장신구·와드, 마나 계열과 주문검, 지원 퀘스트 완성형, 공격형·
    방어형 전설 아이템, 정글 동료 및 맵 11에 노출된 특수 변형을 모두
    효과 프로그램에 연결했다.
  - 원문 효과가 있는 201개는 모두 `IMPLEMENTED`, 효과 태그가 없는 53개는
    `NOT_APPLICABLE`이며 `UNIMPLEMENTED`는 0개다. 모든 문서는 잠긴 16.17.1
    Data Dragon/CDragon provenance와 `CURATED_UNVERIFIED` 검증 상태를 가진다.
  - 전 효과 문서의 스키마 검증과 모든 상태형 프로그램의 누적·지속시간·
    쿨다운 경계를 자동 순회하는 회귀 테스트를 추가했다.
- 완료 조건:
  - 전 아이템이 `IMPLEMENTED` 또는 효과 없음이 검증된 `NOT_APPLICABLE`이다.
  - 패시브/액티브 원문 하나라도 구현 레코드와 대응하지 않으면 테스트가 실패한다.
  - 모든 상태형 효과에 발동 전·발동·만료·쿨다운 경계 테스트가 있다.
  - 전체 후보 계산에서 미구현 효과 blocker가 0건이다.

### P1-061 — 빌드 진행·라인 유지력·교전 진입 모델

- 상태: `DONE`
- 우선순위: `P1`
- 작업:
  - 코어별 구매 시각과 평가 시각을 명시하고, 구간 체류 시간으로 prefix
    지표를 가중한다.
  - 강철의 심장 구매 이후에만 단일 대상 발동 기회와 영구 체력을 누적한다.
  - 워모그의 무조건 체력과 2000 추가 체력 조건부 회복을 분리하고, 패시브가
    잠든 구간을 후보 지표로 노출한다.
  - 기본 체력 재생, 아이템 재생 배율, 생명력 흡수, 워모그를 사용하는 30초
    라인 회복 창을 구현한다.
  - 이동 속도 soft cap, 추격 상대 속도, 아이템 둔화·이동 효과·momentum·
    돌진으로 거리 폐쇄와 접촉 후 가동 시간을 계산한다.
- 결과:
  - 다리우스 대 가렌 방어 분기는 `강철의 심장 → 워모그 → 망자의 갑옷`으로
    바뀌어, 스택 아이템 선구매와 워모그 활성 조건을 동시에 만족한다.
  - `DEFAULT`의 진입 가능 후보와 `OFFENSE`의 순수 피해 후보를 분리했다.
  - `DEFAULT`는 모든 코어에서 접촉 가능해야 하며, 코어별 무아이템 기준
    혼합 EHP 하한도 통과해야 한다. 이에 따라 기본 분기는 `발걸음 분쇄기 →
    스테락의 도전 → 삼위일체`로 교정됐다.
  - 구매 시각, 강철의 심장 발동 빈도, 라인 창, 진입 운동학은 합성 가정이며
    release blocker로 유지한다.
- 후속 정정 (P1-065에서 수정):
  - 위 분기 결과는 상대가 항상 도주한다는 전제에서 나온 값이며 더 이상
    재현되지 않는다. 현재 다리우스 대 가렌 기본·방어 분기는
    `망자의 갑옷 → 몰락한 왕의 검 → 헐리사르`다.
  - 도주 전제는 이동 속도 우위가 없는 빌드의 접촉을 원천 차단해, 교전
    가동률을 "이동 속도 아이템 보유 여부"로 만들고 있었다. 가동률이 피해
    지표에 곱해지므로 이동 효과가 붙은 아이템이 다른 모든 축에서 최하위여도
    선택됐다.

### P1-062 — 역할 대칭형 Champion Cog 전환

- 상태: `DONE`
- 우선순위: `P1`
- 작업:
  - discord.py Cog와 같이 챔피언별 행동을 묶고 레지스트리가 추가·제거·조회
    생명주기를 소유하게 한다.
  - 공격자/상대 전용 타입을 만들지 않고 요청 시점의 `ParticipantContext`로
    `ACTOR`와 `TARGET` 역할을 부여한다.
  - 다리우스 회전과 프리뷰 진입점을 `DariusCog`로 옮기고 기존 함수 API는
    호환 계층으로 유지한다.
- 완료 결과:
  - 잠긴 Data Dragon의 전 챔피언을 이름과 숫자 ID로 조회할 수 있다.
  - 기존 다리우스 회전·프리뷰 회귀 테스트가 Cog를 통해 실행된다.
  - 동일 가렌 Cog가 양쪽 참가자 위치에 들어가는 대칭성 테스트가 있다.

### P1-063 — 임의 챔피언 매치업 확장

- 상태: `DONE_NON_RELEASE`
- 우선순위: `P1`
- 선행: P1-062
- 현재 구현:
  - `MatchupRequest(actor, opponent, actor_item_ids, opponent_item_ids)`로
    `Darius vs Ahri`, `Garen vs Aatrox` 등 임의 조합을 결정론적으로 실행한다.
  - 미큐레이션 챔피언은 기본 공격 fallback을 사용하며 회전·반응 결손을
    blocker로 공개한다. 구조적 범용 추천은 가능하되 release 불가다.
  - 현재 특화 추천 가능 여부와 구조 실행 가능 여부를 분리한다.
  - `DariusCog`의 회전을 상대 Cog의 일반 반응 계약과 합성한다. 가렌 Q/W
    반응은 가렌이 어느 참가자 슬롯에 있든 동일하게 동작한다.
  - 다리우스 공격자는 `Darius vs Ahri`처럼 임의 상대와 1~3코어 프리뷰를
    실행할 수 있다. 미큐레이션 상대는 중립 반응과 균형 피해 혼합 blocker를
    남긴다.
  - 범용 `recommend()`는 요청의 actor Cog에 추천 소유권을 위임한다. 전용
    모델이 없으면 다른 챔피언 모델이 아니라 공용 non-release beam을 쓴다.
  - 가렌 행동 Cog에 잠긴 CDragon의 Q5·E5·R2 계수를 연결했다. R은 공통
    타임라인의 시점별 잃은 체력 피해 출력으로 계산한다.
  - 전용 프리뷰가 없는 Cog를 위해 피해·생존·진입·라인 유지력·혼합 EHP를
    분리 보존하는 제한 폭 3코어 beam을 추가했다. 코어 완성 골드와 강철의
    심장 구매 시점별 스택, 워모그 조건 충족도 함께 평가한다.
  - 공용 아이템 디스패처가 양쪽 참가자의 액티브, 적중, 피해 가함/받음
    트리거를 소유자 기준으로 합성한다. 주문검 준비 상태와 취소된 행동의
    proc 금지를 포함한다.
  - 가렌·아트록스·아리·다리우스 행동/반응 Cog를 추가했다. `Garen vs
    Aatrox`와 역방향 모두 침묵·에어본의 원인 이벤트 취소를 반영한다.
  - beam 폭 기본값은 192다. 폭 96은 결투 11개 분기 중 2개, 5대5 3개 분기
    중 0개에서 전수 탐색과 다른 답을 냈고, 폭 192는 두 경우 모두 전수와
    일치했다. 전수 탐색은 결투 70초·5대5 381초, 폭 192는 각각 10초·65초다.
  - 위 분기 결과는 P1-065 이전 값이며 더 이상 재현되지 않는다. 이는 합성
    결과이며 고정 정답이 아니다.
  - 정적 아이템 강인함은 곱연산으로 합성되어 실명·매혹·침묵·둔화 등
    명시적 감소 가능 상태와 행동 차단 구간을 함께 줄인다. 에어본은 줄이지
    않으며, 둔화 저항은 지속시간이 아니라 둔화량에 적용한다.
  - 매치업의 CC 인과 합성, 아이템 트리거 스케줄, beam 지표 생성·선택을
    독립 헬퍼로 분리했다. `src/lol_build` 전체의 모든 클래스·함수·메서드는
    영문 docstring과 인자별 `:param:`, `:return:` 계약을 회귀 테스트로
    강제한다.
- 남은 검증 작업:
  - Aatrox/Ahri의 합성 계수·적중·시전 타이밍을 잠긴 상세 원본 또는 클라이언트
    실측으로 승격한다.
  - Lifeline 문턱, 지연 피해, 전투 중 조건부 이동/저항 등 아직 blocker인
    상태 의존 트리거를 온라인 타임라인 조건 평가로 옮긴다.
  - blocker가 하나라도 있는 preview는 계속 `INSUFFICIENT_EVIDENCE` 및
    `release_eligible=false`를 유지한다.

### P1-064 — 전 챔피언 전용 Cog 승격

- 상태: `IN_PROGRESS`
- 우선순위: `P1`
- 선행: P1-063
- 완료 조건:
  - 잠긴 roster의 173개 챔피언 모두 전용 물리 모듈과 manifest entry를 가진다.
  - 각 Cog는 `SCAFFOLDED` / `MODELED_UNVERIFIED` / `VERIFIED`를 근거와 함께
    선언하며, 파일 존재만으로 추천 capability를 얻지 않는다.
  - 실제 스킬 회전·반응·진입·유지력·아이템 정책을 역할 중립 이벤트로
    구현하고 결정성·역할 반전 회귀 테스트를 통과한다.
  - 미구현 또는 미검증 메커니즘은 champion-scoped blocker로 남긴다.
- 현재 요약 (2026-09-11 기준, 아래 "진행 기록"의 중간 수치보다 우선):
  - 폴더 기준 todo 31 · wip 104 · modeled_unverified 38 · curated 0.
    manifest 기준 `MODELED_UNVERIFIED` 142 · `SCAFFOLDED` 31 · `VERIFIED` 0.
  - `MULTI_TARGET` 선언 Cog 4개(Amumu, Annie, Karthus, Leona).
  - 보류: Qiyana, Sivir, Zeri, Shyvana(엔진 범위 밖 또는 별도 설계 필요).
- 진행 기록 (시간순 누적, 중간 수치는 당시 값):
  - 전용 모듈 173/173, 상세 원본 3종 173/173, patch lock 538파일.
  - 계산 원본 인덱스 173명·865 슬롯. Q/W/E/R BIN source ref 누락 0건.
  - `MODELED_UNVERIFIED` 109개, `SCAFFOLDED` 64개, `VERIFIED` 0개.
  - CC 면역, 사망 방지, 시간제 공격속도 감소, 런타임 방어력·마법 저항력
    변경을 공통 엔진으로 구현했다.
  - Warwick, Orianna, Trundle, Gnar, Soraka, Kaisa, Brand, DrMundo,
    Blitzcrank, Anivia, Camille, Cassiopeia, Diana, Ekko, Fiora의 역할 중립
    회전과 역할 반전 회귀를 추가했다.
  - 공통 sequence 범위와 기본 공격 간격을 `ChampionCog`로 올리고,
    `ChampionSnapshot`이 스킬 가속을 보존하도록 확장했다.
  - 모델링된 모든 Cog의 잠금 원본 3종과 추천 capability를 공통 계약으로
    검사한다.
  - Akshan, Alistar, Ambessa, Amumu, Aphelios, AurelionSol, Aurora, Azir,
    Bard, Belveth, Braum, Briar, Chogath, Corki, Draven, Elise, Evelynn,
    Ezreal, Fiddlesticks, Fizz 배치를 추가했다.
  - 중단된 다음 배치에서 실행 가능한 본문이 남은 Galio, Gragas, Graves는
    루트 통합 검토와 전용 회귀를 거쳐 승격했다.
  - Terra 5개 배치의 50개 산출물을 루트에서 재감사했다. 실제 다중 스킬
    회전과 역할 중립 반응을 구현한 Gwen, Heimerdinger, Illaoi, Ivern, Janna,
    JarvanIV, Jayce, Jhin, Jinx, Kalista, Karma, Karthus, Kassadin, Katarina,
    Kayle, Kayn, Kennen, Khazix, Kindred, Kled, KogMaw, KSante, Leblanc, LeeSin,
    Leona 25개만 승격했다.
  - 평타 전용 또는 대표 스킬 한 개뿐인 공통 baseline 산출물 25개는 전체
    capability 선언이 부정확하므로 폐기하고 `SCAFFOLDED`를 유지했다.
  - 루트 순차 구현으로 Akali, Gangplank, Hecarim, Hwei, Irelia, Lillia,
    Lissandra, Locke, Lucian, Lulu, Malzahar, Maokai, MasterYi를 추가
    승격했다. Gangplank 화약통을 위해 `DamageOutput` 단위 %/고정 관통을
    공통 엔진에 추가하고,
    전역 관통과의 곱연산 결합 및 이벤트 간 비누출을 회귀 테스트로 고정했다.
  - 전환기 capability 테스트는 특정 scaffold 챔피언을 하드코딩하지 않고
    manifest에서 동적으로 선택하며, 전체 승격 후에는 해당 부정 테스트만
    건너뛰도록 수정했다.
  - Hwei의 선택 주문 조합과 주기 피해, Irelia의 표식 Q 초기화와 W의
    피해 유형별 방어 창, Lillia의 수면-각성 및 Dream Dust 갱신 경계를
    전용 회귀로 고정했다.
  - Lissandra는 자기 시전 궁극기 하나만 사용하면서 최소 회복, 주변 피해,
    피해 면역, CC 면역을 공격·반응 모델에 분리했다.
  - Locke의 Soul Ignition을 위해 일반 피해와 분리된 `HealthCostOutput`을
    공용 엔진에 추가했다. 저항·보호막·피해 집계를 우회하고 체력 하한을
    보존한다. Locke의 Q 표식, E 진입, R 처형과 Lucian의 Lightslinger,
    E 재사용 대기시간 환급, 개별 Culling 탄환을 전용 회귀로 고정했다.
  - Lulu의 Wild Growth를 위해 현재·최대 체력을 함께 올리고 만료 시
    현재 체력을 새 상한으로 제한하는 `MaxHealthModifierOutput`을 추가했다.
    자기 대상 W/E/R과 적 대상 변형을 동시에 적용하지 않는 회귀도 고정했다.
  - Malzahar의 E 갱신 구간, W 공허충 3마리, 개별 R 광선·장판 틱,
    Void Shift 피해 감소·CC 면역을 공격·반응 모델에 분리했다.
  - Maokai의 비수풀 E, W 진입, Q 넉백, 거리 기반 R 최대 속박과
    첫 Sap Magic 회복을 구현하고 동적 재사용 대기시간은 blocker로 남겼다.
  - Master Yi는 R/E 지속시간의 W 일시정지, 평타 기반 Q 환급, 4타
    Double Strike, W 단계별 피해 감소와 R 둔화 면역을 구현했다.
  - Mel은 Q/E 다중 타격, 15스택 R, 강화 평타, W 보호막·이동 속도를
    구현하고 투사체 반사를 projectile metadata blocker로 고정했다. Milio는
    E 2충전, W 회복, Q 공중 제어, R 회복을 구현하되 아군 전달·정화·동적
    강인함을 blocker로 유지했다. Miss Fortune은 Q 기본 대상, W 가속 평타,
    E 8틱, 개별 R 16파를 구현했다.
  - Wukong은 E 진입·공속, Q 방어력 감소, 분신이 모사하는 첫 R과 두 번의
    R 8틱을 구현했다. Morgana는 Q 속박, 현재 잃은 체력에 따라 증가하는 W,
    마법 전용 E 보호막, R의 첫 타격·지연 타격을 구현했다.
  - Naafiri는 현재 패치의 W 무리 강화/R 추격 구조와 Q2 출혈 소비·회복,
    E 두 타격을 구현했다. Nami는 자기 E 3회 강화, W 자기 회복→적 반사,
    Q/R 제어를 구현했다. Nautilus는 Q 진입, W 체력 계수 보호막·지속 피해,
    첫 평타 속박, E 3파, R 공중 제어를 구현했다.
  - Neeko는 단일 대상 E 속박, Q 3회 개화, W 3타 강화, R 준비·착지 제어를
    구현했다. Nidalee는 최대 거리 인간 Q 이후 사냥 표식, 자기 E 회복·공속,
    쿠거 W/E/Q 전환 회전을 구현했다.
  - Nilah는 E 2충전, Q의 치명타 피해·공속 강화·치명타 기반 출력 단위 방어
    관통, W 마법 피해 감소, R 개별 틱·마지막 끌어당김을 구현했다. 공격 회피와
    피해 후 회복·초과 회복 보호막은 필요한 상태 귀속 blocker로 남겼다.
  - Nocturne은 R 진입, Q 흔적의 공격력·이동 속도, W 주문 방어막, E 4틱과
    지연 공포, 기본 공격 환급에 따른 첫·다섯 번째 Umbra Blades 회복을 구현했다.
    W 방어 성공 후 공속 2배는 상대 이벤트 순서 의존 blocker로 유지했다.
  - Nunu & Willump는 최대 성장 W 진입, 챔피언 대상 Q 피해·회복, E 3회
    재시전의 9발과 지연 속박, R 최대 정신집중 피해·보호막을 구현했다. W의
    공중 제어/기절과 E/R 이동 제한을 분리하고 R 중단은 인과 blocker로 남겼다.
  - 전체 789개 테스트와 Ruff 검사를 통과한다.
  - `capabilities = frozenset(CogCapability)` 관용구를 제거했다. 열거형에
    capability를 추가하는 것만으로 98개 Cog가 그 능력을 획득해, "파일 존재만으로
    추천 capability를 얻지 않는다"는 완료 조건을 위반했다. 결투로 얻을 수 있는
    집합은 `DUEL_CAPABILITIES`로 명명하고, 자체 근거가 필요한 능력은 구현한
    Cog가 직접 선언하게 했다. 관용구 재발과 무근거 `MULTI_TARGET` 선언을
    회귀 테스트로 차단한다.
  - 서브 에이전트 없이 순차 구현으로 Pantheon, Poppy, Pyke, Rammus, Renekton,
    XinZhao, Talon, Veigar, Sion, Ziggs, Vi, Zed, Riven, Xerath, Twitch,
    Varus, Shen, Sejuani, Taric, Vladimir, Yasuo, Zilean, Vex, Velkoz,
    Viktor 25명을 추가 승격했다. 각 챔피언은 CommunityDragon 원본
    `DataValues`/`mSpellCalculations`와 Data Dragon 툴팁의 데미지 타입을
    교차 검증하고, 검증 불가 메커니즘(홀드캐스트 최대치, 상태 의존 트리거,
    자원 스택 시스템)은 계산에서 제외한 뒤 챔피언별 blocker로 남겼다.
    전용 회귀 테스트 3개씩과 manifest 승격마다 전체 스위트 재검증을 거쳤다.
  - 레벨 곡선 계산(`ByCharLevelBreakpoints`)의 "AtAndAfter" 필드명 해석이
    모호해, Pantheon E 실드량이 120이 아니라 125가 맞다는 것을 발견하고
    공용 헬퍼 `ChampionCog._level_breakpoint_value`로 승격해 소급 수정했다.
  - `StatModifierOutput`으로 건 이동속도/공속 버프(`MOVE_SPEED_PERCENT`,
    `ATTACK_SPEED` 등)가 실제 전투 계산에는 반영되지 않음을 확인했다.
    엔진이 실제로 소비하는 스탯 키는 `ARMOR`/`MAGIC_RESISTANCE`(저항 계산)와
    `BASIC_ATTACK_DAMAGE_MULTIPLIER`/`CHAMPION_DAMAGE_MULTIPLIER`/
    `SLOW_RESISTANCE_PERCENT` 세 배율뿐이다. Malphite의 기존
    `ATTACK_SPEED_MULTIPLIER` 사용도 같은 패턴이라 이번 세션에서 만든
    회귀가 아니라 엔진 전반의 기존 한계이며, 추천 지표의 핵심인 데미지
    수치 계산에는 영향이 없다.
  - 이어서 Tristana, Rumble, Sona, Urgot, Yone, Zoe, Swain, Singed 8명을
    추가 승격했다(합계 33명). Rumble Q·R과 Singed Q는 다틱 채널을 총합 한
    방으로 근사하거나(Rumble) 실제 다틱 이벤트로(Singed 독 장판) 구현하는
    두 방식을 상황에 맞게 선택했다. Zeri는 기본 공격 자체가 Q로 재정의되는
    구조라 패시브 충전 시스템과 분리 불가능해 보류했고, Shyvana는 드래곤
    변신에 따라 피해 유형이 바뀌는 구조라 보류했다.
  - 현재 `MODELED_UNVERIFIED` 142개 · `SCAFFOLDED` 31개, 테스트 906개.
  - 173개 챔피언 물리 모듈을 성숙도별 하위 폴더로 재배치하고 `manifest.py`의
    `module_name`을 일괄 갱신했다(일회성 스크립트 `/tmp/reorg.py` — 저장소에 없어 재현 불가, 결과
    정합성은 폴더·manifest 일치 회귀 테스트가 보장한다. exact-string 치환 후
    `count == 1` 검증). 최초 배치는 `champions/wip/`를 `MODELED_UNVERIFIED`에
    매핑했으나, "로테이션 구현은 끝났고 클라이언트 검증만 안 됐다"는 상태를
    "아직 작업 중"으로 부르는 게 부정확하다는 지적을 받아
    `champions/modeled_unverified/`로 개명하고 `champions/wip/`는 실제로
    구현이 미완성인 챔피언(현재 `CogMaturity`에는 이 상태가 없어 0개)을 위해
    비워둔 채 예약했다. 최종 구조: `champions/todo/` `SCAFFOLDED` 31개,
    `champions/modeled_unverified/` `MODELED_UNVERIFIED` 142개,
    `champions/curated/` `VERIFIED` 0개, `champions/wip/` 예약(0개, 미사용).
    직접 모듈 import를 쓰던 테스트 13개(test_azir_cog 등)의 경로를 갱신하고,
    `test_all_champion_modules.py`의 모듈 탐색을 비재귀 `glob`에서 `rglob`으로
    바꿨으며, 폴더가 manifest maturity와 항상 일치하는지 검사하는
    `test_champion_module_folder_matches_manifest_maturity` 회귀를 추가했다.
  - 웹 UI에 동일한 성숙도를 curated/modeled_unverified/todo 상태로 노출했다
    (`wip`는 이 시점엔 비어 있어 노출하지 않았다 — 아래에서 채운 뒤 노출).
    `WebService.catalog()`가 부정확했던 `specialized`(전용 Cog 존재 여부만
    표시, 완료·미검증 구분 불가) 필드를 `cog.maturity` 기반
    `status`(`todo`/`modeled_unverified`/`curated`)로 교체하고, 이 값이
    manifest maturity와 항상 일치하는지 검사하는
    `test_catalog_champion_status_matches_manifest_maturity` 회귀를
    추가했다. `app.js`/`index.html`/`app.css`에 챔피언 선택 UI 전 구간(내
    챔피언, 상대 챔피언, 아군·상대팀 슬롯 8개 전부)에 상태 배지
    (TODO/UNVERIFIED/CURATED)와 범례를 추가하고, 드롭다운 옵션 텍스트에도
    접미사로 노출했다. 로컬 서버를 띄워 `/api/catalog` 응답과 정적 자산
    서빙을 curl로 검증했다(Darius→modeled_unverified, Qiyana→todo 확인,
    `node --check app.js` 통과). 전체 스위트(907개) 재검증 통과.
  - `wip/`를 실제로 채웠다. `MODELED_UNVERIFIED` 142개 중 104개는
    ability의 `blockers=(...)`에 표준 `COG_MODEL_UNVERIFIED:<이름>` 외에
    특정 메커니즘 제외·근사를 알리는 리터럴 blocker를 하나 이상 갖고 있음을
    코드 스캔으로 확인했다(예: Katarina
    `KATARINA_R_CHANNEL_INTERRUPTION_AND_PER_TARGET_TICKS_NOT_MODELED`,
    Akali `AKALI_W_INVISIBILITY_AND_TARGETABILITY_NOT_MODELED`). 이 104개는
    `champions/wip/`로, 그런 blocker가 전혀 없는 38개(Darius, Garen, Aatrox,
    Ahri, Pantheon 등)는 `champions/modeled_unverified/`에 남겼다. Rumble처럼
    독스트링에만 제외 사항을 적고 코드 blocker로 남기지 않은 사례는 이
    코드 스캔 기준으로는 걸러지지 않는 한계를 인지한 채 진행했다(사용자
    승인). `test_all_champion_modules.py`에
    `_has_champion_scoped_mechanism_gap`(동일한 정규식 스캔)을 추가해
    `test_champion_module_folder_matches_manifest_maturity`가 폴더·성숙도·
    메커니즘 격차 여부 세 가지를 함께 검증하게 했다. `WebService`의 상태
    산출을 정적 maturity 매핑 대신 `type(cog).__module__`의 폴더 세그먼트를
    그대로 쓰는 `_catalog_status()`로 바꿔(폴더가 유일한 진실 소스),
    todo/modeled_unverified/wip/curated 4단계를 UI에 그대로 노출했다.
    최종 개수: todo 31 · modeled_unverified 38 · wip 104 · curated 0.
    전체 스위트 재검증 통과.
- 다음 배치:
  - 서브 에이전트 없이 남은 31개 챔피언을 하나씩 구현·검증한 뒤 manifest를
    승격한다. Qiyana(지형 의존 스킬), Sivir(데미지가 상태 트리거 의존),
    Zeri(기본 공격=Q 재정의), Shyvana(변신형 피해 유형 전환)는 엔진 범위
    밖이거나 별도 설계가 필요해 보류했다.
  - `MULTI_TARGET`을 실제로 구현한 Cog가 아직 4개(Amumu, Annie, Karthus,
    Leona)뿐이다. 광역기 챔피언이 `ParticipantContext.opposing_side`를
    순회하도록 개별 승격해야 팀 전투에서 단일 대상 가정 blocker가 해소된다.

### P1-065 — 5대5 한타 확장과 교전 전제 정정

- 상태: `DONE_NON_RELEASE`
- 우선순위: `P1`
- 선행: P1-063
- 범위: D-003이 남긴 다대다 시나리오
- 작업:
  - 타임라인을 양 진영 5명씩으로 일반화하고, 결투 결과를 보존한다.
  - 참가자별 피해 귀속을 도입해 아군 기여를 빌드 순위에서 분리한다.
  - 검증 불가능한 교전 판단은 명명된 정책과 blocker로 노출한다.
- 구현:
  - `EntityId`에 `ALLY_2..5` / `TARGET_2..5`를 추가하고 `_opposing`을 진영
    소속으로 판단하게 했다. `ACTOR`와 `TARGET`은 각 진영의 첫 참가자로
    유지되므로 결투 식별자와 이벤트 순서가 그대로다.
  - 시퀀스 대역을 참가자별로 분리했다. 대역이 (액터, 비액터) 쌍으로 짜여
    있어 상대 4명이 충돌했고, 액터와 주 상대는 오프셋 0을 유지해 결투
    이벤트 순서를 보존했다.
  - `ParticipantContext`에 `opponents`와 `opposing_side`를 추가했다. 결투
    에서는 겨누는 대상 한 명으로 폴백하므로 Cog 173개는 무수정 동작한다.
  - `TimelineResult`가 참가자별 최종 상태, 소스별 피해, 사망 시각을 노출한다.
    `actor_damage_dealt`가 빌드 순위의 피해 신호이며 아군 딜을 포함하지 않는다.
  - `ACTOR_SURVIVAL_MS_8S`를 방어·균형 분기의 1순위로 두었다. 액터가 죽으면
    종료 시점 체력이 모든 빌드에서 0이 되어 변별력을 잃기 때문이다. 이 변경으로
    결투 11개 분기 중 1개가 바뀌었다.
  - 병렬 탐색을 추가했다. 코어 단계를 합법 경로 수집 → 고유 프리픽스 병렬
    평가 → 순차 조립으로 나눠, 워커 수가 결과에 영향을 주지 못한다. 결투
    2.6배·5대5 4.0배 단축이며 풀 생성 실패는 순차 진행으로 보고된다.
- 명명된 교전 정책 (모두 blocker 부착):
  - `THREAT_ALLOCATION_POLICY_ASSUMED:position_role_v1` — 기본 공격 사거리로
    전열/후열을, 역할 태그로 처치 우선순위를 정한다. 근접 공격자는 상대
    전열까지만 닿는다. 실제 대상 선정은 플레이어 판단이므로
    `TARGET_SELECTION_SKILL_NOT_MODELED`를 항상 함께 낸다.
  - `PRIMARY_OPPONENT_PINNED_TO_ACTOR` — 정책만 적용하면 내구형 액터가 최하위
    우선순위가 되어 아무도 공격하지 않고, 방어 분기가 순위를 매길 생존 신호가
    사라진다. 요청자가 지정한 매치업의 주 상대는 액터에 고정한다.
  - `PURSUIT_TARGET_POLICY_ASSUMED:range_aware` — 상대가 액터보다 긴 사거리를
    가질 때만 도주한다. 그렇지 않으면 도망쳐서 얻을 것이 없다.
  - `ITEM_ACTIVE_DUTY_SCALED:<program>:per_engagement` — 액티브를 지속시간과
    쿨다운으로 가중한다. 두 값 모두 효과 프로그램에 이미 있었으나 무시되어
    2초 효과가 영구 지속처럼 계산됐다.
  - `TEAM_ARRIVAL_DISTANCE_ASSUMED:<거리>`, `TEAM_ARRIVAL_DASH_RESERVED_ASSUMED`
    — 주 상대 외 참가자는 거리를 좁혀 도착해야 하며 도착 전 행동은 취소된다.
  - `ALLY_CONTRIBUTION_EXCLUDED_FROM_BUILD_RANKING`,
    `TEAM_ENCOUNTER_CHASSIS_METRICS_USE_PRIMARY_OPPONENT_ONLY`
- 결과:
  - 근접 대 근접 매치업 4개의 추천이 모두 바뀌었다. 헤르메스의 시미터가 전
    분기에서 사라졌고 발걸음 분쇄기도 1코어 고정에서 밀려났다. 두 아이템 모두
    이동 효과가 교전 가동률을 통해 피해 지표를 증폭시켜 선택되고 있었다.
  - 상대가 액터보다 긴 사거리를 갖는 매치업 2개는 변화가 없다. 원거리 액터가
    근접 상대를 쫓는 매치업 2개도 좁힐 거리가 짧아 이미 가동률 1.0이었다.
- 남은 검증 작업:
  - 도착 거리 기본값 650은 라인 대치 상수를 재사용한 값이며 팀원 합류 거리의
    근거가 없다.
  - 체급·혼합 EHP 지표가 아직 주 상대만 기준으로 계산된다.
  - 포지셔닝은 도착 시각까지만 모델링하며 교전 중 이탈·재진입은 없다.
  - 매치업 영향 조사는 8개 표본, 액터 4챔피언이다.

### P1-066 — 다리우스·가렌 전용 매치업 코드 제거

- 상태: `DONE_NON_RELEASE`
- 우선순위: `P1`
- 선행: P1-065
- 배경: 다리우스 vs 가렌 균형 분기 아이템(발분·망자·마최)의 근거를 조사하는
  과정에서 처치 문턱(`kill_threshold_met`) 계산이 `opponent_item_ids=None`
  (레거시 3코어 벤치마크 가렌, HP 2563)과 `opponent_item_ids=[]`(웹 UI
  기본값, 가렌이 게임 내내 아이템을 0개 산다고 가정, HP 1763)에서 서로 다른
  상대 상태를 가정한다는 걸 발견했다. 사용자가 "다리우스 vs 가렌 전용 매치업
  코드 자체를 없애고 모든 챔피언이 Cog로만 확장성 있게 관리되어야 한다"고
  판단해, 문턱 재설계 대신 특수 경로 자체를 제거했다.
- 제거:
  - `application/darius_preview.py`(다리우스 vs 가렌 전수 순열 탐색 엔진,
    처치 문턱 게이트 포함) 전체 삭제.
  - `simulation/darius.py`(레거시 상세 로테이션 시뮬레이터, `darius_preview.py`
    전용 소비자였음) 전체 삭제.
  - `cogs/darius.py`의 `.preview()`(상대가 "Garen"인지로 분기해 전용 엔진 또는
    범용 엔진을 선택하던 매치업별 특수 코드), `.simulate_rotation()`,
    `.simulate_against()`(위 레거시 시뮬레이터로의 위임, 고아 코드가 됨) 삭제.
    남은 `build_action_plan`/`build_reaction_plan`/`item_candidate_blocker`는
    다른 챔피언과 동일한 순수 Cog 로테이션이라 그대로 유지했다.
  - `application/matchup.py`의 `getattr(actor_cog, "preview", None)` 분기
    제거 — 이제 모든 액터가 예외 없이 `generic_cog_build_preview`로만
    디스패치된다(어떤 Cog도 더 이상 `.preview`를 정의하지 않음).
  - `fixtures/synthetic/duel_darius_l13_8s_preview_v1.json`(전용 엔진의
    예산·코어 완성 시점 등 내부 설정, 다른 소비자 없음),
    `docs/scenarios/duel_darius_l13_8s_vs_garen_v1.md`(전용 엔진의 계산
    과정을 설명하는 문서) 삭제. `data/curated/champions/122.json`,
    `fixtures/scenarios/duel_darius_l13_8s_vs_garen_v1.json`은
    `scenarios.validation`/`readiness_document`가 파라미터화를 검증하는 데
    쓰는 일반 인프라 예시 데이터라 유지했다(Jax/Teemo 예시와 같은 역할).
  - `tests/test_darius_preview.py`, `tests/test_darius_rotation.py` 삭제.
    `tests/test_team_encounter.py`의 특수 경로 전제 테스트는 이름·설명만
    "모든 액터가 동일한 범용 탐색을 쓴다"로 고쳤다(검증 내용은 이미
    `faces_team` 시 범용 엔진으로 갔으므로 동일).
  - `tests/test_package_architecture.py`의 `cogs` 허용 의존성에서
    `simulation`/`application`을 제거해 `{cogs, core, items}`로 좁혔다
    (darius.py가 더 이상 그 두 패키지에 의존하지 않음 — 예외 자체가 소멸).
  - `docs/architecture.md`, `docs/adr/0003-role-neutral-champion-cogs.md`,
    `docs/web-ui.md`의 "다리우스는 예외" 서술을 제거하고 "모든 챔피언은
    동일한 범용 탐색을 쓴다"로 갱신했다.
- 부수 효과: 처치 문턱(`kill_threshold_met`) 개념 자체가 시스템에서
  사라졌다 — 범용 엔진(`cog_preview.py`)은 애초에 이 게이트를 구현한 적이
  없다. 직전 세션에서 추가한 `KILL_CHECK_BURST_DAMAGE_3S`/
  `KILL_CHECK_THRESHOLD_HP` 메트릭과 웹 UI의 "처치 판정 근거" 표시는 이제
  어떤 챔피언에서도 채워지지 않을 죽은 코드였으므로, 백엔드 부분(darius_preview.py
  삭제로 이미 제거됨)에 이어 프런트엔드(`renderKillCheck`, `.kill-check` CSS,
  관련 `metricLabels` 항목)도 같은 배치에서 제거했다.
- 검증: 전체 테스트 스위트·`ruff check .` 통과. 실제 웹 서버로 다리우스 vs
  가렌을 다시 계산해 `policy_id`가 `generic_*_selection_v1`로 나오는 것을
  확인했다(과거 `darius_*_selection_v1`).

### P1-067 — 범용 추천 탐색을 빔 서치에서 전수 탐색으로 전환

- 상태: `DONE_NON_RELEASE`
- 우선순위: `P1`
- 선행: P1-066
- 배경: P1-066에서 다리우스 vs 가렌 균형/방어 분기 결과(헤르메스의
  시미터가 왜 뽑히는지)를 사용자가 의심해 슬롯별 대안(`slot_runner_up`)을
  직접 대입 평가로 확인한 결과, 빔 폭 192는 물론 2000(10배)까지 키워도
  실제 최적 조합(강철심장→선체파괴자→란두인, 유효체력 7431)을 못 찾고 더
  낮은 값(7278)에 수렴하는 것을 확인했다. `_retain_axis_frontier`가 매
  코어마다 "그 시점 기준 상위권"만 남기는 방식이라, 1코어 단독으로는
  두각을 못 내지만 완성되면 최고가 되는 조합을 구조적으로 못 찾는다.
  사용자가 "10초 대기는 감수하자"며 빔 폭 확대 대신 전수 탐색 전환을
  선택했다.
- 구현:
  - `cog_preview.py`의 `states = _retain_axis_frontier(expanded, beam_width)`를
    `states = expanded`로 교체했다 — 매 코어마다 살아남은 모든 합법 경로를
    다음 코어로 그대로 넘긴다. `_retain_axis_frontier` 함수와 `beam_width`
    매개변수를 완전히 제거했다(더 이상 근사할 이유가 없음).
  - 기존 워커 풀·프리픽스 캐시(`_stage_pool`, `_prefill_stage_cache`,
    `_prefix_cache_key`) 인프라를 그대로 재사용했다 — 순서만 다르고 아이템
    구성이 같은 프리픽스는 여전히 한 번만 계산되므로, 전수 탐색이라도 고유
    프리픽스 수는 다리우스 전용 구엔진(P1-066에서 제거)이 처리하던 규모와
    비슷하다.
  - `test_champion_cogs.py`·`test_parallel_search.py`의 `beam_width=8`
    호출부(총 5곳)를 제거했다 — 더 빠른 근사 모드가 사라졌으므로 이 테스트들도
    이제 전수 탐색으로 돈다.
- 검증:
  - 재계산한 다리우스 vs 가렌 균형/방어 분기에서 헤르메스의 시미터가
    사라지고 발걸음 분쇄기로 대체됐다 — 빔이 실제로 놓쳤던 조합이었음을
    확인. 슬롯 대입(`slot_runner_up`)으로 남은 세 지적을 재검증한 결과:
    (1) 망자의 갑옷이 1코어인 것은 버그가 아니라 방어형 분기의 데미지
    문턱(전체 후보 대비 90%)까지 유일하게 통과하는 선택이었다(대안 0개),
    (2) 헤르메스의 시미터는 실제로 빔이 놓친 결과였고 지금은 안 나온다,
    (3) 란두인의 예언(공격력 0)은 방어 분기 우선순위(생존시간→유효체력→...)가
    애초에 데미지를 안 보는 설계라 여전히 최적이며, 이는 탐색 결함이
    아니라 우선순위 설계의 결과다.
  - 실행 시간: 다리우스 vs 가렌 단일 요청 약 13.8~18.9초(파이썬 직접 호출
    vs 웹 API 왕복 포함). 서버의 `SOCKET_TIMEOUT_SECONDS=30.0`은 이미 이
    범위를 여유 있게 수용한다.
  - 전체 테스트 스위트: 기존 3분 7초 → 5분 58초(0 실패, `beam_width=8`로
    빠르게 돌던 5개 호출부만 느려짐). `ruff check .` 통과.
- 남은 과제: `default`/`defense` 분기의 데미지 문턱(90% 등)이 방어 분기를
  지나치게 순수 생존 위주로 만드는지는 별도 우선순위 설계 검토가 필요하다
  (이번 작업은 탐색이 "이미 정의된 우선순위 기준으로" 최적을 찾도록 고친
  것이지, 우선순위 자체를 재설계하지 않았다). → **P1-068에서 DEFAULT는
  해결, DEFENSE는 스펙대로 유지로 확정.**

### P1-068 — 균형(DEFAULT) 분기의 게이트·순위 기준 역전 수정

- 상태: `DONE_NON_RELEASE`
- 우선순위: `P1`
- 선행: P1-067
- 배경: P1-067로 전수 탐색이 된 뒤에도 사용자가 "균형 빌드가 방어력만
  과도하게 챙긴다"고 지적했다(다리우스 vs 가렌 DEFAULT 8초 피해량이 공격
  분기의 89.5%뿐). `docs/selection-semantics.md`(다리우스 전용 엔진 시절부터
  있던 기존 설계 문서)를 재확인한 결과, 답이 이미 적혀 있었다: "DEFAULT...
  ratio is a gate, not a weighted combination of damage and defense:
  candidates that pass are still ranked by the champion's damage objective."
  즉 DEFAULT는 원래 OFFENSE와 똑같이 **데미지로 순위**를 매기고, 차이는
  "체급(EHP 비율) 게이트를 먼저 통과해야 한다"는 것뿐이었다. 그런데
  `cog_preview.py`의 실제 구현은 이 게이트·순위를 뒤바꿔서 (a) 문서에 없던
  "데미지 90% 이상" 게이트를 추가로 걸고 (b) 순위를 생존 지표로 매기고
  있었다 — 다리우스 전용 엔진이 있던 시절 이후 범용 엔진으로 넘어오면서
  생긴 스펙 이탈이며, 이번 세션에서 만든 회귀가 아니라 기존 결함이다.
  DEFENSE 쪽은 "데미지 손실 한도 게이트 + 생존 순위"가 문서와 정확히
  일치해 손대지 않았다.
- 구현 (`cog_preview.py`):
  - `default_pool` 구성에서 `DAMAGE_TOTAL_8S >= best_chassis_damage * 0.90`
    필터를 제거했다 — 게이트는 `chassis_states`(체급·접근·패시브 준비)
    하나만 남는다. `best_chassis_damage` 변수 자체를 삭제했다.
  - `branch_priorities[DEFAULT]`를 `(ACTOR_SURVIVAL_MS_8S,
    MIXED_EFFECTIVE_HEALTH, ACTOR_END_HP_8S, LANE_RECOVERED_HP_30S)`에서
    `(DAMAGE_TOTAL_8S, MIXED_EFFECTIVE_HEALTH)`로 바꿔 OFFENSE와 동일하게
    데미지 우선으로 순위를 매기게 했다.
  - `branch_reasons[DEFAULT]`를 `BALANCED_CHASSIS_WITH_DAMAGE_FLOOR`에서
    `BALANCED_CHASSIS_GATED_DAMAGE_PRIORITY`로 개명해 실제 동작(게이트만
    체급, 순위는 데미지)과 이름을 일치시켰다. `_default_gate`(슬롯 대안
    탐색용) 게이트도 체급 조건만 검사하도록 맞췄다. DEFENSE에만 있던
    `PRIMARY_DAMAGE_FLOOR_PASSED` constraint를 DEFAULT에서 잘못 같이
    붙이던 것도 제거했다(DEFAULT는 더 이상 데미지 문턱이 없음).
- 검증: 다리우스 vs 가렌 재계산 결과 DEFAULT 8초 피해량이 961.9(공격
  분기의 89.5%) → 1059.6(98.6%)으로 상승했고, 유효체력은 5601.9로
  낮아졌지만 여전히 공격 분기(3685.4)보다 크게 높다 — "체급은 확보하되
  데미지는 최대화"라는 의도대로 균형이 잡혔다. 전체 테스트 스위트(0 실패,
  5분 46초) · `ruff check .` 통과.

### P1-069 — docs 대 구현 전수 대조, same_passive/shared_cooldown 중복 처리 수정

- 상태: `DONE_NON_RELEASE`
- 우선순위: `P1`
- 선행: P1-068
- 배경: 사용자가 P1-068 이후 "docs와 다른 점이 더 있는지" 전수 조사를
  요청했다. 서브 에이전트(fork)로 `docs/` 9개를 코드와 문장 단위 대조한
  결과, 문서 스테일니스 3건(전부 즉시 수정, 코드 변경 없음)과 실제 코드
  결함 1건을 찾았다.
- 문서 스테일니스 수정 (`docs/selection-semantics.md`, `docs/overview.md`,
  `docs/candidate-generation.md`): 3초 처치 문턱(`KILL_THRESHOLD_MET_3S`)과
  ε-Pareto 지배 필터링, Warmog 연속 비활성 시간 추적, 물리/마법 유효체력
  별도 지표 — 전부 삭제된 `darius_preview.py`(다리우스 전용 엔진, P1-066)
  시절 기능이며 지금 유일한 엔진(`cog_preview.py`)엔 처음부터 없었다.
  "지금 없음"으로 명시하도록 다시 썼다. 동점 처리 순서(골드 단순 비교가
  아니라 `CORE_COMPLETION_GOLD_WEIGHTED` 가중값 우선)도 정정했다.
- 코드 결함: `cog_preview.py`가 `same_passive`/`shared_cooldown` 그룹이
  겹치는 아이템 조합(예: 거대한 히드라+발걸음 분쇄기, 둘 다 `HYDRA_CLEAVE`;
  스테락의 도전+맬모셔스의 아귀, 둘 다 `LIFELINE`)을 하드 거부하고
  있었는데, 문서·정본 구현(`items/candidates.py`)은 "구매는 합법, 평가
  시점에 중복 계산만 막는다"였다. 다만 실제 평가 경로(`item_combat.py`)엔
  정본 평가기(`items/evaluation.py`)가 가진 "중복 발견 시 UNKNOWN 반환"
  안전장치가 전혀 없어서, 필터를 단순 삭제하면 효과가 조용히 두 번
  계산될 위험이 있었다(지금까지 찾은 버그 중 가장 위험한 방향 — "일부
  조합을 못 찾는다"가 아니라 "숫자가 틀려진다").
  - 해결: `item_combat.py`에 `duplicate_group_blockers()`를 신설해
    `items/evaluation.py`의 `_duplicate_group` 로직을 그대로 재사용
    (`UNRESOLVED_SAME_PASSIVE:<group>`/`UNRESOLVED_SHARED_COOLDOWN:<group>`
    블로커 생성). `cog_preview.py`의 두 군데(메인 탐색 루프,
    `_path_is_legal_beam` 슬롯 대안 탐색)에 중복돼 있던 인라인
    검사를 이 공용 함수 호출로 교체했다 — 실제로 걸러지는 조합은
    이전과 동일(여전히 채점 불가라 못 이김)하지만, 이제 두 곳이 서로
    다른 로직으로 갈라질 위험이 없고, 검색 중 한 번이라도 이런 조합을
    제외했으면 `SAME_PASSIVE_OR_SHARED_COOLDOWN_DUPLICATES_EXCLUDED`
    블로커로 결과에 명시된다(전에는 조용히 사라졌다).
  - `tests/test_item_combat_duplicate_groups.py` 신규(실제 잠긴 아이템
    ID로 4개 회귀 테스트 — 같은 그룹 두 개 거부, 그룹 안 겹치면 통과,
    `_path_is_legal_beam`이 같은 결과를 냄).
- 남은 사소한 항목(조치 안 함): `purchase_exclusive` 그룹 체크가
  `cog_preview.py`에 있지만 지금 잠긴 아이템 데이터엔 이 필드를 쓰는
  아이템이 0개라 죽은 코드 — 무해해서 그대로 뒀다.
- 검증: 전체 테스트 스위트(0 실패) · `ruff check .` 통과.

### P1-070 — 헤르메스가 계속 선택되는 근본 원인 조사, DEFENSE 분기 소실 폴백 수정

- 상태: `DONE_NON_RELEASE`
- 우선순위: `P1`
- 선행: P1-069
- 배경: 사용자가 다리우스 vs 가렌 웹 UI 스크린샷을 보고 "헤르메스가 왜
  계속 나오냐"고 재차 질문했다. 실측 결과 원인은 공격력이 아니었다:
  이 매치업에서 두 후보 빌드(헤르메스 경로 vs 발걸음 분쇄기 경로) 모두
  2코어 시점에 이미 가렌의 최대 체력(1763)을 전부 넘는 피해를 넣어
  `opponent_hp_lost`가 포화된다. `DAMAGE_TOTAL_8S = opponent_hp_lost ×
  uptime`이므로 이 시점부터 순위는 사실상 uptime(교전 가동률) 경쟁으로
  퇴화하고, uptime은 아이템 액티브의 이속 부여량이 좌우한다.
- 1차 조사: 헤르메스(퀵실버) 액티브의 `MOVE_SPEED_PERCENT` GRANT_STAT
  오퍼레이션에 `decay` 필드가 없어(발걸음 분쇄기는 `decay: LINEAR`로
  명시) 감쇠 없이 꽉 찬 값으로 계산된다는 걸 발견했으나, 원본 락 데이터
  (`item.json`, CDTB 바이너리)엔 감쇠 여부 자체가 기록돼 있지 않아 그
  필드를 채우는 건 프로젝트 자체 소스로 검증 불가능한 추측이 된다 —
  사용자 판단으로 보류.
- 근본 원인: `item_combat.py`의 `_active_duty_factor`가 지원하는 세 정책
  (`uncorrelated`/`per_engagement`/`always_ready`) 중 전역 기본값이
  `per_engagement`로 박혀 있어 액티브의 쿨타임을 아예 무시한다 — 쿨타임
  15초짜리(발걸음 분쇄기 돌진기)든 90초짜리(헤르메스 패닉 버튼)든
  "이번 교전엔 항상 준비돼 있다"고 동일하게 크레딧한다. 헤르메스는
  가렌(물리 100%/마법 0%) 상대로 주 스탯(마법저항 35)이 EHP에 0을
  더하는데도, 이 쿨타임 무시 정책 덕에 이속 부산물만으로 발걸음
  분쇄기보다 uptime을 더 벌어 이긴다.
- 검증: `active_duty_policy="uncorrelated"`(쿨타임 대비 지속시간 비율로
  크레딧)로 8개 매치업(근접×근접, 근접×아리, 아리×근접)을 샘플링.
  근접 vs 근접에서는 헤르메스 → 유무의 유령 검(진짜 결투 아이템)으로
  일관되게 교체됨. 아리가 낀 매치업은 그의 추천 아이템군에 쿨타임
  이속 액티브가 없어 무영향. 부작용 하나 확인: 근접이 아리처럼
  슬리퍼리한 원거리를 쫓아야 하는 매치업(가렌·아트록스 vs 아리)에서
  chassis 게이트가 전부 불통과로 바뀌며 DEFENSE 분기가 통째로 사라짐.
- DEFENSE 분기 소실 폴백 수정 (`cog_preview.py`, 오늘 적용 완료):
  기존엔 chassis 게이트를 만족하는 후보가 없거나, 만족해도 피해 손실
  한도(damage floor)를 넘는 후보가 없으면 `defense = None`이 되어
  `branches` 딕셔너리에서 DEFENSE 키 자체가 사라졌다(`DEFAULT`는 이미
  "chassis 게이트 전원 불통과 시 전체 후보 개방" 폴백이 있었는데
  `DEFENSE`엔 대응 폴백이 없었던 비대칭). 이제 두 단계 게이트를 각각
  독립적으로 완화한다:
  - chassis 게이트 전원 불통과 → 전체 합법 후보로 개방
    (`NO_CANDIDATE_MEETS_ALL_CORE_CHASSIS_FLOORS` 블로커,
    `DEFENSE_FALLBACK_NO_FULL_CHASSIS` 사유 코드)
  - chassis는 통과했지만 피해 손실 한도를 넘는 후보가 없음 → 한도 없이
    chassis 통과 후보 전체로 개방 (`NO_CANDIDATE_MEETS_DEFENSE_DAMAGE_FLOOR`
    블로커, `DEFENSE_FALLBACK_NO_DAMAGE_FLOOR_MET` 사유 코드)
  - `PRIMARY_DAMAGE_FLOOR_PASSED` 제약과 `_defense_gate` 슬롯 대안 탐색도
    동일한 두 단계 로직을 그대로 재사용하도록 맞췄다. `NO_FEASIBLE_
    DEFENSE_BRANCH` 블로커와 `defense is None` 분기는 제거(항상 존재).
  - 웹 UI(`app.js`)의 "적격 방어 분기 없음" 전용 카드는 이제 도달 불가라
    삭제, 새 사유 코드 2개의 한국어 라벨 추가.
  - `tests/test_champion_cogs.py`의
    `test_generic_preview_does_not_fabricate_an_ineligible_defense_branch`를
    `test_generic_preview_falls_back_instead_of_dropping_an_infeasible_defense_branch`로
    재작성 — "분기가 사라지는 게 맞다"에서 "DEFAULT처럼 폴백해야 한다"로
    검증 방향 자체가 바뀜.
  - `docs/selection-semantics.md`의 DEFENSE 절에 두 단계 폴백 명시.
- 전역 정책 전환 적용 완료: DEFENSE 소실 폴백 수정을 전체 스위트로
  검증한 뒤 `active_duty_policy` 기본값을 `matchup.py`
  (`MatchupRequest.active_duty_policy`)와 `cog_preview.py`
  (`_DEFAULT_ACTIVE_DUTY_POLICY`)에서 `per_engagement → uncorrelated`로
  실제 전환했다. `docs/selection-semantics.md`의 "Lane sustain and
  engagement" 절에 근거 설명 추가. 이 전환으로 `test_champion_cogs.py`의
  DEFENSE 폴백 테스트 하나가 실패해(아트록스 vs 아리가 손실 한도 미달
  단계가 아니라 chassis 게이트 자체를 전부 놓치는 단계로 바뀜) 두 매치업
  (아트록스 vs 아리 = chassis 실패, 다리우스 vs 가렌 손실 한도 0 강제 =
  손실 한도 실패)을 각각 검증하는 테스트 2개로 재작성했다.
- 슬롯별 "2위 후보 왜 누락됐나" 표시 (사용자 요청, 오늘 추가): 기존엔
  `alternative_count == 0`(다른 아이템이 있었지만 전부 이 분기의 게이트를
  못 넘김)인 경우 `SlotRunnerUp.item_id = None`이고 비교 데이터가 전혀
  없어 UI에 "대안 없음"이라고만 뜨고 왜 없는지는 알 수 없었다.
  - `_slot_runner_up_beam_candidate`가 게이트를 통과한 후보가 하나도
    없을 때, 게이트를 무시하고 순위만 매겨서 "가장 근접했던 게이트
    실패 후보"(state, metrics)도 함께 반환하도록 확장했다(반환값
    4-tuple → 6-tuple).
  - 신설 `_slot_exclusion_reasons(branch, state, metrics)`가
    `_default_gate`/`_defense_gate`와 정확히 같은 2단계 폴백 구조를
    재사용해 그 후보가 정확히 어떤 조건(`ALL_CORE_ENGAGE_READY_NOT_MET`
    / `ALL_CORE_CHASSIS_READY_NOT_MET` / `ALL_CORE_ITEM_PASSIVES_READY_
    NOT_MET` / DEFENSE 전용 `DEFENSE_DAMAGE_FLOOR_NOT_MET`)를 못
    넘었는지 판정한다.
  - `SlotRunnerUp`(`recommendation/explanation.py`)에
    `excluded_item_id`/`excluded_reason_codes`/`excluded_metric_
    comparisons` 3개 필드 추가, `build_slot_runner_up`이 채워 넣는다.
    공용 비교 로직은 `_metric_comparisons` 헬퍼로 추출해 정상 러너업과
    제외된 후보 양쪽이 재사용한다.
  - 웹 UI(`app.js`)는 `alternative_count == 0`이면서
    `legal_alternative_count > 0`인 슬롯에서 "이 분기 조건을 넘긴 게
    없음 · 가장 근접한 후보 · <아이템명>"을 펼쳐서 사유 코드 목록과
    지표 비교를 보여준다. 새 한국어 라벨 4개(`slotExclusionLabels`) 추가.
  - 실측 예시(`tests/test_champion_cogs.py::
    test_slot_runner_up_names_the_best_gate_failing_alternative_and_why`):
    다리우스 vs 가렌 DEFENSE 분기 1코어(망자의 갑옷) 슬롯은 대안 59개
    중 게이트를 넘긴 게 하나도 없는데, 가장 근접했던 건 워모그의 갑옷 —
    이 결투 길이(8초) 안에선 워모그의 심장 패시브가 활성화되지 않아
    `ALL_CORE_ITEM_PASSIVES_READY_NOT_MET`으로 걸러진다(혼합 유효체력
    +683.6, 30초 회복량 +122.4, 8초 후 체력 +732.7이었을 후보).
- 검증: `tests/test_champion_cogs.py` 단독 통과(18/18). 전체 테스트
  스위트(0 실패) · `ruff check .` 통과.

### D-001 — 통계 플러그인

- 상태: `DEFERRED`
- 시점: Phase 2 이후
- 제약:
  - core 후보를 삭제하거나 계산 점수·순위를 수정할 수 없다.
  - 표본 수, 관측 빈도, recall, 난이도 라벨만 보강한다.
  - 플러그인을 제거해도 core 추천 결과가 같아야 한다.

### D-002 — LLM 기반 큐레이션 초안

- 상태: `DEFERRED`
- 시점: 수작업 큐레이션 비용 측정 이후
- 제약:
  - 빌드 타임에만 사용한다.
  - 숫자 생성과 자동 승인을 금지한다.
  - 사람 검수 전 결과는 `UNVERIFIED`다.

### D-004 — 숙련자(장인) 빌드 정성 근거 코퍼스

- 상태: `TODO`
- 우선순위: `P1`
- 배경: 외부 피드백(2026-09) — "승률 통계보다 실제 장인들이 쓰는 빌드가
  중요하고, 챔피언마다 가는 템이 달라 그 디테일은 통계로 잘 구분되지 않으니
  정성적 데이터가 더 맞을 수 있다." 승률 통계를 추천 점수에서 배제한 이유
  (생존 편향·역인과)와 같은 문제의식이며, `docs/evidence/volibear-build-hypotheses.md`
  가 이미 선례다.
- 역할: 추천 입력이 아니라 **검증·불일치 탐지 자료**다(`docs/overview.md`
  5절의 "감각 — 상위 티어 대조" 계층). 숫자는 계속 계산 엔진만 만든다.
- 작업:
  - 챔피언별 숙련자 빌드 레코드 스키마를 정의한다: 출처(영상/글 URL,
    타임스탬프 또는 챕터), 작성자, 공개일, 해당 패치, 아이템 ID(해당 패치
    Data Dragon 기준), 상황 조건(상대·라인 상태), 연구 단계와 최종안 구분.
  - 파일럿 챔피언 3~5명으로 레코드를 수집하고 아이템 ID를 정규화한다.
  - 같은 챔피언·상대로 엔진의 세 분기를 계산해 불일치 리포트를 만든다.
    각 불일치는 볼리베어 문서의 분류(모델 오류 / 범위 밖 / 증거 부족 /
    미검증 가설)로 판정한다.
- 제약:
  - D-001과 동일하게 core 후보를 삭제하거나 점수·순위를 수정할 수 없다.
  - 숙련자 빌드에는 숙련도·게임 상태·부품 순서 등 v1이 계산하지 않는 축이
    섞여 있으므로, 불일치를 곧바로 엔진 오류로 간주하지 않는다.
  - 요약본·자동 번역은 `UNTRUSTED_DERIVATIVE`로 취급하고 원본 확인 전에는
    가설로만 둔다.
  - 수집은 build-time에만 하며 런타임 네트워크 호출 0회 원칙을 유지한다.
- 완료 조건:
  - 파일럿 챔피언 레코드가 스키마 검증을 통과한다.
  - 불일치 리포트의 모든 항목이 네 분류 중 하나로 판정돼 있다.
  - 모델 오류로 판정된 항목은 개별 Task로 분리돼 있다.

### D-003 — 추가 시나리오와 챔피언 확장

- 상태: `MERGED` (→ P1-063)
- 시점: M0 통과 이후
- 범위: 폭딜 시나리오, 다대다 시나리오, 챔피언 3개 수직 슬라이스
- 진행: 다대다 시나리오는 P1-065로 분리해 구현했다. 폭딜 시나리오는 미착수다.
- 현재 진행:
  - 사용자 요청으로 Darius 대 Garen 레벨 13 결투 fixture와 Darius 챔피언
    프로필을 선행 구현했다.
  - Garen Q 침묵, W 피해 감소 창·보호막, Darius 출혈 5스택·궁 스택
    배율을 구조화했으며 모두 검증 전 상태로 유지한다.
  - Darius 평타·W·Q의 출혈 스택, 5스택 직후 R, 출혈 틱을 전투 이벤트로
    연결하고 Garen Q 침묵에 의한 스킬 취소와 W 보호막·피해 감소 창을
    타임라인에 적용했다.
  - 스테락·칠흑의 양날 도끼·헤르메스·몰락한 왕의 검으로 24개 3코어
    순열을 만들고, 복수 강인함 중첩 12개를 UNKNOWN 정책에 따라 제외한 뒤
    두 번째 `SYNTHETIC_NON_RELEASE` 세 분기를 결정론적으로 생성한다.
  - 미구현 핵심 효과가 있는 경로를 정적 스탯만으로 부분 채점하던 동작을
    제거했다. 전체 효과 구현 전에는 해당 경로가 `UNKNOWN`으로 제외되고
    `NO_SCORABLE_CANDIDATES_UNIMPLEMENTED_ITEM_EFFECTS`를 반환한다.
- 후속 검증:
  - 전 아이템 핵심 패시브·액티브 문서의 구조화는 완료됐고 미구현 인벤토리는
    0개다. 온라인 전투 상태가 필요한 조건은 P1-063의 non-release blocker로
    이동했다.
  - W 실제 공격 초기화와 챔피언별 시전·적중 타이밍은 잠긴 상세 원본 또는
    클라이언트 실측으로 승격한다.

## 바로 착수할 Task

### M0 차단 (코드로 풀 수 없음)

- P0-041·P0-035: 16.17.1 클라이언트 실측 대기. 실측 절차는
  `docs/verification/cc-blind-16.17.1-ko-runbook.md`에 고정돼 있다.
- P0-051·P0-052: 위 실측으로 근거가 승격된 뒤 실제 세 분기와 provenance를
  연결한다.
- P0-023: 중앙 작성 시간 측정만 남은 `PARTIAL`이며 엔진 구현을 막지 않는다.

### 코드로 진행 가능한 다음 작업

1. P1-064 남은 31개 챔피언 승격과 광역기 Cog의 `MULTI_TARGET` 확장.
2. D-004 숙련자 빌드 코퍼스 파일럿 — 엔진 결과를 외부 정성 근거와 대조할
   첫 수단이다.
3. P1-067의 남은 과제: 방어 분기 우선순위 설계 검토(P1-068에서 DEFENSE는
   스펙대로 유지로 확정됐으므로 새 근거가 있을 때만 재개).

최근 작업은 P1-066~070(다리우스 전용 엔진 제거, 전수 탐색 전환, DEFAULT
게이트·순위 수정, 중복 그룹 처리, DEFENSE 폴백과 액티브 가동률 정책)이다.
