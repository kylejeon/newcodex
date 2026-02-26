import { NextRequest, NextResponse } from 'next/server';
import { savePayload } from '@/lib/storage';
import { DashboardPayload } from '@/lib/types';

export const dynamic = 'force-dynamic';

export async function POST(req: NextRequest) {
  try {
    const token = req.headers.get('x-dashboard-token') || '';
    if (!process.env.DASHBOARD_INGEST_TOKEN || token !== process.env.DASHBOARD_INGEST_TOKEN) {
      return NextResponse.json({ ok: false, error: 'unauthorized' }, { status: 401 });
    }

    const body = (await req.json()) as DashboardPayload;
    if (!body?.snapshot?.ts) {
      return NextResponse.json({ ok: false, error: 'invalid payload' }, { status: 400 });
    }

    await savePayload(body);
    return NextResponse.json({ ok: true });
  } catch (e) {
    return NextResponse.json({ ok: false, error: String(e) }, { status: 500 });
  }
}
