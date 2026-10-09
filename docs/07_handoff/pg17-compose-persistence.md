# PostgreSQL 17 로컬 Compose 전환·복구

이 구성은 2026-10-08 Supabase 복원본을 담은 **기존** Docker 볼륨을 사용한다. 일반적인 빈 DB 설치 절차가 아니다. `docker compose up` 전에 아래 볼륨과 데이터베이스 식별자를 확인한다. `docker compose down -v`, 볼륨 삭제/초기화, PG16 데이터 경로 재사용은 금지한다.

## 구성과 선택 이유

- `db`: PostgreSQL 17, 외부 볼륨 `bidcheck_v4_supabase_pg17_20261008`, `55432:5432`, healthcheck와 `unless-stopped`.
- `api`, `migrate`, `notice-poller`, `master-data-import`: 같은 Compose 네트워크의 `db:5432` 사용. `notice-poller`는 `collector` 프로필을 명시할 때만 실행한다.
- 첨부문서는 기존 외부 볼륨 `bid-change-validator-v4_notice_documents_data` 사용.
- Compose 프로젝트는 `bidcheck-v4-pg17`이다. 이전 `bid-change-validator-v4` 프로젝트의 PG16 컨테이너와 볼륨은 그대로 보존한다.
- DB 시작 전 `PG_VERSION=17`과 PostgreSQL system identifier를 확인한다. 기존 볼륨이 없거나 다른 클러스터면 **실패**하며 새 DB를 만들지 않는다. 비정상 종료 후 남을 수 있는 `postmaster.pid`는 PostgreSQL 자체 복구·잠금 검사에 맡긴다.

선택한 방식은 기존 수동 PG17 컨테이너를 중지한 뒤, **같은 데이터 볼륨**을 새 Compose 관리 PG17 컨테이너에 연결하는 것이다. 수동 컨테이너를 Compose가 자동으로 인수할 수 없기 때문이다. 기존 프로젝트에서 `db` 서비스만 PG17로 바꾸면 Compose가 보존해야 할 PG16 컨테이너를 교체할 수 있으므로 프로젝트를 분리했다. 수동 컨테이너를 독립 유지하는 방식은 현재 재시작 정책으로 재부팅은 가능하지만, Compose가 DB의 시작·healthcheck를 관리하지 못하고 재배포 때 기존 PG16 `db`가 다시 올라올 위험이 있다.

## 전환 전 읽기 전용 확인

```powershell
docker inspect bidcheck-v4-supabase-pg17-20261008 --format '{{.HostConfig.RestartPolicy.Name}} {{range .Mounts}}{{.Name}}:{{.Destination}}{{end}}'
docker volume inspect bidcheck_v4_supabase_pg17_20261008 bid-change-validator-v4_notice_documents_data
docker exec bidcheck-v4-supabase-pg17-20261008 psql -U bidjigi -d bidjigi -Atqc "SELECT system_identifier FROM pg_control_system()"
docker exec bidcheck-v4-supabase-pg17-20261008 psql -U bidjigi -d bidjigi -Atqc "SELECT version_num FROM alembic_version"
docker compose --env-file .env config --quiet
```

기준 system identifier는 `7694180214230085666`, Alembic은 `024_analysis_run_coverage`이다. 별도 복원본을 쓰는 경우 식별자를 **실제로 확인한 뒤** `PG17_EXPECTED_SYSTEM_ID`를 지정한다. PR #7의 미병합 migration은 적용하지 않는다. `.env`의 `DATABASE_URL`은 컨테이너 내부 `db:5432/bidjigi`, `POSTGRES_PORT=55432`, `API_PORT=18000`이어야 한다. 비밀번호는 출력하거나 커밋하지 않는다.

## 실제 전환 — 이용자 승인과 작업 중단 확인 후

현재 API를 쓰는 작업자가 없고 백업이 있는지 확인한 뒤 수행한다. 기존 수동 PG17과 새 Compose PG17을 **같은 볼륨에 동시에 실행하면 안 된다**. 아래 명령은 기존 컨테이너를 삭제하지 않는다.

```powershell
docker update --restart=no bid-change-validator-v4-api-1 bidcheck-v4-supabase-pg17-20261008
docker stop bid-change-validator-v4-api-1
docker stop bidcheck-v4-supabase-pg17-20261008
docker compose --env-file .env up -d --build api
docker compose --env-file .env ps
```

`api`의 의존성으로 `db`가 healthy가 된 뒤 `migrate`가 완료된다. `develop`의 migration head가 로컬 DB의 024보다 높으면 자동 적용될 수 있으므로, 실행 직전 두 값을 다시 비교한다. `notice-poller`는 자동으로 켜지지 않는다. 수집이 필요한 경우 팀과 중복 수집 여부를 확인한 뒤 `docker compose --profile collector --env-file .env up -d notice-poller`를 별도로 실행한다.

## 전환 후 확인

```powershell
docker compose --env-file .env ps
docker compose --env-file .env exec -T db psql -U bidjigi -d bidjigi -Atqc "SELECT system_identifier FROM pg_control_system()"
docker compose --env-file .env exec -T db psql -U bidjigi -d bidjigi -Atqc "SELECT 'notices', count(*) FROM bid_notices UNION ALL SELECT 'versions', count(*) FROM bid_notice_versions UNION ALL SELECT 'documents', count(*) FROM notice_documents UNION ALL SELECT 'analyses', count(*) FROM qualification_analysis_runs"
Invoke-WebRequest http://127.0.0.1:18000/health -UseBasicParsing
```

공고/버전/문서/분석의 전환 전 기준은 각각 1,301/1,489/5,781/189건이다. 이후 쓰기가 발생하면 건수는 증가할 수 있으므로 동일 클러스터 식별자, 최신 차수 관계와 데이터 감소 여부를 함께 확인한다. Windows 호스트 `127.0.0.1:55432`와 Compose 내부 `db:5432`의 식별자가 같아야 한다. Docker Desktop이 실행되면 `db`·`api`는 `unless-stopped`로 자동 시작하며, API 재배포 시 `depends_on: service_healthy`가 DB 준비를 기다린다. **Windows 로그인만으로 자동 복구하려면 Docker Desktop의 "Start Docker Desktop when you log in" 설정도 켜야 한다.** 이 설정은 Compose가 관리하지 않으며, 2026-10-08 점검 당시 로컬 `AutoStart=False`였다. Docker Desktop 자체를 켜지 않으면 컨테이너도 시작하지 않는다.

## 롤백

새 프로젝트가 실패하면 먼저 새 API와 DB를 멈춘다. **볼륨은 내리지 않는다.** 원래 수동 컨테이너가 그대로 있고 같은 외부 볼륨을 다시 사용할 수 있다.

```powershell
docker compose --env-file .env stop api db
docker start bidcheck-v4-supabase-pg17-20261008
docker start bid-change-validator-v4-api-1
```

이후 기존 프로젝트 네트워크 `db` alias와 API `/health`를 확인한다. 새 DB가 마이그레이션이나 쓰기를 한 경우 옛 API 이미지와 스키마 호환성을 먼저 확인한다. 기존 PG16 컨테이너·볼륨과 논리/물리 백업은 별도로 보존하며, 롤백 명령에 포함하지 않는다.
