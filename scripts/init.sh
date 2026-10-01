#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# init.sh — 하네스 엔지니어링 개발 환경 시작 스크립트
#
# 논문 근거 (P-02 Initializer Agent):
#   "어떤 Coder 에이전트도 bash init.sh만으로 즉시 작업 시작 가능해야 한다."
#
# 사용법:
#   bash init.sh            # 전체 초기화 + 서버 시작
#   bash init.sh --test     # 초기화 + E2E 기본 테스트만
#   bash init.sh --install  # 의존성 설치만
# ═══════════════════════════════════════════════════════════════════════

set -e  # 오류 발생 시 즉시 중단

# ── 색상 코드 ────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'  # No Color

log_info()    { echo -e "${BLUE}[INFO]${NC}  $1"; }
log_success() { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ── 실행 모드 파싱 ────────────────────────────────────────────────────────────
MODE="full"
for arg in "$@"; do
  case $arg in
    --test)    MODE="test" ;;
    --install) MODE="install" ;;
    --help)
      echo "사용법: bash init.sh [--test|--install|--help]"
      exit 0 ;;
  esac
done

# ── 0. 작업 디렉토리 확인 ────────────────────────────────────────────────────
# 이 스크립트는 scripts/ 안에 있다 — 프로젝트 루트는 그 상위 디렉터리다.
# (이전에는 scripts/ 자신을 루트로 잡아 web_target/requirements.txt 를 찾지 못하고
#  모든 설치 단계를 조용히 건너뛰었다.)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log_info "프로젝트 루트: $PROJECT_ROOT"
cd "$PROJECT_ROOT"

# ── 1. Node.js 버전 확인 ─────────────────────────────────────────────────────
log_info "Node.js 버전 확인 중..."
NODE_VERSION=$(node -v 2>/dev/null | sed 's/v//' | cut -d. -f1)
if [ -z "$NODE_VERSION" ] || [ "$NODE_VERSION" -lt 18 ]; then
  log_error "Node.js 18 이상이 필요합니다. 현재: $(node -v 2>/dev/null || echo '없음')"
fi
log_success "Node.js $(node -v) 확인됨"

# ── 2. 환경변수 파일 확인 ─────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    cp .env.example .env
    log_warn ".env 파일이 없어 .env.example에서 복사했습니다. 값을 직접 설정하세요."
  else
    # 기본 .env 생성
    cat > .env << 'EOF'
# 하네스 엔지니어링 환경변수
VITE_API_BASE_URL=http://localhost:3001/api
VITE_APP_TITLE=Harness Web App

# 서버 설정
API_PORT=3001
NODE_ENV=development

# 데이터베이스 (실제 값으로 교체)
DATABASE_URL=postgresql://localhost:5432/harness_dev
EOF
    log_warn ".env 파일을 기본값으로 생성했습니다. 실제 값으로 교체하세요."
  fi
fi
log_success ".env 파일 확인됨"

# ── 3. 프론트엔드 의존성 설치 ─────────────────────────────────────────────────
if [ -d "web_target" ]; then
  log_info "프론트엔드 의존성 설치 중 (web_target/)..."
  cd web_target
  if [ ! -d "node_modules" ] || [ "package.json" -nt "node_modules" ]; then
    npm install --silent
    log_success "프론트엔드 의존성 설치 완료"
  else
    log_success "프론트엔드 의존성 최신 상태"
  fi
  cd "$PROJECT_ROOT"
fi

# ── 4. Python 의존성 설치 (하네스) ───────────────────────────────────────────
if [ -f "requirements.txt" ]; then
  log_info "Python 하네스 의존성 설치 중..."
  pip install -r requirements.txt -q
  log_success "Python 의존성 설치 완료"
fi

if [ "$MODE" = "install" ]; then
  log_success "의존성 설치 완료. (--install 모드: 서버 시작 생략)"
  exit 0
fi

# ── 5. 기존 개발 서버 정리 ───────────────────────────────────────────────────
log_info "기존 서버 프로세스 정리 중..."
pkill -f "vite" 2>/dev/null || true
pkill -f "node.*server" 2>/dev/null || true
sleep 1

# ── 6. 개발 서버 시작 ────────────────────────────────────────────────────────
DEV_PORT=5173
API_PORT=3001

if [ -d "web_target" ]; then
  log_info "프론트엔드 개발 서버 시작 중 (포트 $DEV_PORT)..."
  cd web_target
  npx vite --port "$DEV_PORT" &
  VITE_PID=$!
  cd "$PROJECT_ROOT"
fi

  # API 서버: server/ 는 web_target 으로 대체된 이전 아키텍처라 삭제했다.
  # 로그인 등을 수동으로 확인하려면 web_target/mock-server.js 를 직접 실행한다.

# ── 7. 헬스체크 ──────────────────────────────────────────────────────────────
log_info "서버 기동 대기 중 (최대 30초)..."
MAX_WAIT=30
WAITED=0

while [ $WAITED -lt $MAX_WAIT ]; do
  if curl -s "http://localhost:$DEV_PORT" > /dev/null 2>&1; then
    log_success "프론트엔드 서버 준비됨: http://localhost:$DEV_PORT"
    break
  fi
  sleep 1
  WAITED=$((WAITED + 1))
done

if [ $WAITED -ge $MAX_WAIT ]; then
  log_warn "프론트엔드 서버 시작 대기 시간 초과. 수동 확인이 필요합니다."
fi

# ── 8. 기본 E2E 스모크 테스트 (Playwright/Puppeteer) ─────────────────────────
if [ "$MODE" = "test" ] || [ "$MODE" = "full" ]; then
  log_info "기본 E2E 스모크 테스트 실행 중..."

  # Playwright 사용 가능 여부 확인
  if command -v playwright > /dev/null 2>&1; then
    cd web_target 2>/dev/null || true
    npx playwright test tests/smoke.spec.ts --reporter=line 2>/dev/null || \
      log_warn "스모크 테스트 실패 — 코드 확인 필요"
    cd "$PROJECT_ROOT"
  elif command -v puppeteer > /dev/null 2>&1; then
    node scripts/smoke_test.js 2>/dev/null || \
      log_warn "스모크 테스트 실패 — 코드 확인 필요"
  else
    log_warn "Playwright/Puppeteer 없음 — E2E 테스트 건너뜀"
  fi
fi

# ── 9. 상태 요약 출력 ────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}═══════════════════════════════════════${NC}"
echo -e "${GREEN}✅  개발 환경 준비 완료${NC}"
echo -e "${GREEN}═══════════════════════════════════════${NC}"
echo -e "   프론트엔드:  ${BLUE}http://localhost:$DEV_PORT${NC}"
echo -e "   프로젝트:    $PROJECT_ROOT"
echo -e "   로그 파일:   $PROJECT_ROOT/web_target/gemini-progress.txt"
echo ""
echo -e "${YELLOW}에이전트 세션 시작:${NC}"
echo -e "   python main.py --task '기능명' --project ./web_target"
echo ""
