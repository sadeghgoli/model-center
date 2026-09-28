"use client";

import { FormEvent, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Shell } from "@/components/shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

type ChatMessage = { role: "user" | "assistant"; content: string };
type ModelChoice = { slug: string; display_name: string; is_active: boolean; model_type?: string };
type VoiceEvent = { type?: string; text?: string; delta?: string; audio?: string; format?: string };

const audioTypes: Record<string, string> = { mp3: "audio/mpeg", wav: "audio/wav", opus: "audio/ogg", aac: "audio/aac", flac: "audio/flac" };

function decodeAudio(value: string) {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

export default function PlaygroundPage() {
  const models = useQuery({ queryKey: ["models"], queryFn: () => api("/api/backend/api/v1/models") });
  const choices = (models.data?.body?.data?.models ?? []) as ModelChoice[];
  const active = choices.filter((item) => item.is_active);
  const chatModels = active.filter((item) => (item.model_type || "chat") === "chat");
  const sttModels = active.filter((item) => item.model_type === "transcription");
  const ttsModels = active.filter((item) => item.model_type === "speech");
  const [mode, setMode] = useState<"text" | "voice">("text");
  const [model, setModel] = useState("qwen3-4b");
  const [sttModel, setSttModel] = useState("");
  const [ttsModel, setTtsModel] = useState("");
  const [voiceName, setVoiceName] = useState("hello");
  const [language, setLanguage] = useState("fa");
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const audioCtx = useRef<AudioContext | null>(null);
  const playback = useRef(Promise.resolve());

  function enqueueClip(bytes: Uint8Array, format: string) {
    const ctx = audioCtx.current;
    playback.current = playback.current.then(async () => {
      if (ctx) {
        try {
          const copy = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
          const decoded = await ctx.decodeAudioData(copy as ArrayBuffer);
          await new Promise<void>((resolve) => {
            const source = ctx.createBufferSource();
            source.buffer = decoded;
            source.connect(ctx.destination);
            source.onended = () => resolve();
            source.start();
          });
          return;
        } catch {
          /* decodeAudioData can reject some encodings; the element below still plays the clip */
        }
      }
      const copy = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
      const url = URL.createObjectURL(new Blob([copy], { type: audioTypes[format] ?? "audio/wav" }));
      await new Promise<void>((resolve) => {
        const audio = new Audio(url);
        audio.onended = () => {
          URL.revokeObjectURL(url);
          resolve();
        };
        audio.onerror = () => {
          URL.revokeObjectURL(url);
          resolve();
        };
        void audio.play().catch(() => resolve());
      });
    });
  }

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

  async function sendVoice(blob: Blob) {
    const history = messages;
    const speechModel = sttModel || sttModels[0]?.slug || "";
    const speakerModel = ttsModel || ttsModels[0]?.slug || "";
    if (!speechModel || !speakerModel) {
      setError("مدل تشخیص گفتار و مدل گفتار را انتخاب کنید.");
      return;
    }
    setError("");
    setPending(true);
    let assistant = "";
    let shown = history;
    try {
      const form = new FormData();
      form.append("file", blob, "speech.webm");
      form.append("model", model);
      form.append("stt_model", speechModel);
      form.append("tts_model", speakerModel);
      form.append("voice", voiceName || "hello");
      form.append("language", language || "fa");
      form.append("response_format", "wav");
      form.append("messages", JSON.stringify([{ role: "system", content: "تو یک دستیار فارسی هستی." }, ...history]));
      const response = await fetch("/api/backend/api/v1/playground/voice", { method: "POST", body: form });
      if (!response.ok || !response.body) {
        const failed = await response.json().catch(() => ({}));
        setError(failed.error?.message ?? "پاسخی از مدل نرسید.");
        return;
      }
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
          let parsed: VoiceEvent;
          try {
            parsed = JSON.parse(data) as VoiceEvent;
          } catch {
            continue;
          }
          if (parsed.type === "transcript" && parsed.text) {
            shown = [...history, { role: "user", content: parsed.text }];
            setMessages(shown);
          }
          if (parsed.type === "text" && parsed.delta) {
            assistant += parsed.delta;
            const visible = assistant;
            setMessages([...shown, { role: "assistant", content: visible }]);
          }
          if (parsed.type === "audio" && parsed.audio) enqueueClip(decodeAudio(parsed.audio), parsed.format ?? "wav");
        }
      }
      if (!assistant.trim()) setError("پاسخی از مدل نرسید.");
    } finally {
      setPending(false);
    }
  }

  async function startRecording() {
    if (pending || recording) return;
    setError("");
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("مرورگر ضبط صدا را پشتیبانی نمی‌کند.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorded = new MediaRecorder(stream);
      chunks.current = [];
      recorded.ondataavailable = (event) => {
        if (event.data.size > 0) chunks.current.push(event.data);
      };
      recorded.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(chunks.current, { type: recorded.mimeType || "audio/webm" });
        void sendVoice(blob);
      };
      recorded.start();
      recorder.current = recorded;
      setRecording(true);
    } catch {
      setError("دسترسی به میکروفون داده نشد.");
    }
  }

  function stopRecording() {
    const Ctx = window.AudioContext;
    if (Ctx && !audioCtx.current) audioCtx.current = new Ctx();
    void audioCtx.current?.resume();
    recorder.current?.stop();
    setRecording(false);
  }

  const chatOptions = chatModels.length > 0 ? chatModels : active;

  return (
    <Shell>
      <h1 className="text-2xl">چت با مدل</h1>
      <div className="flex gap-2">
        <Button type="button" onClick={() => setMode("text")}>متن</Button>
        <Button type="button" onClick={() => setMode("voice")}>صوت</Button>
      </div>
      <label className="grid gap-1">
        مدل گفتگو
        <select className="rounded-md border px-3 py-2" value={model} onChange={(event) => setModel(event.target.value)}>
          {chatOptions.map((item) => (
            <option key={item.slug} value={item.slug}>{item.display_name} ({item.slug})</option>
          ))}
          {choices.length === 0 ? <option value="qwen3-4b">qwen3-4b</option> : null}
        </select>
      </label>
      {mode === "voice" ? (
        <div className="grid gap-3 md:grid-cols-2">
          <label className="grid gap-1">
            تشخیص گفتار
            <select className="rounded-md border px-3 py-2" value={sttModel || sttModels[0]?.slug || ""} onChange={(event) => setSttModel(event.target.value)}>
              {sttModels.map((item) => (
                <option key={item.slug} value={item.slug}>{item.display_name} ({item.slug})</option>
              ))}
              {sttModels.length === 0 ? <option value="">مدلی ثبت نشده</option> : null}
            </select>
          </label>
          <label className="grid gap-1">
            گفتار
            <select className="rounded-md border px-3 py-2" value={ttsModel || ttsModels[0]?.slug || ""} onChange={(event) => setTtsModel(event.target.value)}>
              {ttsModels.map((item) => (
                <option key={item.slug} value={item.slug}>{item.display_name} ({item.slug})</option>
              ))}
              {ttsModels.length === 0 ? <option value="">مدلی ثبت نشده</option> : null}
            </select>
          </label>
          <label className="grid gap-1">
            نام صدا
            <Input value={voiceName} onChange={(event) => setVoiceName(event.target.value)} />
          </label>
          <label className="grid gap-1">
            زبان رونویسی
            <Input value={language} onChange={(event) => setLanguage(event.target.value)} />
          </label>
        </div>
      ) : null}
      <div className="grid min-h-80 gap-3 rounded-xl border border-stone-200 bg-white p-4">
        {messages.length === 0 ? <p className="text-stone-500">{mode === "voice" ? "ضبط را شروع کنید تا مدل جواب بدهد." : "پیام بنویسید تا مدل جواب بدهد."}</p> : null}
        {messages.map((message, index) => (
          <p key={`${message.role}-${index}`} className={message.role === "user" ? "text-stone-900" : "text-emerald-800"}>
            <strong>{message.role === "user" ? "شما: " : "مدل: "}</strong>
            {message.content}
          </p>
        ))}
        {recording ? <p>در حال ضبط…</p> : null}
        {pending ? <p>در حال پاسخ…</p> : null}
        {error ? <p className="text-red-700">{error}</p> : null}
      </div>
      {mode === "text" ? (
        <form className="flex gap-2" onSubmit={onSubmit}>
          <Input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="سلام" />
          <Button type="submit" disabled={pending}>ارسال</Button>
        </form>
      ) : (
        <div className="flex gap-2">
          {recording ? (
            <Button type="button" onClick={stopRecording}>پایان و ارسال</Button>
          ) : (
            <Button type="button" onClick={() => void startRecording()} disabled={pending}>شروع ضبط</Button>
          )}
        </div>
      )}
    </Shell>
  );
}
