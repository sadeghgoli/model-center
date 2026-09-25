"use client";

import { FormEvent, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Shell } from "@/components/shell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

export default function RuntimesPage() {
  const queryClient = useQueryClient();
  const orgs = useQuery({ queryKey: ["orgs"], queryFn: () => api("/api/backend/api/v1/organizations") });
  const orgId = orgs.data?.body?.data?.organizations?.[0]?.id as string | undefined;
  const runtimes = useQuery({ queryKey: ["runtimes", orgId], enabled: Boolean(orgId), queryFn: () => api(`/api/backend/api/v1/runtimes?organization_id=${orgId}`) });
  const [name, setName] = useState("vLLM Server 01");
  const [slug, setSlug] = useState("vllm-01");
  const [type, setType] = useState("vllm");
  const [endpoint, setEndpoint] = useState("http://192.168.1.50:8000/v1");
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState("");

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (!orgId) {
      setError("اول در صفحه سازمان و پروژه یک سازمان بسازید.");
      return;
    }
    const result = await api("/api/backend/api/v1/runtimes", {
      method: "POST",
      body: JSON.stringify({ organization_id: orgId, name, slug, type, endpoint, api_key: apiKey }),
    });
    if (!result.body.success) {
      setError(result.body.error?.message ?? "ثبت ران‌تایم انجام نشد.");
      return;
    }
    setApiKey("");
    queryClient.invalidateQueries({ queryKey: ["runtimes", orgId] });
  }

  async function health(id: string) {
    await api(`/api/backend/api/v1/runtimes/${id}/health`, { method: "POST" });
    queryClient.invalidateQueries({ queryKey: ["runtimes", orgId] });
  }

  return (
    <Shell>
      <h1 className="text-2xl">ران‌تایم‌ها</h1>
      <form className="grid gap-2" onSubmit={onSubmit}>
        <Input value={name} onChange={(event) => setName(event.target.value)} />
        <Input value={slug} onChange={(event) => setSlug(event.target.value)} />
        <select className="rounded-md border px-3 py-2" value={type} onChange={(event) => setType(event.target.value)}>
          <option value="ollama">Ollama</option>
          <option value="vllm">vLLM</option>
          <option value="openai_compatible">OpenAI Compatible</option>
          <option value="custom">Custom</option>
          <option value="local">Local</option>
        </select>
        <Input value={endpoint} onChange={(event) => setEndpoint(event.target.value)} />
        <Input value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="کلید ران‌تایم، اختیاری" />
        {error ? <p className="text-red-700">{error}</p> : null}
        <Button type="submit">ثبت ران‌تایم</Button>
      </form>
      {(runtimes.data?.body?.data?.runtimes ?? []).map((runtime: { id: string; name: string; type: string; health_status: string; gpu_enabled: boolean; model_count: number }) => (
        <Card key={runtime.id}>
          <strong>{runtime.name}</strong>
          <p>نوع: {runtime.type} — وضعیت: {runtime.health_status} — GPU: {runtime.gpu_enabled ? "دارد" : "ندارد"} — مدل‌ها: {runtime.model_count}</p>
          <Button type="button" onClick={() => health(runtime.id)}>بررسی سلامت</Button>
        </Card>
      ))}
    </Shell>
  );
}
