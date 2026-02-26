# Kosdaqpi Vercel Dashboard

## 1) Deploy to Vercel

```bash
cd /Users/yonghyuk/newcodex/vercel-dashboard
npm install
npx vercel
```

Set Vercel env vars:

- `BLOB_READ_WRITE_TOKEN` : Vercel Blob token
- `DASHBOARD_INGEST_TOKEN` : 임의의 긴 비밀 문자열

## 2) Local bot -> Vercel 데이터 업로드

로컬(봇 실행 PC)에서 아래 env를 설정 후 실행:

```bash
export DASHBOARD_VERCEL_URL="https://<your-project>.vercel.app"
export DASHBOARD_INGEST_TOKEN="<same-token>"
export ACCOUNT_MODE="REAL"

/Users/yonghyuk/newcodex/newcodex/bin/python /Users/yonghyuk/newcodex/dashboard_push_to_vercel.py
```

## 3) 주기 업로드(cron 예시)

```bash
*/2 9-15 * * 1-5 cd /Users/yonghyuk/newcodex && DASHBOARD_VERCEL_URL="https://<your-project>.vercel.app" DASHBOARD_INGEST_TOKEN="<same-token>" ACCOUNT_MODE="REAL" /Users/yonghyuk/newcodex/newcodex/bin/python /Users/yonghyuk/newcodex/dashboard_push_to_vercel.py >> /Users/yonghyuk/newcodex/dashboard_push.log 2>&1
```

## Notes
- 대시보드는 `/api/data`를 통해 최신 데이터와 히스토리를 불러옵니다.
- 업로드 API는 `/api/ingest` (헤더: `x-dashboard-token`).
