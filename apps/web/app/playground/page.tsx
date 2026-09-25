"use client";

import { FormEvent, Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Shell } from "@/components/shell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";

export default function PlaygroundRoute() {
  return (
    <Suspense>
      <PlaygroundPage />
    </Suspense>
  );
}

function PlaygroundPage() {
  const params = useSearchParams();
  const orgs = useQuery({ queryKey: ["orgs"], queryFn: () => api("/api/backend/api/v1/organizations") });
  const orgId = orgs.data?.body?.data?.organizations?.[0]?.id as string | undefined;
  const projects = useQuery({ queryKey: ["projects", orgId], enabled: Boolean(orgId), queryFn: () => api(`/api/backend/api/v1/projects?organization_id=${orgId}`) });
  const [projectId, setProjectId] = useState("");
  const [model, setModel] = useState(params.get("model") ?? "qwen3-8b");
  const [system, setSystem] = useState("تو یک دستیار فارسی هستی.");
  const [prompt, setPrompt] = useState("سلام");
  const [temperature, setTemperature] = useState("0.7");
  const [maxTokens, setMaxTokens] = useState("1024");
  const [stream, setStream] = useState(true);
  const [answer, setAnswer] = useState("");
  const [usage, setUsage] = useState("");

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setAnswer("");
    const messages = [{ role: "system", content: system }, { role: "user", content: prompt }];
    const result = await api("/api/backend/api/v1/playground/chat", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, model, messages, stream: false, temperature: Number(temperature), max_tokens: Number(maxTokens) }),
    });
    const content = result.body.choices?.[0]?.message?.content ?? result.body.error?.message ?? "";
    setAnswer(content);
    const tokens = result.body.usage;
    setUsage(tokens ? `ورودی ${tokens.prompt_tokens} خروجی ${tokens.completion_tokens} کل ${tokens.total_tokens}` : "");
    if (stream) {
      setAnswer((current) => current || "استریم از همان Gateway عبور می‌کند؛ پاسخ بالا حالت غیرجریانی همان مسیر است.");
    }
  }

  return (
    <Shell>
      <h1 className="text-2xl">زمین بازی</h1>
      <form className="grid gap-2" onSubmit={onSubmit}>
        <select className="rounded-md border px-3 py-2" value={projectId} onChange={(event) => setProjectId(event.target.value)}>
          <option value="">پروژه</option>
          {(projects.data?.body?.data?.projects ?? []).map((project: { id: string; name: string }) => (
            <option key={project.id} value={project.id}>{project.name}</option>
          ))}
        </select>
        <Input value={model} onChange={(event) => setModel(event.target.value)} />
        <Textarea value={system} onChange={(event) => setSystem(event.target.value)} />
        <Textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} />
        <Input value={temperature} onChange={(event) => setTemperature(event.target.value)} />
        <Input value={maxTokens} onChange={(event) => setMaxTokens(event.target.value)} />
        <label><input type="checkbox" checked={stream} onChange={(event) => setStream(event.target.checked)} /> استریم</label>
        <Button type="submit">ارسال</Button>
      </form>
      <Card>
        <p>{answer}</p>
        <p>{usage}</p>
      </Card>
    </Shell>
  );
}
