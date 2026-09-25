import { ReactNode } from "react";

export function Card({ children }: { children: ReactNode }) {
  return <section className="rounded-xl border border-stone-200 bg-white p-4">{children}</section>;
}
