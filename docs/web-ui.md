# Local Web UI

The Web UI is a thin application adapter over the same patch-locked engine used by tests and
CLI commands. It loads no CDN, font, image, analytics, or gameplay API at runtime. Korean
champion/item names and the nine official item-icon sprite sheets are stored in the local patch
snapshot and covered by `patch.lock.json` hashes.

Start it from the repository root:

```bash
uv run python -m lol_build.application.web
```

Open `http://127.0.0.1:8765`. The server binds to loopback by default. A different local port
can be selected with `--port`; exposing it on a non-loopback host is intentionally not the
default because the service has no authentication layer.

After **빌드 계산 시작** is clicked, the server terminal prints live milestones with a
request identifier. Concurrent requests remain distinguishable and every line is flushed
immediately. Every actor, with no matchup-specific exception, reports the same per-core
milestones from the shared exhaustive search: every legal three-item ordered path is
evaluated, so nothing is pruned between cores before its continuations are tried.

```text
[추천 #0001] START 후보 빌드 계산 요청 수신
[추천 #0001] 1/7 입력 검증 완료
[추천 #0001] 2/7 후보 아이템 풀 준비 완료 · 112개
[추천 #0001] 3/7 1코어 후보 평가 완료 · 누적 81개 / 경로 81개 / 실계산 81개
[추천 #0001] DONE 후보 빌드 계산 완료 · 17.42초
```

The browser developer console also records the submitted input and final elapsed time.

The UI supports two operations:

- **Build recommendation** ranks default, offense, and defense three-core branches for the
  selected actor. Evidence blockers remain visible and release eligibility is never inferred
  by the browser. Each branch includes an expandable **왜 이 빌드인가?** trace: the actual
  selection policy, passed gates, item roles derived from locked stats/effects, and metric
  differences against a finalist runner-up or another selected branch. The result header keeps
  selection outcome, verification, and scope separate, and a visible notice states that current
  game state is `NOT_MODELED`.
- **Current-build combat** evaluates both selected item paths through the role-symmetric
  matchup timeline.

JSON endpoints:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Local process health |
| `GET` | `/api/catalog` | Locked champion and complete-item options |
| `POST` | `/api/evaluate` | Two-sided deterministic matchup |
| `POST` | `/api/recommend` | Actor-owned three-branch recommendation |

POST bodies are limited to 64 KiB, require `application/json`, and accept no more than three
unique complete items per participant.
