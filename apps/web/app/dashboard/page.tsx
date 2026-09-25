"use client";

import { useQuery } from "@tanstack/react-query";
import { Shell } from "@/components/shell";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";

export default function DashboardPage() {
  const orgs = useQuery({
    queryKey: ["orgs"],
    queryFn: () => api("/api/backend/api/v1/organizations"),
  });
  const orgId = orgs.data?.body?.data?.organizations?.[0]?.id as string | undefined;
  const stats = useQuery({
    queryKey: ["dashboard", orgId],
    enabled: Boolean(orgId),
    queryFn: () => api(`/api/backend/api/v1/dashboard?organization_id=${orgId}`),
  });
  const data = stats.data?.body?.data ?? {};
  const cards = [
    ["درخواست‌ها", data.total_requests],
    ["کل توکن", data.total_tokens],
    ["ورودی", data.input_tokens],
    ["خروجی", data.output_tokens],
    ["مدل فعال", data.active_models],
    ["استقرار فعال", data.active_deployments],
    ["کلید فعال", data.active_api_keys],
    ["تأخیر میانگین", data.average_latency_ms],
    ["نرخ خطا", data.error_rate],
  ];
  return (
    <Shell>
      <h1 className="text-2xl">داشبورد</h1>
      <div className="grid gap-3 md:grid-cols-3">
        {cards.map(([label, value]) => (
          <Card key={String(label)}>
            <strong>{label}</strong>
            <p>{value ?? "—"}</p>
          </Card>
        ))}
      </div>
      <Card>
        <strong>درخواست و توکن به تفکیک مدل</strong>
        {(data.requests_by_model ?? []).map((row: { model: string; requests: number; tokens: number }) => (
          <p key={row.model}>{row.model}: {row.requests} درخواست، {row.tokens} توکن</p>
        ))}
      </Card>
    </Shell>
  );
}
