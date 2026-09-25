#!/bin/sh
# Model Center installer for AlmaLinux.
# Docker and the GPU driver are assumed to be installed already.
# This script does not install NVIDIA drivers, Ollama, or vLLM.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
cd "$ROOT"

info() { printf '%s\n' "$*"; }
die() { printf 'خطا: %s\n' "$*" >&2; exit 1; }

if ! command -v docker >/dev/null 2>&1; then
  die "Docker پیدا نشد. اول Docker را نصب کنید."
fi

if ! docker info >/dev/null 2>&1; then
  if command -v systemctl >/dev/null 2>&1; then
    info "سرویس Docker خاموش است. در حال روشن کردن..."
    systemctl enable --now docker || sudo systemctl enable --now docker
  fi
  docker info >/dev/null 2>&1 || die "Docker daemon در دسترس نیست."
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  die "docker compose پیدا نشد. بسته docker-compose-plugin را نصب کنید."
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  info "کارت گرافیک دیده شد:"
  nvidia-smi -L || true
else
  info "nvidia-smi پیدا نشد. خود پلتفرم بدون GPU بالا می‌آید. runtime مدل را جدا وصل کنید."
fi

rand_hex() {
  od -An -N "$1" -tx1 /dev/urandom | tr -d ' \n'
}

if [ ! -f .env ]; then
  info "ساخت .env با رمزهای تصادفی..."
  DB_PASSWORD=$(rand_hex 24)
  JWT_SECRET=$(rand_hex 32)
  PLATFORM_SECRET=$(rand_hex 32)
  cat > .env <<EOF
DATABASE_URL=postgresql+asyncpg://modelcenter:${DB_PASSWORD}@postgres:5432/modelcenter
REDIS_URL=redis://redis:6379/0

JWT_SECRET=${JWT_SECRET}
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=30

AI_PLATFORM_SECRET=${PLATFORM_SECRET}
PUBLIC_BASE_URL=http://127.0.0.1:8090

DEFAULT_ADMIN_EMAIL=
DEFAULT_ADMIN_PASSWORD=

CORS_ORIGINS=http://127.0.0.1:3010,http://localhost:3010
REQUEST_TIMEOUT_SECONDS=60
MAX_BODY_BYTES=1048576

API_PORT=8090
WEB_PORT=3010
POSTGRES_PORT=54329
REDIS_PORT=6381
POSTGRES_USER=modelcenter
POSTGRES_PASSWORD=${DB_PASSWORD}
POSTGRES_DB=modelcenter

AI_PLATFORM_BASE_URL=http://127.0.0.1:8090/v1
AI_PLATFORM_API_KEY=
AI_MODEL=qwen3-8b
EOF
  chmod 600 .env
else
  info ".env از قبل وجود دارد و دست نخورده می‌ماند."
fi

current_email=$(sed -n 's/^DEFAULT_ADMIN_EMAIL=//p' .env | head -n 1)
current_password=$(sed -n 's/^DEFAULT_ADMIN_PASSWORD=//p' .env | head -n 1)

if [ -z "$current_email" ] || [ -z "$current_password" ]; then
  if [ -n "${DEFAULT_ADMIN_EMAIL:-}" ] && [ -n "${DEFAULT_ADMIN_PASSWORD:-}" ]; then
    admin_email=$DEFAULT_ADMIN_EMAIL
    admin_password=$DEFAULT_ADMIN_PASSWORD
  else
    printf 'ایمیل سوپرادمین: '
    read -r admin_email
    printf 'رمز سوپرادمین (حداقل ۸ نویسه): '
    stty -echo
    read -r admin_password
    stty echo
    printf '\n'
  fi
  [ -n "$admin_email" ] || die "ایمیل خالی است."
  [ "${#admin_password}" -ge 8 ] || die "رمز باید حداقل ۸ نویسه باشد."
  tmp=$(mktemp)
  awk -v email="$admin_email" -v password="$admin_password" '
    BEGIN { e = 0; p = 0 }
    /^DEFAULT_ADMIN_EMAIL=/ { print "DEFAULT_ADMIN_EMAIL=" email; e = 1; next }
    /^DEFAULT_ADMIN_PASSWORD=/ { print "DEFAULT_ADMIN_PASSWORD=" password; p = 1; next }
    { print }
    END {
      if (!e) print "DEFAULT_ADMIN_EMAIL=" email
      if (!p) print "DEFAULT_ADMIN_PASSWORD=" password
    }
  ' .env > "$tmp"
  mv "$tmp" .env
  chmod 600 .env
  info "حساب سوپرادمین در .env ثبت شد. رمز در خروجی این اسکریپت چاپ نمی‌شود."
fi

info "ساخت و بالا آوردن API، پنل، PostgreSQL و Redis..."
$COMPOSE --env-file .env -f infra/docker/docker-compose.yml up --build -d

info "منتظر آماده شدن API..."
ready=0
i=0
while [ "$i" -lt 60 ]; do
  if curl -fsS http://127.0.0.1:8090/health >/dev/null 2>&1; then
    ready=1
    break
  fi
  i=$((i + 1))
  sleep 5
done

if [ "$ready" -ne 1 ]; then
  info "API هنوز جواب نداد. آخرین لاگ:"
  $COMPOSE --env-file .env -f infra/docker/docker-compose.yml logs --tail 80 api
  die "نصب کامل نشد. لاگ API را ببینید."
fi

admin_email=$(sed -n 's/^DEFAULT_ADMIN_EMAIL=//p' .env | head -n 1)
info "نصب تمام شد."
info "پنل: http://127.0.0.1:3010"
info "API:  http://127.0.0.1:8090"
info "ورود پنل با ایمیل: ${admin_email}"
info "رمز همان مقداری است که موقع نصب وارد کردید و داخل .env مانده است."
info "سرویس‌ها فقط روی همین ماشین شنود می‌کنند. از رایانه دیگر با تونل SSH وصل شوید:"
info "ssh -L 3010:127.0.0.1:3010 -L 8090:127.0.0.1:8090 user@this-server"
info "Ollama و vLLM نصب نشدند. بعد از ورود، runtime خارجی را در پنل ثبت کنید."
