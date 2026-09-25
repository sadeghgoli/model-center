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
  return (
    <Shell>
      <h1 className="text-2xl">مستندات API</h1>
      <pre className="overflow-auto rounded-xl bg-stone-900 p-4 text-left text-sm text-stone-100" dir="ltr">{curl}</pre>
      <pre className="overflow-auto rounded-xl bg-stone-900 p-4 text-left text-sm text-stone-100" dir="ltr">{python}</pre>
      <pre className="overflow-auto rounded-xl bg-stone-900 p-4 text-left text-sm text-stone-100" dir="ltr">{javascript}</pre>
      <pre className="overflow-auto rounded-xl bg-stone-900 p-4 text-left text-sm text-stone-100" dir="ltr">{javascript.replace("const response", "const response: Response")}</pre>
    </Shell>
  );
}
