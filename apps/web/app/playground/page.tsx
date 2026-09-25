"use client";

import { FormEvent, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Shell } from "@/components/shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

type ChatMessage = { role: "user" | "assistant"; content: string };

export default function PlaygroundPage() {
  const models = useQuery({ queryKey: ["models"], queryFn: () => api("/api/backend/api/v1/models") });
  const choices = (models.data?.body?.data?.models ?? []) as { slug: string; display_name: string; is_active: boolean }[];
  const [model, setModel] = useState("qwen3-4b");
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || pending) return;
    const history = [...messages, { role: "user" as const, content: text }];
    setMessages(history);
    setDraft("");
    setError("");
    setPending(true);
    let assistant = "";
    try {
      const response = await fetch("/api/backend/api/v1/playground/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model,
          messages: [{ role: "system", content: "تو یک دستیار فارسی هستی." }, ...history],
          stream: true,
          temperature: 0.7,
          max_tokens: 1024,
        }),
      });
      if (!response.ok || !response.body) {
        const failed = await response.json().catch(() => ({}));
        setError(failed.error?.message ?? "پاسخی از مدل نرسید.");
        return;
      }
      setMessages([...history, { role: "assistant", content: "" }]);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const data = line.slice(5).trim();
          if (!data || data === "[DONE]") continue;
          let parsed: { choices?: { delta?: { content?: string } }[] };
          try {
            parsed = JSON.parse(data) as { choices?: { delta?: { content?: string } }[] };
          } catch {
            continue;
          }
          const delta = parsed.choices?.[0]?.delta?.content ?? "";
          if (!delta) continue;
          assistant += delta;
          const visible = assistant;
          setMessages([...history, { role: "assistant", content: visible }]);
        }
      }
      if (!assistant.trim()) {
        setError("پاسخی از مدل نرسید.");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <Shell>
      <h1 className="text-2xl">چت با مدل</h1>
      <label className="grid gap-1">
        مدل
        <select className="rounded-md border px-3 py-2" value={model} onChange={(event) => setModel(event.target.value)}>
          {choices.filter((item) => item.is_active).map((item) => (
            <option key={item.slug} value={item.slug}>{item.display_name} ({item.slug})</option>
          ))}
          {choices.length === 0 ? <option value="qwen3-4b">qwen3-4b</option> : null}
        </select>
      </label>
      <div className="grid min-h-80 gap-3 rounded-xl border border-stone-200 bg-white p-4">
        {messages.length === 0 ? <p className="text-stone-500">پیام بنویسید تا مدل جواب بدهد.</p> : null}
        {messages.map((message, index) => (
          <p key={`${message.role}-${index}`} className={message.role === "user" ? "text-stone-900" : "text-emerald-800"}>
            <strong>{message.role === "user" ? "شما: " : "مدل: "}</strong>
            {message.content}
          </p>
        ))}
        {pending ? <p>در حال پاسخ…</p> : null}
        {error ? <p className="text-red-700">{error}</p> : null}
      </div>
      <form className="flex gap-2" onSubmit={onSubmit}>
        <Input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="سلام" />
        <Button type="submit" disabled={pending}>ارسال</Button>
      </form>
    </Shell>
  );
}
