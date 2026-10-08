# AWS 개발·MVP 배포

서울 리전의 단일 EC2에서 Caddy(HTTPS), Vinext, FastAPI, notice-poller를 Docker Compose로 실행한다. 구조화 데이터는 기존 RDS PostgreSQL 17(`bidjigi`, `bidcheck_app`, TLS, Alembic `024`), 첨부 원본은 비공개 S3에 저장한다. 이 Compose에는 DB 컨테이너와 자동 Alembic 서비스가 없다. PR #7의 `025`도 적용하지 않는다.

## 배포

- `develop`의 기존 CI가 성공한 커밋에서만 `AWS dev build and deploy` 워크플로를 수동 실행한다. `deploy=false`는 이미지를 SHA 태그로 빌드·저장만 하고, `deploy=true`는 SSM으로 EC2까지 배포한다. `develop` push만으로 자동 배포하지 않는다.
- GitHub OIDC 역할은 해당 저장소의 `develop`에만 허용된다. EC2는 인스턴스 역할로 S3/ECR/SSM에 접근한다. 장기 AWS 키는 GitHub와 EC2에 저장하지 않는다.
- EC2의 `/opt/bidcheck/.env`는 `prepare-env.py`가 SSM SecureString에서 생성한다. 파일 권한은 `0600`이며 Git에 포함되지 않는다.
- `deploy.sh`는 이미지 pull → 스키마/TLS/RLS 읽기 전용 검사 → 서비스 교체 → HTTPS 헬스체크 순서로 실행한다. 실패하면 이전 SHA 이미지를 다시 띄우며 DB/S3는 되돌리지 않는다. 이전 SHA는 `/opt/bidcheck/.previous-release`에 보관한다.
- 수집기는 `/opt/bidcheck/collector.enabled`가 있을 때만 배포에 포함된다. 로컬 수집기와 동시에 실행하지 않는다. 컨테이너는 정상 종료 신호를 받고 최대 90초 기다린다.

## 검증 및 운영

- `https://15-165-249-43.sslip.io/health`가 200인지 확인하고, `/login`과 인증 후 공고 목록·상세를 확인한다.
- `docker compose --env-file .env -f docker-compose.yml --profile collector ps`와 `logs notice-poller`로 한 개의 수집기만 실행 중인지 확인한다.
- `smoke_storage.py`는 S3에 작은 일회용 객체를 쓰고 읽은 뒤 그 객체만 지우며, 기존 PDF/HWP/HWPX 한 건씩을 읽어 SHA256과 추출을 확인한다. 기존 첨부와 DB는 수정하지 않는다.
- 현재 관리자 비밀번호는 사용자의 요청에 따라 기존 값을 유지한다. 따라서 `APP_ENVIRONMENT=development`, `AUTH_REQUIRED=true`, Secure Cookie로 실행하며 EC2 보안 그룹의 80/443은 현재 개발 PC IP `/32`로 제한한다. 인터넷 전체 공개 전에 강한 비밀번호 교체 및 production 설정 검증이 필요하다.
- HTTPS 인증서는 Caddy 볼륨에 유지된다. IP 제한 상태에서는 ACME 인증기관이 80번 포트에 접근할 수 없으므로 인증서 갱신 때 80번 포트를 잠깐 열어 발급·갱신을 확인한 뒤 즉시 다시 `/32`로 제한해야 한다. 443번은 계속 제한한다.
- RDS와 로컬 PG17 백업은 별도로 보존한다. 장애 시 AWS 수집기 하나를 먼저 중지하고 로컬 수집기를 다시 시작한다. 두 수집기를 동시에 켜지 않는다.

## 비용

단일 `t3.small`, 기존 `db.t3.micro`, 30GiB gp3, 같은 리전 S3/ECR, S3 Gateway VPC Endpoint로 구성했다. NAT Gateway, ALB, 다중 AZ, S3 Versioning과 상시 GitHub 자동 배포는 사용하지 않는다. 월 60달러 예산 알림은 50/80/100%에서 이메일로만 통지하며 자원을 자동 중지하지 않는다.
