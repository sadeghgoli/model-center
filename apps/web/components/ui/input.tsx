import { InputHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn("w-full rounded-md border border-stone-300 bg-white px-3 py-2", className)} {...props} />;
}
