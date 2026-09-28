import { Shell } from "@/components/shell";

const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:9005";

export default function DocsPage() {
  const curl = `curl ${base}/v1/chat/completions \\
  -H "Authorization: Bearer sk-gsm-xxxxxxxx" \\
  -H "Content-Type: application/json" \\
  -d '{"model":"qwen3-8b","messages":[{"role":"user","content":"سلام"}]}'`;
  const python = `from openai import OpenAI

client = OpenAI(base_url="${base}/v1", api_key="sk-gsm-...")
response = client.chat.completions.create(model="qwen3-8b", messages=[{"role": "user", "content": "سلام"}])
print(response.choices[0].message.content)`;
  const javascript = `const response = await fetch("${base}/v1/chat/completions", {
  method: "POST",
  headers: { Authorization: "Bearer sk-gsm-...", "Content-Type": "application/json" },
  body: JSON.stringify({ model: "qwen3-8b", messages: [{ role: "user", content: "سلام" }] })
});`;
  const transcribe = `curl ${base}/v1/audio/transcriptions \\
  -H "Authorization: Bearer sk-gsm-xxxxxxxx" \\
  -F "file=@speech.webm" \\
  -F "model=whisper" \\
  -F "language=fa"`;
  const speech = `curl ${base}/v1/audio/speech \\
  -H "Authorization: Bearer sk-gsm-xxxxxxxx" \\
  -H "Content-Type: application/json" \\
  -d '{"model":"pocket-tts-fa","input":"سلام.","voice":"hello","response_format":"wav"}' \\
  --output reply.wav`;
  const voice = `curl ${base}/v1/audio/chat \\
  -H "Authorization: Bearer sk-gsm-xxxxxxxx" \\
  -F "file=@speech.webm" \\
  -F "model=qwen3-8b" \\
  -F "stt_model=whisper" \\
  -F "tts_model=pocket-tts-fa" \\
  -F "messages=[]" \\
  -F "voice=hello" \\
  -F "response_format=wav" \\
  -F "language=fa"`;
  return (
    <Shell>
      <h1 className="text-2xl">مستندات API</h1>
      <pre className="overflow-auto rounded-xl bg-stone-900 p-4 text-left text-sm text-stone-100" dir="ltr">{curl}</pre>
      <pre className="overflow-auto rounded-xl bg-stone-900 p-4 text-left text-sm text-stone-100" dir="ltr">{python}</pre>
      <pre className="overflow-auto rounded-xl bg-stone-900 p-4 text-left text-sm text-stone-100" dir="ltr">{javascript}</pre>
      <pre className="overflow-auto rounded-xl bg-stone-900 p-4 text-left text-sm text-stone-100" dir="ltr">{javascript.replace("const response", "const response: Response")}</pre>
      <h2 className="text-xl">صوت</h2>
      <pre className="overflow-auto rounded-xl bg-stone-900 p-4 text-left text-sm text-stone-100" dir="ltr">{transcribe}</pre>
      <pre className="overflow-auto rounded-xl bg-stone-900 p-4 text-left text-sm text-stone-100" dir="ltr">{speech}</pre>
      <pre className="overflow-auto rounded-xl bg-stone-900 p-4 text-left text-sm text-stone-100" dir="ltr">{voice}</pre>
    </Shell>
  );
}
