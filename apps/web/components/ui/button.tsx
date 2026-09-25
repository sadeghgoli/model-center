import { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function Button({ className, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cn("rounded-md bg-stone-900 px-3 py-2 text-sm text-white disabled:opacity-60", className)}
      {...props}
    />
  );
}
