import { connection } from "next/server";

/**
 * Frontend liveness probe used by the Docker health check. Deliberately does not
 * call the backend: a backend outage must not cause the frontend to be restarted.
 */
export async function GET() {
  await connection(); // evaluate per request, never prerendered at build time
  return Response.json(
    { status: "ok", service: "frontend" },
    { headers: { "Cache-Control": "no-store" } },
  );
}
