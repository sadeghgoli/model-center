"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Shell } from "@/components/shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

type ChatMessage = { role: "user" | "assistant"; content: string; reasoning?: string };
type ModelChoice = { slug: string; display_name: string; is_active: boolean; model_type?: string };
type VoiceEvent = { type?: string; text?: string; delta?: string; audio?: string; format?: string };

type Phase = "idle" | "listening" | "hearing" | "thinking" | "playing";

const audioTypes: Record<string, string> = { mp3: "audio/mpeg", wav: "audio/wav", opus: "audio/ogg", aac: "audio/aac", flac: "audio/flac" };
const phaseLabels: Record<Phase, string> = {
  idle: "",
  listening: "در حال گوش دادن… صحبت کنید",
  hearing: "در حال شنیدن…",
  thinking: "در حال پاسخ…",
  playing: "مدل در حال صحبت است…",
};
const FRAME_MS = 50;
const CALIBRATE_MS = 400;
const SPEECH_START_MS = 200;
const SILENCE_END_MS = 1000;
const MIN_SPEECH_MS = 600;
const MAX_TURN_MS = 30000;
const IDLE_RESTART_MS = 15000;

function decodeAudio(value: string) {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

const WAV_RATE = 16000;

async function toWav(blob: Blob, ctx: AudioContext): Promise<Blob> {
  const decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
  const length = Math.max(1, Math.ceil(decoded.duration * WAV_RATE));
  const offline = new OfflineAudioContext(1, length, WAV_RATE);
  const source = offline.createBufferSource();
  source.buffer = decoded;
  source.connect(offline.destination);
  source.start();
  const samples = (await offline.startRendering()).getChannelData(0);
  const view = new DataView(new ArrayBuffer(44 + samples.length * 2));
  const text = (offset: number, value: string) => {
    for (let index = 0; index < value.length; index += 1) view.setUint8(offset + index, value.charCodeAt(index));
  };
  text(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, WAV_RATE, true);
  view.setUint32(28, WAV_RATE * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, samples.length * 2, true);
  samples.forEach((value, index) => {
    const clamped = Math.max(-1, Math.min(1, value));
    view.setInt16(44 + index * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  });
  return new Blob([view.buffer], { type: "audio/wav" });
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
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState("");
  const [messages, setMessagesState] = useState<ChatMessage[]>([]);
  const history = useRef<ChatMessage[]>([]);
  const audioCtx = useRef<AudioContext | null>(null);
  const playback = useRef(Promise.resolve());
  const playbackGeneration = useRef(0);
  const playingSource = useRef<AudioBufferSourceNode | null>(null);
  const talking = useRef(false);
  const micStream = useRef<MediaStream | null>(null);
  const analyser = useRef<AnalyserNode | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const meter = useRef<number | null>(null);
  const inflight = useRef<AbortController | null>(null);

  function setMessages(next: ChatMessage[]) {
    history.current = next;
    setMessagesState(next);
  }

  function ensureAudio() {
    if (!audioCtx.current && window.AudioContext) audioCtx.current = new window.AudioContext();
    void audioCtx.current?.resume();
    return audioCtx.current;
  }

  function stopPlayback() {
    playbackGeneration.current += 1;
    playingSource.current?.stop();
    playingSource.current = null;
    playback.current = Promise.resolve();
  }

  function enqueueClip(bytes: Uint8Array, format: string) {
    const ctx = audioCtx.current;
    const generation = playbackGeneration.current;
    playback.current = playback.current.then(async () => {
      if (generation !== playbackGeneration.current) return;
      if (ctx) {
        try {
          const copy = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
          const decoded = await ctx.decodeAudioData(copy as ArrayBuffer);
          if (generation !== playbackGeneration.current) return;
          await new Promise<void>((resolve) => {
            const source = ctx.createBufferSource();
            source.buffer = decoded;
            source.connect(ctx.destination);
            source.onended = () => resolve();
            playingSource.current = source;
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
    const previous = history.current;
    const speechModel = sttModel || sttModels[0]?.slug || "";
    const speakerModel = ttsModel || ttsModels[0]?.slug || "";
    if (!speechModel || !speakerModel) {
      setError("مدل تشخیص گفتار و مدل گفتار را انتخاب کنید.");
      return;
    }
    setError("");
    setPending(true);
    let assistant = "";
    let reasoning = "";
    let shown = previous;
    const controller = new AbortController();
    inflight.current = controller;
    try {
      const ctx = ensureAudio();
      let upload = blob;
      let uploadName = "speech.webm";
      if (ctx) {
        try {
          upload = await toWav(blob, ctx);
          uploadName = "speech.wav";
        } catch {
          upload = blob;
        }
      }
      const form = new FormData();
      form.append("file", upload, uploadName);
      form.append("model", model);
      form.append("stt_model", speechModel);
      form.append("tts_model", speakerModel);
      form.append("voice", voiceName || "hello");
      form.append("language", language || "fa");
      form.append("response_format", "wav");
      form.append(
        "messages",
        JSON.stringify([
          { role: "system", content: "تو یک دستیار فارسی هستی." },
          ...previous.map((item) => ({ role: item.role, content: item.content })),
        ]),
      );
      const response = await fetch("/api/backend/api/v1/playground/voice", { method: "POST", body: form, signal: controller.signal });
      if (!response.ok || !response.body) {
        const failed = await response.json().catch(() => ({}));
        const message: string = failed.error?.message ?? "";
        if (talking.current && message === "Speech was not recognized.") return;
        setError(message || `پاسخی از مدل نرسید (کد ${response.status}).`);
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
            shown = [...previous, { role: "user", content: parsed.text }];
            setMessages(shown);
          }
          if (parsed.type === "error") setError((parsed as { error?: { message?: string } }).error?.message ?? "خطا در پاسخ مدل.");
          if ((parsed.type === "text" || parsed.type === "reasoning") && parsed.delta) {
            if (parsed.type === "text") assistant += parsed.delta;
            else reasoning += parsed.delta;
            setMessages([...shown, { role: "assistant", content: assistant, reasoning }]);
          }
          if (parsed.type === "audio" && parsed.audio) {
            if (talking.current) setPhase("playing");
            enqueueClip(decodeAudio(parsed.audio), parsed.format ?? "wav");
          }
        }
      }
      if (!assistant.trim()) setError("پاسخی از مدل نرسید.");
      await playback.current;
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "ارتباط با سرور قطع شد.");
    } finally {
      if (inflight.current === controller) inflight.current = null;
      setPending(false);
    }
  }

  function stopMeter() {
    if (meter.current !== null) window.clearInterval(meter.current);
    meter.current = null;
  }

  function listen() {
    const stream = micStream.current;
    const node = analyser.current;
    if (!talking.current || !stream || !node) return;
    setPhase("listening");
    const samples = new Float32Array(node.fftSize);
    let parts: Blob[] = [];
    let noise = 0;
    let calibrated = 0;
    let loud = 0;
    let quiet = 0;
    let spoken = 0;
    let waited = 0;
    let heard = false;

    const begin = () => {
      parts = [];
      const next = new MediaRecorder(stream);
      next.ondataavailable = (event) => {
        if (event.data.size > 0) parts.push(event.data);
      };
      next.start(250);
      recorder.current = next;
    };

    const finish = (send: boolean) => {
      stopMeter();
      const current = recorder.current;
      recorder.current = null;
      if (!current || current.state === "inactive") return;
      current.onstop = () => {
        if (!send || !talking.current) return;
        const blob = new Blob(parts, { type: current.mimeType || "audio/webm" });
        setPhase("thinking");
        void sendVoice(blob).then(() => listen());
      };
      current.stop();
    };

    begin();
    meter.current = window.setInterval(() => {
      node.getFloatTimeDomainData(samples);
      let sum = 0;
      for (const value of samples) sum += value * value;
      const level = Math.sqrt(sum / samples.length);
      if (calibrated < CALIBRATE_MS) {
        noise = noise === 0 ? level : noise * 0.8 + level * 0.2;
        calibrated += FRAME_MS;
        return;
      }
      const threshold = Math.max(0.02, noise * 3.5);
      if (level > threshold) {
        loud += FRAME_MS;
        quiet = 0;
      } else {
        quiet += FRAME_MS;
        loud = 0;
        if (!heard) noise = noise * 0.95 + level * 0.05;
      }
      if (!heard) {
        waited += FRAME_MS;
        if (loud >= SPEECH_START_MS) {
          heard = true;
          setPhase("hearing");
        } else if (waited >= IDLE_RESTART_MS) {
          finish(false);
          listen();
        }
        return;
      }
      spoken += FRAME_MS;
      if ((quiet >= SILENCE_END_MS && spoken - quiet >= MIN_SPEECH_MS) || spoken >= MAX_TURN_MS) finish(true);
      else if (quiet >= SILENCE_END_MS) {
        finish(false);
        listen();
      }
    }, FRAME_MS);
  }

  async function startConversation() {
    if (talking.current) return;
    setError("");
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("مرورگر ضبط صدا را پشتیبانی نمی‌کند.");
      return;
    }
    const speechModel = sttModel || sttModels[0]?.slug || "";
    const speakerModel = ttsModel || ttsModels[0]?.slug || "";
    if (!speechModel || !speakerModel) {
      setError("مدل تشخیص گفتار و مدل گفتار را انتخاب کنید.");
      return;
    }
    const ctx = ensureAudio();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      micStream.current = stream;
      if (ctx) {
        const node = ctx.createAnalyser();
        node.fftSize = 1024;
        ctx.createMediaStreamSource(stream).connect(node);
        analyser.current = node;
      }
    } catch {
      setError("دسترسی به میکروفون داده نشد.");
      return;
    }
    talking.current = true;
    listen();
  }

  function endConversation() {
    talking.current = false;
    stopMeter();
    const current = recorder.current;
    recorder.current = null;
    if (current && current.state !== "inactive") {
      current.onstop = null;
      current.stop();
    }
    inflight.current?.abort();
    stopPlayback();
    micStream.current?.getTracks().forEach((track) => track.stop());
    micStream.current = null;
    analyser.current = null;
    setPhase("idle");
  }

  useEffect(() => () => endConversation(), []);

  const chatOptions = chatModels.length > 0 ? chatModels : active;

  return (
    <Shell>
      <h1 className="text-2xl">چت با مدل</h1>
      <div className="flex gap-2">
        <Button type="button" onClick={() => setMode("text")} disabled={phase !== "idle"}>متن</Button>
        <Button type="button" onClick={() => setMode("voice")}>صوت</Button>
      </div>
      <label className="grid gap-1">
        مدل گفتگو
        <select className="rounded-md border px-3 py-2" value={model} disabled={phase !== "idle"} onChange={(event) => setModel(event.target.value)}>
          {chatOptions.map((item) => (
            <option key={item.slug} value={item.slug}>{item.display_name} ({item.slug})</option>
          ))}
          {choices.length === 0 ? <option value="qwen3-4b">qwen3-4b</option> : null}
        </select>
      </label>
      {mode === "voice" ? (
        <fieldset className="grid gap-3 md:grid-cols-2" disabled={phase !== "idle"}>
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
        </fieldset>
      ) : null}
      <div className="grid min-h-80 gap-3 rounded-xl border border-stone-200 bg-white p-4">
        {messages.length === 0 ? <p className="text-stone-500">{mode === "voice" ? "روی «شروع گفتگو» بزنید و صحبت کنید؛ هر بار که ساکت شوید، صدایتان خودکار ارسال می‌شود." : "پیام بنویسید تا مدل جواب بدهد."}</p> : null}
        {messages.map((message, index) => (
          <div key={`${message.role}-${index}`} className="grid gap-1">
            {message.reasoning ? (
              <details className="text-sm text-stone-500">
                <summary className="cursor-pointer">{message.content ? "فکر مدل" : "در حال فکر کردن…"}</summary>
                <p className="whitespace-pre-wrap" dir="auto">{message.reasoning.trim()}</p>
              </details>
            ) : null}
            {message.content || !message.reasoning ? (
              <p className={message.role === "user" ? "text-stone-900" : "text-emerald-800"}>
                <strong>{message.role === "user" ? "شما: " : "مدل: "}</strong>
                {message.content}
              </p>
            ) : null}
          </div>
        ))}
        {phase !== "idle" ? <p className="text-stone-600">{phaseLabels[phase]}</p> : pending ? <p>در حال پاسخ…</p> : null}
        {error ? <p className="text-red-700">{error}</p> : null}
      </div>
      {mode === "text" ? (
        <form className="flex gap-2" onSubmit={onSubmit}>
          <Input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="سلام" />
          <Button type="submit" disabled={pending}>ارسال</Button>
        </form>
      ) : (
        <div className="flex gap-2">
          {phase !== "idle" ? (
            <Button type="button" onClick={endConversation}>پایان گفتگو</Button>
          ) : (
            <Button type="button" onClick={() => void startConversation()} disabled={pending}>شروع گفتگو</Button>
          )}
        </div>
      )}
    </Shell>
  );
}
