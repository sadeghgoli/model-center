"use client";

import { FormEvent, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Shell } from "@/components/shell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

export default function ProjectsPage() {
  const queryClient = useQueryClient();
  const orgs = useQuery({ queryKey: ["orgs"], queryFn: () => api("/api/backend/api/v1/organizations") });
  const [orgName, setOrgName] = useState("GSM");
  const [orgSlug, setOrgSlug] = useState("gsm");
  const orgId = orgs.data?.body?.data?.organizations?.[0]?.id as string | undefined;
  const projects = useQuery({ queryKey: ["projects", orgId], enabled: Boolean(orgId), queryFn: () => api(`/api/backend/api/v1/projects?organization_id=${orgId}`) });
  const models = useQuery({ queryKey: ["models"], queryFn: () => api("/api/backend/api/v1/models") });
  const [projectName, setProjectName] = useState("Voice Agent");
  const [projectSlug, setProjectSlug] = useState("voice-agent");
  const [selected, setSelected] = useState("");
  const [modelId, setModelId] = useState("");
  const [keyName, setKeyName] = useState("gsm-voice");
  const [rawKey, setRawKey] = useState("");

  async function createOrg(event: FormEvent) {
    event.preventDefault();
    await api("/api/backend/api/v1/organizations", { method: "POST", body: JSON.stringify({ name: orgName, slug: orgSlug }) });
    queryClient.invalidateQueries({ queryKey: ["orgs"] });
  }

  async function createProject(event: FormEvent) {
    event.preventDefault();
    if (!orgId) return;
    await api("/api/backend/api/v1/projects", { method: "POST", body: JSON.stringify({ organization_id: orgId, name: projectName, slug: projectSlug }) });
    queryClient.invalidateQueries({ queryKey: ["projects", orgId] });
  }

  async function allowModel(event: FormEvent) {
    event.preventDefault();
    await api(`/api/backend/api/v1/projects/${selected}/models`, { method: "POST", body: JSON.stringify({ model_id: modelId }) });
  }

  async function createKey(event: FormEvent) {
    event.preventDefault();
    const result = await api(`/api/backend/api/v1/projects/${selected}/api-keys`, { method: "POST", body: JSON.stringify({ name: keyName, model_ids: modelId ? [modelId] : [] }) });
    setRawKey(result.body.data?.api_key ?? "");
  }

  return (
    <Shell>
      <h1 className="text-2xl">سازمان و پروژه</h1>
      <form className="grid gap-2 md:grid-cols-3" onSubmit={createOrg}>
        <Input value={orgName} onChange={(event) => setOrgName(event.target.value)} />
        <Input value={orgSlug} onChange={(event) => setOrgSlug(event.target.value)} />
        <Button type="submit">ساخت سازمان</Button>
      </form>
      <form className="grid gap-2 md:grid-cols-3" onSubmit={createProject}>
        <Input value={projectName} onChange={(event) => setProjectName(event.target.value)} />
        <Input value={projectSlug} onChange={(event) => setProjectSlug(event.target.value)} />
        <Button type="submit">ساخت پروژه</Button>
      </form>
      {(projects.data?.body?.data?.projects ?? []).map((project: { id: string; name: string; slug: string }) => (
        <Card key={project.id}>
          <button type="button" onClick={() => setSelected(project.id)}>{project.name} — {project.slug}</button>
        </Card>
      ))}
      {selected ? (
        <form className="grid gap-2" onSubmit={allowModel}>
          <select className="rounded-md border px-3 py-2" value={modelId} onChange={(event) => setModelId(event.target.value)}>
            <option value="">مدل مجاز</option>
            {(models.data?.body?.data?.models ?? []).map((model: { id: string; slug: string }) => (
              <option key={model.id} value={model.id}>{model.slug}</option>
            ))}
          </select>
          <Button type="submit">فعال کردن دسترسی مدل</Button>
          <Input value={keyName} onChange={(event) => setKeyName(event.target.value)} />
          <Button type="button" onClick={createKey}>ساخت کلید API</Button>
          {rawKey ? <p>کلید فقط یک‌بار نشان داده می‌شود: {rawKey}</p> : null}
        </form>
      ) : null}
    </Shell>
  );
}
