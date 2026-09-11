# Rift Foundry

> [!NOTE]
> Rift Foundry is a personal "toy project" currently in progress;
> there is no guarantee that all results will be accurate or perfect.

패치에 고정된(patch-locked) 로컬 League of Legends 아이템 빌드 추천 엔진입니다.
런타임에 LLM이나 외부 네트워크를 호출하지 않습니다. **숫자는 전부 결정적
계산 엔진이 생성**하고 — 승률 통계나 LLM이 빌드를 정하지 않습니다 — 무엇을
계산하지 않는지도 응답에 그대로 드러냅니다.

**사전 요구사항**: Python 3.12 이상, [uv](https://docs.astral.sh/uv/getting-started/installation/).

```console
uv sync --locked --dev
uv run python -m lol_build.application.web
# → http://127.0.0.1:8765
```

## 왜 이런 접근인가

- **최적화가 아니라 제약 만족 문제로 다룹니다.** 골드는 예산이 아니라
  타임라인(대부분 3~4코어에서 게임이 끝남)이고, DPS는 목적함수가 아니라
  생존과 곱셈으로 엮여 있으며, 폭딜은 가중합이 아니라 문턱 게이트로 다뤄야
  합니다(단, 현재 범용 엔진에는 처치 문턱 게이트가 없고 교전 진입·체급·패시브
  준비도 게이트만 있습니다 — `docs/selection-semantics.md`).
- **숫자를 LLM이 만들면 구조적으로 틀리고 검증이 불가능해집니다.** 그래서
  추천은 계산 엔진이 하고, LLM이 관여하더라도 빌드 타임 지식 베이스
  구축뿐이며 그 지식도 사람이 검증합니다.
- **승률 통계는 추천 점수에 쓰지 않습니다.** 생존 편향·역인과(밀리는
  사람이 방어템을 산다)로 오염돼 있어 방어 아이템을 구조적으로 저평가하기
  때문입니다. 통계는 설명·비교에만 씁니다.
- **모델이 담지 못하는 축은 없는 것처럼 취급하지 않습니다.** 예를 들어
  현재 게임 상태(우위/열세)는 계산하지 않는데, 이 사실을 숨기지 않고 모든
  추천 응답의 `assumptions.game_state` 필드로 노출합니다.

왜 이렇게 설계했는지, 교전·빌드가 정확히 어떤 공식과 규칙으로 계산되는지는
**[`docs/overview.md`](docs/overview.md)**에 자세히 있습니다.

## 프로젝트 구조

```text
src/lol_build/
├── core/            # Decimal 수식, 전투 공식, 타임라인 이벤트, CC, 검증
├── items/           # 잠긴 아이템 카탈로그, 효과, 후보 생성, 빌드 진행
├── cogs/            # 역할 중립 챔피언 행동과 레지스트리 (아래 표)
├── scenarios/       # 시나리오 계약과 클라이언트 실측 근거
├── simulation/      # core 전투 타입 위에서 도는 로테이션 스케줄러
├── recommendation/  # 게이트, Pareto 선택, 응답, 근거(provenance)
├── application/     # 매치업 디스패치·프리뷰·Web UI (합성 루트)
└── buildtime/       # 스냅샷 수집, 패치락 검증, 드리프트 리포트
```

의존 방향은 항상 `core`를 향하고, `application`이 합성 루트입니다. 경계는
`tests/test_package_architecture.py`가 강제합니다(`docs/architecture.md`).

## 챔피언 Cog 성숙도

173명 전원이 `src/lol_build/cogs/champions/` 아래 전용 모듈을 갖고, 폴더
위치가 곧 성숙도입니다(어긋나면 `tests/test_all_champion_modules.py` 실패).

| 폴더 | 의미 | 개수 |
|---|---|---|
| `todo/` | 미구현 (기본 공격 폴백뿐) | 31 |
| `wip/` | 로테이션은 있지만 특정 메커니즘을 명시적으로 제외/근사 | 104 |
| `modeled_unverified/` | 로테이션 전체 구현, 클라이언트 검증만 대기 | 38 |
| `curated/` | 구현·검증 모두 완료 | 0 |

분류 기준과 한계는 `docs/overview.md`의 [6절](docs/overview.md#6-챔피언-cog-성숙도--폴더-분류-기준)에 있습니다.

## 시작하기

```console
# 전체 검증 (pytest, ruff check는 통과; ruff format --check는 아직 미적용 —
# ADR-0001 참고)
uv run pytest && uv run ruff check .

# 로컬 Web UI
uv run python -m lol_build.application.web

# 1대1 CLI — 역할 대칭 매치업 디스패치
uv run python -m lol_build.application.matchup Garen Aatrox \
  --actor-items 6631 --opponent-items 3071 --recommend

# 추천 게이트를 오프라인으로 직접 확인
uv run python -m lol_build.recommendation.readiness --root .
```

Web UI는 로컬호스트에만 바인딩되고, 런타임에 CDN·이미지·게임 API를 전혀
불러오지 않습니다 — 자세한 내용은 `docs/web-ui.md`.

## v1 범위 밖

가장 큰 항목은 **게임 상태 축**(우위/열세에 따라 정답 빌드가 뒤집히는 것)이며,
밴픽 시점엔 입력이 없고 승률 통계로 검증도 안 돼서 v1엔 넣지 않았습니다.
대신 방어 분기가 항상 남도록 하는 회귀 테스트와 `assumptions.game_state`
라벨을 안전장치로 넣었습니다. 그 밖에 부품 구매 순서, 장기 라인전, CC 채널
분해도 범위 밖입니다. 전체 근거는 `docs/overview.md`의
[7절](docs/overview.md#7-의도적으로-빠진-것--v1-범위-밖), 계획은 `TASKS.md`에
있습니다.

## 기여 규칙

- 숫자는 `Decimal`만 — `float`는 계산·출력 경계에서 거부됩니다.
- 근거 없이 값을 만들지 않습니다 — 검증 불가능한 메커니즘은 챔피언 스코프
  blocker로 남기고, 2차 자료는 원본 확인 전까지 가설로만 취급합니다.
- 성공 기준을 불편한 결과 때문에 옮기지 않습니다 — 범위 한계는 명시하되
  목표는 유지합니다.
- 새 축을 추가하기 전에 기존 모델로 표현 가능한지 먼저 시도합니다.
- 커밋 전에 `uv run pytest && uv run ruff check .`.
- 작업 계획·완료 조건·현재 근거는 `TASKS.md`에서 관리합니다.

근거는 `docs/overview.md`의 [8절](docs/overview.md#8-기여-규칙의-근거)에 있습니다.

## 라이선스

[PolyForm Noncommercial License 1.0.0](LICENSE) — 비상업적 목적(연구·학습·
개인 취미 프로젝트)은 자유롭게 사용할 수 있습니다. 상업적 사용은 별도
라이선스가 필요합니다 — `LICENSE` 파일의 "Commercial licensing" 항목을
참고하세요.

## 더 읽을 것

설계 근거·계산 규칙·ADR을 포함한 전체 문서 색인은
**[`docs/README.md`](docs/README.md)**에 있습니다.
