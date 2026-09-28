"use client";

import { FormEvent, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Shell } from "@/components/shell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

export default function ModelDetailPage() {
  const params = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const model = useQuery({ queryKey: ["model", params.id], queryFn: () => api(`/api/backend/api/v1/models/${params.id}`) });
  const deployments = useQuery({ queryKey: ["deployments", params.id], queryFn: () => api(`/api/backend/api/v1/deployments?model_id=${params.id}`) });
  const orgs = useQuery({ queryKey: ["orgs"], queryFn: () => api("/api/backend/api/v1/organizations") });
  const orgId = orgs.data?.body?.data?.organizations?.[0]?.id as string | undefined;
  const runtimes = useQuery({ queryKey: ["runtimes", orgId], enabled: Boolean(orgId), queryFn: () => api(`/api/backend/api/v1/runtimes?organization_id=${orgId}`) });
  const data = model.data?.body?.data;
  const [runtimeId, setRuntimeId] = useState("");
  const [runtimeModel, setRuntimeModel] = useState("Qwen/Qwen3-8B");
  const [name, setName] = useState("Qwen3 8B Production");

  async function deploy(event: FormEvent) {
    event.preventDefault();
    await api("/api/backend/api/v1/deployments", {
      method: "POST",
      body: JSON.stringify({ model_id: params.id, runtime_id: runtimeId, name, slug: name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "deploy", runtime_model_name: runtimeModel, gpu_required: 1 }),
    });
    queryClient.invalidateQueries({ queryKey: ["deployments", params.id] });
  }

  async function disable() {
    await api(`/api/backend/api/v1/models/${params.id}/disable`, { method: "POST" });
    queryClient.invalidateQueries({ queryKey: ["model", params.id] });
  }

  return (
    <Shell>
      <h1 className="text-2xl">{data?.display_name ?? "مدل"}</h1>
      <Card>
        <p>خانواده: {data?.model_family || "—"}</p>
        <p>پارامتر: {data?.parameter_count || "—"}</p>
        <p>زمینه: {data?.context_window}</p>
        <p>ارائه‌دهنده: {data?.provider_name || "—"}</p>
        <p>مجوز: {data?.license || "—"}</p>
        <Button type="button" onClick={disable}>غیرفعال</Button>
      </Card>
      <form className="grid gap-2" onSubmit={deploy}>
        <Input value={name} onChange={(event) => setName(event.target.value)} />
        <select className="rounded-md border px-3 py-2" value={runtimeId} onChange={(event) => setRuntimeId(event.target.value)}>
          <option value="">ران‌تایم</option>
          {(runtimes.data?.body?.data?.runtimes ?? []).map((runtime: { id: string; name: string }) => (
            <option key={runtime.id} value={runtime.id}>{runtime.name}</option>
          ))}
        </select>
        <Input value={runtimeModel} onChange={(event) => setRuntimeModel(event.target.value)} />
        <Button type="submit">استقرار</Button>
      </form>
      {(deployments.data?.body?.data?.deployments ?? []).map((item: DeploymentItem) => (
        <DeploymentCard key={item.id} item={item} onSaved={() => queryClient.invalidateQueries({ queryKey: ["deployments", params.id] })} />
      ))}
    </Shell>
  );
}

type DeploymentItem = { id: string; name: string; runtime_type: string; status: string; gpu_required: number; runtime_model_name: string };

function DeploymentCard({ item, onSaved }: { item: DeploymentItem; onSaved: () => void }) {
  const [runtimeModel, setRuntimeModel] = useState(item.runtime_model_name);
  const [message, setMessage] = useState("");

  async function update(fields: Record<string, string>) {
    const response = await api(`/api/backend/api/v1/deployments/${item.id}`, { method: "PATCH", body: JSON.stringify(fields) });
    const saved = response.status < 400;
    setMessage(saved ? "ذخیره شد." : response.body?.error?.message ?? "ذخیره نشد.");
    if (saved) onSaved();
  }

  return (
    <Card>
      <strong>{item.name}</strong>
      <p>ران‌تایم: {item.runtime_type} — وضعیت: {item.status === "running" ? "فعال" : "متوقف"} — GPU: {item.gpu_required}</p>
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          update({ runtime_model_name: runtimeModel });
        }}
      >
        <label className="text-sm">نام مدل ران‌تایم:</label>
        <Input className="max-w-sm" dir="ltr" value={runtimeModel} onChange={(event) => setRuntimeModel(event.target.value)} />
        <Button type="submit" disabled={!runtimeModel.trim() || runtimeModel.trim() === item.runtime_model_name}>ذخیره</Button>
        <Button type="button" onClick={() => update({ desired_status: item.status === "running" ? "stopped" : "running" })}>
          {item.status === "running" ? "توقف" : "فعال‌سازی"}
        </Button>
      </form>
      {message ? <p className="text-sm">{message}</p> : null}
    </Card>
  );
}
