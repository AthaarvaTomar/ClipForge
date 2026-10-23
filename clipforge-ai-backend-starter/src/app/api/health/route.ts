import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json({
    ok: true,
    service: "clipforge-ai-api",
    timestamp: new Date().toISOString()
  });
}
