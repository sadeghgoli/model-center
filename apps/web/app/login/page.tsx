"use client";

import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const schema = z.object({
  email: z.string().email(),
  password: z.string().min(8),
});

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const form = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema) });

  async function onSubmit(values: z.infer<typeof schema>) {
    setError("");
    const response = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values) });
    const body = await response.json();
    if (!response.ok || !body.success) {
      setError(body.error?.message ?? "ورود انجام نشد.");
      return;
    }
    router.push("/dashboard");
  }

  return (
    <main className="mx-auto max-w-md p-8">
      <h1 className="mb-4 text-2xl">ورود به مرکز مدل</h1>
      <form className="grid gap-3" onSubmit={form.handleSubmit(onSubmit)}>
        <Input type="email" placeholder="ایمیل" {...form.register("email")} />
        <Input type="password" placeholder="رمز" {...form.register("password")} />
        {error ? <p className="text-red-700">{error}</p> : null}
        <Button type="submit">ورود</Button>
      </form>
    </main>
  );
}
