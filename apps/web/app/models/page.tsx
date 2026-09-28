"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Shell } from "@/components/shell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

export default function ModelsPage() {
  const queryClient = useQueryClient();
  const models = useQuery({ queryKey: ["models"], queryFn: () => api("/api/backend/api/v1/models") });
  const [name, setName] = useState("Qwen3 8B");
  const [slug, setSlug] = useState("qwen3-8b");
  const [modelType, setModelType] = useState("chat");
  const [error, setError] = useState("");
  const typeLabels: Record<string, string> = { chat: "گفتگو", transcription: "تشخیص گفتار", speech: "گفتار" };

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const audio = modelType !== "chat";
    const result = await api("/api/backend/api/v1/models", { method: "POST", body: JSON.stringify({ name, slug, display_name: name, model_type: modelType, supports_chat: !audio, supports_streaming: !audio, supports_tools: modelType === "chat", supports_audio: audio }) });
    if (!result.body.success) {
      setError(result.body.error?.message ?? "ساخته نشد.");
      return;
    }
    queryClient.invalidateQueries({ queryKey: ["models"] });
  }

  return (
    <Shell>
      <h1 className="text-2xl">مدل‌ها</h1>
      <form className="grid gap-2 md:grid-cols-4" onSubmit={onSubmit}>
        <Input value={name} onChange={(event) => setName(event.target.value)} />
        <Input value={slug} onChange={(event) => setSlug(event.target.value)} />
        <select className="rounded-md border px-3 py-2" value={modelType} onChange={(event) => setModelType(event.target.value)}>
          <option value="chat">گفتگو</option>
          <option value="transcription">تشخیص گفتار</option>
          <option value="speech">گفتار</option>
        </select>
        <Button type="submit">افزودن مدل</Button>
      </form>
      {error ? <p className="text-red-700">{error}</p> : null}
      {models.isError || (models.data && models.data.status >= 400) ? (
        <p className="text-red-700">لیست مدل‌ها بارگذاری نشد ({models.data?.body?.error?.message ?? "API در دسترس نیست"}).</p>
      ) : null}
      {(models.data?.body?.data?.models ?? []).map((model: { id: string; display_name: string; slug: string; model_type: string; context_window: number; is_active: boolean; running_deployments: number; supports_chat: boolean; supports_streaming: boolean; supports_tools: boolean }) => (
        <Card key={model.id}>
          <strong>{model.display_name}</strong>
          <p>شناسه: {model.slug}</p>
          <p>نوع: {typeLabels[model.model_type] ?? model.model_type} — زمینه: {model.context_window}</p>
          <p>توانایی: {model.supports_chat ? "گفتگو " : ""}{model.supports_streaming ? "استریم " : ""}{model.supports_tools ? "ابزار" : ""}</p>
          <p>استقرار در حال اجرا: {model.running_deployments} — {model.is_active ? "فعال" : "خاموش"}</p>
          <p className="mt-2 flex gap-3">
            <Link href={`/models/${model.id}`}>مشاهده</Link>
            <Link href={`/playground?model=${model.slug}`}>زمین بازی</Link>
          </p>
        </Card>
      ))}
    </Shell>
  );
}
